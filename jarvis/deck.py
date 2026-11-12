"""발표 자료(PowerPoint)를 그린다 — 디자인 스타일 7가지 · 장 형식 12가지 (색은 office.THEMES).

같은 내용이라도 스타일에 따라 표지 · 제목 자리 · 카드 · 번호 · 장식이 완전히 달라진다:
  clean(깔끔) · bold(강렬) · side(사이드바) · tech(테크) · editorial(매거진) · pastel(파스텔) · corporate(비즈니스)
장 형식: bullets · section · two_column · stats · chart · timeline · process · cards · table · highlight · quote · closing
본문은 스타일마다 정해진 '본문 칸'(AREA) 안에만 그린다 — 그래서 어느 스타일에서도 글이 장 밖으로 나가지 않는다.
이 파일은 그리기만 한다 (내용 검사 · 넘치는 목록 나누기 · 저장은 office.build_presentation).
"""
from __future__ import annotations

import collections
import datetime
import hashlib
import math
import re

from .office import (BODY_SIZES, CHARTS, FONT, H, M, STYLES, W, Theme, _em, _hexmix, _lines, _listish, _text, fit_size,
                     number, palette, parse_bullets, roomy_gap, split_items)

SERIF = "바탕"          # 매거진 스타일의 제목 (없는 PC 에서는 파워포인트가 기본 한글 글꼴로 바꿔 보여 준다)
MONO = "Consolas"      # 테크 스타일의 작은 표시 · 숫자
Ink = collections.namedtuple("Ink", "head body strong mark")     # 카드 위에 쓸 색: 제목 · 글 · 큰 숫자 · 글머리 기호
_KEY = re.compile(r"^(?P<k>[^:：—–]{1,18}?)\s*(?:[:：]\s+|\s+[—–]\s+)(?P<v>\S.*)$")


def lum(hex_: str) -> float:
    r, g, b = (int(hex_[i:i + 2], 16) / 255 for i in (0, 2, 4))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a: str, b: str) -> float:
    """두 색의 명암비 (1 ~ 21). 글자로 읽히려면 3 은 넘어야 한다."""
    def rel(hex_: str) -> float:
        out = 0.0
        for i, k in ((0, 0.2126), (2, 0.7152), (4, 0.0722)):
            c = int(hex_[i:i + 2], 16) / 255
            out += k * (c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4)
        return out
    hi, lo = sorted((rel(a), rel(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def size_for(text: str, steps, floor: float) -> float:
    """글 길이에 맞는 글자 크기: steps = ((이 길이까지, 크기), …), 더 길면 floor."""
    e = _em(text)
    for limit, size in steps:
        if e <= limit:
            return size
    return floor


def keyword(line: str) -> tuple[str | None, str]:
    """'엽록체: 빛을 흡수하는 곳' → ('엽록체', '빛을 흡수하는 곳'). 그런 모양이 아니면 (None, 원래 글)."""
    m = _KEY.match(line)
    if not m:
        return None, line
    key = m["k"].strip()
    if not key or _em(key) > 12 or re.search(r"https?$", key):
        return None, line
    return key, m["v"].strip()


class Deck:
    AREA = {"clean": (M, 1.95, W - 2 * M, H - 1.95 - 0.75),
            "bold": (0.95, 2.0, W - 0.95 - 0.8, H - 2.0 - 0.7),
            "side": (4.6, 0.8, W - 4.6 - 0.75, H - 1.6),
            "tech": (M, 1.95, W - 2 * M, H - 1.95 - 0.8),
            "editorial": (1.0, 2.25, W - 2.0, H - 2.25 - 0.7),
            "pastel": (0.95, 1.95, W - 1.9, H - 1.95 - 0.9),
            "corporate": (0.7, 1.75, W - 1.4, H - 1.75 - 0.85)}
    MARK = {"clean": ("●", 100), "bold": ("■", 75), "side": ("●", 100), "tech": ("►", 70), "editorial": ("–", 100),
            "pastel": ("●", 100), "corporate": ("■", 65)}

    def __init__(self, theme: Theme, title: str, style: str = "clean") -> None:
        from pptx import Presentation
        from pptx.util import Inches
        self.t, self.title = theme, title
        self.style = style if style in STYLES else "clean"
        self.prs = Presentation()
        self.prs.slide_width, self.prs.slide_height = Inches(W), Inches(H)
        self.blank = self.prs.slide_layouts[6]
        self.count = 0
        self.notes = 0
        self.seed = int(hashlib.md5(title.encode("utf-8")).hexdigest()[:8], 16)   # 같은 제목이면 같은 장식
        self.dark = lum(theme.bg) < 0.45
        self.band = theme.title if not self.dark else theme.surface                # 진한 띠 (side · corporate)
        self.on_band = theme.bg if not self.dark else theme.title
        base = ("FFE1E8", "FFF0C2", "D9EEFF", "DBF4E3", "E9E0FF")                  # 파스텔 (분홍 · 노랑 · 하늘 · 민트 · 보라)
        self.pastels = [p if not self.dark else _hexmix(p, theme.bg, 0.8) for p in base]
        self.strong = ("F0628A", "E2A100", "2D8FD5", "2E9D63", "8656D8")
        self.hface = SERIF if self.style == "editorial" else None                  # 제목 글꼴
        # 강조색으로 쓰는 글자 · 숫자 — 바탕 위에서 잘 안 보이는 강조색(노랑 등)이면 제목 색으로
        self.ink = theme.accent if contrast(theme.accent, theme.bg) >= 2.6 else theme.title
        self.nface = SERIF if self.style == "editorial" else MONO if self.style == "tech" else None   # 큰 숫자 글꼴

    @property
    def body(self) -> tuple[float, float]:
        """본문 칸의 (너비, 높이) — 목록이 넘치는지 볼 때 쓴다."""
        return self.AREA[self.style][2:]

    # ================================================================ 기본 도구
    def rgb(self, hex_: str):
        from pptx.dml.color import RGBColor
        return RGBColor.from_string(hex_)

    def slide(self, notes: str = "", bg: str | None = None):
        s = self.prs.slides.add_slide(self.blank)
        fill = s.background.fill
        fill.solid()
        fill.fore_color.rgb = self.rgb(bg or self.t.bg)
        self.count += 1
        if _text(notes):
            s.notes_slide.notes_text_frame.text = str(notes).strip()
            self.notes += 1
        return s

    def box(self, s, x, y, w, h, color: str | None, shape: str = "rect", radius: float = 0.08, line: str | None = None,
            line_w: float = 1.0, alpha: float | None = None):
        """도형 하나. color=None 이면 속을 비운다. line: 테두리 색, alpha: 불투명도(%)."""
        from pptx.enum.shapes import MSO_SHAPE
        from pptx.oxml.ns import qn
        from pptx.util import Inches, Pt
        kind = {"rect": MSO_SHAPE.RECTANGLE, "round": MSO_SHAPE.ROUNDED_RECTANGLE, "oval": MSO_SHAPE.OVAL,
                "chevron": MSO_SHAPE.CHEVRON}[shape]
        sh = s.shapes.add_shape(kind, Inches(x), Inches(y), Inches(w), Inches(h))
        if color is None:
            sh.fill.background()
        else:
            sh.fill.solid()
            sh.fill.fore_color.rgb = self.rgb(color)
            if alpha is not None:
                clr = sh._element.spPr.find(qn("a:solidFill")).find(qn("a:srgbClr"))
                clr.append(clr.makeelement(qn("a:alpha"), {"val": str(int(alpha * 1000))}))
        if line is None:
            sh.line.fill.background()
        else:
            sh.line.color.rgb = self.rgb(line)
            sh.line.width = Pt(line_w)
        self._bare(sh)
        if shape == "round":
            sh.adjustments[0] = radius
        return sh

    @staticmethod
    def _bare(sh) -> None:
        """도형에 붙는 테마 효과(그림자 · 기본 선)를 뗀다 — 프로그램마다 다르게 보이지 않게."""
        from pptx.oxml.ns import qn
        sh.shadow.inherit = False
        style = sh._element.find(qn("p:style"))
        if style is not None:
            sh._element.remove(style)

    def glow(self, s, x, y, d, color: str, strength: float = 30):
        """가운데가 밝고 가장자리로 갈수록 사라지는 둥근 빛 (테크 스타일)."""
        from pptx.enum.shapes import MSO_SHAPE
        from pptx.oxml.ns import qn
        from pptx.util import Inches
        sh = s.shapes.add_shape(MSO_SHAPE.OVAL, Inches(x), Inches(y), Inches(d), Inches(d))
        sh.line.fill.background()
        self._bare(sh)
        sh.fill.gradient()
        grad = sh._element.spPr.find(qn("a:gradFill"))
        for child in list(grad):
            grad.remove(child)
        stops = grad.makeelement(qn("a:gsLst"), {})
        for pos, a in ((0, strength), (55000, strength * 0.4), (100000, 0)):
            gs = stops.makeelement(qn("a:gs"), {"pos": str(pos)})
            clr = gs.makeelement(qn("a:srgbClr"), {"val": color})
            clr.append(clr.makeelement(qn("a:alpha"), {"val": str(int(a * 1000))}))
            gs.append(clr)
            stops.append(gs)
        grad.append(stops)
        path = grad.makeelement(qn("a:path"), {"path": "circle"})
        path.append(path.makeelement(qn("a:fillToRect"), {"l": "50000", "t": "50000", "r": "50000", "b": "50000"}))
        grad.append(path)
        return sh

    def _font(self, run, size: float, color: str, bold: bool = False, face: str | None = None, track: int = 0) -> None:
        from pptx.oxml.ns import qn
        from pptx.util import Pt
        f = run.font
        f.size, f.bold, f.name = Pt(size), bold, face or FONT
        f.color.rgb = self.rgb(color)
        rpr = run._r.get_or_add_rPr()
        if track:
            rpr.set("spc", str(track))                       # 글자 사이 (1/100 pt)
        prev = rpr.find(qn("a:latin"))
        east = FONT if face == MONO else face or FONT         # 한글은 '동아시아 글꼴' 칸에 넣어야 적용된다 (순서: latin → ea → cs)
        for tag in ("a:ea", "a:cs"):
            el = rpr.find(qn(tag))
            if el is None:
                el = rpr.makeelement(qn(tag), {})
                prev.addnext(el)
            el.set("typeface", east)
            prev = el

    def _frame(self, s, x, y, w, h, anchor: str = "top"):
        from pptx.enum.text import MSO_ANCHOR, MSO_AUTO_SIZE
        from pptx.util import Inches
        tb = s.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
        tf = tb.text_frame
        tf.word_wrap = True
        tf.auto_size = MSO_AUTO_SIZE.NONE                    # 크기는 미리 맞춘다 (프로그램마다 줄이는 방식이 달라서)
        tf.margin_left = tf.margin_right = Inches(0.04)
        tf.margin_top = tf.margin_bottom = Inches(0.02)
        tf.vertical_anchor = {"top": MSO_ANCHOR.TOP, "middle": MSO_ANCHOR.MIDDLE, "bottom": MSO_ANCHOR.BOTTOM}[anchor]
        return tb, tf

    def text(self, s, x, y, w, h, lines, size: float, color: str, bold: bool = False, align: str = "left",
             anchor: str = "top", spacing: float = 1.15, face: str | None = None, track: int = 0):
        """글 상자 (lines: 문단들). 줄 바꿈 · 여백 · 정렬을 맞춘다."""
        from pptx.enum.text import PP_ALIGN
        from pptx.util import Pt
        tb, tf = self._frame(s, x, y, w, h, anchor)
        for i, line in enumerate([lines] if isinstance(lines, str) else lines):
            p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
            p.alignment = {"left": PP_ALIGN.LEFT, "center": PP_ALIGN.CENTER, "right": PP_ALIGN.RIGHT}[align]
            p.line_spacing = spacing
            if i:
                p.space_before = Pt(size * 0.3)
            self._font(p.add_run(), size, color, bold, face, track)
            p.runs[0].text = str(line)
        return tb

    def bullets(self, s, x, y, w, h, items: list[tuple[str, int]], size: float, color: str | None = None,
                gap: float = 0.55, mark: str | None = None):
        """글머리 기호 목록 (스타일의 기호 · 하위 항목은 짧은 줄). '핵심어: 설명' 은 핵심어를 굵게."""
        from pptx.oxml.ns import qn
        from pptx.util import Inches, Pt
        tb, tf = self._frame(s, x, y, w, h)
        tf.margin_top = tf.margin_bottom = Inches(0.05)
        char, pct = self.MARK[self.style]
        t = self.t
        for i, (line, level) in enumerate(items):
            p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
            sz = size * (0.86 if level else 1.0)
            p.line_spacing = 1.12
            p.space_before = Pt(0 if i == 0 else sz * gap)
            ppr = p._p.get_or_add_pPr()
            ppr.set("marL", str(int(Inches(0.42 + 0.4 * level))))
            ppr.set("indent", str(int(-Inches(0.32))))
            for tag, attrs in (("a:buClr", None), ("a:buSzPct", {"val": str((100 if level else pct) * 1000)}),
                               ("a:buFont", {"typeface": "Arial"}), ("a:buChar", {"char": "–" if level else char})):
                el = ppr.makeelement(qn(tag), attrs or {})
                if tag == "a:buClr":
                    el.append(el.makeelement(qn("a:srgbClr"), {"val": mark or (t.muted if level else t.accent)}))
                ppr.append(el)
            ink = color or (t.muted if level else t.text)
            key, rest = keyword(line) if not level else (None, line)
            if key:
                self._font(p.add_run(), sz, color or t.title, True)
                p.runs[0].text = key
                self._font(p.add_run(), sz, ink)
                p.runs[1].text = f": {rest}"
            else:
                self._font(p.add_run(), sz, ink)
                p.runs[0].text = line
        return tb

    def badge(self, s, x, y, d, label: str, i: int = 0, on_accent_card: bool = False) -> None:
        """번호 표시 (스타일에 따라 동그라미 · 네모 · 테두리 · 숫자만)."""
        t, st = self.t, self.style
        size = d * 72 * 0.42
        if st == "editorial":
            self.text(s, x - 0.05, y - 0.1, d + 0.5, d + 0.2, label, d * 72 * 0.7, self.ink, bold=True, anchor="middle",
                      face=SERIF)
            return
        if on_accent_card:
            fill, ink, line = t.on_accent, t.accent, None
        elif st == "tech":
            fill, ink, line = None, self.ink, t.accent
        elif st == "pastel":
            fill, ink, line = self.strong[i % 5], "FFFFFF", None
        else:
            fill, ink, line = t.accent, t.on_accent, None
        self.box(s, x, y, d, d, fill, "rect" if st in ("bold", "corporate") else "oval", line=line, line_w=1.5)
        self.text(s, x - 0.1, y, d + 0.2, d, label, size, ink, bold=True, align="center", anchor="middle", face=self.nface)

    def card(self, s, x, y, w, h, i: int = 0, gap: float = 0.4, lead: bool = True) -> Ink:
        """스타일에 맞는 카드 바탕을 그리고, 그 위에 쓸 색을 돌려준다. lead=False 면 첫 카드를 따로 강조하지 않는다."""
        t, st = self.t, self.style
        first = i == 0 and lead
        if st == "bold":
            if first:
                self.box(s, x, y, w, h, t.accent)
                return Ink(t.on_accent, t.on_accent, t.on_accent, t.on_accent)
            self.box(s, x, y, w, h, t.surface)
            return Ink(t.title, t.text, self.ink, t.accent)
        if st == "side":
            self.box(s, x, y, w, h, t.surface)
            self.box(s, x, y, 0.08, h, t.accent if first or not lead else t.muted)
        elif st == "tech":
            self.box(s, x, y, w, h, t.surface, "round", 0.03, line=t.accent if first else t.soft, line_w=1.25)
        elif st == "editorial":
            if i:
                self.box(s, x - gap / 2, y, 0.012, h, t.muted)
            return Ink(t.title, t.text, self.ink, t.accent)
        elif st == "pastel":
            self.box(s, x, y, w, h, self.pastels[i % 5], "round", 0.1)
            strong = t.accent if self.dark else self.strong[i % 5]
            return Ink(t.title, t.text, strong, strong)
        elif st == "corporate":
            self.box(s, x, y, w, h, t.bg, line=t.soft, line_w=0.75)
            self.box(s, x, y, w, 0.07, t.accent if first or not lead else t.muted)
        else:
            self.box(s, x, y, w, h, t.surface, "round", 0.05)
            self.box(s, x, y, w, 0.09, t.accent if first or not lead else t.muted)
        return Ink(self.ink if first else t.title, t.text, self.ink, t.accent)

    def page(self, title: str, notes: str = ""):
        """본문 장 하나: 스타일의 바탕 · 제목 자리 · 쪽 번호를 그리고 (장, 본문 칸 x, y, w, h) 를 돌려준다."""
        s = self.slide(notes)
        getattr(self, f"_head_{self.style}")(s, title)
        return (s, *self.AREA[self.style])

    def plain(self, notes: str = ""):
        """제목 자리가 없는 장 (인용): 스타일의 바탕 장식만."""
        s, t, st = self.slide(notes), self.t, self.style
        if st == "bold":
            self.box(s, 0, 0, 0.28, H, t.accent)
        elif st == "side":
            self.box(s, 0, 0, 0.55, H, t.surface)
            self.box(s, 0.13, 0.85, 0.29, 0.29, t.accent)
        elif st == "tech":
            self._tech_base(s)
        elif st == "editorial":
            self.box(s, 1.0, 0.86, W - 2.0, 0.012, t.muted)
            self.box(s, 1.0, H - 0.9, W - 2.0, 0.012, t.muted)
        elif st == "pastel":
            self._blobs(s, self.count)
        elif st == "corporate":
            self.box(s, 0, 0, W, 0.2, self.band)
            self.box(s, 0, 0.2, W, 0.05, t.accent)
        return s

    # ================================================================ 표지
    def cover(self, title: str, subtitle: str) -> None:
        getattr(self, f"_cover_{self.style}")(title, subtitle)

    def _cover_clean(self, title, subtitle):
        t = self.t
        s = self.slide()
        self.box(s, W - 4.6, -1.6, 6.2, 6.2, t.surface, "oval")
        self.box(s, W - 2.3, 3.9, 3.4, 3.4, t.soft, "oval")
        self.box(s, M, 2.35, 0.14, 2.2, t.accent)
        size = size_for(title, ((12, 54), (18, 46), (26, 38), (36, 32)), 28)
        self.text(s, M + 0.45, 2.1, W - 2 * M - 3.2, 1.9, title, size, t.title, bold=True, anchor="bottom", spacing=1.05)
        if subtitle:
            self.text(s, M + 0.45, 4.1, W - 2 * M - 3.2, 0.9, subtitle, 18, t.muted)

    def _cover_bold(self, title, subtitle):
        t = self.t
        s = self.slide(bg=t.accent)
        self.box(s, W - 5.6, H - 4.9, 7.6, 7.6, _hexmix(t.accent, t.on_accent, 0.14), "oval")
        self.box(s, W - 3.1, -1.5, 3.6, 3.6, _hexmix(t.accent, "000000", 0.16), "oval")
        if subtitle:
            pw = min(W - 2 * M, _em(subtitle) * 15 / 72 + 0.8)
            self.box(s, M, 0.85, pw, 0.52, None, "round", 0.5, line=t.on_accent, line_w=1.5)
            self.text(s, M, 0.85, pw, 0.52, subtitle, 15, t.on_accent, bold=True, align="center", anchor="middle")
        size = size_for(title, ((8, 72), (12, 62), (18, 52), (26, 42), (38, 34)), 28)
        self.text(s, M, 1.7, W - 2 * M - 1.6, 3.75, title, size, t.on_accent, bold=True, anchor="bottom", spacing=1.02)
        self.box(s, M, 5.75, 1.7, 0.13, t.on_accent)

    def _mosaic(self, s, x, y, cols, rows, cell, gap, on_band: bool = False) -> None:
        """둥근 네모 모자이크 — 제목에 따라 칸의 색 · 모양이 달라진다."""
        t = self.t
        if on_band:
            tones = [_hexmix(self.band, self.on_band, a) for a in (0.07, 0.13, 0.07, 0.2, 0.1)]
        else:
            tones = [t.surface, t.soft, t.surface, _hexmix(t.accent, t.bg, 0.6), t.surface, t.soft]
        n = cols * rows
        hot, cold = self.seed % n, (self.seed // 7) % n
        if cold == hot:
            cold = (hot + 5) % n
        k = self.seed
        for i in range(n):
            k = (k * 1103515245 + 12345) & 0x7FFFFFFF
            r, c = divmod(i, cols)
            color = t.accent if i == hot else (self.on_band if on_band else self.band) if i == cold else tones[(k >> 8) % len(tones)]
            self.box(s, x + c * (cell + gap), y + r * (cell + gap), cell, cell, color,
                     "oval" if (k >> 4) % 6 == 0 else "round", 0.16)

    def _cover_side(self, title, subtitle):
        t = self.t
        s = self.slide()
        self.box(s, 0, 0, 5.7, H, self.band)
        self.box(s, 0.75, 0.9, 0.36, 0.36, t.accent)
        size = size_for(title, ((7, 50), (12, 42), (20, 36), (30, 30), (44, 26)), 22)
        self.text(s, 0.75, 1.6, 4.4, 3.7, title, size, self.on_band, bold=True, anchor="bottom", spacing=1.08)
        self.box(s, 0.75, 5.5, 1.0, 0.09, t.accent)
        if subtitle:
            self.text(s, 0.75, 5.75, 4.4, 1.0, subtitle, 16, _hexmix(self.on_band, self.band, 0.3))
        self._mosaic(s, 6.39, 1.43, 4, 3, 1.4, 0.22)

    def _tech_base(self, s, big: bool = False) -> None:
        t = self.t
        if big:
            self.glow(s, W - 7.2, -0.8, 9.0, t.accent, 34)
        else:
            self.glow(s, W - 4.6, -3.0, 6.6, t.accent, 26)
        for x, y, w, h in ((0.35, 0.35, 0.45, 0.025), (0.35, 0.35, 0.025, 0.45),
                           (W - 0.8, H - 0.375, 0.45, 0.025), (W - 0.375, H - 0.8, 0.025, 0.45)):
            self.box(s, x, y, w, h, t.accent)

    def _rings(self, s, cx, cy) -> None:
        t = self.t
        for i, r in enumerate((1.25, 2.1, 2.95)):
            self.box(s, cx - r, cy - r, 2 * r, 2 * r, None, "oval", line=t.accent if i == 0 else t.soft,
                     line_w=1.75 if i == 0 else 1.0)
        self.box(s, cx - 0.16, cy - 0.16, 0.32, 0.32, t.accent, "oval")

    def _cover_tech(self, title, subtitle):
        t = self.t
        s = self.slide()
        self._tech_base(s, big=True)
        self._rings(s, W - 3.1, H / 2)
        self.text(s, M, 1.0, 7, 0.35, f"PRESENTATION  //  {datetime.date.today().year}", 12, self.ink, bold=True,
                  face=MONO, track=200)
        size = size_for(title, ((9, 60), (14, 50), (20, 42), (30, 34)), 28)
        self.text(s, M, 1.7, 7.6, 3.2, title, size, t.title, bold=True, anchor="bottom", spacing=1.05)
        self.box(s, M, 5.1, 2.2, 0.05, t.accent)
        if subtitle:
            self.text(s, M, 5.3, 7.6, 0.9, subtitle, 18, t.muted)

    def _cover_editorial(self, title, subtitle):
        t = self.t
        s = self.slide()
        self.text(s, 1.0, 0.62, 6, 0.3, "PRESENTATION", 11, self.ink, bold=True, track=400)
        self.text(s, W - 5.0, 0.62, 4.0, 0.3, datetime.date.today().strftime("%Y. %m. %d"), 11, t.muted, align="right",
                  track=100)
        self.box(s, 1.0, 1.02, W - 2.0, 0.03, t.title)
        size = size_for(title, ((9, 66), (14, 56), (20, 46), (30, 38), (44, 30)), 26)
        self.text(s, 1.0, 1.4, W - 2.0, 3.9, title, size, t.title, bold=True, anchor="middle", spacing=1.12, face=SERIF)
        self.box(s, 1.0, 5.6, W - 2.0, 0.012, t.muted)
        if subtitle:
            self.text(s, 1.0, 5.78, W - 4.0, 0.8, subtitle, 16, t.text)
        self.box(s, W - 1.9, 5.88, 0.9, 0.09, t.accent)

    def _blobs(self, s, k: int) -> None:
        p = self.pastels
        self.box(s, W - 2.7, -1.4, 3.8, 3.8, p[k % 5], "oval")
        self.box(s, -1.3, H - 2.1, 3.2, 3.2, p[(k + 2) % 5], "oval")

    def _sticker(self, s, k: int) -> None:
        t, p = self.t, self.pastels
        self.box(s, -1.8, -1.8, 6.4, 6.4, p[k % 5], "oval")
        self.box(s, W - 5.2, H - 4.6, 7.2, 7.2, p[(k + 1) % 5], "oval")
        self.box(s, W - 3.3, 0.55, 1.7, 1.7, p[(k + 2) % 5], "oval")
        self.box(s, 1.3, H - 2.3, 1.4, 1.4, p[(k + 3) % 5], "oval")
        self.box(s, 1.9, 1.7, W - 3.8, 4.1, t.bg, "round", 0.1, line=t.soft, line_w=2.0)

    def _cover_pastel(self, title, subtitle):
        t = self.t
        s = self.slide()
        self._sticker(s, self.seed % 5)
        size = size_for(title, ((9, 56), (14, 48), (20, 40), (30, 34)), 28)
        self.text(s, 2.4, 1.95, W - 4.8, 2.6 if subtitle else 3.6, title, size, t.title, bold=True, align="center",
                  anchor="middle", spacing=1.1)
        if subtitle:
            pw = min(W - 5.4, _em(subtitle) * 16 / 72 + 1.0)
            self.box(s, (W - pw) / 2, 4.75, pw, 0.6, t.accent, "round", 0.5)
            self.text(s, (W - pw) / 2, 4.75, pw, 0.6, subtitle, 16, t.on_accent, bold=True, align="center", anchor="middle")

    def _cover_corporate(self, title, subtitle):
        t = self.t
        s = self.slide()
        self.box(s, 0, 0, 0.32, H - 1.35, t.accent)
        self.box(s, 0, H - 1.35, W, 1.35, self.band)
        self.box(s, 0.95, 0.9, 0.42, 0.42, t.accent)
        self.text(s, 1.52, 0.9, 6, 0.42, "발표 자료", 13, t.muted, bold=True, anchor="middle", track=100)
        size = size_for(title, ((10, 54), (16, 46), (24, 38), (34, 32)), 26)
        self.text(s, 0.95, 1.7, W - 1.9, 2.6, title, size, t.title, bold=True, anchor="bottom", spacing=1.06)
        self.box(s, 0.95, 4.5, W - 1.9, 0.045, t.accent)
        if subtitle:
            self.text(s, 0.95, 4.7, W - 1.9, 0.9, subtitle, 20, t.text)
        self.text(s, 0.95, H - 1.35, 6, 1.35, datetime.date.today().strftime("%Y. %m. %d"), 13,
                  _hexmix(self.on_band, self.band, 0.25), bold=True, anchor="middle", track=150)

    # ================================================================ 본문 장의 제목 자리 · 쪽 번호
    def _head_clean(self, s, title):
        t = self.t
        self.text(s, M, 0.48, W - 2 * M, 0.95, title, size_for(title, ((26, 30), (36, 26)), 22), t.title, bold=True,
                  anchor="bottom")
        self.box(s, M, 1.5, 0.9, 0.07, t.accent)
        self.text(s, M, H - 0.5, 8, 0.3, self.title, 10, t.muted)
        self.text(s, W - M - 1.5, H - 0.5, 1.5, 0.3, str(self.count), 10, t.muted, align="right")

    def _head_bold(self, s, title):
        t = self.t
        self.box(s, 0, 0, 0.28, H, t.accent)
        self.text(s, 0.95, 0.5, W - 0.95 - 2.7, 0.95, title, size_for(title, ((20, 32), (30, 26), (44, 22)), 18), t.title,
                  bold=True, anchor="bottom")
        self.box(s, 0.95, 1.52, 1.3, 0.1, t.accent)
        self.text(s, W - 2.5, 0.28, 1.75, 1.15, f"{self.count:02d}", 54, t.soft, bold=True, align="right", anchor="middle")
        self.text(s, 0.95, H - 0.5, 8, 0.3, self.title, 10, t.muted)

    def _head_side(self, s, title):
        t = self.t
        self.box(s, 0, 0, 4.0, H, t.surface)
        self.box(s, 0.6, 0.85, 0.3, 0.3, t.accent)
        self.text(s, 0.6, 1.4, 3.0, 3.9, title, size_for(title, ((8, 30), (14, 28), (24, 24), (36, 20)), 18), t.title,
                  bold=True, spacing=1.12)
        self.text(s, 0.6, H - 1.3, 1.6, 0.6, f"{self.count:02d}", 26, self.ink, bold=True, anchor="bottom")
        self.text(s, 0.6, H - 0.62, 3.1, 0.3, self.title, 9, t.muted)

    def _head_tech(self, s, title):
        t = self.t
        self._tech_base(s)
        self.text(s, M, 0.4, 5, 0.3, f"//  {self.count:02d}", 12, self.ink, bold=True, face=MONO, track=150)
        self.text(s, M, 0.66, W - 2 * M - 1.5, 0.86, title, size_for(title, ((24, 28), (34, 24)), 20), t.title, bold=True,
                  anchor="bottom")
        self.box(s, M, 1.64, W - 2 * M, 0.012, t.soft)
        self.box(s, M, 1.62, 1.1, 0.045, t.accent)
        self.text(s, M, H - 0.5, 8, 0.3, self.title, 9, t.muted)

    def _head_editorial(self, s, title):
        t = self.t
        self.text(s, 1.0, 0.5, 8, 0.3, self.title, 10, t.muted, track=80)
        self.text(s, W - 3.0, 0.5, 2.0, 0.3, f"{self.count:02d}", 10, self.ink, bold=True, align="right", track=100)
        self.box(s, 1.0, 0.86, W - 2.0, 0.012, t.muted)
        self.text(s, 1.0, 1.0, W - 2.0, 0.9, title, size_for(title, ((25, 30), (36, 26)), 22), t.title, bold=True,
                  anchor="middle", face=SERIF)
        self.box(s, 1.0, 1.98, 0.6, 0.05, t.accent)

    def _head_pastel(self, s, title):
        t = self.t
        self._blobs(s, self.count)
        room = W - 1.9 - 2.2
        size = next((z for z in (26, 22, 18) if _em(title) * z / 72 + 1.0 <= room), 16)
        pw = min(room, _em(title) * size / 72 + 1.0)
        ph = 0.9 if _em(title) * size / 72 + 1.0 <= room else 1.2
        self.box(s, 0.95, 0.5, pw, ph, t.accent, "round", 0.5)
        self.text(s, 1.15, 0.5, pw - 0.4, ph, title, size, t.on_accent, bold=True, align="center", anchor="middle")
        self.box(s, W - 1.3, H - 0.9, 0.52, 0.52, self.pastels[(self.count + 1) % 5], "oval")
        self.text(s, W - 1.4, H - 0.9, 0.72, 0.52, str(self.count), 11, t.title, bold=True, align="center", anchor="middle")
        self.text(s, 2.0, H - 0.55, 7, 0.3, self.title, 10, t.muted)

    def _head_corporate(self, s, title):
        t = self.t
        self.box(s, 0, 0, W, 1.15, self.band)
        self.box(s, 0, 1.15, W, 0.06, t.accent)
        self.text(s, 0.7, 0.15, W - 1.4 - 1.4, 0.85, title, size_for(title, ((30, 26), (40, 22)), 18), self.on_band,
                  bold=True, anchor="middle")
        self.text(s, W - 1.9, 0.15, 1.2, 0.85, f"{self.count:02d}", 16, _hexmix(self.on_band, self.band, 0.4), bold=True,
                  align="right", anchor="middle")
        self.box(s, 0.7, H - 0.62, W - 1.4, 0.012, t.soft)
        self.text(s, 0.7, H - 0.52, 8, 0.3, self.title, 9, t.muted)

    # ================================================================ 장 구분
    def section(self, number: int, title: str, items: list[tuple[str, int]], notes: str) -> None:
        getattr(self, f"_section_{self.style}")(number, title, [line for line, _ in items[:3]], notes)

    def _section_clean(self, number, title, lines, notes):
        t = self.t
        s = self.slide(notes)
        self.box(s, 0, 0, 4.4, H, t.accent)
        self.text(s, 0.6, 2.3, 3.4, 1.6, f"{number:02d}", 88, t.on_accent, bold=True, anchor="middle")
        self.text(s, 5.0, 2.4, W - 5.0 - M, 1.5, title, size_for(title, ((14, 40), (22, 34)), 28), t.title, bold=True,
                  anchor="bottom")
        if lines:
            self.text(s, 5.0, 4.05, W - 5.0 - M, 2.0, lines, 18, t.muted)

    def _section_bold(self, number, title, lines, notes):
        t = self.t
        s = self.slide(notes, bg=t.accent)
        self.text(s, M - 0.1, 0.3, 7, 3.4, f"{number:02d}", 190, _hexmix(t.accent, t.on_accent, 0.25), bold=True,
                  anchor="middle")
        self.text(s, M, 3.75, W - 2 * M, 1.7, title, size_for(title, ((12, 54), (18, 46), (28, 38)), 30), t.on_accent,
                  bold=True, anchor="bottom")
        self.box(s, M, 5.6, 1.4, 0.11, t.on_accent)
        if lines:
            self.text(s, M, 5.85, W - 2 * M, 1.2, lines, 18, _hexmix(t.on_accent, t.accent, 0.15))

    def _section_side(self, number, title, lines, notes):
        t = self.t
        s = self.slide(notes, bg=self.band)
        self.text(s, 0.9, 0.85, 5, 2.2, f"{number:02d}", 120, t.accent, bold=True, anchor="middle")
        self.text(s, 0.9, 3.2, 7.6, 1.7, title, size_for(title, ((12, 48), (18, 42), (28, 34)), 28), self.on_band,
                  bold=True, anchor="bottom")
        self.box(s, 0.9, 5.05, 1.0, 0.09, t.accent)
        if lines:
            self.text(s, 0.9, 5.3, 7.6, 1.4, lines, 18, _hexmix(self.on_band, self.band, 0.3))
        self._mosaic(s, W - 3.75, 1.43, 2, 3, 1.4, 0.22, on_band=True)

    def _section_tech(self, number, title, lines, notes):
        t = self.t
        s = self.slide(notes)
        self._tech_base(s, big=True)
        self.text(s, M, 1.15, 6, 0.35, f"SECTION  //  {number:02d}", 13, self.ink, bold=True, face=MONO, track=200)
        self.text(s, M - 0.08, 1.55, 6, 2.0, f"{number:02d}", 110, self.ink, bold=True, anchor="middle", face=MONO)
        self.text(s, M, 3.6, W - 2 * M - 2.0, 1.5, title, size_for(title, ((14, 46), (20, 40), (30, 32)), 28), t.title,
                  bold=True, anchor="bottom")
        self.box(s, M, 5.27, W - 2 * M, 0.012, t.soft)
        self.box(s, M, 5.25, 1.6, 0.05, t.accent)
        if lines:
            self.text(s, M, 5.48, W - 2 * M, 1.3, lines, 18, t.muted)

    def _section_editorial(self, number, title, lines, notes):
        t = self.t
        s = self.slide(notes)
        self.text(s, 1.0, 1.75, W - 2.0, 0.35, f"PART {number:02d}", 13, self.ink, bold=True, align="center", track=400)
        self.box(s, W / 2 - 2.2, 2.3, 4.4, 0.025, t.title)
        self.text(s, 1.0, 2.5, W - 2.0, 2.05, title, size_for(title, ((12, 52), (18, 44), (26, 36)), 30), t.title, bold=True,
                  align="center", anchor="middle", face=SERIF)
        self.box(s, W / 2 - 2.2, 4.72, 4.4, 0.012, t.muted)
        if lines:
            self.text(s, 1.5, 4.95, W - 3.0, 1.5, lines, 18, t.muted, align="center")

    def _section_pastel(self, number, title, lines, notes):
        t, p = self.t, self.pastels
        s = self.slide(notes)
        k = number
        self.box(s, W - 3.2, -1.6, 4.6, 4.6, p[(k + 1) % 5], "oval")
        self.box(s, -1.0, H - 1.9, 2.8, 2.8, p[(k + 3) % 5], "oval")
        self.box(s, 1.3, 1.55, 4.4, 4.4, p[k % 5], "oval")
        self.text(s, 1.3, 1.55, 4.4, 4.4, f"{number:02d}", 110, t.accent if self.dark else self.strong[k % 5], bold=True,
                  align="center", anchor="middle")
        self.text(s, 6.3, 2.3, W - 6.3 - 0.9, 1.7, title, size_for(title, ((10, 44), (16, 38), (24, 30)), 26), t.title,
                  bold=True, anchor="bottom")
        self.box(s, 6.3, 4.15, 1.2, 0.12, t.accent, "round", 0.5)
        if lines:
            self.text(s, 6.3, 4.45, W - 6.3 - 0.9, 1.7, lines, 18, t.muted)

    def _section_corporate(self, number, title, lines, notes):
        t = self.t
        s = self.slide(notes, bg=self.band)
        self.box(s, 0, 0, 0.32, H, t.accent)
        self.text(s, 1.0, 1.35, 4, 1.4, f"{number:02d}", 72, t.accent, bold=True, anchor="bottom")
        self.box(s, 1.0, 2.9, 0.8, 0.06, t.accent)
        self.text(s, 1.0, 3.1, W - 2.0, 1.7, title, size_for(title, ((14, 46), (20, 40), (30, 32)), 28), self.on_band,
                  bold=True)
        if lines:
            self.text(s, 1.0, 4.95, W - 2.0, 1.5, lines, 18, _hexmix(self.on_band, self.band, 0.3))

    # ================================================================ 마무리
    def closing(self, title: str, items: list[tuple[str, int]], notes: str) -> None:
        getattr(self, f"_closing_{self.style}")(title or "감사합니다", [line for line, _ in items[:3]], notes)

    def _closing_clean(self, title, lines, notes):
        t = self.t
        s = self.slide(notes)
        self.box(s, -1.8, H - 3.2, 5.2, 5.2, t.surface, "oval")
        self.box(s, W - 3.0, -1.4, 4.2, 4.2, t.soft, "oval")
        self.text(s, M, 2.5, W - 2 * M, 1.5, title, size_for(title, ((10, 54), (18, 42)), 34), t.title, bold=True,
                  align="center", anchor="middle")
        if lines:
            self.text(s, M, 4.15, W - 2 * M, 1.6, lines, 20, t.muted, align="center")

    def _closing_bold(self, title, lines, notes):
        t = self.t
        s = self.slide(notes, bg=t.accent)
        self.box(s, -2.2, H - 3.6, 6.0, 6.0, _hexmix(t.accent, t.on_accent, 0.14), "oval")
        self.box(s, W - 3.4, -1.6, 4.4, 4.4, _hexmix(t.accent, "000000", 0.16), "oval")
        self.text(s, M, 2.2, W - 2 * M, 1.9, title, size_for(title, ((8, 66), (14, 52), (22, 40)), 32), t.on_accent,
                  bold=True, align="center", anchor="middle")
        if lines:
            self.text(s, M, 4.3, W - 2 * M, 1.6, lines, 20, _hexmix(t.on_accent, t.accent, 0.12), align="center")

    def _closing_side(self, title, lines, notes):
        t = self.t
        s = self.slide(notes)
        self.box(s, W - 5.7, 0, 5.7, H, self.band)
        self.text(s, W - 5.0, 1.9, 4.3, 2.4, title, size_for(title, ((7, 50), (12, 42), (20, 34)), 28), self.on_band,
                  bold=True, anchor="bottom", spacing=1.08)
        self.box(s, W - 5.0, 4.5, 1.0, 0.09, t.accent)
        if lines:
            self.text(s, W - 5.0, 4.75, 4.3, 1.9, lines, 16, _hexmix(self.on_band, self.band, 0.3))
        self._mosaic(s, 0.69, 1.43, 4, 3, 1.4, 0.22)

    def _closing_tech(self, title, lines, notes):
        t = self.t
        s = self.slide(notes)
        self._tech_base(s, big=True)
        self._rings(s, W - 3.1, H / 2)
        self.text(s, M, 2.0, 7.6, 2.0, title, size_for(title, ((8, 60), (14, 48), (22, 38)), 30), t.title, bold=True,
                  anchor="bottom")
        self.box(s, M, 4.2, 2.2, 0.05, t.accent)
        if lines:
            self.text(s, M, 4.45, 7.6, 1.8, lines, 18, t.muted)

    def _closing_editorial(self, title, lines, notes):
        t = self.t
        s = self.slide(notes)
        self.box(s, W / 2 - 2.2, 2.05, 4.4, 0.025, t.title)
        self.text(s, 1.0, 2.25, W - 2.0, 2.0, title, size_for(title, ((8, 60), (14, 50), (22, 40)), 32), t.title, bold=True,
                  align="center", anchor="middle", face=SERIF)
        self.box(s, W / 2 - 2.2, 4.45, 4.4, 0.012, t.muted)
        if lines:
            self.text(s, 1.5, 4.7, W - 3.0, 1.7, lines, 18, t.muted, align="center")

    def _closing_pastel(self, title, lines, notes):
        t = self.t
        s = self.slide(notes)
        self._sticker(s, (self.seed + 2) % 5)
        self.text(s, 2.4, 1.95, W - 4.8, 2.2 if lines else 3.6, title, size_for(title, ((8, 56), (14, 46), (22, 36)), 30),
                  t.title, bold=True, align="center", anchor="middle")
        if lines:
            self.text(s, 2.6, 4.2, W - 5.2, 1.45, lines, 18, t.muted, align="center")

    def _closing_corporate(self, title, lines, notes):
        t = self.t
        s = self.slide(notes, bg=self.band)
        self.box(s, 0, 0, 0.32, H, t.accent)
        self.text(s, 1.0, 2.2, W - 2.0, 1.8, title, size_for(title, ((8, 60), (14, 48), (22, 38)), 30), self.on_band,
                  bold=True, align="center", anchor="middle")
        self.box(s, W / 2 - 0.6, 4.15, 1.2, 0.06, t.accent)
        if lines:
            self.text(s, 1.5, 4.4, W - 3.0, 1.7, lines, 18, _hexmix(self.on_band, self.band, 0.3), align="center")

    # ================================================================ 목차 · 참고 자료
    def agenda(self, titles: list[str]) -> None:
        s, x, y, w, h = self.page("목차")
        t = self.t
        titles = titles[:12]
        cols = 1 if len(titles) <= 7 else 2
        per = math.ceil(len(titles) / cols)
        col_w = w / cols
        step = min(1.05, h / per)
        big = cols == 1 and len(titles) <= 4
        num, size = (34, 28) if big else (26, 22 if cols == 1 else 20 if col_w > 5 else 15)
        if not big and step < 0.75:
            num, size = 20, min(size, 16)
        top = y + (h - step * per) * (0.3 if big else 0.15)
        nw = 1.35 if big else 1.0
        for c in range(cols):
            for r, name in enumerate(titles[c * per:(c + 1) * per]):
                n = c * per + r + 1
                yy = top + r * step
                self.text(s, x + c * col_w, yy, nw, step, f"{n:02d}", num, self.ink, bold=True, anchor="middle", face=self.nface)
                self.text(s, x + c * col_w + nw, yy, col_w - nw - 0.2, step, name, size, t.text, anchor="middle",
                          face=self.hface)
                if self.style in ("editorial", "corporate", "tech") and r < per - 1:
                    self.box(s, x + c * col_w, yy + step - 0.006, col_w - 0.3, 0.012, t.soft)

    def sources(self, refs: list[str]) -> None:
        width, height = self.body
        parts = split_items([(r, 0) for r in refs], width, height, 14)
        start = 0
        for k, part in enumerate(parts):
            s, x, y, w, h = self.page("참고 자료" if k == 0 else "참고 자료 (계속)")
            size = fit_size(part, w, h, (18, 16, 15, 14, 13, 12)) or 12
            lines = [f"{start + i + 1}. {line}" for i, (line, _) in enumerate(part)]
            start += len(part)
            self.text(s, x, y, w, h, lines, size, self.t.text, spacing=1.1)

    # ================================================================ 본문 장
    PAIRS = ((28, 20), (26, 19), (24, 18), (22, 16), (20, 15), (18, 14), (16, 13), (14, 12))

    @staticmethod
    def _pair_height(pair, ts: float, ds: float, width: float) -> float:
        """(제목, 설명) 한 묶음이 차지하는 높이 (인치)."""
        a, b = pair
        return (_lines(a, ts, width * 0.93) * ts * 1.22 + (_lines(b, ds, width * 0.93) * ds * 1.3 if b else 0)) / 72 + 0.12

    def _pair_sizes(self, pairs, width: float, height: float, biggest: float = 26) -> tuple[float, float]:
        """(제목, 설명) 묶음들이 모두 칸(너비 × 높이)에 들어가는 가장 큰 (제목 크기, 설명 크기)."""
        for ts, ds in self.PAIRS:
            if ts <= biggest and all(self._pair_height(p, ts, ds, width) <= height for p in pairs):
                return ts, ds
        return self.PAIRS[-1]

    def _rows_fit(self, pairs, w: float, h: float):
        """짧은 목록(2~5개)은 번호가 붙은 줄로 보여 준다 → (글자 크기, 줄 높이). 안 맞으면 None.
        pairs: [(핵심어 | None, 글)] — 핵심어가 있으면 핵심어를 굵게 위에, 설명을 그 아래에 쓴다."""
        n = len(pairs)
        if not 2 <= n <= 5:
            return None
        rh = min(1.6, h / n)
        if rh < 0.95:
            return None
        tw = (w - 1.25) * 0.95
        for size in ((28, 24, 22, 20, 18) if n <= 3 else (24, 22, 20, 18)):
            ok = True
            for key, text in pairs:
                if key:
                    need = (size * 1.3 + _lines(text, size * 0.8, tw) * size * 0.8 * 1.3) / 72 if text else size * 1.3 / 72
                    ok = ok and need <= rh - 0.12 and _lines(key, size, tw) == 1
                else:
                    ok = ok and _lines(text, size, tw) * size * 1.25 / 72 <= rh - 0.12
            if ok:
                return size, rh
        return None

    def rows(self, s, x, y, w, h, pairs, size: float, rh: float, connect: bool = False) -> None:
        """번호 줄 목록. connect=True 면 번호들을 세로 선으로 잇는다 (단계)."""
        t, n = self.t, len(pairs)
        top = y + (h - rh * n) * 0.35
        tx, tw = x + 1.2, w - 1.25
        plain = self.style in ("clean", "side", "editorial") and not connect
        d = 0.62
        if connect and n > 1:
            self.box(s, x + 0.1 + d / 2 - 0.015, top + rh / 2, 0.03, rh * (n - 1), t.soft)
        for i, (key, text) in enumerate(pairs):
            ry = top + i * rh
            if plain:
                self.text(s, x, ry, 1.1, rh, f"{i + 1:02d}", min(30, size + 4), self.ink, bold=True, anchor="middle",
                          face=self.nface)
            else:
                if connect and self.style == "editorial":
                    self.box(s, x + 0.1, ry + (rh - d) / 2, d, d, t.bg, "oval")     # 세로 선을 가린다
                self.badge(s, x + 0.1, ry + (rh - d) / 2, d, f"{i + 1}", i)
            if key:
                small = size * 0.8
                kh = size * 1.3 / 72
                dh = _lines(text, small, tw * 0.95) * small * 1.3 / 72 if text else 0
                start = ry + (rh - kh - dh) / 2
                self.text(s, tx, start, tw, kh + 0.05, key, size, t.title, bold=True, anchor="middle", face=self.hface)
                if text:
                    self.text(s, tx, start + kh, tw, dh + 0.15, text, small, t.text if self.dark else t.muted)
            else:
                self.text(s, tx, ry, tw, rh, text, size, t.text, anchor="middle")
            if i < n - 1 and not connect:
                self.box(s, x, ry + rh - 0.006, w, 0.012, t.soft)

    def bullet_slide(self, title: str, items: list[tuple[str, int]], notes: str) -> None:
        s, x, y, w, h = self.page(title, notes)
        if not items:
            return
        if not any(level for _, level in items):
            pairs = [keyword(line) for line, _ in items]
            fit = self._rows_fit(pairs, w, h)
            if fit:
                self.rows(s, x, y, w, h, pairs, *fit)
                return
        size = fit_size(items, w, h) or BODY_SIZES[-1]
        self.bullets(s, x, y, w, h, items, size, gap=roomy_gap(items, size, w, h))

    def two_column(self, title: str, left: dict, right: dict, notes: str) -> None:
        s, x, y, w, h = self.page(title, notes)
        gap = 0.4
        cw = (w - gap) / 2
        cards = [(left or {}), (right or {})]
        parsed = [parse_bullets(c.get("bullets") or c.get("points")) for c in cards]
        size = min(fit_size(p, cw - 0.6, h - 1.2, (24, 22, 20, 18, 16, 14)) or 14 for p in parsed) if any(parsed) else 18
        for i, (card, items) in enumerate(zip(cards, parsed)):
            cx = x + i * (cw + gap)
            ink = self.card(s, cx, y, cw, h, i, gap)
            self.text(s, cx + 0.3, y + 0.25, cw - 0.6, 0.7, _text(card.get("heading")) or ("A" if i == 0 else "B"), 22,
                      ink.head, bold=True, face=self.hface)
            if items:
                spread = min(roomy_gap(p, size, cw - 0.6, h - 1.2) for p in parsed if p)   # (gap 은 카드 사이 간격)
                on_fill = ink.body != self.t.text
                self.bullets(s, cx + 0.3, y + 1.0, cw - 0.6, h - 1.2, items, size, color=ink.body if on_fill else None,
                             gap=spread, mark=ink.mark if on_fill else None)

    def stats(self, title: str, stats: list[dict], notes: str) -> None:
        s, x, y, w, h = self.page(title, notes)
        t = self.t
        stats = [st for st in stats if _text(st.get("value")) or _text(st.get("label"))][:4] or [{"value": "-", "label": ""}]
        n, gap = len(stats), 0.35
        cw = (w - gap * (n - 1)) / n
        ch = min(h, 3.9)
        top = y + (h - ch) * 0.35
        for i, st in enumerate(stats):
            cx = x + i * (cw + gap)
            ink = self.card(s, cx, top, cw, ch, i, gap)
            value = _text(st.get("value"))
            vsize = next((z for z in (60, 54, 46, 38, 30, 24) if _em(value) * z / 72 * 1.3 <= cw - 0.4), 20)   # 굵은 숫자는 넓다
            self.text(s, cx + 0.15, top + 0.45, cw - 0.3, 1.5, value, vsize, ink.strong, bold=True, align="center",
                      anchor="middle", face=self.nface)
            self.box(s, cx + cw / 2 - 0.35, top + 2.05, 0.7, 0.05, ink.body if ink.body != t.text else t.soft)
            label = _text(st.get("label"))
            lsize = 20 if _lines(label, 20, cw - 0.5) <= 2 else 17 if _lines(label, 17, cw - 0.5) <= 3 else 14
            self.text(s, cx + 0.25, top + 2.25, cw - 0.5, 1.5, label, lsize, ink.body, align="center")

    def chart(self, title: str, spec: dict, items: list[tuple[str, int]], notes: str) -> bool:
        """진짜 차트 (파워포인트에서 바로 고칠 수 있음). 데이터가 차트로 그릴 수 없으면 False (→ 목록 장으로)."""
        from pptx.chart.data import CategoryChartData
        from pptx.enum.chart import (XL_CHART_TYPE, XL_LABEL_POSITION, XL_LEGEND_POSITION, XL_MARKER_STYLE,
                                     XL_TICK_LABEL_POSITION)
        from pptx.oxml.ns import qn
        from pptx.util import Inches, Pt
        kind = str(spec.get("type") or "column").strip().lower()
        kind = {"막대": "column", "가로막대": "bar", "꺾은선": "line", "선": "line", "원": "pie", "파이": "pie"}.get(kind, kind)
        if kind not in CHARTS:
            kind = "column"
        cats = [_text(c) for c in _listish(spec.get("categories"))][:24]
        series = []
        for i, ser in enumerate([x for x in _listish(spec.get("series")) if isinstance(x, dict)][:6]):
            vals = [number(v) for v in _listish(ser.get("values"))][:len(cats)]
            if any(v is not None for v in vals):
                series.append((_text(ser.get("name")) or f"값 {i + 1}", vals + [None] * (len(cats) - len(vals))))
        if not cats or not series:
            return False
        if kind == "pie":
            series = series[:1]
        data = CategoryChartData()
        data.categories = cats
        for name, vals in series:
            data.add_series(name, vals)
        s, x, y, w, h = self.page(title, notes)
        width = w * (0.64 if items else 1.0)
        top, height = y - 0.1, h + 0.1
        xl = {"column": XL_CHART_TYPE.COLUMN_CLUSTERED, "bar": XL_CHART_TYPE.BAR_CLUSTERED,
              "line": XL_CHART_TYPE.LINE_MARKERS, "pie": XL_CHART_TYPE.PIE}[kind]
        ch = s.shapes.add_chart(xl, Inches(x), Inches(top), Inches(width), Inches(height), data).chart
        t, colors = self.t, palette(self.t)
        ch.has_title = False                    # 장 제목이 위에 있다
        ch.font.size, ch.font.name = Pt(14), FONT
        ch.font.color.rgb = self.rgb(t.text)
        unit = _text(spec.get("unit")).replace('"', "")
        plot = ch.plots[0]
        plot.has_data_labels = True
        dl = plot.data_labels
        fmt = f'General"{unit}"' if unit else "General"
        dl.number_format, dl.number_format_is_linked = fmt, False
        dl.font.size = Pt(13)
        dl.font.color.rgb = self.rgb(t.text)
        if kind == "pie":
            dl.position = XL_LABEL_POSITION.OUTSIDE_END
            for i, pt in enumerate(plot.series[0].points):
                pt.format.fill.solid()
                pt.format.fill.fore_color.rgb = self.rgb(colors[i % len(colors)] if i < len(colors) else
                                                         _hexmix(colors[i % len(colors)], t.bg, 0.3))
        else:
            dl.position = XL_LABEL_POSITION.ABOVE if kind == "line" else XL_LABEL_POSITION.OUTSIDE_END
            if kind != "line":
                plot.gap_width = 70
            mean = [sum(v for v in vals if v is not None) / max(1, sum(v is not None for v in vals)) for _, vals in series]
            high, low = mean.index(max(mean)), mean.index(min(mean))
            for i, ser in enumerate(plot.series):
                c = self.rgb(colors[i % len(colors)])
                if kind == "line":
                    ser.smooth = False
                    ser.format.line.color.rgb = c
                    ser.format.line.width = Pt(3)
                    ser.marker.style, ser.marker.size = XL_MARKER_STYLE.CIRCLE, 8
                    ser.marker.format.fill.solid()
                    ser.marker.format.fill.fore_color.rgb = c
                    ser.marker.format.line.color.rgb = c
                    if len(series) > 1:                 # 선이 여러 개: 위쪽 선은 숫자를 위에, 아래쪽 선은 아래에 (겹치지 않게)
                        sl = ser.data_labels
                        sl.show_value = i in (high, low)       # 가운데 선들의 숫자는 감춘다 (눈금으로 읽는다)
                        sl.number_format, sl.number_format_is_linked = fmt, False
                        sl.font.size = Pt(13)
                        sl.font.color.rgb = self.rgb(t.text)
                        sl.position = XL_LABEL_POSITION.ABOVE if i == high else XL_LABEL_POSITION.BELOW
                else:
                    ser.format.fill.solid()
                    ser.format.fill.fore_color.rgb = c
            for axis in (ch.category_axis, ch.value_axis):
                axis.tick_labels.font.size = Pt(13)
                axis.tick_labels.font.color.rgb = self.rgb(t.muted)
                axis.format.line.color.rgb = self.rgb(t.soft)
            ch.category_axis.tick_label_position = XL_TICK_LABEL_POSITION.LOW   # 음수가 있어도 이름은 맨 아래에
            if kind == "bar":                               # 가로 막대: 첫 항목이 맨 위에 (위에서 아래로 읽게), 눈금은 아래 그대로
                ch.category_axis.reverse_order = True
                crosses = ch.value_axis._element.find(qn("c:crosses"))
                if crosses is not None:
                    crosses.set("val", "max")              # 숫자 축이 마지막 항목(맨 아래) 쪽에서 만나게
            ch.value_axis.has_major_gridlines = True
            ch.value_axis.major_gridlines.format.line.color.rgb = self.rgb(t.soft)
            ch.value_axis.format.line.fill.background()
        ch.has_legend = kind == "pie" or len(series) > 1
        if ch.has_legend:
            ch.legend.position = XL_LEGEND_POSITION.RIGHT if kind == "pie" else XL_LEGEND_POSITION.BOTTOM
            ch.legend.include_in_layout = False
            ch.legend.font.size = Pt(13)
            ch.legend.font.color.rgb = self.rgb(t.text)
        self._chart_fonts(ch)
        if items:
            bx = x + width + 0.35
            bw = x + w - bx
            size = fit_size(items, bw, height - 0.3, (22, 20, 18, 16, 14)) or 14
            self.bullets(s, bx, top + 0.3, bw, height - 0.3, items, size)
        return True

    def _chart_fonts(self, ch) -> None:
        """차트 안의 모든 글자에 한글 글꼴(동아시아 글꼴 칸)을 넣는다 — 순서: latin → ea → cs."""
        from pptx.oxml.ns import qn
        after = {qn(t) for t in ("a:cs", "a:sym", "a:hlinkClick", "a:hlinkMouseOver", "a:rtl", "a:extLst")}
        for rpr in list(ch._chartSpace.iter(qn("a:defRPr"))) + list(ch._chartSpace.iter(qn("a:rPr"))):
            latin = rpr.find(qn("a:latin"))
            if latin is None:
                latin = rpr.makeelement(qn("a:latin"), {})
                nxt = next((c for c in rpr if c.tag in after or c.tag == qn("a:ea")), None)
                nxt.addprevious(latin) if nxt is not None else rpr.append(latin)
            latin.set("typeface", FONT)
            ea = rpr.find(qn("a:ea"))
            if ea is None:
                ea = rpr.makeelement(qn("a:ea"), {})
                latin.addnext(ea)
            ea.set("typeface", FONT)

    def _node(self, s, cx, cy, i: int, d: float = 0.36) -> None:
        t = self.t
        if self.style in ("tech", "editorial"):
            self.box(s, cx - d / 2, cy - d / 2, d, d, t.bg, "oval", line=t.accent, line_w=2.5)
        elif self.style in ("bold", "corporate"):
            self.box(s, cx - d / 2, cy - d / 2, d, d, t.accent)
        else:
            self.box(s, cx - d / 2, cy - d / 2, d, d, self.strong[i % 5] if self.style == "pastel" else t.accent, "oval")
            self.box(s, cx - d * 0.2, cy - d * 0.2, d * 0.4, d * 0.4, t.bg, "oval")

    def timeline(self, title: str, events: list[dict], notes: str) -> None:
        """연표: 가로 선 위에 시점들, 그 아래에 사건과 설명. 칸이 좁으면 세로로 내려 쓴다."""
        s, x, y, w, h = self.page(title, notes)
        t = self.t
        ev = events[:6]
        n = len(ev)
        soft = t.text if self.dark else t.muted
        whens = [_text(e.get("when")) or f"{i + 1}" for i, e in enumerate(ev)]
        pairs = [(_text(e.get("title")), _text(e.get("text"))) for e in ev]
        cw = w / n
        if cw < 2.3 or any(_em(wh) * 17 / 72 * 1.2 > cw - 0.15 for wh in whens):      # 세로 연표
            rh = min(1.5, h / n)
            top = y + (h - rh * n) * 0.35
            ww = min(2.6, max(1.3, max(_em(wh) for wh in whens) * 20 / 72 * 1.25 + 0.2))
            lx = x + ww + 0.35
            tsize, dsize = self._pair_sizes(pairs, w - ww - 1.0, rh - 0.1, 22)
            self.box(s, lx - 0.015, top + rh / 2, 0.03, rh * (n - 1), t.soft)
            for i, (name, body) in enumerate(pairs):
                ry = top + i * rh
                self.text(s, x, ry, ww, rh, whens[i], 20, self.ink, bold=True, align="right", anchor="middle", face=self.nface)
                self._node(s, lx, ry + rh / 2, i, 0.3)
                th = _lines(name, tsize, w - ww - 1.0) * tsize * 1.22 / 72 + 0.06 if name else 0
                dh = _lines(body, dsize, w - ww - 1.0) * dsize * 1.3 / 72 + 0.06 if body else 0
                start = ry + (rh - th - dh) / 2
                if name:
                    self.text(s, lx + 0.45, start, w - ww - 0.85, th + 0.05, name, tsize, t.title, bold=True, anchor="middle",
                              face=self.hface)
                if body:
                    self.text(s, lx + 0.45, start + th, w - ww - 0.85, dh + 0.1, body, dsize, soft)
            return
        wsize = next((z for z in (30, 26, 22, 19, 17) if all(_em(wh) * z / 72 * 1.2 <= cw - 0.15 for wh in whens)), 17)
        tsize, dsize = self._pair_sizes(pairs, cw - 0.4, h - 1.75 - 0.5, 22)
        tall = max((_lines(a, tsize, (cw - 0.4) * 0.93) * tsize * 1.22 + _lines(b, dsize, (cw - 0.4) * 0.93) * dsize * 1.3 * bool(b)) / 72
                   for a, b in pairs)
        ly = y + 1.1 + max(0.0, (h - 1.1 - 0.55 - tall) * 0.4)        # 시점 · 선 · 설명 묶음을 본문 칸 가운데쯤에
        self.box(s, x + cw / 2, ly - 0.02, w - cw, 0.04, t.soft)
        for i, (name, body) in enumerate(pairs):
            cx = x + cw * (i + 0.5)
            self._node(s, cx, ly, i)
            self.text(s, cx - cw / 2 + 0.05, ly - 1.25, cw - 0.1, 0.95, whens[i], wsize, self.ink, bold=True, align="center",
                      anchor="bottom", face=self.nface)
            th = _lines(name, tsize, (cw - 0.4) * 0.93) * tsize * 1.22 / 72 + 0.1 if name else 0
            if name:
                self.text(s, cx - cw / 2 + 0.15, ly + 0.45, cw - 0.3, th, name, tsize, t.title, bold=True, align="center",
                          face=self.hface)
            if body:
                self.text(s, cx - cw / 2 + 0.15, ly + 0.45 + th, cw - 0.3, max(0.4, y + h - (ly + 0.45 + th)), body, dsize,
                          soft, align="center")

    def process(self, title: str, steps: list[dict], notes: str) -> None:
        """단계: 번호가 붙은 카드들이 화살표로 이어진다. 칸이 좁거나 단계가 많으면 세로로 내려 쓴다."""
        s, x, y, w, h = self.page(title, notes)
        t = self.t
        st = steps[:6]
        n = len(st)
        pairs = [(_text(p.get("title")), _text(p.get("text"))) for p in st]
        arrow = 0.46 if n > 1 else 0
        cw = (w - arrow * (n - 1)) / n
        if cw < 2.35:
            fit = self._rows_fit(pairs, w, h)
            if fit:
                self.rows(s, x, y, w, h, pairs, *fit, connect=True)
                return
        tsize, dsize = self._pair_sizes(pairs, cw - 0.6, min(h, 4.4) - 1.35 - 0.3, 28 if n <= 3 else 24)
        if tsize <= 18:                                        # 가로 카드에는 글이 너무 작아진다 → 세로로 (들어가면)
            fit = self._rows_fit(pairs, w, h)
            if fit and fit[0] > tsize:
                self.rows(s, x, y, w, h, pairs, *fit, connect=True)
                return
        ch = min(h, 4.4, max(3.0, 1.35 + max(self._pair_height(p, tsize, dsize, cw - 0.6) for p in pairs) + 0.45))   # 내용에 맞는 높이
        top = y + (h - ch) * 0.4
        for i, (name, body) in enumerate(pairs):
            cx = x + i * (cw + arrow)
            ink = self.card(s, cx, top, cw, ch, i, arrow, lead=False)
            self.badge(s, cx + 0.3, top + 0.4, 0.66, f"{i + 1}", i)
            th = _lines(name, tsize, (cw - 0.6) * 0.93) * tsize * 1.22 / 72 + 0.1
            self.text(s, cx + 0.3, top + 1.35, cw - 0.6, th, name, tsize, t.title, bold=True, face=self.hface)
            if body:
                self.text(s, cx + 0.3, top + 1.4 + th, cw - 0.6, max(0.4, ch - 1.55 - th), body, dsize, ink.body)
            if i < n - 1:
                self.box(s, cx + cw + 0.11, top + ch / 2 - 0.2, 0.24, 0.4, t.accent if self.style in ("bold", "tech") else t.soft,
                         "chevron")

    def cards(self, title: str, cards: list[dict], notes: str) -> None:
        """카드 묶음 (2~6개): 번호 · 제목 · 짧은 설명."""
        s, x, y, w, h = self.page(title, notes)
        t = self.t
        cs = cards[:6]
        n = len(cs)
        pairs = [(_text(c.get("title")), _text(c.get("text"))) for c in cs]
        cols = n if n <= 3 else 2 if n == 4 else 3
        if n == 3 and w < 9:                                   # 좁은 칸(사이드바 스타일)에서는 세로로 쌓는다
            fit = self._rows_fit(pairs, w, h)
            if fit:
                self.rows(s, x, y, w, h, pairs, *fit)
                return
        rows = math.ceil(n / cols)
        gap = 0.3
        cw = (w - gap * (cols - 1)) / cols
        head = 1.3 if rows == 1 else 0.72
        if rows == 1:
            tsize, dsize = self._pair_sizes(pairs, cw - 0.6, min(h, 4.4) - head - 0.3, 28 if n <= 3 else 24)
            ch = min(h, 4.4, max(3.0, head + max(self._pair_height(p, tsize, dsize, cw - 0.6) for p in pairs) + 0.45))
            top = y + (h - ch) * 0.4
        else:
            ch = (h - gap * (rows - 1)) / rows
            top = y
            tsize, dsize = self._pair_sizes(pairs, cw - 0.6, ch - head - 0.25, 22)
        for i, (name, body) in enumerate(pairs):
            r, k = divmod(i, cols)
            cx, cy = x + k * (cw + gap), top + r * (ch + gap)
            ink = self.card(s, cx, cy, cw, ch, i, gap, lead=False)
            if rows == 1:
                self.badge(s, cx + 0.3, cy + 0.4, 0.62, f"{i + 1}", i)
            else:
                self.text(s, cx + 0.3, cy + 0.22, 1.2, 0.45, f"{i + 1:02d}", 17, ink.strong, bold=True, face=self.nface)
            th = _lines(name, tsize, (cw - 0.6) * 0.93) * tsize * 1.22 / 72 + 0.1
            self.text(s, cx + 0.3, cy + head, cw - 0.6, th, name, tsize, t.title, bold=True, face=self.hface)
            if body:
                self.text(s, cx + 0.3, cy + head + th + 0.05, cw - 0.6, max(0.35, ch - head - th - 0.2), body, dsize, ink.body)

    def _cell(self, cell, text: str, size: float, color: str, fill: str, bold: bool = False, align: str = "left") -> None:
        from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
        from pptx.util import Inches
        cell.fill.solid()
        cell.fill.fore_color.rgb = self.rgb(fill)
        cell.margin_left = cell.margin_right = Inches(0.14)
        cell.margin_top = cell.margin_bottom = Inches(0.05)
        cell.vertical_anchor = MSO_ANCHOR.MIDDLE
        tf = cell.text_frame
        tf.word_wrap = True
        p = tf.paragraphs[0]
        p.alignment = PP_ALIGN.CENTER if align == "center" else PP_ALIGN.LEFT
        self._font(p.add_run(), size, color, bold)
        p.runs[0].text = text

    def table(self, title: str, spec: dict, notes: str) -> bool:
        """표 (머리글 + 최대 8줄 · 6칸). 그릴 것이 없으면 False (→ 목록 장으로)."""
        from pptx.util import Inches
        cols = [_text(c) for c in _listish(spec.get("columns"))][:6]
        rows = [[_text(v) for v in r][:len(cols)] for r in (spec.get("rows") or []) if isinstance(r, (list, tuple))][:8]
        if not cols or not rows:
            return False
        s, x, y, w, h = self.page(title, notes)
        t = self.t
        nr, nc = len(rows) + 1, len(cols)
        lens = [max([_em(cols[j])] + [_em(r[j]) for r in rows if j < len(r)]) for j in range(nc)]
        lens = [min(max(v, 4), 20) for v in lens]
        widths = [w * v / sum(lens) for v in lens]
        rh = min(1.0, h / nr)
        size = 12                                              # 모든 칸이 두 줄 안에 들어가는 가장 큰 글자
        for z in (22, 20, 18, 16, 14):
            if z * 1.25 * 2 / 72 + 0.1 > rh and z > 14:
                continue
            if all(_lines(v, z, widths[j] - 0.35) <= (2 if z * 2.5 / 72 + 0.1 <= rh else 1)
                   for r in [cols] + rows for j, v in enumerate(r) if j < nc):
                size = z
                break
        top = y + max(0.0, (h - rh * nr) * 0.25)
        frame = s.shapes.add_table(nr, nc, Inches(x), Inches(top), Inches(w), Inches(rh * nr))
        tbl = frame.table
        tbl.horz_banding = False
        used = 0
        for j in range(nc):
            cwid = int(Inches(widths[j])) if j < nc - 1 else int(Inches(w)) - used
            tbl.columns[j].width = cwid
            used += cwid
        for i in range(nr):
            tbl.rows[i].height = Inches(rh)
        head_fill, head_ink = (self.band, self.on_band) if self.style in ("corporate", "side", "editorial") else (t.accent, t.on_accent)
        for j, c in enumerate(cols):
            self._cell(tbl.cell(0, j), c, size, head_ink, head_fill, bold=True, align="center")
        for i, r in enumerate(rows, 1):
            for j in range(nc):
                self._cell(tbl.cell(i, j), r[j] if j < len(r) else "", size, t.title if j == 0 else t.text,
                           t.surface if i % 2 else _hexmix(t.surface, t.bg, 0.55), bold=j == 0,
                           align="left" if j == 0 else "center")
        return True

    def highlight(self, title: str, statement: str, detail: str, notes: str) -> None:
        """한 문장을 크게 (핵심 메시지)."""
        s, x, y, w, h = self.page(title, notes)
        t, st = self.t, self.style
        bx, by, bw, bh = x, y + 0.05, w, h - 0.15
        ink, sub, bar = t.title, t.muted, t.accent
        if st in ("bold", "corporate"):
            self.box(s, bx, by, bw, bh, t.accent)
            ink, sub, bar = t.on_accent, _hexmix(t.on_accent, t.accent, 0.15), t.on_accent
        elif st == "pastel":
            self.box(s, bx, by, bw, bh, self.pastels[self.count % 5], "round", 0.08)
        elif st == "tech":
            self.box(s, bx, by, bw, bh, t.surface, "round", 0.03, line=t.accent, line_w=1.5)
        elif st == "editorial":
            self.box(s, bx, by, bw, 0.02, t.title)
            self.box(s, bx, by + bh - 0.012, bw, 0.012, t.muted)
        else:
            self.box(s, bx, by, bw, bh, t.surface, "round", 0.04)
            self.box(s, bx, by, 0.12, bh, t.accent)
        tw = bw - 1.4
        room = bh * (0.56 if detail else 0.8)
        size = next((z for z in (48, 42, 36, 30, 26, 22) if _lines(statement, z, tw) * z * 1.25 / 72 <= room), 20)
        if detail:
            self.text(s, bx + 0.7, by + 0.3, tw, bh * 0.6 - 0.3, statement, size, ink, bold=True, align="center",
                      anchor="bottom", spacing=1.2, face=self.hface)
            self.box(s, bx + bw / 2 - 0.45, by + bh * 0.6 + 0.2, 0.9, 0.06, bar)
            dsize = 20 if _lines(detail, 20, tw) <= 2 else 17
            self.text(s, bx + 0.7, by + bh * 0.6 + 0.42, tw, bh * 0.4 - 0.55, detail, dsize, sub, align="center")
        else:
            self.text(s, bx + 0.7, by + 0.3, tw, bh - 0.6, statement, size, ink, bold=True, align="center", anchor="middle",
                      spacing=1.2, face=self.hface)

    def quote(self, title: str, quote: str, by: str, notes: str) -> None:
        s = self.plain(notes)
        t = self.t
        left = 1.25 if self.style in ("side", "editorial") else M
        self.box(s, left, 1.2, 0.12, 4.6, t.accent)
        self.text(s, left + 0.5, 0.75, 2, 1.4, "“", 110, t.soft, bold=True, face=self.hface)
        size = 32 if _em(quote) <= 60 else 26 if _em(quote) <= 100 else 22 if _em(quote) <= 150 else 18
        self.text(s, left + 0.6, 1.9, W - left - M - 1.0, 3.3, quote, size, t.title, anchor="middle", spacing=1.25,
                  face=self.hface)
        if _text(by):
            self.text(s, left + 0.6, 5.35, W - left - M - 1.0, 0.6, f"— {_text(by)}", 18, t.muted, align="right")
        self.text(s, left, H - 0.5, 8, 0.3, self.title, 10, t.muted)
