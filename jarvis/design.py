"""디자인 결과물 — 카드뉴스 · 포스터를 화면 클릭 없이 바로 이미지로 만든다.

미리캔버스 같은 사이트를 화면을 보며 조작하면 느리고 실패할 수 있다. 자주 만드는 카드뉴스 · 포스터는 여기서 직접 그린다:
  · build_cardnews: 1080×1080 정사각형 카드 여러 장 (표지 · 내용 · 마무리) → 폴더에 01.png… + 한 묶음 PDF
  · build_poster: A4(또는 A3) 세로 포스터 → PNG + PDF (인쇄용)
카드 한 장마다 배치(layout)를 고른다: point(큰 아이콘 + 문장) · list(번호 상자) · stat(큰 숫자) · steps(단계) · compare(두 칸 비교) · quote(인용).
배치를 안 주면 글에서 알아서 고른다. 모양(style)은 clean · bold · gradient · pastel, 색은 발표 자료(office.py)와 같은 테마를 쓴다.
글은 상자에 맞게 크기를 줄이고(최소 크기에서도 넘치면 '…') 줄을 바꾼다 (한국어는 띄어쓰기 단위로, 마지막 줄이 짧지 않게 고르게).
도형은 두 배 크기로 그린 뒤 줄여 가장자리를 매끄럽게 한다. 이 파일은 그림만 만든다 (저장 폴더 · 열기는 tools.py).
"""
from __future__ import annotations

import math
import os
import re
import shutil
import urllib.parse
from dataclasses import dataclass
from pathlib import Path

from . import icons
from .office import THEMES, Theme, _strings, _text

SS = 2                                  # 두 배로 그려서 줄인다 (도형 가장자리를 매끄럽게)
CARD = 1080
A4 = (1240, 1754)                       # 150dpi A4 세로
MAX_CARDS = 12
STYLES = ("clean", "bold", "gradient", "pastel")
LAYOUTS = ("point", "list", "stat", "steps", "compare", "quote")

_WIN = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"
_ASSET_FONTS = Path(__file__).resolve().parent.parent / "assets" / "fonts"
_FONTS = {
    "regular": [_ASSET_FONTS / "Pretendard-Regular.otf", _WIN / "malgun.ttf",
                Path("/usr/share/fonts/truetype/nanum/NanumGothic.ttf"),
                Path("/usr/share/fonts/truetype/nanum/NanumSquareR.ttf"), Path("/usr/share/fonts/truetype/nanum/NanumBarunGothic.ttf")],
    "semibold": [_ASSET_FONTS / "Pretendard-SemiBold.otf"],
    "bold": [_ASSET_FONTS / "Pretendard-ExtraBold.otf", _WIN / "malgunbd.ttf",
             Path("/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf"),
             Path("/usr/share/fonts/truetype/nanum/NanumSquareB.ttf"), Path("/usr/share/fonts/truetype/nanum/NanumBarunGothicBold.ttf")],
    "black": [_ASSET_FONTS / "Pretendard-Black.otf"],
}
_FALLBACK = {"semibold": "bold", "black": "bold", "bold": "regular"}      # 그 굵기 파일이 없을 때 대신 쓸 굵기
_CACHE: dict = {}


def font_file(weight: str = "regular") -> Path:
    """한글 글꼴 파일 (Pretendard, 없으면 Windows 맑은 고딕). 없으면 ValueError."""
    w = weight
    while w:
        for p in _FONTS.get(w, []):
            if p.exists():
                return p
        w = _FALLBACK.get(w, "") if w != "regular" else ""
    raise ValueError("한글 글꼴(맑은 고딕)을 찾지 못했습니다.")


def _font(weight: str, size: float):
    from PIL import ImageFont
    key = (weight, int(size))
    if key not in _CACHE:
        _CACHE[key] = ImageFont.truetype(str(font_file(weight)), max(1, int(size)))
    return _CACHE[key]


# ---------------------------------------------------------------- 색
def _rgb(c) -> tuple[int, int, int]:
    if not isinstance(c, str):
        return tuple(int(v) for v in c)             # type: ignore[return-value]
    c = c.lstrip("#")
    return tuple(int(c[i:i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]


def _mix(a, b, t: float) -> tuple[int, int, int]:
    ca, cb = _rgb(a), _rgb(b)
    return tuple(round(x + (y - x) * t) for x, y in zip(ca, cb))  # type: ignore[return-value]


def _lum(c) -> float:
    """상대 밝기 (WCAG)."""
    def ch(v):
        v /= 255
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    r, g, b = _rgb(c)
    return 0.2126 * ch(r) + 0.7152 * ch(g) + 0.0722 * ch(b)


def _contrast(a, b) -> float:
    la, lb = sorted((_lum(a), _lum(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def _best_ink(bgs, candidates=("FFFFFF", "0B1020")):
    """배경(들) 위에서 가장 잘 보이는 글자색 — 가장 나쁜 배경 기준으로 대비가 큰 것."""
    return max((_rgb(c) for c in candidates), key=lambda c: min(_contrast(c, b) for b in bgs))


def _legible(color, bgs, need: float = 3.0):
    """강조색을 글자로 쓸 때 배경과 대비가 모자라면 밝기를 조금씩 바꿔 읽히게 한다."""
    c = _rgb(color)
    bgs = [_rgb(b) for b in bgs]
    toward = "000000" if sum(_lum(b) for b in bgs) / len(bgs) > 0.4 else "FFFFFF"
    for _ in range(14):
        if min(_contrast(c, b) for b in bgs) >= need:
            break
        c = _mix(c, toward, 0.12)
    return c


@dataclass
class Pal:
    """한 장을 그리는 데 쓰는 색 모음 (테마 + 스타일)."""
    style: str
    bg: tuple
    grad: tuple | None          # (위, 아래) 배경 그라데이션 — 없으면 단색 bg
    panel: tuple                # 카드 안의 상자 (목록 · 비교 칸…)
    panel_a: float
    card: tuple                 # 포스터 구역 상자
    card_a: float
    sheet: tuple | None         # 파스텔: 카드 위에 까는 흰 판
    strip: tuple                # 포스터 정보 띠
    strip_a: float
    title: tuple
    text: tuple
    muted: tuple
    accent: tuple               # 도형을 칠하는 강조색
    ink: tuple                  # 글자로 쓰는 강조색 (배경 위에서 읽히게 조정)
    on_accent: tuple
    soft: tuple
    head: tuple | None          # 포스터 머리 (위색, 아래색) — None 이면 쪽 배경을 그대로
    head_ink: tuple
    foot: tuple                 # 포스터 아래 어두운 띠


def _pal(th: Theme, style: str) -> Pal:
    st = style if style in STYLES else "clean"
    acc, onacc = _rgb(th.accent), _rgb(th.on_accent)
    bg, surf = _rgb(th.bg), _rgb(th.surface)
    title, text, muted, soft = _rgb(th.title), _rgb(th.text), _rgb(th.muted), _rgb(th.soft)
    deep = _mix(acc, "0B1020", 0.30)
    foot = _mix(acc, "0B1020", 0.84)
    white = (255, 255, 255)
    strip = white if _lum(bg) > 0.5 else _mix(surf, "FFFFFF", 0.06)
    P = Pal(st, bg, None, surf, 1.0, surf, 1.0, None, strip, 1.0, title, text, muted, acc,
            _legible(acc, [bg, surf]), onacc, soft, (acc, deep), _best_ink([acc, deep], ("FFFFFF", "0B1020", th.on_accent)), foot)
    if st == "bold":
        P.head = (acc, acc)
        P.head_ink = _best_ink([acc], ("FFFFFF", "0B1020", th.on_accent))
    elif st == "pastel":
        pb = _mix(acc, "FFFFFF", 0.86)
        dark = title if _lum(title) < 0.25 else _rgb("1E2433")
        P.bg, P.sheet = pb, white
        P.panel, P.card, P.strip = _mix(acc, "FFFFFF", 0.90), white, white
        P.title, P.text, P.muted = dark, _mix(dark, "FFFFFF", 0.15), _mix(dark, "FFFFFF", 0.50)
        P.soft, P.ink = _mix(acc, "FFFFFF", 0.6), _legible(acc, [pb, white, P.panel])
        P.head = (_mix(acc, "FFFFFF", 0.74), _mix(acc, "FFFFFF", 0.82))
        P.head_ink = dark
    elif st == "gradient":
        c0, c1, ink = acc, deep, white
        for t in (0.50, 0.38, 0.26):                    # 글자가 충분히 읽힐 때까지 그라데이션 폭을 좁힌다
            c1 = _mix(acc, "0B1020", t)
            ink = _best_ink([c0, c1])
            if min(_contrast(ink, c0), _contrast(ink, c1)) >= 4.0:
                break
        mid = _mix(c0, c1, 0.5)
        P.grad, P.bg, P.head = (c0, c1), mid, None
        P.panel, P.panel_a, P.card, P.card_a, P.strip, P.strip_a = ink, 0.14, ink, 0.14, ink, 0.18
        P.title, P.ink, P.accent, P.head_ink = ink, ink, ink, ink
        P.text, P.muted = _mix(ink, mid, 0.06), _mix(ink, mid, 0.22)
        P.on_accent, P.soft = _mix(mid, "0B1020", 0.45) if ink == white else _mix(mid, "FFFFFF", 0.9), _mix(ink, mid, 0.5)
        P.foot = _mix(c1, "0B1020", 0.55)
    return P


# ---------------------------------------------------------------- 글 배치
def wrap(draw, text: str, font, width: float) -> list[str]:
    """띄어쓰기 단위로 줄을 바꾼다. 한 낱말이 너무 길면 글자 단위로 끊는다."""
    lines: list[str] = []
    for para in str(text).splitlines() or [""]:
        cur = ""
        for word in para.split(" "):
            trial = f"{cur} {word}".strip() if cur else word
            if draw.textlength(trial, font=font) <= width:
                cur = trial
                continue
            if cur:
                lines.append(cur)
            if draw.textlength(word, font=font) <= width:
                cur = word
                continue
            cur = ""
            for ch in word:
                if draw.textlength(cur + ch, font=font) <= width:
                    cur += ch
                else:
                    lines.append(cur)
                    cur = ch
        lines.append(cur)
    return [line for line in lines if line.strip()] or [""]


def _balance(draw, text: str, font, width: float, lines: list[str]) -> list[str]:
    """줄 수는 그대로 두고 줄 너비를 좁혀 마지막 줄이 한두 글자만 남는 것을 막는다."""
    if len(lines) < 2 or "\n" in str(text):
        return lines
    lo, hi, best = width * 0.55, width, lines
    for _ in range(8):
        mid = (lo + hi) / 2
        trial = wrap(draw, text, font, mid)
        if len(trial) <= len(lines):
            best, hi = trial, mid
        else:
            lo = mid
    return best


def fit(draw, text: str, weight: str, width: float, height: float, big: float, small: float,
        gap: float = 1.25, max_lines: int | None = None) -> tuple[object, list[str], float]:
    """상자에 들어가는 가장 큰 글자 → (글꼴, 줄들, 크기). 가장 작게 해도 넘치면 남는 줄을 '…' 로 줄인다."""
    size = big
    while True:
        f = _font(weight, size)
        lines = wrap(draw, text, f, width)
        if (len(lines) * size * gap <= height and (max_lines is None or len(lines) <= max_lines)) or size <= small:
            break
        size = max(small, size * 0.92)
    keep = max(1, min(len(lines), int(height // (size * gap)), max_lines or 999))
    if keep < len(lines):
        lines = lines[:keep]
        while lines[-1] and draw.textlength(lines[-1] + "…", font=f) > width:
            lines[-1] = lines[-1][:-1]
        lines[-1] += "…"
    else:
        lines = _balance(draw, text, f, width, lines)
    return f, lines, size


def text_block(draw, xy, lines, font, size, color, gap: float = 1.25, align: str = "left", width: float = 0) -> float:
    """줄들을 그린다 → 그린 높이."""
    x, y = xy
    for i, line in enumerate(lines):
        lx = x
        if align == "center":
            lx = x + (width - draw.textlength(line, font=font)) / 2
        elif align == "right":
            lx = x + width - draw.textlength(line, font=font)
        draw.text((lx, y + i * size * gap), line, font=font, fill=color)
    return len(lines) * size * gap


_BULLET = re.compile(r"^\s*(?:[•·▪*]\s*|[-–]\s+)")


def bullet_block(draw, box, items: list[str], theme: Theme | None, big: float, small: float, gap: float = 1.42,
                 dot=None, ink=None) -> None:
    """글머리 기호 목록 (강조색 점 · 다음 줄은 들여쓰기 맞춤). 상자에 맞게 크기를 줄이고, 그래도 넘치면 마지막 줄을 '…' 로 맺는다."""
    x0, y0, x1, y1 = box
    items = [_BULLET.sub("", s) for s in items if s.strip()]     # 글머리 기호는 점으로 그린다
    if not items:
        return
    dot = _rgb(dot if dot is not None else theme.accent)
    ink = _rgb(ink if ink is not None else theme.text)
    size = big
    while True:
        f = _font("regular", size)
        indent = size * 1.15
        blocks = [wrap(draw, it, f, x1 - x0 - indent) for it in items]
        total = sum(len(b) for b in blocks) * size * gap + (len(items) - 1) * size * 0.55
        if total <= y1 - y0 or size <= small:
            break
        size = max(small, size * 0.93)
    y = y0
    for bi, lines in enumerate(blocks):
        if y + size * gap > y1 + 1:
            break
        r = size * 0.17
        cy = y + size * 0.62
        draw.ellipse((x0 + size * 0.2 - r, cy - r, x0 + size * 0.2 + r, cy + r), fill=dot)
        for li, line in enumerate(lines):
            if y + size * gap > y1 + 1:
                break
            more = li + 1 < len(lines) or bi + 1 < len(blocks)
            if more and y + size * gap * 2 > y1 + 1:             # 이 줄이 마지막으로 들어갈 자리 → 남은 글이 있으면 '…'
                while line and draw.textlength(line + "…", font=f) > x1 - x0 - indent:
                    line = line[:-1]
                line += "…"
                draw.text((x0 + indent, y), line, font=f, fill=ink)
                return
            draw.text((x0 + indent, y), line, font=f, fill=ink)
            y += size * gap
        y += size * 0.55


def _domain(ref: str) -> str:
    """출처 한 줄을 짧게: URL 이면 사이트 주소만, 아니면 앞부분만."""
    m = re.search(r"https?://\S+", ref)
    if m:
        host = urllib.parse.urlparse(m.group(0)).netloc.removeprefix("www.")
        head = ref[:m.start()].strip(" —-:|")
        return f"{head} ({host})" if head else host
    return ref[:60]


# ---------------------------------------------------------------- 그리는 붓 (설계 좌표 → 실제 픽셀)
class Pen:
    """설계 좌표(카드는 1080 기준)로 말하면 s 배 크기의 그림에 그린다. 반투명 도형 · 글자 · 아이콘은 따로 마스크에 그려 합성한다."""

    def __init__(self, w: float, h: float, s: float, fill=(255, 255, 255)):
        from PIL import Image, ImageDraw
        self.s = s
        self.img = Image.new("RGB", (round(w * s), round(h * s)), _rgb(fill))
        self.d = ImageDraw.Draw(self.img)

    # -- 바탕
    def vgrad(self, box, c0, c1) -> None:
        """위→아래 그라데이션 (처음은 c0 그대로 — 가장자리 색이 어긋나지 않게 천천히 시작)."""
        x0, y0, x1, y1 = (round(v * self.s) for v in box)
        c0, c1 = _rgb(c0), _rgb(c1)
        n = max(1, y1 - y0)
        for i in range(n):
            t = i / n
            t = t * t * (3 - 2 * t)
            self.d.line([(x0, y0 + i), (x1, y0 + i)], fill=tuple(round(a + (b - a) * t) for a, b in zip(c0, c1)))

    # -- 도형
    def _paint(self, fn, box, fill, a: float, outline=None, width: float = 0) -> None:
        x0, y0, x1, y1 = (v * self.s for v in box)
        w = int(width * self.s)
        if a >= 0.999:
            fn(self.d, (x0, y0, x1, y1), _rgb(fill) if fill is not None else None,
               _rgb(outline) if outline is not None else None, w)
            return
        from PIL import Image, ImageDraw
        W, H = self.img.size
        ix0, iy0 = max(0, math.floor(x0) - w - 2), max(0, math.floor(y0) - w - 2)
        ix1, iy1 = min(W, math.ceil(x1) + w + 2), min(H, math.ceil(y1) + w + 2)
        if ix1 <= ix0 or iy1 <= iy0:
            return
        m = Image.new("L", (ix1 - ix0, iy1 - iy0), 0)
        v = int(255 * max(0.0, a))
        fn(ImageDraw.Draw(m), (x0 - ix0, y0 - iy0, x1 - ix0, y1 - iy0), v if fill is not None else None,
           v if outline is not None else None, w)
        self.img.paste(_rgb(fill if fill is not None else outline), (ix0, iy0), m)

    def rect(self, box, fill=None, a: float = 1.0, r: float = 0, outline=None, width: float = 0) -> None:
        rr = r * self.s
        self._paint(lambda d, b, f, o, w: d.rounded_rectangle(b, radius=rr, fill=f, outline=o, width=w) if rr else
                    d.rectangle(b, fill=f, outline=o, width=w), box, fill, a, outline, width)

    def oval(self, box, fill=None, a: float = 1.0, outline=None, width: float = 0) -> None:
        self._paint(lambda d, b, f, o, w: d.ellipse(b, fill=f, outline=o, width=w), box, fill, a, outline, width)

    def disc(self, c, r: float, fill, a: float = 1.0) -> None:
        self.oval((c[0] - r, c[1] - r, c[0] + r, c[1] + r), fill, a)

    def line(self, p0, p1, fill, width: float, a: float = 1.0) -> None:
        x0, y0, x1, y1 = p0[0], p0[1], p1[0], p1[1]
        self._paint(lambda d, b, f, o, w: d.line([(b[0], b[1]), (b[2], b[3])], fill=f, width=max(1, int(width * self.s))),
                    (min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1)) if a >= 0.999 else (x0, y0, x1, y1), fill, a)

    # -- 글자 · 아이콘
    def font(self, weight: str, size: float):
        return _font(weight, size * self.s)

    def width(self, text: str, weight: str, size: float) -> float:
        return self.d.textlength(text, font=self.font(weight, size)) / self.s

    def text(self, xy, s: str, font, fill, a: float = 1.0, anchor: str = "la") -> None:
        x, y = xy[0] * self.s, xy[1] * self.s
        if a >= 0.999:
            self.d.text((x, y), s, font=font, fill=_rgb(fill), anchor=anchor)
            return
        from PIL import Image, ImageDraw
        l, t, r, b = font.getbbox(s, anchor=anchor)
        m = Image.new("L", (int(r - l) + 6, int(b - t) + 6), 0)
        ImageDraw.Draw(m).text((-l + 3, -t + 3), s, font=font, fill=int(255 * a), anchor=anchor)
        self.img.paste(_rgb(fill), (int(x + l - 3), int(y + t - 3)), m)

    def icon(self, name, c, size: float, fill, a: float = 1.0) -> bool:
        g = icons.glyph(name)
        if g is None:
            return False
        self.text(c, g, icons.font(round(size * self.s)), fill, a, "mm")
        return True

    def fit(self, text: str, weight: str, w: float, h: float, big: float, small: float, gap: float = 1.25,
            max_lines: int | None = None):
        f, lines, size = fit(self.d, text, weight, w * self.s, h * self.s, big * self.s, small * self.s, gap, max_lines)
        return f, lines, size / self.s

    def lines(self, xy, lines, f, size, fill, gap: float = 1.25, align: str = "left", width: float = 0, a: float = 1.0) -> float:
        """줄들을 그린다 (설계 좌표) → 그린 높이."""
        for i, line in enumerate(lines):
            lx = xy[0]
            if align != "left":
                tw = self.d.textlength(line, font=f) / self.s
                lx += (width - tw) / 2 if align == "center" else width - tw
            self.text((lx, xy[1] + i * size * gap), line, f, fill, a)
        return len(lines) * size * gap

    def vtext(self, box, text: str, weight: str, big: float, small: float, fill, gap: float = 1.25,
              max_lines: int | None = None, align: str = "left", valign: str = "middle", a: float = 1.0) -> tuple[float, int]:
        """상자 안에 글을 맞춰(크기 줄이기 → '…') 정렬해 그린다 → (글자 크기, 줄 수)."""
        x0, y0, x1, y1 = box
        f, lines, size = self.fit(text, weight, x1 - x0, y1 - y0, big, small, gap, max_lines)
        h = len(lines) * size * gap
        y = y0 + {"top": 0.0, "middle": (y1 - y0 - h) / 2, "bottom": y1 - y0 - h}[valign]
        self.lines((x0, y), lines, f, size, fill, gap, align, x1 - x0, a)
        return size, len(lines)

    def bullets(self, box, items, big: float, small: float, dot, ink, gap: float = 1.42) -> None:
        s = self.s
        bullet_block(self.d, tuple(v * s for v in box), items, None, big * s, small * s, gap, dot, ink)


# ---------------------------------------------------------------- 글 읽기 (카드 한 장의 내용 다듬기 · 배치 고르기)
_UNIT = r"%|퍼센트|배|명|개|원|만\s?원|억|조|건|시간|분|초|개월|kg|km|cm|점|위|회|곳|번|권|가지|도"
_STAT_END = re.compile(rf"(\d[\d,]*(?:\.\d+)?)\s*({_UNIT})\s*(?:입니다|이에요|예요|이다|다|[.!…])?\s*$", re.I)
_NUM = re.compile(r"^\s*([+\-~약]?\s*\d[\d,]*(?:\.\d+)?)\s*(.*)$")
_QUOTE = re.compile(r"^\s*[“\"‘'「『](.+?)[”\"’'」』]\s*(?:[-–—~―]+\s*(.+))?$", re.S)
_IMPERATIVE = re.compile(r"(세요|해요|하자|하라|해라|마세요|[가-힣]기|ㅂ시다)[.!]?$")
_STEPWORD = re.compile(r"방법|순서|단계|과정|절차|하는 법|루틴|step|how", re.I)
_SEQ = re.compile(r"^\s*(?:\d{1,2}\s*[.)]|[①-⑩]|처음|먼저|다음|그다음|마지막|끝으로|first|then|finally)", re.I)
_BAD = re.compile(r"^\s*(?:[✕✖×xX❌✗]|no\b)\s*[:.)\-]?\s*", re.I)
_GOOD = re.compile(r"^\s*(?:[○◯✓✔⭕oO]|yes\b)\s*[:.)\-]?\s*", re.I)
_ALIAS = {"number": "stat", "big": "stat", "bignumber": "stat", "step": "steps", "process": "steps", "vs": "compare",
          "comparison": "compare", "versus": "compare", "quotation": "quote", "bullets": "list", "bullet": "list",
          "numbered": "list", "text": "point", "hero": "point", "basic": "point"}


def _items(v) -> list[str]:
    """글 · 목록 · 엉뚱한 값(숫자 등) 어느 것이 와도 글 목록으로."""
    if v is None:
        return []
    if not isinstance(v, (str, list, tuple)):
        v = [str(v)]
    return [_text(x) for x in _strings(v) if _text(x)]


def _side(v, default_title: str) -> dict:
    """비교 한쪽 — 글 · 목록 · {title, items|bullets|text} 모두 받는다."""
    if isinstance(v, dict):
        return {"title": _text(v.get("title") or v.get("heading") or v.get("label")) or default_title,
                "items": _items(v.get("items") or v.get("bullets") or v.get("text"))}
    return {"title": default_title, "items": _items(v)}


def _infer_compare(title: str, items: list[str]) -> tuple[dict, dict] | None:
    """비교 내용을 글에서 알아낸다: '✕ …/○ …' 표시 · '전: …/후: …' · 'A vs B' 줄들 · 제목의 'A vs B'."""
    bad = [_BAD.sub("", s) for s in items if _BAD.match(s)]
    good = [_GOOD.sub("", s) for s in items if _GOOD.match(s)]
    if bad and good:
        return {"title": "하지 마세요", "items": bad}, {"title": "이렇게 하세요", "items": good}
    pre = [re.sub(r"^\s*(?:전|before|기존)\s*[:：]\s*", "", s, flags=re.I) for s in items if re.match(r"^\s*(?:전|before|기존)\s*[:：]", s, re.I)]
    post = [re.sub(r"^\s*(?:후|after|변화)\s*[:：]\s*", "", s, flags=re.I) for s in items if re.match(r"^\s*(?:후|after|변화)\s*[:：]", s, re.I)]
    if pre and post:
        return {"title": "Before", "items": pre}, {"title": "After", "items": post}
    ta, tb = "", ""
    m = re.split(r"\s+(?:vs\.?|VS|대|와|과|↔)\s+|\s*vs\.?\s*", title, maxsplit=1)
    if len(m) == 2 and m[0].strip() and m[1].strip():
        ta, tb = m[0].strip(), re.sub(r"\s*(?:비교|차이)\s*$", "", m[1]).strip()
    pairs = [re.split(r"\s+vs\.?\s+", s, maxsplit=1, flags=re.I) for s in items]
    if items and all(len(p) == 2 for p in pairs):
        return {"title": ta or "A", "items": [p[0].strip() for p in pairs]}, {"title": tb or "B", "items": [p[1].strip() for p in pairs]}
    if (ta and len(items) >= 2) or (re.search(r"비교|vs|차이", title, re.I) and len(items) >= 2 and len(items) % 2 == 0):
        half = (len(items) + 1) // 2
        return {"title": ta or "A", "items": items[:half]}, {"title": tb or "B", "items": items[half:]}
    return None


def _stat_parse(number: str, unit: str = "") -> tuple[str, str]:
    m = _NUM.match(number)
    if m and not unit:
        return m.group(1).strip(), m.group(2).strip()
    return number.strip(), unit.strip()


def _norm_card(c, i: int) -> dict:
    """카드 한 장 → 정리된 내용 + 고른 배치. 알 수 없는 배치 · 모자란 내용은 안전한 배치로 돌린다."""
    c = c if isinstance(c, dict) else {"title": str(c)}
    title = _text(c.get("title")) or f"{i}"
    items = [_text(_BULLET.sub("", s)) for s in _items(c.get("bullets") or c.get("text") or c.get("items"))]
    card = {"title": title, "items": items, "highlight": _text(c.get("highlight")), "icon": _text(c.get("icon")),
            "caption": _text(c.get("caption")), "number": "", "unit": "", "left": None, "right": None, "quote": "", "by": _text(c.get("by"))}
    want = _text(c.get("layout")).lower().replace("-", "").replace("_", "").replace(" ", "")
    want = _ALIAS.get(want, want)
    if want not in LAYOUTS:
        want = ""
    # -- 숫자
    if c.get("number") not in (None, ""):
        card["number"], card["unit"] = _stat_parse(_text(c.get("number")), _text(c.get("unit")))
    elif want in ("", "stat"):
        for src in ("highlight", "title"):
            m = _STAT_END.search(card[src])
            if m:
                card["number"], card["unit"] = m.group(1), m.group(2)
                rest = card[src][:m.start()].strip(" ,·:-—")
                if src == "title":
                    card["title"] = rest or title
                elif not card["caption"]:
                    card["caption"] = rest
                card["highlight"] = "" if src == "highlight" else card["highlight"]
                break
    # -- 비교
    if c.get("left") is not None or c.get("right") is not None:
        card["left"], card["right"] = _side(c.get("left"), "Before"), _side(c.get("right"), "After")
    elif want in ("", "compare"):
        inf = _infer_compare(card["title"], items)
        if inf:
            card["left"], card["right"] = inf
    # -- 인용
    q = _text(c.get("quote"))
    if q:
        card["quote"] = q
    elif want in ("", "quote"):
        for src in ([items[0]] if items else []) + [card["title"]]:
            m = _QUOTE.match(src)
            if m and len(m.group(1)) > 8:
                card["quote"], card["by"] = _text(m.group(1)), card["by"] or _text(m.group(2))
                if src is not card["title"]:
                    card["items"] = items[1:]
                break
    # -- 배치 고르기
    n = len(card["items"])
    short = all(len(s) <= 40 for s in card["items"])
    if want == "stat" and not card["number"]:
        m = _STAT_END.search(" ".join([card["title"], *card["items"]]))
        card["number"], card["unit"] = (m.group(1), m.group(2)) if m else ("", "")
    layout = want
    if layout == "stat" and not card["number"]:
        layout = ""
    if layout == "compare" and not (card["left"] and card["right"]):
        layout = "list" if n >= 2 else "point"
    if layout == "quote" and not card["quote"]:
        card["quote"] = card["items"][0] if card["items"] else card["title"]
    if layout in ("list", "steps") and not card["items"]:
        layout = "point"
    if not layout:
        if c.get("quote") not in (None, "") or card["quote"]:
            layout = "quote"
        elif card["number"]:
            layout = "stat"
        elif card["left"] and card["right"]:
            layout = "compare"
        elif 3 <= n <= 5 and short and (_STEPWORD.search(card["title"]) or sum(bool(_SEQ.match(s)) for s in card["items"]) >= 2
                                        or all(_IMPERATIVE.search(s) for s in card["items"])):
            layout = "steps"
        elif 3 <= n <= 6 and short:
            layout = "list"
        else:
            layout = "point"
    card["layout"] = layout
    if layout == "steps":
        card["items"] = [_SEQ.sub("", s) if _SEQ.match(s) and s.strip()[:1].isdigit() else s for s in card["items"]]
    return card


def _split_head(s: str) -> tuple[str, str]:
    """'제목: 설명' · '제목 — 설명' 꼴이면 (제목, 설명), 아니면 (글, '')."""
    m = re.match(r"^(.{2,18}?)\s*(?:[:：]\s+|\s[—–-]\s)\s*(.+)$", s)
    if m and "http" not in m.group(1):
        return m.group(1).strip(), m.group(2).strip()
    return s, ""


# ---------------------------------------------------------------- 카드뉴스 쪽 공통
X0, X1, BOT = 90, 990, 940


def _page(P: Pal, w: float, h: float, s: float, alt: bool = False) -> Pen:
    p = Pen(w, h, s, P.bg)
    if P.grad:
        c0, c1 = P.grad
        p.vgrad((0, 0, w, h), *((c1, c0) if alt else (c0, c1)))
    return p


def _footer(p: Pen, P: Pal, n: int, total: int, brand: str, color=None) -> None:
    col = color or P.muted
    f = p.font("regular", 26)
    page = f"{n} / {total}"
    p.text((990 - p.width(page, "regular", 26), 985), page, f, col)
    if brand:
        p.text((90, 985), brand[:40], f, col)


def _badge(p: Pen, P: Pal, c, d: float, name: str | None, on_band: bool = False) -> None:
    """아이콘을 동그란 바탕 위에 올린다 (아이콘 글꼴이 없으면 아무것도 그리지 않음)."""
    if not icons.glyph(name):
        return
    if on_band:
        p.disc(c, d / 2, P.on_accent, 0.18)
        p.icon(name, c, d * 0.56, P.on_accent)
    else:
        p.disc(c, d / 2, P.accent if P.style != "gradient" else P.accent, 1.0 if P.style != "gradient" else 0.22)
        p.icon(name, c, d * 0.56, P.on_accent if P.style != "gradient" else P.ink)


def _cover(P: Pal, title: str, tag: str, total: int, icon: str | None):
    acc, on = P.accent, P.on_accent
    pastel, bold = P.style == "pastel", P.style == "bold"
    if P.style == "gradient":
        p = _page(P, CARD, CARD, SS)
        ink, sub = P.ink, P.muted
        p.disc((860, 250), 380, ink, 0.07)
        p.disc((1000, 960), 300, ink, 0.07)
    elif pastel:
        p = _page(P, CARD, CARD, SS)
        ink, sub = P.title, P.muted
        p.disc((900, 880), 420, acc, 0.9)
        p.disc((1000, 130), 200, acc, 0.22)
        p.disc((130, 960), 120, acc, 0.15)
    else:
        p = Pen(CARD, CARD, SS, acc)
        ink = on
        sub = _mix(on, acc, 0.25)
        p.disc((1010, 950), 390, on, 0.14)
        p.disc((1000, 0), 240, on, 0.08)
        if bold:
            p.rect((0, 830, CARD, CARD), _mix(acc, "0B1020", 0.22))
            sub = _mix(on, _mix(acc, "0B1020", 0.22), 0.2)
    if icon:
        if pastel:
            p.icon(icon, (880, 860), 400, "FFFFFF" if _contrast("FFFFFF", acc) >= 2 else P.title)
        else:
            p.icon(icon, (840, 330), 620, ink, 0.13 if P.style == "gradient" else 0.2)
    if tag:
        f = p.font("bold", 30)
        tw = p.width(tag, "bold", 30)
        p.rect((90, 110, 90 + tw + 56, 170), r=30, outline=ink, width=3)
        p.text((118, 124), tag, f, ink)
    big = "black" if bold else "bold"
    f, lines, size = p.fit(title, big, 880, 470, 118, 62, gap=1.18, max_lines=4)
    h = len(lines) * size * 1.18
    p.lines((90, 300 + (470 - h) / 2), lines, f, size, ink, 1.18)
    p.rect((90, 880, 170, 888), ink if not pastel else acc)
    sf = p.font("regular", 28)
    p.text((90, 912), "옆으로 넘겨 보세요  →", sf, sub)
    page = f"1 / {total}"
    p.text((990 - p.width(page, "regular", 28), 912), page, sf, sub)
    return p.img


def _head(p: Pen, P: Pal, n: int, title: str, badge: bool, icon: str | None) -> float:
    """내용 카드의 윗부분 (번호 · 제목 · 작은 아이콘) → 본문이 시작하는 y."""
    tw = 900 - (150 if badge and icons.glyph(icon) else 0)
    if P.style == "bold":
        p.rect((0, 0, CARD, 318), P.accent)
        p.text((90, 62), f"{n:02d}", p.font("bold", 34), P.on_accent, 0.75)
        f, lines, size = p.fit(title, "black", tw, 190, 68, 40, gap=1.16, max_lines=3)
        h = len(lines) * size * 1.16
        p.lines((90, 118 + (180 - h) / 2), lines, f, size, P.on_accent, 1.16)
        if badge:
            _badge(p, P, (930, 160), 120, icon, on_band=True)
        return 360
    chip = f"{n:02d}"
    cw = p.width(chip, "bold", 30) + 44
    p.rect((90, 78, 90 + cw, 130), P.accent, r=26)
    p.text((90 + cw / 2, 104), chip, p.font("bold", 30), P.on_accent, anchor="mm")
    f, lines, size = p.fit(title, "bold", tw, 175, 66, 40, gap=1.18, max_lines=3)
    h = p.lines((90, 158), lines, f, size, P.title, 1.18)
    if badge:
        _badge(p, P, (930, 150), 120, icon)
    return max(158 + h + 34, 270)


def _highlight(p: Pen, P: Pal, text: str) -> None:
    p.rect((90, 806, 990, 946), P.panel, P.panel_a, r=24)
    p.rect((90, 806, 104, 946), P.accent if P.style != "gradient" else P.ink, r=7)
    p.vtext((134, 812, 962, 940), text, "bold", 40, 26, P.title, max_lines=2)


# ---------------------------------------------------------------- 카드 배치들
def _lay_point(p: Pen, P: Pal, c: dict, box, icon) -> None:
    x0, y0, x1, y1 = box
    items = c["items"]
    has_icon = bool(icons.glyph(icon))
    if len(items) <= 1 and (not items or len(items[0]) < 90):
        if has_icon:                                     # 아이콘 하나 + 문장 하나를 가운데에
            cy = y0 + (y1 - y0) * (0.30 if items else 0.5)
            p.disc((540, cy), 150, P.accent, 1.0 if P.style != "gradient" else 0.22)
            p.disc((540, cy), 188, P.accent, 0.12)
            p.icon(icon, (540, cy), 190, P.on_accent if P.style != "gradient" else P.ink)
        if items:
            top = y0 + (y1 - y0) * 0.30 + (215 if has_icon else -90)
            p.vtext((x0 + 20, top, x1 - 20, y1), items[0], "semibold", 54, 32, P.title, align="center", valign="top", gap=1.35)
        return
    lead, rest = items[0], items[1:]
    d = 170
    if has_icon:
        p.disc((x0 + d / 2, y0 + d / 2 + 6), d / 2, P.accent, 1.0 if P.style != "gradient" else 0.22)
        p.icon(icon, (x0 + d / 2, y0 + d / 2 + 6), 104, P.on_accent if P.style != "gradient" else P.ink)
    lx = x0 + (d + 36 if has_icon else 0)
    if len(items) <= 2 and len(lead) < 70:
        p.vtext((lx, y0, x1, y0 + d + 10), lead, "semibold", 48, 32, P.title, max_lines=3)
        p.bullets((x0, y0 + d + 50, x1, y1), rest, 42, 26, P.accent if P.style != "gradient" else P.ink, P.text)
    else:
        p.bullets((x0, y0 + (d + 40 if has_icon else 0), x1, y1), items, 42, 26,
                  P.accent if P.style != "gradient" else P.ink, P.text)


def _row_text(p: Pen, P: Pal, box, text: str, big: float, small: float) -> None:
    head, desc = _split_head(text)
    x0, y0, x1, y1 = box
    if not desc:
        p.vtext(box, text, "semibold", big, small, P.title, max_lines=3, gap=1.28)
        return
    hh = (y1 - y0) * 0.46
    p.vtext((x0, y0, x1, y0 + hh), head, "bold", big, small, P.title, max_lines=1, valign="bottom")
    p.vtext((x0, y0 + hh + 2, x1, y1), desc, "regular", big * 0.8, small * 0.82, P.text, max_lines=2, valign="top", gap=1.3)


def _lay_list(p: Pen, P: Pal, c: dict, box, icon) -> None:
    x0, y0, x1, y1 = box
    items = c["items"][:6]
    if len(c["items"]) > 6:
        items[-1] = " · ".join(c["items"][5:])
    gap = 18
    n = len(items)
    rh = min(150, (y1 - y0 - gap * (n - 1)) / n)
    top = y0 + max(0, (y1 - y0 - (rh * n + gap * (n - 1))) * 0.4)
    for i, it in enumerate(items):
        ry = top + i * (rh + gap)
        p.rect((x0, ry, x1, ry + rh), P.panel, P.panel_a, r=24)
        bd = min(rh - 30, 76)
        bx, by = x0 + 22, ry + (rh - bd) / 2
        p.rect((bx, by, bx + bd, by + bd), P.accent if P.style != "gradient" else P.ink, r=bd * 0.3)
        p.text((bx + bd / 2, by + bd / 2 + 1), str(i + 1), p.font("black", bd * 0.55), P.on_accent, anchor="mm")
        _row_text(p, P, (bx + bd + 28, ry + 10, x1 - 26, ry + rh - 10), it, 38, 22)


def _lay_steps(p: Pen, P: Pal, c: dict, box, icon) -> None:
    x0, y0, x1, y1 = box
    items = c["items"][:7]
    if len(c["items"]) > 7:
        items[-1] = " · ".join(c["items"][6:])
    n = len(items)
    rh = min(150, (y1 - y0) / n)
    y0 += max(0, (y1 - y0 - rh * n) * 0.4)
    d = min(84, rh * 0.62)
    cx = x0 + 44
    ink = P.accent if P.style != "gradient" else P.ink
    for i in range(n - 1):                              # 동그라미 사이를 잇는 줄
        cy0 = y0 + i * rh + rh / 2 + d / 2
        cy1 = y0 + (i + 1) * rh + rh / 2 - d / 2
        p.rect((cx - 3, cy0 + 4, cx + 3, cy1 - 4), P.soft if P.style != "gradient" else P.ink, 0.55 if P.style == "gradient" else 1.0, r=3)
    for i, it in enumerate(items):
        cy = y0 + i * rh + rh / 2
        p.disc((cx, cy), d / 2 + 6, ink, 0.16)
        p.disc((cx, cy), d / 2, ink)
        p.text((cx, cy + 1), str(i + 1), p.font("black", d * 0.5), P.on_accent, anchor="mm")
        _row_text(p, P, (x0 + 110, cy - rh / 2 + 6, x1, cy + rh / 2 - 6), it, 38, 22)


def _lay_compare(p: Pen, P: Pal, c: dict, box, icon) -> None:
    x0, y0, x1, y1 = box
    gap = 36
    cw = (x1 - x0 - gap) / 2
    ph = min(y1 - y0, 150 + 100 * max(len(c["left"]["items"]), len(c["right"]["items"]), 1))
    y0 += (y1 - y0 - ph) * 0.3                           # 칸이 짧으면 본문 영역 안에서 조금 아래로
    y1 = y0 + ph
    sides = ((c["left"], x0, "close", True), (c["right"], x0 + cw + gap, "check_circle", False))
    for side, sx, ic, neg in sides:
        head_col = _mix(P.title, P.bg, 0.45) if (neg and P.style != "gradient") else (P.accent if P.style != "gradient" else P.ink)
        on_head = _best_ink([head_col], (P.on_accent, "FFFFFF", "0B1020")) if P.style != "gradient" else P.on_accent
        p.rect((sx, y0, sx + cw, y1), P.panel, P.panel_a, r=28)
        p.rect((sx, y0, sx + cw, y0 + 96), head_col, 1.0 if P.style != "gradient" else (0.55 if neg else 0.95), r=28)
        p.rect((sx, y0 + 60, sx + cw, y0 + 96), head_col, 1.0 if P.style != "gradient" else (0.55 if neg else 0.95))
        hx = sx + 28
        if icons.glyph(ic):
            p.icon(ic, (sx + 52, y0 + 48), 44, on_head)
            hx = sx + 90
        p.vtext((hx, y0 + 4, sx + cw - 20, y0 + 92), side["title"], "bold", 38, 22, on_head, max_lines=1)
        dot = _mix(P.title, P.bg, 0.5) if neg and P.style != "gradient" else (P.ink if P.style == "gradient" else P.accent)
        p.bullets((sx + 26, y0 + 124, sx + cw - 24, y1 - 24), side["items"][:6] or ["—"], 38, 22, dot, P.text)
    cx, cy = x0 + cw + gap / 2, y0 + 48
    p.disc((cx, cy), 31, P.bg if not P.grad else P.grad[0])
    p.text((cx, cy + 1), "VS", p.font("black", 25), P.title, anchor="mm")


def _lay_stat(p: Pen, P: Pal, c: dict, box, icon) -> None:
    x0, y0, x1, y1 = box
    cx = 540
    p.disc((cx, y0 + (y1 - y0) * 0.42), 270, P.accent if P.style != "gradient" else P.ink, 0.07)
    if icons.glyph(icon):
        p.disc((cx, y0 + 28), 46, P.accent if P.style != "gradient" else P.ink, 0.18 if P.style == "gradient" else 1.0)
        p.icon(icon, (cx, y0 + 28), 52, P.on_accent if P.style != "gradient" else P.ink)
    num, unit = c["number"][:14], c["unit"]
    if len(unit) > 8:
        unit = unit[:7] + "…"
    size = 330.0
    while True:
        nw = p.width(num, "black", size)
        uw = p.width(unit, "black", size * 0.34) if unit else 0
        if nw + uw + (size * 0.06 if unit else 0) <= 860 or size <= 40:
            break
        size *= 0.93
    total = nw + uw + (size * 0.06 if unit else 0)
    left = cx - total / 2
    base = y0 + (y1 - y0) * 0.44 + size * 0.40
    ink = P.ink
    p.text((left, base), num, p.font("black", size), ink, anchor="ls")
    if unit:
        p.text((left + nw + size * 0.06, base), unit, p.font("black", size * 0.34), ink, anchor="ls")
    cap = c["caption"] or (" ".join(c["items"]) if c["items"] else "") or c["highlight"]
    if cap:
        p.vtext((x0 + 60, base + 40, x1 - 60, y1), cap, "semibold", 44, 26, P.text, align="center", valign="top", max_lines=3, gap=1.35)


def _lay_quote(p: Pen, P: Pal, c: dict, box, icon) -> None:
    x0, y0, x1, y1 = box
    ink = P.ink
    p.text((x0 - 4, y0 + 175), "“", p.font("black", 280), ink, anchor="ls")
    by = c["by"] or c["highlight"]
    qy1 = y1 - (110 if by else 20)
    p.vtext((x0 + 20, y0 + 205, x1 - 10, qy1), c["quote"], "semibold", 58, 32, P.title, gap=1.38, valign="top")
    if by:
        p.rect((x0 + 20, y1 - 82, x0 + 80, y1 - 76), ink)
        p.vtext((x0 + 20, y1 - 66, x1, y1 + 4), "— " + by.lstrip("—–- "), "bold", 36, 22, P.muted if P.style != "gradient" else P.text, max_lines=1)


_LAYOUT = {"point": _lay_point, "list": _lay_list, "steps": _lay_steps, "compare": _lay_compare, "stat": _lay_stat,
           "quote": _lay_quote}


def _card(P: Pal, n: int, total: int, c: dict, icon: str | None, brand: str):
    p = _page(P, CARD, CARD, SS)
    if P.sheet:                                          # 파스텔: 연한 바탕 위에 흰 판
        p.rect((36, 36, CARD - 36, CARD - 36), P.sheet, r=56)
    if P.style == "bold":
        p.text((1050, 1030), f"{n:02d}", p.font("black", 430), P.accent, 0.05, anchor="rs")
    layout = c["layout"]
    top = _head(p, P, n, c["title"], layout in ("list", "steps", "compare"), icon)
    has_hl = bool(c["highlight"]) and layout in ("point", "list", "steps", "compare")
    box = (X0, top, X1, 786 if has_hl else BOT)
    try:
        _LAYOUT[layout](p, P, c, box, icon)
    except Exception:                                    # 배치를 그리다 막혀도 카드는 만든다 — 글머리 목록으로
        p.rect((X0, top, X1, BOT), P.bg if not P.grad else P.grad[0])
        p.bullets((X0, top, X1, 786 if has_hl else BOT), c["items"] or [c["title"]], 44, 26, P.accent, P.text)
    if has_hl:
        _highlight(p, P, c["highlight"])
    _footer(p, P, n + 1, total, brand)
    return p.img


def _closing(P: Pal, message: str, lines: list[str], refs: list[str], total: int, icon: str | None):
    bold = P.style == "bold"
    if bold:
        p = Pen(CARD, CARD, SS, P.accent)
        ink, body, mut = P.on_accent, P.on_accent, _mix(P.on_accent, P.accent, 0.3)
        p.disc((100, 1000), 340, P.on_accent, 0.10)
        badge_fill, badge_on = P.on_accent, P.accent
    elif P.style == "gradient":
        p = _page(P, CARD, CARD, SS, alt=True)
        ink, body, mut = P.title, P.text, P.muted
        p.disc((100, 1000), 340, P.ink, 0.08)
        badge_fill, badge_on = P.ink, P.on_accent
    else:
        pastel = P.style == "pastel"
        p = Pen(CARD, CARD, SS, P.panel if pastel else P.panel)
        if pastel:
            p.rect((0, 0, CARD, CARD), P.bg)
            p.rect((36, 36, CARD - 36, CARD - 36), P.sheet, r=56)
        p.disc((100, 1000), 340, P.soft, 0.55 if pastel else 1.0)
        ink, body, mut = P.title, P.text, P.muted
        badge_fill, badge_on = P.accent, P.on_accent
    y0 = 250
    if icons.glyph(icon):
        p.disc((540, 200), 76, badge_fill)
        p.icon(icon, (540, 200), 92, badge_on)
        y0 = 300
    room = 320 if lines else 380
    f, ml, size = p.fit(message or "감사합니다", "bold" if not bold else "black", 900, room, 96, 52, gap=1.2, max_lines=3)
    h = len(ml) * size * 1.2
    y = y0 + (room - h) / 2
    p.lines((90, y), ml, f, size, ink, 1.2, align="center", width=900)
    if lines:
        sf, sl, ss = p.fit(" ".join(lines), "regular", 860, 150, 38, 26, gap=1.35, max_lines=3)
        p.lines((110, y + h + 36), sl, sf, ss, body, 1.35, align="center", width=860)
    if refs:
        rf = p.font("regular", 21)
        p.text((90, 850), "출처", p.font("bold", 22), mut)
        for i, r in enumerate(refs[:3]):
            p.text((90, 885 + i * 30), _domain(r)[:60], rf, mut)
    page = f"{total} / {total}"
    p.text((990 - p.width(page, "regular", 26), 985), page, p.font("regular", 26), mut)
    return p.img


def _save(img, w: int, h: int, path: Path) -> object:
    from PIL import Image
    out = img.resize((w, h), Image.LANCZOS)
    out.save(path)                      # (optimize 는 몇 배 느려 쓰지 않는다)
    return out


def build_cardnews(folder: Path, title: str, cards: list, subtitle: str = "", closing: str = "",
                   sources=None, theme: str = "light", *, style: str = "clean", icon: str = "") -> dict:
    """카드뉴스를 만든다 → {'cards': 장 수, 'pdf': PDF 경로, 'files': 그림 경로들, 'layouts': 카드별 배치, 'style': 스타일}.

    카드 한 장: {title, bullets|text, highlight, layout, icon, number, unit, caption, left, right, quote, by}.
    style: clean · bold · gradient · pastel (모르는 값은 clean). icon: 표지 아이콘 (없으면 제목에서 고름)."""
    title = _text(title)
    if not title:
        raise ValueError("카드뉴스 제목(title)이 필요합니다.")
    if not isinstance(cards, list) or not cards:
        raise ValueError("내용 카드(cards)가 하나 이상 필요합니다.")
    if len(cards) > MAX_CARDS:
        raise ValueError(f"카드가 너무 많습니다 ({len(cards)}장). 내용 카드는 {MAX_CARDS}장 이하로 만드세요.")
    th = THEMES.get((theme or "light").strip().lower(), THEMES["light"])
    st = _text(style).lower()
    P = _pal(th, st if st in STYLES else "clean")
    folder = Path(folder)
    if folder.exists():
        shutil.rmtree(folder)                    # 고쳐 만들 때 (overwrite) 예전 장이 남지 않게
    folder.mkdir(parents=True)
    refs = [_text(r) for r in _strings(sources)]
    total = len(cards) + 2
    sub = _text(subtitle)
    norm = [_norm_card(c, i) for i, c in enumerate(cards, 1)]
    end = closing if isinstance(closing, str) else ""
    first, *rest = (end.splitlines() or ["감사합니다"]) if end.strip() else ["감사합니다"]
    cover_icon = icons.pick(icon, title, sub, kind="cover")
    given = [(c["icon"], [c["title"], *c["items"], c["highlight"], c["caption"]]) for c in norm]
    picks = icons.assign(given, spare="cards", avoid=[cover_icon] if cover_icon else ())
    end_icon = icons.pick(None, _text(first), kind="closing", avoid=[x for x in [cover_icon, *picks] if x])
    imgs = [_cover(P, title, sub, total, cover_icon)]
    for i, (c, ic) in enumerate(zip(norm, picks), 1):
        imgs.append(_card(P, i, total, c, ic, sub or title))
    imgs.append(_closing(P, _text(first), [_text(x) for x in rest if x.strip()], refs, total, end_icon))
    files, saved = [], []
    for i, img in enumerate(imgs, 1):
        path = folder / f"{i:02d}.png"
        saved.append(_save(img, CARD, CARD, path))
        files.append(path)
    pdf = folder / f"{folder.name}.pdf"
    saved[0].save(pdf, save_all=True, append_images=saved[1:], resolution=150)
    return {"cards": len(files), "pdf": pdf, "files": files, "layouts": [c["layout"] for c in norm], "style": P.style}


# ---------------------------------------------------------------- 포스터
_INFO_KEYS = re.compile(r"일시|날짜|일정|시간|기간|장소|위치|대상|참가|참여|문의|연락|비용|참가비|신청|접수|마감|주최|주관", re.I)


def _info_items(info, secs: list[dict]) -> tuple[list[dict], list[dict]]:
    """정보 띠에 넣을 칸들 → (정보 칸들, 띠에 쓰고 남은 구역들). info 를 안 주면 '일시 · 장소…' 구역에서 뽑는다."""
    out: list[dict] = []
    if isinstance(info, (list, tuple)) and info:
        for it in info:
            if isinstance(it, dict):
                text = _text(it.get("text") or it.get("value") or it.get("content"))
                if text:
                    out.append({"icon": _text(it.get("icon")), "label": _text(it.get("label") or it.get("title")), "text": text})
            elif _text(it):
                out.append({"icon": "", "label": "", "text": _text(it)})
        return out[:4], secs
    rest: list[dict] = []
    for s in secs:
        head = _text(s.get("heading"))
        body = " · ".join(_items(s.get("bullets") or s.get("text")))
        if head and body and len(out) < 4 and _INFO_KEYS.search(head) and len(body) <= 40:
            out.append({"icon": _text(s.get("icon")), "label": head, "text": body})
        else:
            rest.append(s)
    if not rest:                                         # 구역이 하나도 안 남으면 그대로 구역으로 둔다
        return [], secs
    return out, rest


def _bul_height(d, items: list[str], f, width: float, size: float, gap: float) -> float:
    items = [_BULLET.sub("", s) for s in items if s.strip()]
    if not items:
        return 0.0
    return sum(len(wrap(d, it, f, width - size * 1.15)) for it in items) * size * gap + (len(items) - 1) * size * 0.55


def build_poster(path: Path, title: str, sections: list, subtitle: str = "", highlight: str = "", footer: str = "",
                 sources=None, theme: str = "light", size: str = "a4", *, style: str = "clean", icon: str = "",
                 info=None) -> dict:
    """포스터를 만든다 (PNG + 같은 이름의 PDF) → {'sections': 구역 수, 'pdf': PDF 경로, 'size': (가로, 세로), 'style', 'info': 정보 칸 수}.

    sections: [{heading, bullets|text, icon}]. info: [{icon?, label, text}] — 일시 · 장소 같은 핵심 정보 띠
    (안 주면 '일시 · 장소 · 대상…' 제목의 짧은 구역에서 뽑는다). style: clean · bold · gradient · pastel."""
    title = _text(title)
    if not title:
        raise ValueError("포스터 제목(title)이 필요합니다.")
    secs = [s if isinstance(s, dict) else {"heading": "", "bullets": [str(s)]} for s in (sections or [])]
    if not secs and not _text(highlight):
        raise ValueError("포스터에 넣을 내용(sections)이 필요합니다.")
    if len(secs) > 6:
        raise ValueError("포스터 구역(sections)은 6개 이하로 만드세요.")
    th = THEMES.get((theme or "light").strip().lower(), THEMES["light"])
    st = _text(style).lower()
    P = _pal(th, st if st in STYLES else "clean")
    k = 1.4142 if str(size).lower() == "a3" else 1.0
    W, H = round(A4[0] * k), round(A4[1] * k)
    S = SS * k                                   # 기준(A4) 좌표 → 실제 그리는 좌표
    n_secs = len(secs)
    strip_items, body_secs = _info_items(info, secs)
    # -- 아이콘 고르기 (머리 → 정보 칸 → 구역, 서로 겹치지 않게)
    sub, hl = _text(subtitle), _text(highlight)
    head_icon = icons.pick(icon, title, sub, hl, kind="poster")
    used = [head_icon] if head_icon else []
    info_ic = icons.assign([(it["icon"], [it["label"], it["text"]]) for it in strip_items], spare="steps", avoid=used) if strip_items else []
    used += [x for x in info_ic if x]
    sec_ic = icons.assign([(s.get("icon"), [_text(s.get("heading")), *_items(s.get("bullets") or s.get("text"))]) for s in body_secs],
                          spare="cards", avoid=used) if body_secs else []

    p = _page(P, 1240, 1754, S)
    ink = P.head_ink
    head = 660 if strip_items else 620
    bold = P.style == "bold"
    # -- 머리
    if P.head is not None:
        if P.style == "pastel":
            p.rect((0, -90, 1240, head), P.head[0], r=70)
            p.disc((1060, 120), 300, P.accent, 0.25)
        else:
            p.vgrad((0, 0, 1240, head), *P.head)
    p.disc((1060, 90), 330, ink, 0.08)
    p.disc((1130, head - 120), 200, ink, 0.06)
    if bold:
        p.rect((0, head - 34, 1240, head), _mix(P.accent, "0B1020", 0.25))
    if head_icon:
        p.icon(head_icon, (960, 330), 640, ink, 0.10)
        p.disc((175, 165), 75, ink, 0.18)
        p.icon(head_icon, (175, 165), 92, ink)
    sub_h = 0.0
    if sub:
        sf, sl, ss = p.fit(sub, "regular", 1040, 90, 40, 26, gap=1.3, max_lines=2)
        sub_h = len(sl) * ss * 1.3
    zone_top, zone_bot = 270, (head - 125 if strip_items else head - 50) - (sub_h + 24 if sub else 0)
    f, lines, sz = p.fit(title, "black" if bold else "bold", 1040, zone_bot - zone_top, 128, 62, gap=1.12, max_lines=3)
    block = len(lines) * sz * 1.12
    ty = zone_top + max(0.0, (zone_bot - zone_top - block) / 2)
    p.lines((100, ty), lines, f, sz, ink, 1.12)
    if sub:
        p.lines((100, ty + block + 24), sl, sf, ss, _mix(ink, P.head[1] if P.head else P.bg, 0.15), 1.3)
    y = head + 50
    # -- 정보 띠
    if strip_items:
        sy0, sy1 = head - 80, head + 80
        if not P.grad:                                   # 부드러운 그림자 (겹쳐 그려 번지게)
            for off, al in ((12, 0.03), (8, 0.04), (4, 0.05)):
                p.rect((100 + off / 2, sy0 + off, 1140 - off / 2, sy1 + off), "000000", al, r=34)
        p.rect((100, sy0, 1140, sy1), P.strip, P.strip_a, r=34)
        icon_w = 74
        # 칸 너비: 글이 한 줄로 들어갈 만큼을 먼저 주고, 남는 폭은 글 길이에 비례해 나눈다 (모자라면 비례해 줄여 두 줄로)
        needs = [(icon_w if icons.glyph(info_ic[i]) else 12) + max(p.width(it["text"], "bold", 32), p.width(it["label"], "semibold", 21)) + 36
                 for i, it in enumerate(strip_items)]
        inner = 1040 - 40
        scale = inner / sum(needs) if sum(needs) > 0 else 1.0
        widths = [n_ * scale for n_ in needs]
        x = 120.0
        boxes = []
        for wd in widths:
            boxes.append((x, x + wd))
            x += wd
        tsize = 34.0
        for i, (it, (bx0, bx1)) in enumerate(zip(strip_items, boxes)):  # 모든 칸이 같은 글자 크기를 쓰게 가장 작은 쪽에 맞춘다
            tx0 = bx0 + (icon_w if icons.glyph(info_ic[i]) else 12)
            _, _, tsz = p.fit(it["text"], "bold", bx1 - tx0 - 14, 70 - (24 if it["label"] else 0), 34, 19, gap=1.2, max_lines=2)
            tsize = min(tsize, tsz)
        mid = (sy0 + sy1) / 2
        for i, (it, (bx0, bx1)) in enumerate(zip(strip_items, boxes)):
            if i:
                p.rect((bx0 - 1, sy0 + 30, bx0 + 1, sy1 - 30), P.muted, 0.35)
            has = bool(icons.glyph(info_ic[i]))
            tx0 = bx0 + (icon_w if has else 12)
            if has:
                cx = bx0 + 38
                p.disc((cx, mid), 29, P.accent, 0.22 if P.style == "gradient" else 1.0)
                p.icon(info_ic[i], (cx, mid), 34, P.ink if P.style == "gradient" else P.on_accent)
            f_, tl, tz = p.fit(it["text"], "bold", bx1 - tx0 - 14, 70 - (24 if it["label"] else 0), tsize, tsize, gap=1.2, max_lines=2)
            lab_h = 28 if it["label"] else 0
            top = mid - (lab_h + len(tl) * tz * 1.2) / 2
            if it["label"]:
                p.vtext((tx0, top, bx1 - 8, top + 26), it["label"], "semibold", 21, 15, P.muted, max_lines=1, valign="top")
            p.lines((tx0, top + lab_h), tl, f_, tz, P.title, 1.2)
        y = sy1 + 36
    # -- 강조 문구
    if hl and strip_items:
        p.rect((100, y, 1140, y + 118), P.panel, P.panel_a, r=30)
        p.rect((100, y, 114, y + 118), P.accent if P.style != "gradient" else P.ink, r=7)
        p.vtext((150, y + 8, 1100, y + 110), hl, "bold", 50, 28, P.ink if P.style != "gradient" else P.title, max_lines=2, align="center")
        y += 118 + 38
    elif hl:
        hb = (100, head - 70, 1140, head + 110)
        p.rect((hb[0] + 8, hb[1] + 10, hb[2] + 8, hb[3] + 10), "000000", 0.10, r=28)
        p.rect(hb, P.strip if not P.grad else P.grad[0], 1.0 if not P.grad else 1.0, r=28, outline=P.accent if not P.grad else P.ink, width=4)
        p.vtext((140, hb[1] + 10, 1100, hb[3] - 10), hl, "bold", 52, 30, P.ink if not P.grad else P.ink, max_lines=2, align="center")
        y = hb[3] + 50
    # -- 구역들
    foot_top = 1754 - 170
    if body_secs:
        cols = 1 if len(body_secs) <= 2 else 2
        rows = -(-len(body_secs) // cols)
        gap = 34
        cw = (1040 - gap * (cols - 1)) / cols
        avail = foot_top - 36 - y
        ch = min((avail - gap * (rows - 1)) / rows, 380)
        y += max(0.0, (avail - (ch * rows + gap * (rows - 1))) * 0.4)
        bw = cw - 70
        # 모든 구역이 같은 글자 크기를 쓰게: 머리글 · 본문 크기를 가장 많은 글을 가진 구역에 맞춘다
        hs = 50.0
        for s in body_secs:
            if _text(s.get("heading")):
                _, _, hz = p.fit(_text(s.get("heading")), "bold", cw - 160, 70, 50, 28, gap=1.2, max_lines=2)
                hs = min(hs, hz)
        head_h = 110 if any(_text(s.get("heading")) for s in body_secs) else 40
        bsz = 44.0
        while bsz > 22:
            f_ = _font("regular", bsz * S)
            if all(_bul_height(p.d, _items(s.get("bullets") or s.get("text")), f_, bw * S, bsz * S, 1.42) / S <= ch - head_h - 56
                   for s in body_secs):
                break
            bsz *= 0.94
        for i, s in enumerate(body_secs):
            r, c = divmod(i, cols)
            x0, y0 = 100 + c * (cw + gap), y + r * (ch + gap)
            p.rect((x0, y0, x0 + cw, y0 + ch), P.card, P.card_a, r=28)
            if bold:
                p.rect((x0, y0 + 22, x0 + 10, y0 + ch - 22), P.accent, r=5)
            heading = _text(s.get("heading"))
            ty = y0 + 34
            if icons.glyph(sec_ic[i]):
                p.disc((x0 + 68, y0 + 66), 33, P.accent, 0.22 if P.style == "gradient" else 1.0)
                p.icon(sec_ic[i], (x0 + 68, y0 + 66), 40, P.ink if P.style == "gradient" else P.on_accent)
                if heading:
                    p.vtext((x0 + 120, y0 + 26, x0 + cw - 30, y0 + 106), heading, "bold", hs, hs, P.title, max_lines=2)
                ty = y0 + 124
            elif heading:
                p.rect((x0 + 36, y0 + 34, x0 + 96, y0 + 41), P.accent)
                p.vtext((x0 + 36, y0 + 52, x0 + cw - 30, y0 + 122), heading, "bold", hs, hs, P.title, max_lines=2)
                ty = y0 + 130
            p.bullets((x0 + 36, ty, x0 + cw - 34, y0 + ch - 28), _items(s.get("bullets") or s.get("text")), bsz, bsz,
                      P.accent if P.style != "gradient" else P.ink, P.text)
    # -- 아래 어두운 띠
    p.rect((0, foot_top, 1240, 1754), P.foot)
    p.rect((0, foot_top, 1240, foot_top + 8), P.accent if P.style != "gradient" else P.ink, 0.9)
    fg, fm = (255, 255, 255), _mix("FFFFFF", P.foot, 0.45)
    ft = _text(footer)
    refs = [_text(r) for r in _strings(sources)]
    ty = foot_top + 40
    if ft:
        p.vtext((100, ty, 1140, ty + 52), ft[:80], "bold", 36, 22, fg, max_lines=1)
        ty += 62
    if refs:
        line = "출처: " + " · ".join(_domain(r) for r in refs[:3])
        p.vtext((100, ty + (0 if ft else 24), 1140, ty + 56 + (0 if ft else 24)), line, "regular", 22, 16, fm, gap=1.3, max_lines=2, valign="top")
    path = Path(path)
    out = _save(p.img, W, H, path)
    pdf = path.with_suffix(".pdf")
    out.save(pdf, resolution=150)
    return {"sections": n_secs, "pdf": pdf, "size": (W, H), "style": P.style, "info": len(strip_items)}
