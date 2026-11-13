"""보고서(Word .docx) 그리기 — 표지 · 목차 · 본문(머리글 · 쪽 번호) 을 갖춘 보고서 모양.

구성
  · 표지 구역: 'REPORT' 띠 · 아이콘 · 큰 제목 · 부제 · 오른쪽 아래 정보(과목 · 이름 · 날짜). 머리글 · 쪽 번호가 없다.
  · 본문 구역: 머리글(제목) · 아래 가운데 쪽 번호(1부터). 큰 장이 3개 이상이면 목차 쪽이 맨 앞에 붙는다.
  · 큰 제목은 강조색 번호 + 연한 아래 줄, 작은 제목은 왼쪽 막대, 핵심 요약 · 강조 상자는 연한 바탕 + 왼쪽 막대,
    표는 짙은 남색 머리글 줄 + 줄무늬.
문단 · 구역 속성은 OOXML 스키마가 정한 자식 순서대로 넣는다 (순서가 틀리면 워드가 파일을 못 연다).
이 파일은 그리기만 한다 (입력 검사 · 저장 이름은 office.build_document · tools.py).
"""
from __future__ import annotations

import datetime
import io
import re

from . import icons
from .office import FONT, _docx_font, _em, _strings, _text, numeric_text, parse_bullets, pretty_ref, rich_parts

NAVY = "16213A"        # 제목 · 표 머리글 (짙은 남색)
ACCENT = "1F3A8A"      # 번호 · 막대 (강조색)
MUTED = "6B7487"
RULE = "D5DBE6"        # 연한 줄
SUMMARY_FILL, SUMMARY_BAR = "EEF2FB", ACCENT
CALLOUT_FILL, CALLOUT_BAR = "FFF6DF", "E2A100"
TEXT_WIDTH = 9185      # A4 본문 폭 (좌우 여백 2.4 cm) — twip

_PPR = ("pStyle keepNext keepLines pageBreakBefore framePr widowControl numPr suppressLineNumbers pBdr shd tabs "
        "suppressAutoHyphens kinsoku wordWrap overflowPunct topLinePunct autoSpaceDE autoSpaceDN bidi adjustRightInd "
        "snapToGrid spacing ind contextualSpacing mirrorIndents suppressOverlap jc textDirection textAlignment "
        "textboxTightWrap outlineLvl divId cnfStyle rPr sectPr pPrChange").split()
_RPR = ("rStyle rFonts b bCs i iCs caps smallCaps strike dstrike outline shadow emboss imprint noProof snapToGrid vanish "
        "webHidden color spacing w kern position sz szCs highlight u effect bdr shd fitText vertAlign rtl cs em lang "
        "eastAsianLayout specVanish oMath").split()
_TBLPR = ("tblStyle tblpPr tblOverlap bidiVisual tblStyleRowBandSize tblStyleColBandSize tblW jc tblCellSpacing tblInd "
          "tblBorders shd tblLayout tblCellMar tblLook tblCaption tblDescription").split()
_TCPR = ("cnfStyle tcW gridSpan hMerge vMerge tcBorders shd noWrap tcMar textDirection tcFitText vAlign hideMark").split()
_TRPR = "cnfStyle divId gridBefore gridAfter wBefore wAfter cantSplit trHeight tblHeader tblCellSpacing jc hidden".split()
_SECTPR = ("headerReference footerReference footnotePr endnotePr type pgSz pgMar paperSrc pgBorders lnNumType pgNumType "
           "cols formProt vAlign noEndnote titlePg textDirection bidi rtlGutter docGrid printerSettings").split()


# ---------------------------------------------------------------- XML 도구
def _el(tag: str, **attrs):
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    e = OxmlElement(tag)
    for k, v in attrs.items():
        e.set(qn(f"w:{k}"), str(v))
    return e


def _put(parent, el, order: list[str]):
    """el 을 스키마 순서(order)에 맞는 자리에 넣는다 (같은 태그가 이미 있으면 바꾼다)."""
    for old in parent.findall(el.tag):
        parent.remove(old)
    me = order.index(el.tag.split("}")[1])
    for child in parent:
        name = child.tag.split("}")[1]
        if name in order and order.index(name) > me:
            child.addprevious(el)
            return el
    parent.append(el)
    return el


def _borders(ppr, **sides) -> None:
    """문단 테두리. 예: left=(굵기 1/8pt, 글과 간격 pt, 색), top=…, bottom=…"""
    bdr = _el("w:pBdr")
    for side in ("top", "left", "bottom", "right"):
        if side in sides:
            sz, space, color = sides[side]
            bdr.append(_el(f"w:{side}", val="single", sz=sz, space=space, color=color))
    _put(ppr, bdr, _PPR)


def _shd(parent, fill: str, order: list[str]) -> None:
    _put(parent, _el("w:shd", val="clear", color="auto", fill=fill), order)


def _spacing(ppr, before: float = 0, after: float = 0, line: float | None = None) -> None:
    """문단 앞뒤 간격(pt) · 줄 간격(배)."""
    attrs = {"before": round(before * 20), "after": round(after * 20)}
    if line:
        attrs.update(line=round(line * 240), lineRule="auto")
    _put(ppr, _el("w:spacing", **attrs), _PPR)


def _indent(ppr, left: int = 0, right: int = 0, first: int | None = None) -> None:
    attrs = {"left": left, "right": right}
    if first is not None:
        attrs["hanging" if first < 0 else "firstLine"] = abs(first)
    _put(ppr, _el("w:ind", **attrs), _PPR)


def _run(p, text: str, size: float | None = None, bold: bool | None = None, color: str | None = None,
         track: int = 0, parent=None):
    """글 조각 하나. track: 글자 사이 넓힘(1/20 pt). parent: 문단 대신 이 요소(하이퍼링크 등) 속에 넣을 때."""
    from docx.shared import Pt, RGBColor
    r = p.add_run(text)
    if size:
        r.font.size = Pt(size)
    if bold is not None:
        r.font.bold = bold
    if color:
        r.font.color.rgb = RGBColor.from_string(color)
    if track:
        _put(r._r.get_or_add_rPr(), _el("w:spacing", val=track), _RPR)
    if parent is not None:
        parent.append(r._r)
    return r


# ---------------------------------------------------------------- 글자 모양 (스타일)
def _style(doc, name: str, size: float, color: str, bold: bool = True, italic: bool = False):
    from docx.oxml.ns import qn
    from docx.shared import Pt, RGBColor
    st = doc.styles[name]
    _docx_font(st.font, st.element)
    st.font.size, st.font.bold, st.font.italic = Pt(size), bold, italic
    st.font.color.rgb = RGBColor.from_string(color)
    rpr = st.element.get_or_add_rPr()
    for tag in ("w:spacing", "w:kern"):                      # 바탕 틀의 글자 사이 · 자간 맞춤은 지운다
        for e in rpr.findall(qn(tag)):
            rpr.remove(e)
    return st


def _ppr_of(style):
    from docx.oxml.ns import qn
    ppr = style.element.get_or_add_pPr()
    for e in ppr.findall(qn("w:pBdr")):
        ppr.remove(e)
    return ppr


def setup_styles(doc) -> None:
    from docx.shared import Pt
    normal = doc.styles["Normal"]
    _docx_font(normal.font, normal.element)
    normal.font.size = Pt(11)
    normal.paragraph_format.line_spacing = 1.45
    normal.paragraph_format.space_after = Pt(6)
    _style(doc, "Title", 34, NAVY)
    ppr = _ppr_of(doc.styles["Title"])
    _spacing(ppr, 0, 10, 1.15)
    _style(doc, "Subtitle", 15, MUTED, bold=False)
    _spacing(_ppr_of(doc.styles["Subtitle"]), 0, 8, 1.3)
    _style(doc, "Heading 1", 17, NAVY)
    ppr = _ppr_of(doc.styles["Heading 1"])
    _spacing(ppr, 24, 10, 1.2)
    _borders(ppr, bottom=(6, 4, RULE))
    _style(doc, "Heading 2", 13, NAVY)
    ppr = _ppr_of(doc.styles["Heading 2"])
    _spacing(ppr, 14, 6, 1.2)
    _indent(ppr, left=170)
    _borders(ppr, left=(30, 6, ACCENT))
    for name, size in (("List Bullet", 11), ("List Number", 10)):
        st = doc.styles[name]
        _docx_font(st.font, st.element)
        st.font.size = Pt(size)


# ---------------------------------------------------------------- 표지
def _icon_picture(name: str, px: int = 360) -> bytes | None:
    """남색 동그라미 위에 흰 아이콘 (아이콘 글꼴이 없으면 None)."""
    glyph = icons.png(name, "FFFFFF", int(px * 0.56)) if name else None
    if not glyph:
        return None
    from PIL import Image, ImageDraw
    base = Image.new("RGBA", (px, px), (0, 0, 0, 0))
    ImageDraw.Draw(base).ellipse((0, 0, px - 1, px - 1), fill=tuple(int(NAVY[i:i + 2], 16) for i in (0, 2, 4)) + (255,))
    g = Image.open(io.BytesIO(glyph)).convert("RGBA")
    base.alpha_composite(g, ((px - g.width) // 2, (px - g.height) // 2))
    out = io.BytesIO()
    base.save(out, "PNG", optimize=True)
    return out.getvalue()


def _fixed_table(doc, widths: list[int]):
    """칸 너비가 고정된 표 (twip)."""
    from docx.shared import Twips
    t = doc.add_table(rows=0, cols=len(widths))
    t.autofit = False
    pr = t._tbl.tblPr
    _put(pr, _el("w:tblW", w=sum(widths), type="dxa"), _TBLPR)
    _put(pr, _el("w:tblLayout", type="fixed"), _TBLPR)
    for col, w in zip(t.columns, widths):
        col.width = Twips(w)
    return t


def _cell_prep(cell, width: int, fill: str | None = None, valign: str = "center", margins: tuple | None = None) -> None:
    pr = cell._tc.get_or_add_tcPr()
    _put(pr, _el("w:tcW", w=width, type="dxa"), _TCPR)
    if fill:
        _shd(pr, fill, _TCPR)
    if margins:
        mar = _el("w:tcMar")
        for side, v in zip(("top", "left", "bottom", "right"), margins):
            mar.append(_el(f"w:{side}", w=v, type="dxa"))
        _put(pr, mar, _TCPR)
    _put(pr, _el("w:vAlign", val=valign), _TCPR)


def _cover_band(doc) -> None:
    """맨 위의 'REPORT' 띠: 왼쪽 강조색 조각 + 남색 띠."""
    widths = [300, TEXT_WIDTH - 300]
    t = _fixed_table(doc, widths)
    row = t.add_row()
    _put(row._tr.get_or_add_trPr(), _el("w:trHeight", val=560, hRule="exact"), _TRPR)
    for cell, w, fill in zip(row.cells, widths, (ACCENT, NAVY)):
        _cell_prep(cell, w, fill, margins=(0, 240 if fill == NAVY else 0, 0, 0))
    p = row.cells[1].paragraphs[0]
    _spacing(p._p.get_or_add_pPr(), 0, 0, 1.0)
    _run(p, "REPORT", 11, True, "FFFFFF", track=80)


def _split_subtitle(subtitle: str) -> tuple[str, list[str]]:
    """'과학 · 홍길동' → ('과학', ['홍길동', 오늘 날짜]). 부제에 연도가 있으면 날짜는 더하지 않는다."""
    parts = [x.strip() for x in re.split(r"\s*[·|•]\s*", _text(subtitle)) if x.strip()]
    meta = parts[1:]
    if not re.search(r"(?:19|20)\d{2}", _text(subtitle)):
        meta.append(datetime.date.today().strftime("%Y. %m. %d"))
    return (parts[0] if parts else ""), meta


def _cover(doc, title: str, subtitle: str, icon: str | None) -> None:
    from docx.shared import Cm, Pt
    _cover_band(doc)
    p = doc.add_paragraph()
    _spacing(p._p.get_or_add_pPr(), 110, 0)
    pic = _icon_picture(icons.pick(icon, title, subtitle, kind="report")) if icons.available() else None
    if pic:
        p.add_run().add_picture(io.BytesIO(pic), width=Cm(2.4))
    size = 34 if _em(title) <= 14 else 28 if _em(title) <= 22 else 24 if _em(title) <= 34 else 20
    t = doc.add_paragraph(title, style="Title")
    _spacing(t._p.get_or_add_pPr(), 26, 12, 1.15)
    t.runs[0].font.size = Pt(size)
    rule = doc.add_paragraph()                                  # 제목 밑의 짧은 강조 줄
    rp = rule._p.get_or_add_pPr()
    _spacing(rp, 0, 14)
    _indent(rp, right=TEXT_WIDTH - 1700)
    _borders(rp, bottom=(36, 1, ACCENT))
    subject, meta = _split_subtitle(subtitle)
    if subject:
        doc.add_paragraph(subject, style="Subtitle")
    if meta:                                                    # 오른쪽 아래에 붙는 정보 상자 (쪽 아래 끝 맞춤)
        m = doc.add_paragraph()
        mp = m._p.get_or_add_pPr()
        frame = _el("w:framePr", w=4400, hRule="auto", wrap="around", vAnchor="margin", hAnchor="margin",
                    xAlign="right", yAlign="bottom")
        _put(mp, frame, _PPR)
        _borders(mp, top=(12, 8, ACCENT))
        _spacing(mp, 0, 0, 1.5)
        _put(mp, _el("w:jc", val="right"), _PPR)
        for i, line in enumerate(meta):
            r = _run(m, line, 11 if i < len(meta) - 1 else 11.5, i == len(meta) - 1, NAVY if i == len(meta) - 1 else MUTED)
            if i < len(meta) - 1:
                r.add_break()


# ---------------------------------------------------------------- 머리글 · 쪽 번호
def _field(paragraph, code: str, size: float, color: str) -> None:
    for kind in ("begin", "instr", "end"):
        r = _run(paragraph, "", size, None, color)
        if kind == "instr":
            el = _el("w:instrText")
            el.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
            el.text = f" {code} "
        else:
            el = _el("w:fldChar", fldCharType=kind)
        r._r.append(el)


def _header_footer(section, title: str) -> None:
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    section.header.is_linked_to_previous = False
    section.footer.is_linked_to_previous = False
    hp = section.header.paragraphs[0]
    hp.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    _borders(hp._p.get_or_add_pPr(), bottom=(4, 4, RULE))
    _run(hp, title, 9, False, MUTED)
    fp = section.footer.paragraphs[0]
    fp.alignment = WD_ALIGN_PARAGRAPH.CENTER
    _field(fp, "PAGE", 10, MUTED)


# ---------------------------------------------------------------- 제목 · 목차 · 상자
_HEAD_NUM = re.compile(r"^(\d{1,2}(?:[.\-]\d{1,2})*[.)]?)(\s+)(\S.*)$")


class _Marks:
    """제목마다 책갈피를 달아 목차에서 눌러 이동할 수 있게 한다."""

    def __init__(self) -> None:
        self.n = 0

    def wrap(self, p, name: str) -> None:
        self.n += 1
        start = _el("w:bookmarkStart", id=self.n, name=name)
        end = _el("w:bookmarkEnd", id=self.n)
        runs = p._p.findall("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}r")
        if runs:
            runs[0].addprevious(start)
            runs[-1].addnext(end)


def _heading(doc, marks: _Marks, text: str, level: int, auto: str, name: str, page_break: bool = False):
    p = doc.add_paragraph(style=f"Heading {level}")
    m = _HEAD_NUM.match(text)
    if m:
        _run(p, m.group(1), color=ACCENT)
        _run(p, m.group(2) + m.group(3))
    elif auto:
        _run(p, auto, color=ACCENT)
        _run(p, "  " + text)
    else:
        _run(p, text)
    if page_break:
        _put(p._p.get_or_add_pPr(), _el("w:pageBreakBefore"), _PPR)
    marks.wrap(p, name)
    return p


def _toc(doc, entries: list[tuple[int, str, str, str]]) -> None:
    """목차 쪽: (수준, 번호, 제목, 책갈피) 목록. 쪽 번호 없이 눌러서 이동하는 목록."""
    label = doc.add_paragraph()
    _spacing(label._p.get_or_add_pPr(), 0, 0)
    _run(label, "CONTENTS", 9.5, True, ACCENT, track=60)
    head = doc.add_paragraph()
    hp = head._p.get_or_add_pPr()
    _spacing(hp, 2, 16, 1.2)
    _run(head, "목차", 24, True, NAVY)
    numbered = any(num for _, num, _, _ in entries)
    for level, num, text, mark in entries:
        p = doc.add_paragraph()
        ppr = p._p.get_or_add_pPr()
        _borders(ppr, bottom=(4, 5, "E3E7EF"))
        _put(ppr, _el("w:tabs"), _PPR).append(_el("w:tab", val="left", pos=700 if level == 1 else 1150))
        _spacing(ppr, 3, 3, 1.3)
        if level == 2:
            _indent(ppr, left=450)
        link = _el("w:hyperlink", anchor=mark, history=1)
        p._p.append(link)
        if num:
            _run(p, num, 12 if level == 1 else 10.5, True, ACCENT, parent=link)
        _run(p, ("\t" if num or (numbered and level == 1) else "") + text, 12 if level == 1 else 10.5, level == 1, NAVY if level == 1 else MUTED,
             parent=link)


def _box_lines(v) -> tuple[str, list[str], bool]:
    """상자 내용 읽기: 글 · 글 목록 · {title, text|bullets} → (작은 제목, 줄들, 글머리 기호를 붙일지)."""
    title = ""
    if isinstance(v, dict):
        title = _text(v.get("title") or v.get("heading") or v.get("label"))
        v = v.get("bullets") or v.get("points") or v.get("text") or v.get("paragraphs")
    bullets = isinstance(v, (list, tuple))
    return title, [x.strip() for x in _strings(v)], bullets


def _box(doc, label: str, lines: list[str], bullets: bool, fill: str, bar: str) -> None:
    """연한 바탕 + 왼쪽 막대 상자 (같은 모양의 문단이 이어지면 워드가 하나의 상자로 그린다)."""
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    rows = ([("label", label)] if label else []) + [("line", x) for x in lines]
    for i, (kind, text) in enumerate(rows):
        p = doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.LEFT
        ppr = p._p.get_or_add_pPr()
        _borders(ppr, top=(4, 6, fill), left=(36, 8, bar), bottom=(4, 6, fill))
        _shd(ppr, fill, _PPR)
        _spacing(ppr, 10 if i == 0 else 0, 14 if i == len(rows) - 1 else 3, 1.4)
        _indent(ppr, left=420, right=120, first=-260 if bullets else None)   # 모든 문단의 들여쓰기가 같아야 한 상자로 이어진다
        if kind == "label":
            _run(p, label, 10, True, bar if bar != CALLOUT_BAR else "9A6B00", track=40)
        else:
            if bullets:
                _run(p, "•  ", 11, True, bar)
            for t, b in rich_parts(text, keyword=bullets):
                _run(p, t, 11, True if b else None)


# ---------------------------------------------------------------- 표
def _table(doc, cols: list[str], rows: list, caption: str) -> None:
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.shared import Pt
    n = len(cols)
    lens = [min(max(max([_em(cols[j])] + [_em(_text(r[j])) for r in rows if j < len(r)]), 4), 24) for j in range(n)]
    widths = [max(int(TEXT_WIDTH * v / sum(lens)), 1000) for v in lens]
    widths[-1] += TEXT_WIDTH - sum(widths)
    numeric = [any(j < len(r) and _text(r[j]) for r in rows)
               and all(not _text(r[j]) or numeric_text(r[j]) for r in rows if j < len(r)) for j in range(n)]
    t = _fixed_table(doc, widths)
    pr = t._tbl.tblPr
    line = {"val": "single", "sz": 4, "space": 0, "color": "C3CBDB"}
    bd = _el("w:tblBorders")
    for side in ("top", "left", "bottom", "right", "insideH", "insideV"):
        bd.append(_el(f"w:{side}", **(line if side in ("top", "bottom", "insideH") else {"val": "nil"})))
    _put(pr, bd, _TBLPR)
    mar = _el("w:tblCellMar")
    for side, v in (("top", 70), ("left", 130), ("bottom", 70), ("right", 130)):
        mar.append(_el(f"w:{side}", w=v, type="dxa"))
    _put(pr, mar, _TBLPR)
    for r in range(len(rows) + 1):
        row = t.add_row()
        trpr = row._tr.get_or_add_trPr()
        _put(trpr, _el("w:cantSplit"), _TRPR)
        if r == 0:
            _put(trpr, _el("w:tblHeader"), _TRPR)
        fill = NAVY if r == 0 else "F3F5FA" if r % 2 == 0 else None
        for j in range(n):
            cell = row.cells[j]
            _cell_prep(cell, widths[j], fill)
            text = cols[j] if r == 0 else (_text(rows[r - 1][j]) if j < len(rows[r - 1]) else "")
            p = cell.paragraphs[0]
            ppr = p._p.get_or_add_pPr()
            _spacing(ppr, 0, 0, 1.25)
            if len(rows) <= 12 and r < len(rows):
                _put(ppr, _el("w:keepNext"), _PPR)               # 작은 표는 쪽을 넘어 갈라지지 않게
            p.alignment = (WD_ALIGN_PARAGRAPH.CENTER if r == 0 else
                           WD_ALIGN_PARAGRAPH.RIGHT if numeric[j] else WD_ALIGN_PARAGRAPH.LEFT)
            _run(p, text, 10, True if r == 0 or j == 0 else None, "FFFFFF" if r == 0 else None)
    cap = doc.add_paragraph()
    cap.alignment = WD_ALIGN_PARAGRAPH.CENTER
    _spacing(cap._p.get_or_add_pPr(), 4, 10)
    if caption:
        _run(cap, caption, 9, False, MUTED)
    else:
        _run(cap, "", 2)                                         # 표 뒤에는 늘 문단이 있어야 한다 (아주 작게)
        _spacing(cap._p.get_or_add_pPr(), 0, 6)


def outline(items: list[dict], refs: list) -> tuple[bool, dict[int, str], list[tuple[int, str, str, str]]]:
    """장 목록 훑기 → (목차를 둘지, {장 번호: 큰 제목에 붙일 자동 번호}, 목차 줄들[(수준, 번호, 제목, 책갈피)]).
    큰 제목이 3개 이상이면 목차를 둔다. 제목에 번호('1.')가 하나도 없으면 01 · 02 … 를 붙인다."""
    lead = [s for s in items if _text(s.get("heading")) and str(s.get("level", 1)).strip() != "2"]
    numbered = any(_HEAD_NUM.match(_text(s.get("heading"))) for s in lead)          # 번호를 직접 붙여 줬나
    autos: dict[int, str] = {}
    k = 0
    for idx, s in enumerate(items):
        if s in lead:
            k += 1
            autos[idx] = "" if numbered else f"{k:02d}"
    rows = []
    for idx, s in enumerate(items):
        h = _text(s.get("heading"))
        if not h:
            continue
        lv = 2 if str(s.get("level", 1)).strip() == "2" else 1
        m = _HEAD_NUM.match(h)
        rows.append((lv, m.group(1) if m else autos.get(idx, "") if lv == 1 else "", m.group(3) if m else h, f"_Toc{idx + 1}"))
    if refs:
        rows.append((1, "", "참고 자료", "_Toc_refs"))
    return len(lead) >= 3, autos, rows


# ---------------------------------------------------------------- 보고서 전체
def build(path, title: str, sections: list, subtitle: str = "", sources=None, summary=None, icon: str | None = None) -> dict:
    from docx import Document
    from docx.enum.section import WD_SECTION
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.shared import Cm
    from docx.oxml.ns import qn
    doc = Document()
    sec = doc.sections[0]
    sec.page_width, sec.page_height = Cm(21.0), Cm(29.7)
    sec.top_margin = sec.bottom_margin = Cm(2.5)
    sec.left_margin = sec.right_margin = Cm(2.4)
    sec.header_distance = sec.footer_distance = Cm(1.25)
    setup_styles(doc)

    items = [s if isinstance(s, dict) else {"paragraphs": [str(s)]} for s in sections]
    refs = [pretty_ref(_text(r)) for r in _strings(sources)]
    use_toc, autos, toc_rows = outline(items, refs)

    _cover(doc, title, subtitle, icon)
    body = doc.add_section(WD_SECTION.NEW_PAGE)
    _header_footer(body, title)
    _put(body._sectPr, _el("w:pgNumType", start=1), _SECTPR)                       # 본문부터 1쪽
    marks = _Marks()
    if use_toc:
        _toc(doc, toc_rows)
    s_title, s_lines, s_bullets = _box_lines(summary)
    if s_lines:
        _box(doc, s_title or "핵심 요약", s_lines, s_bullets, SUMMARY_FILL, SUMMARY_BAR)

    tables = 0
    first_head = use_toc
    for idx, sec_ in enumerate(items):
        heading = _text(sec_.get("heading"))
        level = 2 if str(sec_.get("level", 1)).strip() == "2" else 1
        if heading:
            _heading(doc, marks, heading, level, autos.get(idx, "") if level == 1 else "", f"_Toc{idx + 1}",
                     page_break=first_head)
            first_head = False
        for para in _strings(sec_.get("paragraphs")):
            p = doc.add_paragraph()
            p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
            for t, b in rich_parts(para):
                _run(p, t, None, True if b else None)
        pts = sec_.get("points") if not (sec_.get("paragraphs") or sec_.get("bullets")) else None   # 개요만 받은 장
        for line, lvl in parse_bullets(sec_.get("bullets") or pts):
            p = doc.add_paragraph(style="List Bullet")
            for t, b in rich_parts(line, keyword=not lvl):
                _run(p, t, None, True if b else None)
            if lvl:
                p.paragraph_format.left_indent = Cm(1.6)
        c_title, c_lines, c_bullets = _box_lines(sec_.get("callout"))
        if c_lines:
            _box(doc, c_title, c_lines, c_bullets, CALLOUT_FILL, CALLOUT_BAR)
        table = sec_.get("table")
        if isinstance(table, dict) and table.get("columns"):
            cols = [_text(c) for c in table["columns"]]
            rows = [r for r in (table.get("rows") or []) if isinstance(r, (list, tuple))]
            _table(doc, cols, rows, _text(table.get("caption")))
            tables += 1
    if refs:
        h = doc.add_heading(level=1)
        _run(h, "참고 자료")
        marks.wrap(h, "_Toc_refs")
        for r in refs:
            doc.add_paragraph(r, style="List Number")

    # 맨 끝이 표이면 워드가 빈 문단을 하나 더 만들어 빈 쪽이 생길 수 있으므로, 끝에 아주 작은 문단을 둔다
    last = doc.element.body[-2] if len(doc.element.body) > 1 else None          # [-1] 은 마지막 구역 설정(sectPr)
    if last is not None and last.tag == qn("w:tbl"):
        tiny = doc.add_paragraph()
        _run(tiny, "", 2)
        _spacing(tiny._p.get_or_add_pPr(), 0, 0, 1.0)
    doc.core_properties.title = title
    doc.core_properties.subject = _text(subtitle)
    doc.core_properties.author = "J.A.R.V.I.S"
    doc.core_properties.last_modified_by = "J.A.R.V.I.S"
    doc.save(str(path))
    return {"sections": len(sections), "tables": tables}
