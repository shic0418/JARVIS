"""한글(HWPX) 문서 만들기 — 보고서를 한컴오피스 한글에서 바로 열리는 .hwpx 로 저장한다.

HWPX 는 한컴오피스의 열린 문서 형식(OWPML, KS X 6101)으로, XML 파일 몇 개를 ZIP 으로 묶은 것이다.
바탕 틀(hwpx_template/)은 python-hwpx(Apache-2.0)의 빈 문서 Skeleton.hwpx 에서 가져왔다 — hwpx_template/LICENSE-python-hwpx 참고.
그 틀의 글자 모양(charPr) · 문단 모양(paraPr) · 테두리(borderFill) 목록에 보고서용 모양을 덧붙이고, 본문(section0)에 문단을 채운다.
워드 보고서(office.build_document)와 같은 sections 를 받는다: heading · level · paragraphs · bullets · points · table.
표준 라이브러리만 쓴다 (한컴오피스가 없어도 만들 수 있다).
"""
from __future__ import annotations

import re
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .office import _strings, _text, numeric_text, parse_bullets, pretty_ref, rich_parts

TEMPLATE = Path(__file__).with_name("hwpx_template")
BODY_WIDTH = 42520          # A4 본문 폭 (바탕 틀의 쪽 여백 기준, HWPUNIT = 1/7200 인치)
ACCENT = "#1F3A8A"          # 워드 보고서와 같은 제목 색


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


@dataclass(frozen=True)
class ParaSpec:
    align: str                    # JUSTIFY · LEFT · CENTER
    left: int = 0
    intent: int = 0               # 음수면 내어쓰기
    prev: int = 0
    next: int = 0
    line: int = 160               # 줄 간격 %
    keep_next: bool = False


# 바탕 틀에 글자 모양 0~6 번, 문단 모양 0~19 번, 테두리 1~2 번이 있으므로 그 뒤에 붙인다
CHARS: dict[str, CharSpec] = {
    "body": CharSpec(11),
    "bodyB": CharSpec(11, bold=True),
    "title": CharSpec(22, bold=True, gothic=True, color="#16213A"),
    "subtitle": CharSpec(11, color="#6B7487"),
    "h1": CharSpec(16, bold=True, gothic=True, color=ACCENT),
    "h2": CharSpec(13, bold=True, gothic=True, color=ACCENT),
    "th": CharSpec(10, bold=True, gothic=True),
    "td": CharSpec(10),
    "caption": CharSpec(9, color="#6B7487"),
    "ref": CharSpec(10),
}
PARAS: dict[str, ParaSpec] = {
    "body": ParaSpec("JUSTIFY", next=600, line=165),
    "title": ParaSpec("CENTER", next=400, line=130),
    "subtitle": ParaSpec("CENTER", next=1400, line=130),
    "h1": ParaSpec("LEFT", prev=1800, next=600, line=130, keep_next=True),
    "h2": ParaSpec("LEFT", prev=1100, next=400, line=130, keep_next=True),
    "list": ParaSpec("LEFT", left=1800, intent=-1100, next=200, line=150),
    "list2": ParaSpec("LEFT", left=3400, intent=-1100, next=200, line=150),
    "cell": ParaSpec("LEFT", line=130),
    "cellR": ParaSpec("RIGHT", line=130),
    "cellC": ParaSpec("CENTER", line=130),
    "caption": ParaSpec("CENTER", prev=200, next=600, line=130),
}
CHAR_ID = {k: 7 + i for i, k in enumerate(CHARS)}
PARA_ID = {k: 20 + i for i, k in enumerate(PARAS)}
BORDER_TABLE, BORDER_HEAD, BORDER_STRIPE = 3, 4, 5


def _char_pr(template: str, cid: int, s: CharSpec) -> str:
    font = "0" if s.gothic else "1"
    x = re.sub(r' id="\d+"', f' id="{cid}"', template, count=1)
    x = re.sub(r'height="\d+"', f'height="{round(s.size * 100)}"', x, count=1)
    x = re.sub(r'textColor="#[0-9A-Fa-f]{6}"', f'textColor="{s.color}"', x, count=1)
    x = re.sub(r"<hh:fontRef [^>]*/>", "<hh:fontRef " + " ".join(
        f'{k}="{font}"' for k in ("hangul", "latin", "hanja", "japanese", "other", "symbol", "user")) + "/>", x, count=1)
    marks = ("<hh:italic/>" if s.italic else "") + ("<hh:bold/>" if s.bold else "")   # 스키마 순서: offset 다음 italic, bold
    if marks:
        x = re.sub(r"(<hh:offset [^>]*/>)", lambda m: m.group(1) + marks, x, count=1)
    return x


def _para_pr(template: str, pid: int, s: ParaSpec) -> str:
    x = re.sub(r' id="\d+"', f' id="{pid}"', template, count=1)
    x = re.sub(r'<hh:align horizontal="\w+"', f'<hh:align horizontal="{s.align}"', x, count=1)
    x = re.sub(r'keepWithNext="\d"', f'keepWithNext="{1 if s.keep_next else 0}"', x, count=1)
    for name, val in (("intent", s.intent), ("left", s.left), ("prev", s.prev), ("next", s.next)):
        x = re.sub(rf'<hc:{name} value="-?\d+" unit="HWPUNIT"/>', f'<hc:{name} value="{val}" unit="HWPUNIT"/>', x)
    return re.sub(r'<hh:lineSpacing type="PERCENT" value="\d+"', f'<hh:lineSpacing type="PERCENT" value="{s.line}"', x)


def _border_fills() -> str:
    sides = "".join(f'<hh:{s}Border type="SOLID" width="0.12 mm" color="#B8C2D6"/>' for s in ("left", "right", "top", "bottom"))

    def one(bid: int, fill: str) -> str:
        return (f'<hh:borderFill id="{bid}" threeD="0" shadow="0" centerLine="NONE" breakCellSeparateLine="0">'
                '<hh:slash type="NONE" Crooked="0" isCounter="0"/><hh:backSlash type="NONE" Crooked="0" isCounter="0"/>'
                f'{sides}<hh:diagonal type="SOLID" width="0.1 mm" color="#000000"/>{fill}</hh:borderFill>')
    def fill(color: str) -> str:
        return f'<hc:fillBrush><hc:winBrush faceColor="{color}" hatchColor="#999999" alpha="0"/></hc:fillBrush>'
    return one(BORDER_TABLE, "") + one(BORDER_HEAD, fill("#DCE4F7")) + one(BORDER_STRIPE, fill("#F5F7FB"))


def build_header() -> str:
    """바탕 틀의 header.xml 에 보고서용 모양을 덧붙인다."""
    h = _read("header.xml")
    char0 = re.search(r'<hh:charPr id="0".*?</hh:charPr>', h, re.S).group(0)
    para0 = re.search(r'<hh:paraPr id="0".*?</hh:paraPr>', h, re.S).group(0)

    def count(tag: str) -> int:
        return int(re.search(rf'<hh:{tag} itemCnt="(\d+)"', h).group(1))
    n_char, n_para, n_border = count("charProperties"), count("paraProperties"), count("borderFills")
    if (n_char, n_para, n_border) != (7, 20, 2):
        raise ValueError("HWPX 바탕 틀이 예상과 다릅니다.")
    chars = "".join(_char_pr(char0, CHAR_ID[k], s) for k, s in CHARS.items())
    paras = "".join(_para_pr(para0, PARA_ID[k], s) for k, s in PARAS.items())
    h = h.replace(f'<hh:charProperties itemCnt="{n_char}">', f'<hh:charProperties itemCnt="{n_char + len(CHARS)}">', 1)
    h = h.replace("</hh:charProperties>", chars + "</hh:charProperties>", 1)
    h = h.replace(f'<hh:paraProperties itemCnt="{n_para}">', f'<hh:paraProperties itemCnt="{n_para + len(PARAS)}">', 1)
    h = h.replace("</hh:paraProperties>", paras + "</hh:paraProperties>", 1)
    h = h.replace(f'<hh:borderFills itemCnt="{n_border}">', f'<hh:borderFills itemCnt="{n_border + 3}">', 1)
    return h.replace("</hh:borderFills>", _border_fills() + "</hh:borderFills>", 1)


# ---------------------------------------------------------------- 본문
class _Body:
    def __init__(self) -> None:
        self.parts: list[str] = []
        self._id = 0

    def pid(self) -> int:
        self._id += 1
        return self._id

    def para(self, para_key: str, inner: str) -> str:
        return (f'<hp:p id="{self.pid()}" paraPrIDRef="{PARA_ID[para_key]}" styleIDRef="0" pageBreak="0" '
                f'columnBreak="0" merged="0">{inner}</hp:p>')

    def add(self, para_key: str, inner: str) -> None:
        self.parts.append(self.para(para_key, inner))


def _run(char_key: str, text: str) -> str:
    t = f"<hp:t>{_esc(text)}</hp:t>" if text else "<hp:t/>"
    return f'<hp:run charPrIDRef="{CHAR_ID[char_key]}">{t}</hp:run>'


def _rich(text: str, base: str = "body", bold: str = "bodyB", keyword: bool = False) -> str:
    """**굵게** 표시를 굵은 글자로 (keyword=True 면 '핵심어: 설명' 의 핵심어도 — 워드 · 발표 자료와 같게)."""
    return "".join(_run(bold if b else base, t) for t, b in rich_parts(text, keyword))


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


def build_section(title: str, sections: list, subtitle: str = "", sources=None) -> tuple[str, dict]:
    """본문 section0.xml → (XML, {'sections': 장 수, 'tables': 표 수})."""
    b = _Body()
    b.add("title", _run("title", title))
    if _text(subtitle):
        b.add("subtitle", _run("subtitle", _text(subtitle)))
    tables = 0
    for sec in sections:
        if not isinstance(sec, dict):
            sec = {"paragraphs": [str(sec)]}
        heading = _text(sec.get("heading"))
        level = 2 if str(sec.get("level", 1)).strip() == "2" else 1
        if heading:
            b.add(f"h{level}", _run(f"h{level}", heading))
        for para in _strings(sec.get("paragraphs")):
            b.add("body", _rich(para.strip()))
        outline = sec.get("points") if not (sec.get("paragraphs") or sec.get("bullets")) else None   # 개요만 받은 장
        for line, lvl in parse_bullets(sec.get("bullets") or outline):
            b.add("list2" if lvl else "list", _run("body", "–  " if lvl else "•  ") + _rich(line, keyword=not lvl))
        table = sec.get("table")
        if isinstance(table, dict) and table.get("columns"):
            cols = [_text(c) for c in table["columns"]]
            rows = [[_text(v) for v in r] for r in (table.get("rows") or []) if isinstance(r, (list, tuple))]
            b.parts.append(_table(b, cols, rows))
            if _text(table.get("caption")):
                b.add("caption", _run("caption", _text(table["caption"])))
            tables += 1
    refs = [pretty_ref(_text(r)) for r in _strings(sources)]
    if refs:
        b.add("h1", _run("h1", "참고 자료"))
        for i, r in enumerate(refs, 1):
            b.add("list", _run("ref", f"{i}.  {r}"))
    section = _read("section0.xml")
    # 첫 문단(쪽 설정이 든 바탕 틀 문단)에 아래 가운데 쪽 번호를 넣는다
    section = section.replace(
        '<hp:ctrl><hp:colPr id="" type="NEWSPAPER" layout="LEFT" colCount="1" sameSz="1" sameGap="0"/></hp:ctrl>',
        '<hp:ctrl><hp:colPr id="" type="NEWSPAPER" layout="LEFT" colCount="1" sameSz="1" sameGap="0"/></hp:ctrl>'
        '<hp:ctrl><hp:pageNum pos="BOTTOM_CENTER" formatType="DIGIT" sideChar="-"/></hp:ctrl>', 1)
    return section.replace("</hs:sec>", "".join(b.parts) + "</hs:sec>"), {"sections": len(sections), "tables": tables}


def _content_hpf(title: str) -> str:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    x = _read("content.hpf").replace("<opf:title/>", f"<opf:title>{_esc(title)}</opf:title>", 1)
    x = x.replace("synthetic-fixture-author", "J.A.R.V.I.S")
    x = re.sub(r'(<opf:meta name="CreatedDate" content="text">)[^<]*', lambda m: m.group(1) + now, x)
    x = re.sub(r'(<opf:meta name="ModifiedDate" content="text">)[^<]*', lambda m: m.group(1) + now, x)
    return re.sub(r'(<opf:meta name="date" content="text">)[^<]*',
                  lambda m: m.group(1) + _esc(datetime.now().strftime("%Y년 %m월 %d일")), x)


def build_hwpx(path: Path, title: str, sections: list, subtitle: str = "", sources=None) -> dict:
    """보고서를 한글(.hwpx) 파일로 만든다 → {'sections': 장 수, 'tables': 표 수}."""
    title = _text(title)
    if not title:
        raise ValueError("문서 제목(title)이 필요합니다.")
    if not isinstance(sections, list) or not sections:
        raise ValueError("내용(sections)이 하나 이상 필요합니다.")
    section, info = build_section(title, sections, subtitle, sources)
    preview = "\r\n".join([title] + [_text(s.get("heading")) for s in sections if isinstance(s, dict) and s.get("heading")])
    with zipfile.ZipFile(str(path), "w") as z:
        # mimetype 은 맨 앞에, 압축하지 않고 (OCF 규칙 — 한글이 이것으로 형식을 알아본다)
        z.writestr(zipfile.ZipInfo("mimetype"), "application/hwp+zip", compress_type=zipfile.ZIP_STORED)
        for name, data in (
            ("version.xml", _read("version.xml")),
            ("Contents/header.xml", build_header()),
            ("Contents/section0.xml", section),
            ("Preview/PrvText.txt", preview[:1024]),
            ("settings.xml", _read("settings.xml")),
            ("META-INF/container.rdf", _read("container.rdf")),
            ("Contents/content.hpf", _content_hpf(title)),
            ("META-INF/container.xml", _read("container.xml")),
            ("META-INF/manifest.xml", _read("manifest.xml")),
        ):
            z.writestr(name, data, compress_type=zipfile.ZIP_DEFLATED)
    return info
