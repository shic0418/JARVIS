"""한글(HWPX) 문서 만들기 — 보고서를 한컴오피스 한글에서 바로 열리는 .hwpx 로 저장한다.

HWPX 는 한컴오피스의 열린 문서 형식(OWPML, KS X 6101)으로, XML 파일 몇 개를 ZIP 으로 묶은 것이다.
바탕 틀(hwpx_template/)은 python-hwpx(Apache-2.0)의 빈 문서 Skeleton.hwpx 에서 가져왔다 — hwpx_template/LICENSE-python-hwpx 참고.
그 틀의 글자 모양(charPr) · 문단 모양(paraPr) · 테두리(borderFill) 목록에 보고서용 모양을 덧붙이고, 본문(section)에 문단을 채운다.
워드 보고서(office.build_document)와 같은 구성이다 (그림은 넣지 않는다):
  · 표지 구역(section0): 'REPORT' 띠(문단 바탕색) · 큰 제목 · 강조 줄 · 부제 · 오른쪽 아래 정보. 쪽 번호가 없다.
  · 본문 구역(section1): 쪽 번호가 1부터 (아래 가운데). 큰 장이 3개 이상이면 목차 쪽이 맨 앞에, 그 다음 쪽부터 본문.
  · 큰 제목은 강조색 번호 + 아래 줄(문단 테두리), 작은 제목은 왼쪽 막대, 핵심 요약 · 강조 상자는 문단 테두리 + 바탕색.
sections 는 heading · level · paragraphs · bullets · points · table · callout, 문서 전체의 summary 를 받는다.
표준 라이브러리만 쓴다 (한컴오피스가 없어도 만들 수 있다).
"""
from __future__ import annotations

import re
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .office import _em, _strings, _text, numeric_text, parse_bullets, pretty_ref, rich_parts
from .report import _HEAD_NUM, _box_lines, _split_subtitle, outline

TEMPLATE = Path(__file__).with_name("hwpx_template")
BODY_WIDTH = 42520          # A4 본문 폭 (바탕 틀의 쪽 여백 기준, HWPUNIT = 1/7200 인치)
ACCENT = "#1F3A8A"          # 워드 보고서와 같은 강조색
NAVY = "#16213A"
MUTED = "#6B7487"


def _esc(s: str) -> str:
    s = s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
    return re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", s)      # XML 에 넣을 수 없는 제어 문자


def _read(name: str) -> str:
    return (TEMPLATE / name).read_text(encoding="utf-8")


# ---------------------------------------------------------------- 글자 · 문단 모양
@dataclass(frozen=True)
class CharSpec:
    size: float
    bold: bool = False
    italic: bool = False
    gothic: bool = False          # True = 함초롬돋움, False = 함초롬바탕
    color: str = "#000000"
    spacing: int = 0              # 자간 (%)


# 테두리 번호 (바탕 틀에 1~2 번이 있으므로 3 번부터)
BORDER_TABLE, BORDER_HEAD, BORDER_STRIPE = 3, 4, 5
BORDER_RULE, BORDER_BAR, BORDER_CALLOUT, BORDER_SUMMARY, BORDER_BAND, BORDER_ACCENT, BORDER_META, BORDER_TOC = range(6, 14)


@dataclass(frozen=True)
class ParaSpec:
    align: str                    # JUSTIFY · LEFT · CENTER · RIGHT
    left: int = 0
    intent: int = 0               # 음수면 내어쓰기
    prev: int = 0
    next: int = 0
    line: int = 160               # 줄 간격 %
    keep_next: bool = False
    right: int = 0
    border: int = 2               # 문단 테두리·바탕 (borderFill 번호, 2 = 없음)
    gap: tuple = (0, 0, 0, 0)     # 테두리와 글 사이 간격 (왼쪽, 오른쪽, 위, 아래)
    connect: bool = False         # 같은 테두리가 이어지는 문단들을 한 상자로


# 바탕 틀에 글자 모양 0~6 번, 문단 모양 0~19 번이 있으므로 그 뒤에 붙인다
CHARS: dict[str, CharSpec] = {
    "body": CharSpec(11),
    "bodyB": CharSpec(11, bold=True),
    "title": CharSpec(22, bold=True, gothic=True, color=NAVY),
    "subtitle": CharSpec(11, color=MUTED),
    "h1": CharSpec(16, bold=True, gothic=True, color=NAVY),
    "h1n": CharSpec(16, bold=True, gothic=True, color=ACCENT),
    "h2": CharSpec(13, bold=True, gothic=True, color=NAVY),
    "h2n": CharSpec(13, bold=True, gothic=True, color=ACCENT),
    "th": CharSpec(10, bold=True, gothic=True, color="#FFFFFF"),
    "td": CharSpec(10),
    "caption": CharSpec(9, color=MUTED),
    "ref": CharSpec(10),
    "band": CharSpec(11, bold=True, gothic=True, color="#FFFFFF", spacing=40),
    "ctitle": CharSpec(30, bold=True, gothic=True, color=NAVY),
    "ctitle2": CharSpec(24, bold=True, gothic=True, color=NAVY),
    "ctitle3": CharSpec(20, bold=True, gothic=True, color=NAVY),
    "csub": CharSpec(15, gothic=True, color=MUTED),
    "cmeta": CharSpec(11, gothic=True, color=MUTED),
    "cdate": CharSpec(11.5, bold=True, gothic=True, color=NAVY),
    "tiny": CharSpec(4),
    "tlabel": CharSpec(9.5, bold=True, gothic=True, color=ACCENT, spacing=40),
    "thead": CharSpec(22, bold=True, gothic=True, color=NAVY),
    "toc1": CharSpec(12, bold=True, gothic=True, color=NAVY),
    "toc1n": CharSpec(12, bold=True, gothic=True, color=ACCENT),
    "toc2": CharSpec(10.5, gothic=True, color=MUTED),
    "boxlabel": CharSpec(10, bold=True, gothic=True, color=ACCENT),
    "calllabel": CharSpec(10, bold=True, gothic=True, color="#9A6B00"),
}
PARAS: dict[str, ParaSpec] = {
    "body": ParaSpec("JUSTIFY", next=600, line=165),
    "title": ParaSpec("CENTER", next=400, line=130),
    "subtitle": ParaSpec("CENTER", next=1400, line=130),
    "h1": ParaSpec("LEFT", prev=1800, next=0, line=130, keep_next=True, border=BORDER_RULE, gap=(0, 0, 0, 300)),   # 아래 줄은 다음 간격 뒤에 그려지므로 next=0
    "h2": ParaSpec("LEFT", left=600, prev=0, next=0, line=130, keep_next=True, border=BORDER_BAR, gap=(300, 0, 100, 100)),
    "list": ParaSpec("LEFT", left=1800, intent=-1100, next=200, line=150),
    "list2": ParaSpec("LEFT", left=3400, intent=-1100, next=200, line=150),
    "cell": ParaSpec("LEFT", line=130),
    "cellR": ParaSpec("RIGHT", line=130),
    "cellC": ParaSpec("CENTER", line=130),
    "caption": ParaSpec("CENTER", prev=200, next=600, line=130),
    "band": ParaSpec("LEFT", line=230, border=BORDER_BAND, gap=(600, 0, 300, 300)),
    "ctitle": ParaSpec("LEFT", prev=16000, next=500, line=125),
    "crule": ParaSpec("LEFT", line=100, next=0, border=BORDER_ACCENT),
    "csub": ParaSpec("LEFT", prev=800, line=140, next=400),
    "cmeta": ParaSpec("RIGHT", line=160),
    "cmeta1": ParaSpec("RIGHT", prev=24000, line=160),
    "tlabel": ParaSpec("LEFT", line=130),
    "thead": ParaSpec("LEFT", prev=200, next=1400, line=130),
    "toc1": ParaSpec("LEFT", prev=350, next=0, line=150, border=BORDER_TOC, gap=(0, 0, 0, 250)),
    "toc2": ParaSpec("LEFT", left=1400, prev=250, next=0, line=140, border=BORDER_TOC, gap=(0, 0, 0, 200)),
    "boxs": ParaSpec("LEFT", prev=0, next=0, line=165, border=BORDER_SUMMARY, gap=(600, 400, 250, 250), connect=True),
    "boxc": ParaSpec("LEFT", prev=0, next=0, line=165, border=BORDER_CALLOUT, gap=(600, 400, 250, 250), connect=True),
    "gap": ParaSpec("LEFT", line=100, next=500),
    "gapS": ParaSpec("LEFT", line=100, next=500, keep_next=False),
    "gapB": ParaSpec("LEFT", line=100, next=1000),
}
CHAR_ID = {k: 7 + i for i, k in enumerate(CHARS)}
PARA_ID = {k: 20 + i for i, k in enumerate(PARAS)}


def _char_pr(template: str, cid: int, s: CharSpec) -> str:
    font = "0" if s.gothic else "1"
    x = re.sub(r' id="\d+"', f' id="{cid}"', template, count=1)
    x = re.sub(r'height="\d+"', f'height="{round(s.size * 100)}"', x, count=1)
    x = re.sub(r'textColor="#[0-9A-Fa-f]{6}"', f'textColor="{s.color}"', x, count=1)
    x = re.sub(r"<hh:fontRef [^>]*/>", "<hh:fontRef " + " ".join(
        f'{k}="{font}"' for k in ("hangul", "latin", "hanja", "japanese", "other", "symbol", "user")) + "/>", x, count=1)
    if s.spacing:
        x = re.sub(r"<hh:spacing [^>]*/>", "<hh:spacing " + " ".join(
            f'{k}="{s.spacing}"' for k in ("hangul", "latin", "hanja", "japanese", "other", "symbol", "user")) + "/>", x, count=1)
    marks = ("<hh:italic/>" if s.italic else "") + ("<hh:bold/>" if s.bold else "")   # 스키마 순서: offset 다음 italic, bold
    if marks:
        x = re.sub(r"(<hh:offset [^>]*/>)", lambda m: m.group(1) + marks, x, count=1)
    return x


def _para_pr(template: str, pid: int, s: ParaSpec) -> str:
    x = re.sub(r' id="\d+"', f' id="{pid}"', template, count=1)
    x = re.sub(r'<hh:align horizontal="\w+"', f'<hh:align horizontal="{s.align}"', x, count=1)
    x = re.sub(r'keepWithNext="\d"', f'keepWithNext="{1 if s.keep_next else 0}"', x, count=1)
    for name, val in (("intent", s.intent), ("left", s.left), ("right", s.right), ("prev", s.prev), ("next", s.next)):
        x = re.sub(rf'<hc:{name} value="-?\d+" unit="HWPUNIT"/>', f'<hc:{name} value="{val}" unit="HWPUNIT"/>', x)
    gl, gr, gt, gb = s.gap
    x = re.sub(r"<hh:border [^>]*/>", f'<hh:border borderFillIDRef="{s.border}" offsetLeft="{gl}" offsetRight="{gr}" '
               f'offsetTop="{gt}" offsetBottom="{gb}" connect="{1 if s.connect else 0}" ignoreMargin="0"/>', x, count=1)
    return re.sub(r'<hh:lineSpacing type="PERCENT" value="\d+"', f'<hh:lineSpacing type="PERCENT" value="{s.line}"', x)


def _border_fills() -> str:
    def side(name: str, spec) -> str:
        if spec is None:
            return f'<hh:{name}Border type="NONE" width="0.1 mm" color="#000000"/>'
        width, color = spec
        return f'<hh:{name}Border type="SOLID" width="{width}" color="{color}"/>'

    def one(bid: int, fill: str = "", **sides) -> str:
        borders = "".join(side(n, sides.get(n)) for n in ("left", "right", "top", "bottom"))
        brush = f'<hc:fillBrush><hc:winBrush faceColor="{fill}" hatchColor="#999999" alpha="0"/></hc:fillBrush>' if fill else ""
        return (f'<hh:borderFill id="{bid}" threeD="0" shadow="0" centerLine="NONE" breakCellSeparateLine="0">'
                '<hh:slash type="NONE" Crooked="0" isCounter="0"/><hh:backSlash type="NONE" Crooked="0" isCounter="0"/>'
                f'{borders}<hh:diagonal type="SOLID" width="0.1 mm" color="#000000"/>{brush}</hh:borderFill>')
    grid = ("0.12 mm", "#B8C2D6")
    box = {k: grid for k in ("left", "right", "top", "bottom")}
    return (one(BORDER_TABLE, **box) + one(BORDER_HEAD, NAVY, **box) + one(BORDER_STRIPE, "#F5F7FB", **box)
            + one(BORDER_RULE, bottom=("0.12 mm", "#D5DBE6"))
            + one(BORDER_BAR, left=("0.7 mm", ACCENT))
            + one(BORDER_CALLOUT, "#FFF6DF", left=("0.7 mm", "#E2A100"))
            + one(BORDER_SUMMARY, "#EEF2FB", left=("0.7 mm", ACCENT))
            + one(BORDER_BAND, NAVY)
            + one(BORDER_ACCENT, bottom=("1.0 mm", ACCENT))
            + one(BORDER_META, top=("0.4 mm", ACCENT))   # (지금은 쓰지 않는다 — 한글은 위 테두리를 윗 간격 위에 그린다)
            + one(BORDER_TOC, bottom=("0.12 mm", "#E3E7EF")))




def build_header() -> str:
    """바탕 틀의 header.xml 에 보고서용 모양을 덧붙인다."""
    h = _read("header.xml").replace('secCnt="1"', 'secCnt="2"', 1)       # 구역이 둘 (표지 · 본문)
    char0 = re.search(r'<hh:charPr id="0".*?</hh:charPr>', h, re.S).group(0)
    para0 = re.search(r'<hh:paraPr id="0".*?</hh:paraPr>', h, re.S).group(0)

    def count(tag: str) -> int:
        return int(re.search(rf'<hh:{tag} itemCnt="(\d+)"', h).group(1))
    n_char, n_para, n_border = count("charProperties"), count("paraProperties"), count("borderFills")
    if (n_char, n_para, n_border) != (7, 20, 2):
        raise ValueError("HWPX 바탕 틀이 예상과 다릅니다.")
    chars = "".join(_char_pr(char0, CHAR_ID[k], s) for k, s in CHARS.items())
    paras = "".join(_para_pr(para0, PARA_ID[k], s) for k, s in PARAS.items())
    fills = _border_fills()
    added = len(re.findall(r"<hh:borderFill ", fills))
    h = h.replace(f'<hh:charProperties itemCnt="{n_char}">', f'<hh:charProperties itemCnt="{n_char + len(CHARS)}">', 1)
    h = h.replace("</hh:charProperties>", chars + "</hh:charProperties>", 1)
    h = h.replace(f'<hh:paraProperties itemCnt="{n_para}">', f'<hh:paraProperties itemCnt="{n_para + len(PARAS)}">', 1)
    h = h.replace("</hh:paraProperties>", paras + "</hh:paraProperties>", 1)
    h = h.replace(f'<hh:borderFills itemCnt="{n_border}">', f'<hh:borderFills itemCnt="{n_border + added}">', 1)
    return h.replace("</hh:borderFills>", fills + "</hh:borderFills>", 1)


# ---------------------------------------------------------------- 본문
class _Body:
    def __init__(self) -> None:
        self.parts: list[str] = []
        self._id = 0

    def pid(self) -> int:
        self._id += 1
        return self._id

    def para(self, para_key: str, inner: str, page_break: bool = False) -> str:
        return (f'<hp:p id="{self.pid()}" paraPrIDRef="{PARA_ID[para_key]}" styleIDRef="0" pageBreak="{1 if page_break else 0}" '
                f'columnBreak="0" merged="0">{inner}</hp:p>')

    def add(self, para_key: str, inner: str, page_break: bool = False) -> None:
        self.parts.append(self.para(para_key, inner, page_break))


def _run(char_key: str, text: str) -> str:
    t = f"<hp:t>{_esc(text)}</hp:t>" if text else "<hp:t/>"
    return f'<hp:run charPrIDRef="{CHAR_ID[char_key]}">{t}</hp:run>'


def _rich(text: str, base: str = "body", bold: str = "bodyB", keyword: bool = False) -> str:
    """**굵게** 표시를 굵은 글자로 (keyword=True 면 '핵심어: 설명' 의 핵심어도 — 워드 · 발표 자료와 같게)."""
    return "".join(_run(bold if b else base, t) for t, b in rich_parts(text, keyword))


def _heading_runs(text: str, level: int, auto: str) -> str:
    m = _HEAD_NUM.match(text)
    if m:
        return _run(f"h{level}n", m.group(1)) + _run(f"h{level}", m.group(2) + m.group(3))
    if auto:
        return _run(f"h{level}n", auto) + _run(f"h{level}", "  " + text)
    return _run(f"h{level}", text)


def _table(body: _Body, columns: list[str], rows: list[list[str]]) -> str:
    cols = max(1, len(columns))
    cw = BODY_WIDTH // cols
    grid = [columns] + rows
    numeric = [all(numeric_text(r[c]) or not r[c] for r in rows if c < len(r)) and any(c < len(r) and r[c] for r in rows)
               for c in range(cols)]

    def cell(text: str, r: int, c: int) -> str:
        head = r == 0
        fill = BORDER_HEAD if head else BORDER_STRIPE if r % 2 == 0 else BORDER_TABLE
        align = "cellC" if head else "cellR" if numeric[c] else "cell"      # 숫자 칸은 오른쪽 맞춤
        return (f'<hp:tc name="" header="{1 if head else 0}" hasMargin="0" protect="0" editable="0" dirty="0" '
                f'borderFillIDRef="{fill}">'
                '<hp:subList id="" textDirection="HORIZONTAL" lineWrap="BREAK" vertAlign="CENTER" linkListIDRef="0" '
                'linkListNextIDRef="0" textWidth="0" textHeight="0" hasTextRef="0" hasNumRef="0">'
                + body.para(align, _run("th" if head else "td", text)) +
                f'</hp:subList><hp:cellAddr colAddr="{c}" rowAddr="{r}"/><hp:cellSpan colSpan="1" rowSpan="1"/>'
                f'<hp:cellSz width="{cw}" height="1000"/><hp:cellMargin left="510" right="510" top="141" bottom="141"/></hp:tc>')
    trs = "".join("<hp:tr>" + "".join(cell(row[c] if c < len(row) else "", r, c) for c in range(cols)) + "</hp:tr>"
                  for r, row in enumerate(grid))
    tbl = (f'<hp:tbl id="{body.pid()}" zOrder="0" numberingType="TABLE" textWrap="TOP_AND_BOTTOM" textFlow="BOTH_SIDES" '
           'lock="0" dropcapstyle="None" pageBreak="CELL" repeatHeader="1" '
           f'rowCnt="{len(grid)}" colCnt="{cols}" cellSpacing="0" borderFillIDRef="{BORDER_TABLE}" noAdjust="0">'
           f'<hp:sz width="{cw * cols}" widthRelTo="ABSOLUTE" height="{1000 * len(grid)}" heightRelTo="ABSOLUTE" protect="0"/>'
           '<hp:pos treatAsChar="1" affectLSpacing="0" flowWithText="1" allowOverlap="0" holdAnchorAndSO="0" vertRelTo="PARA" '
           'horzRelTo="COLUMN" vertAlign="TOP" horzAlign="LEFT" vertOffset="0" horzOffset="0"/>'
           '<hp:outMargin left="0" right="0" top="0" bottom="0"/><hp:inMargin left="510" right="510" top="141" bottom="141"/>'
           f"{trs}</hp:tbl>")
    return body.para("body", f'<hp:run charPrIDRef="{CHAR_ID["body"]}">{tbl}</hp:run>')


def _box(b: _Body, key: str, label_char: str, label: str, lines: list[str], bullets: bool) -> None:
    """바탕색 + 왼쪽 막대 상자 (같은 문단 모양이 이어지면 한글이 한 상자로 그린다) 뒤에 작은 빈 문단."""
    if label:
        b.add(key, _run(label_char, label))
    for line in lines:
        b.add(key, (_run("body", "•  ") if bullets else "") + _rich(line, keyword=bullets))
    b.add("gap", _run("tiny", ""))


def _first_run(template: str, hide_first_num: bool, page_start: int, page_num: bool) -> str:
    """바탕 틀 첫 문단의 쪽 설정 묶음(secPr + 단 설정)을 구역에 맞게 고쳐 돌려준다."""
    run = re.search(r'<hp:run charPrIDRef="0"><hp:secPr.*?</hp:run>', template, re.S).group(0)
    run = run.replace('hideFirstPageNum="0"', f'hideFirstPageNum="{1 if hide_first_num else 0}"', 1)
    run = run.replace('<hp:startNum pageStartsOn="BOTH" page="0"', f'<hp:startNum pageStartsOn="BOTH" page="{page_start}"', 1)
    if page_num:      # 아래 가운데 쪽 번호
        run = run.replace("</hp:run>", '<hp:ctrl><hp:pageNum pos="BOTTOM_CENTER" formatType="DIGIT" sideChar="-"/></hp:ctrl></hp:run>')
    return run


def _wrap(template: str, parts: list[str], lead: str) -> str:
    """구역 파일: 바탕 틀의 머리(이름공간) + 첫 문단에 쪽 설정 묶음을 끼운 문단들."""
    head = template[:template.index("<hp:p ")]
    first = re.sub(r"(<hp:p [^>]*>)", lambda m: m.group(1) + lead, parts[0], count=1)
    return head + first + "".join(parts[1:]) + "</hs:sec>"


def build_sections(title: str, sections: list, subtitle: str = "", sources=None, summary=None) -> tuple[str, str, dict]:
    """본문 → (표지 section0.xml, 본문 section1.xml, {'sections': 장 수, 'tables': 표 수})."""
    b = _Body()
    items = [s if isinstance(s, dict) else {"paragraphs": [str(s)]} for s in sections]
    refs = [pretty_ref(_text(r)) for r in _strings(sources)]
    use_toc, autos, toc_rows = outline(items, refs)

    # ---- 표지
    subject, meta = _split_subtitle(subtitle)
    em = _em(title)
    cover = [b.para("band", _run("band", "REPORT")),
             b.para("ctitle", _run("ctitle" if em <= 14 else "ctitle2" if em <= 34 else "ctitle3", title)),
             b.para("crule", _run("tiny", ""))]
    if subject:
        cover.append(b.para("csub", _run("csub", subject)))
    for i, line in enumerate(meta):
        last = i == len(meta) - 1
        cover.append(b.para("cmeta1" if i == 0 else "cmeta", _run("cdate" if last else "cmeta", line)))

    # ---- 본문 구역 (목차 → 핵심 요약 → 장들)
    if use_toc:
        b.add("tlabel", _run("tlabel", "CONTENTS"))
        b.add("thead", _run("thead", "목차"))
        for level, num, text, _ in toc_rows:
            if level == 1:
                b.add("toc1", (_run("toc1n", num + "   ") if num else "") + _run("toc1", text))
            else:
                b.add("toc2", (_run("toc2", num + "  ") if num else "") + _run("toc2", text))
    s_title, s_lines, s_bullets = _box_lines(summary)
    if s_lines:
        if use_toc:
            b.add("gapB", _run("tiny", ""))
        _box(b, "boxs", "boxlabel", s_title or "핵심 요약", s_lines, s_bullets)
    tables = 0
    page_break = use_toc            # 목차 · 요약 쪽 다음에 본문을 새 쪽에서
    for idx, sec in enumerate(items):
        heading = _text(sec.get("heading"))
        level = 2 if str(sec.get("level", 1)).strip() == "2" else 1
        if heading:
            if level == 2:                               # 막대 상자 안에 윗 간격이 들어가지 않게, 간격은 빈 문단으로
                b.add("gapB", _run("tiny", ""), page_break)
                page_break = False
            b.add(f"h{level}", _heading_runs(heading, level, autos.get(idx, "") if level == 1 else ""), page_break)
            b.add("gapS", _run("tiny", ""))
            page_break = False
        for para in _strings(sec.get("paragraphs")):
            b.add("body", _rich(para.strip()))
        outline_pts = sec.get("points") if not (sec.get("paragraphs") or sec.get("bullets")) else None   # 개요만 받은 장
        for line, lvl in parse_bullets(sec.get("bullets") or outline_pts):
            b.add("list2" if lvl else "list", _run("body", "–  " if lvl else "•  ") + _rich(line, keyword=not lvl))
        c_title, c_lines, c_bullets = _box_lines(sec.get("callout"))
        if c_lines:
            _box(b, "boxc", "calllabel", c_title, c_lines, c_bullets)
        table = sec.get("table")
        if isinstance(table, dict) and table.get("columns"):
            cols = [_text(c) for c in table["columns"]]
            rows = [[_text(v) for v in r] for r in (table.get("rows") or []) if isinstance(r, (list, tuple))]
            b.parts.append(_table(b, cols, rows))
            if _text(table.get("caption")):
                b.add("caption", _run("caption", _text(table["caption"])))
            tables += 1
    if refs:
        b.add("h1", _run("h1", "참고 자료"))
        b.add("gapS", _run("tiny", ""))
        for i, r in enumerate(refs, 1):
            b.add("list", _run("ref", f"{i}.  {r}"))
    if not b.parts:
        b.add("body", _run("body", ""))
    tpl = _read("section0.xml")
    sec0 = _wrap(tpl, cover, _first_run(tpl, True, 0, False))                     # 표지: 쪽 번호 없음
    sec1 = _wrap(tpl, b.parts, _first_run(tpl, False, 1, True))                    # 본문: 1쪽부터
    return sec0, sec1, {"sections": len(sections), "tables": tables}


def build_section(title: str, sections: list, subtitle: str = "", sources=None, summary=None) -> tuple[str, dict]:
    """(옛 이름) 본문 구역 section1.xml → (XML, 개수)."""
    _, body, info = build_sections(title, sections, subtitle, sources, summary)
    return body, info


def _content_hpf(title: str) -> str:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    x = _read("content.hpf").replace("<opf:title/>", f"<opf:title>{_esc(title)}</opf:title>", 1)
    x = x.replace("synthetic-fixture-author", "J.A.R.V.I.S")
    x = x.replace('<opf:item id="section0" href="Contents/section0.xml" media-type="application/xml"/>',
                  '<opf:item id="section0" href="Contents/section0.xml" media-type="application/xml"/>'
                  '<opf:item id="section1" href="Contents/section1.xml" media-type="application/xml"/>', 1)
    x = x.replace('<opf:itemref idref="section0" linear="yes"/>',
                  '<opf:itemref idref="section0" linear="yes"/><opf:itemref idref="section1" linear="yes"/>', 1)
    x = re.sub(r'(<opf:meta name="CreatedDate" content="text">)[^<]*', lambda m: m.group(1) + now, x)
    x = re.sub(r'(<opf:meta name="ModifiedDate" content="text">)[^<]*', lambda m: m.group(1) + now, x)
    return re.sub(r'(<opf:meta name="date" content="text">)[^<]*',
                  lambda m: m.group(1) + _esc(datetime.now().strftime("%Y년 %m월 %d일")), x)


def _container_rdf() -> str:
    x = _read("container.rdf")
    part = ('<rdf:Description rdf:about=""><ns0:hasPart xmlns:ns0="http://www.hancom.co.kr/hwpml/2016/meta/pkg#" '
            'rdf:resource="Contents/section1.xml"/></rdf:Description><rdf:Description rdf:about="Contents/section1.xml">'
            '<rdf:type rdf:resource="http://www.hancom.co.kr/hwpml/2016/meta/pkg#SectionFile"/></rdf:Description>')
    mark = '<rdf:Description rdf:about=""><rdf:type rdf:resource="http://www.hancom.co.kr/hwpml/2016/meta/pkg#Document"/>'
    return x.replace(mark, part + mark, 1)


def build_hwpx(path: Path, title: str, sections: list, subtitle: str = "", sources=None, summary=None) -> dict:
    """보고서를 한글(.hwpx) 파일로 만든다 → {'sections': 장 수, 'tables': 표 수}."""
    title = _text(title)
    if not title:
        raise ValueError("문서 제목(title)이 필요합니다.")
    if not isinstance(sections, list) or not sections:
        raise ValueError("내용(sections)이 하나 이상 필요합니다.")
    sec0, sec1, info = build_sections(title, sections, subtitle, sources, summary)
    preview = "\r\n".join([title] + [_text(s.get("heading")) for s in sections if isinstance(s, dict) and s.get("heading")])
    with zipfile.ZipFile(str(path), "w") as z:
        # mimetype 은 맨 앞에, 압축하지 않고 (OCF 규칙 — 한글이 이것으로 형식을 알아본다)
        z.writestr(zipfile.ZipInfo("mimetype"), "application/hwp+zip", compress_type=zipfile.ZIP_STORED)
        for name, data in (
            ("version.xml", _read("version.xml")),
            ("Contents/header.xml", build_header()),
            ("Contents/section0.xml", sec0),
            ("Contents/section1.xml", sec1),
            ("Preview/PrvText.txt", preview[:1024]),
            ("settings.xml", _read("settings.xml")),
            ("META-INF/container.rdf", _container_rdf()),
            ("Contents/content.hpf", _content_hpf(title)),
            ("META-INF/container.xml", _read("container.xml")),
            ("META-INF/manifest.xml", _read("manifest.xml")),
        ):
            z.writestr(name, data, compress_type=zipfile.ZIP_DEFLATED)
    return info
