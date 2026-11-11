"""화면을 Claude 에게 보여 줄 때 쓰는 계산 — 보낼 크기 · 좌표 변환 · 번호 상자 표시 · 화면 변화 감지.

왜 크기를 직접 맞추나
  Claude 는 이미지를 28×28 픽셀 조각으로 나눠 보고, 모델 등급마다 '긴 변'과 '조각 수' 한도가 있다.
      표준 등급 (Claude 4.6 이하)    긴 변 1568px · 조각 1568개
      고해상도 등급 (Claude 4.7 이상) 긴 변 2576px · 조각 4784개
  한도를 넘는 이미지는 서버가 한 번 더 줄이는데, 그러면 Claude 가 말하는 좌표는 '줄어든 이미지' 기준이 되어
  우리가 보낸 이미지와 어긋난다. 예전에는 긴 변만 1568 에 맞췄는데(1920×1080 → 1568×882), 표준 등급에서는
  조각 수 한도 때문에 1456×819 로 다시 줄어 클릭이 화면 가로로 7~8% 씩 빗나갔다.
  그래서 보내기 전에 '서버가 다시 줄이지 않을 가장 큰 크기'로 직접 맞춘다 (resized_size 는 공식 문서의 기준 구현).
  고해상도 등급에서는 1920×1080 화면을 줄이지 않고 그대로 보낼 수 있어 작은 글자까지 읽힌다.

PIL · numpy 만 쓰므로 Windows 가 아니어도 테스트할 수 있다.
"""
from __future__ import annotations

import base64
import io
import math
import re
import time
from dataclasses import dataclass
from typing import Callable

# (긴 변 한도, 조각 수 한도)
STANDARD = (1568, 1568)
HIGH = (2576, 4784)
# 고해상도 등급이라도 화면 캡처는 가로 1920 까지만 보낸다: 1080p 면 글자가 충분히 읽히고(공식 권장),
# 그보다 큰 이미지는 중간 전달 과정(Claude Code)에서 다시 줄어 좌표가 어긋날 수 있다. 1932 = 28 의 배수로 올린 1920.
SCREEN_EDGE_CAP = 1932
ZOOM_MIN_EDGE = 1280          # 확대해서 볼 때 긴 변이 이보다 작으면 키운다 (조각당 글자가 커져 작은 글씨가 읽힌다)
ZOOM_MAX_FACTOR = 3.0
JPEG_QUALITY = 85
MAX_IMAGE_BYTES = 1_200_000   # 인코딩한 이미지 크기 상한 (넘으면 화질을 낮춘다)
MAX_MARKS = 80                # 번호 상자는 이 개수까지만 그린다 (너무 많으면 화면을 가린다)


# ---------------------------------------------------------------------------- 보낼 크기
def count_image_tokens(width: int, height: int) -> int:
    """이미지가 쓰는 조각(시각 토큰) 수: 28×28 픽셀마다 하나."""
    return math.ceil(width / 28) * math.ceil(height / 28)


def resized_size(width: int, height: int, max_edge: int = 1568, max_tokens: int = 1568) -> tuple[int, int]:
    """Claude 가 이미지를 줄이는 크기 (여백 붙이기 전). 한도 안이면 그대로. — 공식 문서의 기준 구현."""

    def fits(w: int, h: int) -> bool:
        return (math.ceil(w / 28) * 28 <= max_edge and math.ceil(h / 28) * 28 <= max_edge
                and count_image_tokens(w, h) <= max_tokens)

    if fits(width, height):
        return (width, height)
    if height > width:
        rh, rw = resized_size(height, width, max_edge, max_tokens)
        return (rw, rh)
    aspect = width / height
    lo, hi = 1, width   # lo 는 항상 들어가고 hi 는 항상 안 들어간다
    while lo + 1 < hi:
        mid = (lo + hi) // 2
        if fits(mid, max(round(mid / aspect), 1)):
            lo = mid
        else:
            hi = mid
    return (lo, max(round(lo / aspect), 1))


_MODEL = re.compile(r"claude-(?:[a-z]+)-(\d{1,2})(?:-(\d{1,2}))?(?:-\d{8})?(?:\[.*\])?$")


def tier_for_model(model: str | None) -> str:
    """모델 이름 → 'high' | 'standard'. 버전을 알 수 없으면(별칭 'haiku' 등) 안전한 쪽인 표준 등급으로 본다.
    표준 등급 크기로 보낸 이미지는 어느 모델에서도 다시 줄어들지 않는다."""
    m = _MODEL.match((model or "").strip().lower())
    if not m:
        return "standard"
    major, minor = int(m.group(1)), int(m.group(2) or 0)
    return "high" if (major, minor) >= (4, 7) else "standard"


def limits(tier: str) -> tuple[int, int]:
    if tier == "high":
        return (min(HIGH[0], SCREEN_EDGE_CAP), HIGH[1])
    return STANDARD


def send_size(width: int, height: int, tier: str) -> tuple[int, int]:
    """이 등급의 모델에게 보낼 크기 (서버가 다시 줄이지 않는 가장 큰 크기, 키우지는 않음)."""
    edge, tokens = limits(tier)
    return resized_size(max(1, int(width)), max(1, int(height)), edge, tokens)


def zoom_size(width: int, height: int, tier: str) -> tuple[int, int]:
    """확대해서 볼 영역(실제 픽셀 width×height)을 보낼 크기. 작은 영역은 키워서 글자가 잘 보이게 한다."""
    w, h = max(1, int(width)), max(1, int(height))
    f = min(ZOOM_MAX_FACTOR, max(1.0, ZOOM_MIN_EDGE / max(w, h)))
    edge, tokens = limits(tier)
    return resized_size(max(1, round(w * f)), max(1, round(h * f)), edge, tokens)


# ---------------------------------------------------------------------------- 좌표
@dataclass(frozen=True)
class View:
    """Claude 가 마지막으로 본 이미지와 실제 화면의 대응.

    이미지의 (0,0) 은 화면의 (ox, oy) 이고, 이미지 1픽셀은 화면에서 가로 sx · 세로 sy 픽셀이다."""
    ox: float
    oy: float
    sx: float
    sy: float
    w: int            # 이미지 크기 (Claude 가 본 크기)
    h: int
    kind: str = "screen"   # screen | window | zoom

    def to_screen(self, x: float, y: float) -> tuple[int, int]:
        """이미지 좌표 → 화면 좌표. 이미지 밖으로 조금 벗어난 값은 가장자리로 당긴다."""
        x = min(max(float(x), 0.0), self.w - 1.0)
        y = min(max(float(y), 0.0), self.h - 1.0)
        return (round(self.ox + x * self.sx), round(self.oy + y * self.sy))

    def rect_to_screen(self, x: float, y: float, w: float, h: float) -> tuple[int, int, int, int]:
        """이미지 안의 영역 (x, y, w, h) → 화면의 (왼쪽, 위, 오른쪽, 아래)."""
        x0 = min(max(float(x), 0.0), float(self.w))
        y0 = min(max(float(y), 0.0), float(self.h))
        x1 = min(max(x0 + max(float(w), 1.0), 0.0), float(self.w))
        y1 = min(max(y0 + max(float(h), 1.0), 0.0), float(self.h))
        return (round(self.ox + x0 * self.sx), round(self.oy + y0 * self.sy),
                round(self.ox + x1 * self.sx), round(self.oy + y1 * self.sy))

    def from_screen(self, X: float, Y: float) -> tuple[float, float]:
        return ((X - self.ox) / self.sx, (Y - self.oy) / self.sy)

    def contains(self, x: float, y: float) -> bool:
        return -0.5 <= x <= self.w - 0.5 and -0.5 <= y <= self.h - 0.5


def make_view(bbox: tuple[int, int, int, int], size: tuple[int, int], kind: str = "screen") -> View:
    """화면의 bbox(왼, 위, 오, 아래)를 size(가로, 세로) 이미지로 보냈을 때의 대응."""
    left, top, right, bottom = bbox
    w, h = size
    return View(float(left), float(top), (right - left) / max(1, w), (bottom - top) / max(1, h), int(w), int(h), kind)


# ---------------------------------------------------------------------------- 인코딩
def encode(img) -> tuple[str, str]:
    """PIL 이미지 → (base64, media_type). 글자가 뭉개지지 않는 화질의 JPEG, 너무 크면 화질을 낮춘다."""
    img = img.convert("RGB")
    for q in (JPEG_QUALITY, 75, 62, 50):
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=q, optimize=True)
        if buf.tell() <= MAX_IMAGE_BYTES or q == 50:
            break
    return base64.standard_b64encode(buf.getvalue()).decode("ascii"), "image/jpeg"


# ---------------------------------------------------------------------------- 번호 상자
_COLORS = [(255, 59, 79), (40, 170, 255), (255, 176, 32), (64, 220, 120), (214, 110, 255), (255, 255, 255)]
_FONT_CACHE: dict[int, object] = {}


def _font(size: int):
    f = _FONT_CACHE.get(size)
    if f is None:
        from PIL import ImageFont
        for name in ("arialbd.ttf", "arial.ttf", "malgunbd.ttf", "DejaVuSans-Bold.ttf", "DejaVuSans.ttf"):
            try:
                f = ImageFont.truetype(name, size)
                break
            except OSError:
                continue
        else:
            try:
                f = ImageFont.load_default(size)
            except TypeError:   # 아주 오래된 Pillow
                f = ImageFont.load_default()
        _FONT_CACHE[size] = f
    return f


def pick_marks(items: list[tuple[int, tuple[int, int, int, int]]], view: View,
               max_marks: int = MAX_MARKS) -> list[tuple[int, tuple[int, int, int, int]]]:
    """화면 좌표의 요소 [(번호, (왼, 위, 오, 아래))] 중 이미지 안에 보이는 것만 이미지 좌표로 바꿔 돌려준다.
    거의 같은 자리의 상자는 하나만 남기고(겹쳐 그리면 번호를 읽을 수 없다), 너무 많으면 앞에서부터 max_marks 개."""
    out: list[tuple[int, tuple[int, int, int, int]]] = []
    seen: list[tuple[int, int, int, int]] = []
    for n, (left, top, right, bottom) in items:
        x0, y0 = view.from_screen(left, top)
        x1, y1 = view.from_screen(right, bottom)
        if x1 <= 2 or y1 <= 2 or x0 >= view.w - 2 or y0 >= view.h - 2:
            continue                                   # 이미지 밖
        box = (max(0, round(x0)), max(0, round(y0)), min(view.w - 1, round(x1)), min(view.h - 1, round(y1)))
        if box[2] - box[0] < 6 or box[3] - box[1] < 6:
            continue                                   # 너무 작아 번호를 붙일 수 없다
        if any(abs(box[0] - s[0]) < 6 and abs(box[1] - s[1]) < 6 and abs(box[2] - s[2]) < 6 and abs(box[3] - s[3]) < 6
               for s in seen):
            continue
        seen.append(box)
        out.append((n, box))
        if len(out) >= max_marks:
            break
    return out


def annotate(img, marks: list[tuple[int, tuple[int, int, int, int]]]):
    """이미지 좌표의 상자마다 테두리와 번호를 그린 새 이미지. 번호는 read_ui/click_ui 의 번호와 같다."""
    from PIL import ImageDraw
    out = img.convert("RGB").copy()
    d = ImageDraw.Draw(out)
    size = max(11, min(16, round(out.width / 120)))
    font = _font(size)
    for i, (n, (x0, y0, x1, y1)) in enumerate(marks):
        color = _COLORS[i % len(_COLORS)]
        d.rectangle((x0, y0, x1, y1), outline=color, width=2)
        label = str(n)
        try:
            tw = round(d.textlength(label, font=font))
        except Exception:
            tw = len(label) * size // 2
        lw, lh = tw + 6, size + 4
        # 번호표: 상자 위쪽 바깥에 자리가 있으면 거기, 없으면 상자 안 왼쪽 위
        lx = min(max(0, x0), out.width - lw)
        ly = y0 - lh if y0 - lh >= 0 else y0
        d.rectangle((lx, ly, lx + lw, ly + lh), fill=color)
        d.text((lx + 3, ly + 1), label, fill=(0, 0, 0), font=font)
    return out


# ---------------------------------------------------------------------------- 화면 변화
_SMALL = (480, 270)       # 비교용 크기: 1080p 화면의 4×4 픽셀이 한 칸 (탭 제목 · 체크 표시처럼 작은 변화도 몇 칸은 바뀐다)
_LEVEL = 12               # 한 칸의 밝기가 이만큼 넘게 달라지면 바뀐 칸
_MIN_CELLS = 3            # 바뀐 칸이 이보다 적으면 변화 없음 (잡티)
TINY_CELLS = 12           # 이보다 적으면 깜빡이는 글자 커서 정도의 변화


def small_gray(img):
    """비교용으로 작게 줄인 흑백 배열 (int16)."""
    import numpy as np
    from PIL import Image
    return np.asarray(img.convert("L").resize(_SMALL, Image.BOX), dtype=np.int16)


def _changed(a, b):
    import numpy as np
    return np.abs(a - b) > _LEVEL


def changed_fraction(a, b) -> float:
    """두 화면(small_gray 결과)에서 눈에 띄게 달라진 부분의 비율 0..1."""
    if a is None or b is None or a.shape != b.shape:
        return 1.0
    return float(_changed(a, b).mean())


def changed_where(a, b) -> str:
    """달라진 부분이 화면의 어디쯤인지 ('왼쪽 위', '가운데', '오른쪽 아래' …). 넓게 퍼져 있거나 알 수 없으면 빈 글."""
    import numpy as np
    if a is None or b is None or a.shape != b.shape:
        return ""
    ys, xs = np.nonzero(_changed(a, b))
    if len(xs) == 0:
        return ""
    h, w = a.shape
    if (xs.max() - xs.min()) > w * 0.6 or (ys.max() - ys.min()) > h * 0.6:
        return ""
    col = ("왼쪽", "", "오른쪽")[min(2, int(xs.mean() * 3 / w))]
    row = ("위", "", "아래")[min(2, int(ys.mean() * 3 / h))]
    return f"{col} {row}".strip() or "가운데"


@dataclass
class Change:
    fraction: float    # 동작 전과 비교해 달라진 비율
    settled: bool      # 화면이 멈췄는가 (False 면 동영상·로딩처럼 계속 바뀌는 중)
    seconds: float
    where: str = ""    # 달라진 곳 (좁은 범위일 때만)
    cells: int = _SMALL[0] * _SMALL[1]     # 비교한 칸 수

    def text(self) -> str:
        if not self.settled:
            return f"화면이 계속 바뀌는 중 (동영상이거나 아직 불러오는 중, {self.seconds:.1f}초 기다림)"
        n = self.fraction * self.cells
        at = f" — {self.where}" if self.where else ""
        if n < _MIN_CELLS:
            return "화면에 변화 없음 — 동작이 먹지 않았을 수 있음"
        if n < TINY_CELLS:
            return f"화면이 아주 조금만 바뀜{at} (깜빡이는 글자 커서일 수도 있음)"
        if self.fraction < 0.005:
            return f"화면의 작은 부분이 바뀜{at}"
        if self.fraction < 0.08:
            return f"화면 일부가 바뀜 (약 {max(1, round(self.fraction * 100))}%{at})"
        return f"화면이 크게 바뀜 (약 {round(self.fraction * 100)}%)"


def settle(grab: Callable[[], object], before, timeout: float = 2.5, interval: float = 0.15, quiet: int = 2,
           nochange_wait: float = 1.0,
           sleep: Callable[[float], None] = time.sleep, clock: Callable[[], float] = time.monotonic) -> Change:
    """동작 뒤 화면이 멈출 때까지 기다린다 (연속 quiet 번 같으면 멈춘 것, 최대 timeout 초).

    grab() 은 small_gray 형태의 현재 화면을 돌려준다. before 는 동작 전 화면.
    고정 시간 기다리기 대신 쓰면, 빨리 끝난 동작은 빨리 넘어가고 느린 페이지는 다 뜰 때까지 기다린다.
    아무 변화가 없을 때는 nochange_wait 초까지는 더 지켜본다 (반응이 늦게 시작되는 화면을 '변화 없음'으로 단정하지 않게)."""
    t0 = clock()
    prev = None
    same = 0
    cur = before
    while True:
        sleep(interval)
        cur = grab()
        if prev is not None and changed_fraction(prev, cur) < 0.003:
            same += 1
            if same >= quiet:
                frac = changed_fraction(before, cur)
                if frac * cur.size >= _MIN_CELLS or clock() - t0 >= nochange_wait:
                    return Change(frac, True, clock() - t0, changed_where(before, cur), cur.size)
        else:
            same = 0
        prev = cur
        if clock() - t0 >= timeout:
            return Change(changed_fraction(before, cur), False, clock() - t0, "", getattr(cur, "size", 1))
