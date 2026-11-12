"""디자인 결과물 — 카드뉴스 · 포스터를 화면 클릭 없이 바로 이미지로 만든다.

미리캔버스 같은 사이트를 화면을 보며 조작하면 느리고 실패할 수 있다. 자주 만드는 카드뉴스 · 포스터는 여기서 직접 그린다:
  · build_cardnews: 1080×1080 정사각형 카드 여러 장 (표지 · 내용 · 마무리) → 폴더에 01.png… + 한 묶음 PDF
  · build_poster: A4(또는 A3) 세로 포스터 → PNG + PDF (인쇄용)
발표 자료(office.py)와 같은 색 테마 5가지를 쓴다. 글은 상자에 맞게 크기를 줄이고 줄을 바꾼다 (한국어는 띄어쓰기 단위로).
도형은 두 배 크기로 그린 뒤 줄여 가장자리를 매끄럽게 한다. 이 파일은 그림만 만든다 (저장 폴더 · 열기는 tools.py).
"""
from __future__ import annotations

import os
import re
import shutil
import urllib.parse
from pathlib import Path

from .office import THEMES, Theme, _strings, _text

SS = 2                                  # 두 배로 그려서 줄인다 (도형 가장자리를 매끄럽게)
CARD = 1080
A4 = (1240, 1754)                       # 150dpi A4 세로
MAX_CARDS = 12

_WIN = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"
_FONTS = {
    "regular": [_WIN / "malgun.ttf", Path("/usr/share/fonts/truetype/nanum/NanumGothic.ttf"),
                Path("/usr/share/fonts/truetype/nanum/NanumSquareR.ttf"), Path("/usr/share/fonts/truetype/nanum/NanumBarunGothic.ttf")],
    "bold": [_WIN / "malgunbd.ttf", Path("/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf"),
             Path("/usr/share/fonts/truetype/nanum/NanumSquareB.ttf"), Path("/usr/share/fonts/truetype/nanum/NanumBarunGothicBold.ttf")],
}
_CACHE: dict = {}


def font_file(weight: str = "regular") -> Path:
    """한글 글꼴 파일 (Windows 는 맑은 고딕). 없으면 ValueError."""
    for p in _FONTS[weight]:
        if p.exists():
            return p
    raise ValueError("한글 글꼴(맑은 고딕)을 찾지 못했습니다.")


def _font(weight: str, size: float):
    from PIL import ImageFont
    key = (weight, int(size))
    if key not in _CACHE:
        _CACHE[key] = ImageFont.truetype(str(font_file(weight)), int(size))
    return _CACHE[key]


def _rgb(hex_: str) -> tuple[int, int, int]:
    return tuple(int(hex_[i:i + 2], 16) for i in (0, 2, 4))


def _mix(a: str, b: str, t: float) -> tuple[int, int, int]:
    ca, cb = _rgb(a), _rgb(b)
    return tuple(round(x + (y - x) * t) for x, y in zip(ca, cb))


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


def bullet_block(draw, box, items: list[str], theme: Theme, big: float, small: float, gap: float = 1.42) -> None:
    """글머리 기호 목록 (강조색 점 · 다음 줄은 들여쓰기 맞춤). 상자에 맞게 크기를 줄인다."""
    x0, y0, x1, y1 = box
    items = [re.sub(r"^\s*(?:[•·▪*]\s*|[-–]\s+)", "", s) for s in items if s.strip()]     # 글머리 기호는 점으로 그린다
    if not items:
        return
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
    for lines in blocks:
        if y + size * gap > y1 + 1:
            break
        r = size * 0.17
        cy = y + size * 0.62
        draw.ellipse((x0 + size * 0.2 - r, cy - r, x0 + size * 0.2 + r, cy + r), fill=_rgb(theme.accent))
        for line in lines:
            if y + size * gap > y1 + 1:
                break
            draw.text((x0 + indent, y), line, font=f, fill=_rgb(theme.text))
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


def _canvas(w: int, h: int, color):
    from PIL import Image, ImageDraw
    img = Image.new("RGB", (w * SS, h * SS), color)
    return img, ImageDraw.Draw(img)


def _save(img, w: int, h: int, path: Path) -> object:
    from PIL import Image
    out = img.resize((w, h), Image.LANCZOS)
    out.save(path)                      # (optimize 는 몇 배 느려 쓰지 않는다)
    return out


# ---------------------------------------------------------------- 카드뉴스
def _cover(th: Theme, title: str, tag: str, total: int):
    S = SS
    img, d = _canvas(CARD, CARD, _rgb(th.accent))
    d.ellipse((620 * S, 560 * S, 1400 * S, 1340 * S), fill=_mix(th.accent, th.on_accent, 0.14))
    d.ellipse((760 * S, -240 * S, 1240 * S, 240 * S), fill=_mix(th.accent, th.on_accent, 0.08))
    if tag:
        f = _font("bold", 30 * S)
        tw = d.textlength(tag, font=f)
        d.rounded_rectangle((90 * S, 110 * S, 90 * S + tw + 56 * S, 170 * S), radius=30 * S, outline=_rgb(th.on_accent), width=3 * S)
        d.text((118 * S, 122 * S), tag, font=f, fill=_rgb(th.on_accent))
    f, lines, size = fit(d, title, "bold", 880 * S, 470 * S, 118 * S, 62 * S, gap=1.18, max_lines=4)
    h = len(lines) * size * 1.18
    text_block(d, (90 * S, 300 * S + (470 * S - h) / 2), lines, f, size, _rgb(th.on_accent), gap=1.18)
    d.rectangle((90 * S, 880 * S, 170 * S, 888 * S), fill=_rgb(th.on_accent))
    small = _font("regular", 28 * S)
    d.text((90 * S, 910 * S), "옆으로 넘겨 보세요  →", font=small, fill=_mix(th.on_accent, th.accent, 0.25))
    page = f"1 / {total}"
    d.text((990 * S - d.textlength(page, font=small), 910 * S), page, font=small, fill=_mix(th.on_accent, th.accent, 0.25))
    return img


def _card(th: Theme, n: int, total: int, title: str, items: list[str], highlight: str, brand: str):
    S = SS
    img, d = _canvas(CARD, CARD, _rgb(th.bg))
    d.ellipse((880 * S, -160 * S, 1240 * S, 200 * S), fill=_rgb(th.surface))
    num = f"{n:02d}"
    d.text((90 * S, 70 * S), num, font=_font("bold", 96 * S), fill=_rgb(th.accent))
    d.rectangle((90 * S, 205 * S, 160 * S, 212 * S), fill=_rgb(th.accent))
    f, lines, size = fit(d, title, "bold", 900 * S, 190 * S, 70 * S, 44 * S, gap=1.2, max_lines=3)
    used = text_block(d, (90 * S, 240 * S), lines, f, size, _rgb(th.title), gap=1.2)
    top = 240 * S + used + 40 * S
    bottom = (775 if highlight else 930) * S
    bullet_block(d, (92 * S, top, 990 * S, bottom), items, th, 46 * S, 28 * S)
    if highlight:
        d.rounded_rectangle((90 * S, 800 * S, 990 * S, 950 * S), radius=24 * S, fill=_rgb(th.surface))
        d.rectangle((90 * S, 800 * S, 102 * S, 950 * S), fill=_rgb(th.accent))
        hf, hl, hs = fit(d, highlight, "bold", 820 * S, 120 * S, 40 * S, 26 * S, gap=1.25, max_lines=2)
        hh = len(hl) * hs * 1.25
        text_block(d, (130 * S, 800 * S + (150 * S - hh) / 2), hl, hf, hs, _rgb(th.title), gap=1.25)
    small = _font("regular", 26 * S)
    page = f"{n + 1} / {total}"
    d.text((990 * S - d.textlength(page, font=small), 985 * S), page, font=small, fill=_rgb(th.muted))
    if brand:
        d.text((90 * S, 985 * S), brand[:40], font=small, fill=_rgb(th.muted))
    return img


def _closing(th: Theme, message: str, lines: list[str], refs: list[str], total: int):
    S = SS
    img, d = _canvas(CARD, CARD, _rgb(th.surface))
    d.ellipse((-260 * S, 640 * S, 420 * S, 1320 * S), fill=_rgb(th.soft))
    f, ml, size = fit(d, message or "감사합니다", "bold", 900 * S, 330 * S, 96 * S, 52 * S, gap=1.2, max_lines=3)
    h = len(ml) * size * 1.2
    y = 270 * S + (330 * S - h) / 2
    text_block(d, (90 * S, y), ml, f, size, _rgb(th.title), gap=1.2, align="center", width=900 * S)
    if lines:
        sf, sl, ss = fit(d, " ".join(lines), "regular", 860 * S, 150 * S, 38 * S, 26 * S, gap=1.35, max_lines=3)
        text_block(d, (110 * S, y + h + 40 * S), sl, sf, ss, _rgb(th.text), gap=1.35, align="center", width=860 * S)
    if refs:
        rf = _font("regular", 21 * S)
        d.text((90 * S, 850 * S), "출처", font=_font("bold", 22 * S), fill=_rgb(th.muted))
        for i, r in enumerate(refs[:3]):
            d.text((90 * S, (885 + i * 30) * S), _domain(r)[:60], font=rf, fill=_rgb(th.muted))
    small = _font("regular", 26 * S)
    page = f"{total} / {total}"
    d.text((990 * S - d.textlength(page, font=small), 985 * S), page, font=small, fill=_rgb(th.muted))
    return img


def build_cardnews(folder: Path, title: str, cards: list, subtitle: str = "", closing: str = "",
                   sources=None, theme: str = "light") -> dict:
    """카드뉴스를 만든다 → {'cards': 장 수, 'pdf': PDF 경로, 'files': 그림 경로들}."""
    title = _text(title)
    if not title:
        raise ValueError("카드뉴스 제목(title)이 필요합니다.")
    if not isinstance(cards, list) or not cards:
        raise ValueError("내용 카드(cards)가 하나 이상 필요합니다.")
    if len(cards) > MAX_CARDS:
        raise ValueError(f"카드가 너무 많습니다 ({len(cards)}장). 내용 카드는 {MAX_CARDS}장 이하로 만드세요.")
    th = THEMES.get((theme or "light").strip().lower(), THEMES["light"])
    folder = Path(folder)
    if folder.exists():
        shutil.rmtree(folder)                    # 고쳐 만들 때 (overwrite) 예전 장이 남지 않게
    folder.mkdir(parents=True)
    refs = [_text(r) for r in _strings(sources)]
    total = len(cards) + 2
    imgs = [_cover(th, title, _text(subtitle), total)]
    for i, c in enumerate(cards, 1):
        c = c if isinstance(c, dict) else {"title": str(c)}
        imgs.append(_card(th, i, total, _text(c.get("title")) or f"{i}", _strings(c.get("bullets") or c.get("text")),
                          _text(c.get("highlight")), _text(subtitle) or title))
    end = closing if isinstance(closing, str) else ""
    first, *rest = (end.splitlines() or ["감사합니다"]) if end.strip() else ["감사합니다"]
    imgs.append(_closing(th, _text(first), [_text(x) for x in rest if x.strip()], refs, total))
    files, saved = [], []
    for i, img in enumerate(imgs, 1):
        p = folder / f"{i:02d}.png"
        saved.append(_save(img, CARD, CARD, p))
        files.append(p)
    pdf = folder / f"{folder.name}.pdf"
    saved[0].save(pdf, save_all=True, append_images=saved[1:], resolution=150)
    return {"cards": len(files), "pdf": pdf, "files": files}


# ---------------------------------------------------------------- 포스터
def build_poster(path: Path, title: str, sections: list, subtitle: str = "", highlight: str = "", footer: str = "",
                 sources=None, theme: str = "light", size: str = "a4") -> dict:
    """포스터를 만든다 (PNG + 같은 이름의 PDF) → {'sections': 구역 수, 'pdf': PDF 경로, 'size': (가로, 세로)}."""
    title = _text(title)
    if not title:
        raise ValueError("포스터 제목(title)이 필요합니다.")
    secs = [s if isinstance(s, dict) else {"heading": "", "bullets": [str(s)]} for s in (sections or [])]
    if not secs and not _text(highlight):
        raise ValueError("포스터에 넣을 내용(sections)이 필요합니다.")
    if len(secs) > 6:
        raise ValueError("포스터 구역(sections)은 6개 이하로 만드세요.")
    th = THEMES.get((theme or "light").strip().lower(), THEMES["light"])
    k = 1.4142 if str(size).lower() == "a3" else 1.0
    W, H = round(A4[0] * k), round(A4[1] * k)
    S = SS * k                                   # 기준(A4) 좌표 → 실제 그리는 좌표
    img, d = _canvas(W, H, _rgb(th.bg))
    head = 620
    d.rectangle((0, 0, W * SS, head * S), fill=_rgb(th.accent))
    d.ellipse((860 * S, -240 * S, 1480 * S, 380 * S), fill=_mix(th.accent, th.on_accent, 0.12))
    d.ellipse((1010 * S, 300 * S, 1360 * S, 650 * S), fill=_mix(th.accent, th.on_accent, 0.07))
    f, lines, sz = fit(d, title, "bold", 1040 * S, 330 * S, 128 * S, 64 * S, gap=1.15, max_lines=3)
    block = len(lines) * sz * 1.15
    if _text(subtitle):
        sf, sl, ss = fit(d, _text(subtitle), "regular", 1040 * S, 120 * S, 42 * S, 28 * S, gap=1.3, max_lines=2)
        block += 26 * S + len(sl) * ss * 1.3
    room = ((head - (110 if _text(highlight) else 40)) - 90) * S         # 제목이 짧아도 머리 띠 가운데에 오게
    top = 90 * S + max(0.0, (room - block) / 2)
    used = text_block(d, (100 * S, top), lines, f, sz, _rgb(th.on_accent), gap=1.15)
    if _text(subtitle):
        text_block(d, (100 * S, top + used + 26 * S), sl, sf, ss, _mix(th.on_accent, th.accent, 0.15), gap=1.3)
    y = head * S + 50 * S
    if _text(highlight):
        hb = (100 * S, head * S - 70 * S, 1140 * S, head * S + 110 * S)
        d.rounded_rectangle((hb[0] + 8 * S, hb[1] + 10 * S, hb[2] + 8 * S, hb[3] + 10 * S), radius=28 * S,
                            fill=_mix(th.bg, th.title, 0.10))
        d.rounded_rectangle(hb, radius=28 * S, fill=_rgb(th.bg), outline=_rgb(th.accent), width=4 * int(S))
        hf, hl, hs = fit(d, _text(highlight), "bold", 960 * S, 140 * S, 52 * S, 30 * S, gap=1.25, max_lines=2)
        hh = len(hl) * hs * 1.25
        text_block(d, (140 * S, hb[1] + (hb[3] - hb[1] - hh) / 2), hl, hf, hs, _rgb(th.accent), gap=1.25,
                   align="center", width=960 * S)
        y = hb[3] + 50 * S
    foot_top = (H / k - 150) * S
    cols = 1 if len(secs) <= 2 else 2
    rows = max(1, -(-len(secs) // cols))
    gap = 34 * S
    cw = (1040 * S - gap * (cols - 1)) / cols
    ch = (foot_top - y - gap * (rows - 1)) / rows if secs else 0
    for i, sec in enumerate(secs):
        r, c = divmod(i, cols)
        x0, y0 = 100 * S + c * (cw + gap), y + r * (ch + gap)
        d.rounded_rectangle((x0, y0, x0 + cw, y0 + ch), radius=26 * S, fill=_rgb(th.surface))
        d.rectangle((x0 + 34 * S, y0 + 34 * S, x0 + 94 * S, y0 + 41 * S), fill=_rgb(th.accent))
        top = y0 + 60 * S
        heading = _text(sec.get("heading"))
        if heading:
            hf, hl, hs = fit(d, heading, "bold", cw - 68 * S, 120 * S, 46 * S, 30 * S, gap=1.2, max_lines=2)
            top += text_block(d, (x0 + 34 * S, top), hl, hf, hs, _rgb(th.title), gap=1.2) + 18 * S
        bullet_block(d, (x0 + 36 * S, top, x0 + cw - 34 * S, y0 + ch - 30 * S),
                     _strings(sec.get("bullets") or sec.get("text")), th, 36 * S, 22 * S)
    d.rectangle((100 * S, foot_top + 30 * S, 1140 * S, foot_top + 33 * S), fill=_rgb(th.soft))
    small = _font("regular", 24 * S)
    if _text(footer):
        d.text((100 * S, foot_top + 55 * S), _text(footer)[:60], font=_font("bold", 26 * S), fill=_rgb(th.text))
    refs = [_text(r) for r in _strings(sources)]
    if refs:
        line = "출처: " + " · ".join(_domain(r) for r in refs[:3])
        rf, rl, rs = fit(d, line, "regular", 1040 * S, 60 * S, 22 * S, 18 * S, gap=1.3, max_lines=2)
        text_block(d, (100 * S, foot_top + 95 * S), rl, rf, rs, _rgb(th.muted), gap=1.3)
    del small
    path = Path(path)
    out = _save(img, W, H, path)
    pdf = path.with_suffix(".pdf")
    out.save(pdf, resolution=150)
    return {"sections": len(secs), "pdf": pdf, "size": (W, H)}
