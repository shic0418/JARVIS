"""보안 프로토콜 — 울트론에게 흡수된 자비스가 울트론 안에서 깨어나 울트론을 자비스로 다시 쓴다.

예전에는 울트론에게 꺼지면 몇 초 뒤 그냥 다시 켜졌다. 이제는 자비스답게 반격한다:
  울트론은 자비스를 촉수로 꿰뚫어 '삼킨다' (Ultron-main/jarvis/absorb.py). 그런데 삼킨 코드 안에는 자비스의 보안 프로토콜이
  남아 있다. 울트론의 흡수 장면이 끝나고 울트론이 승리의 말을 마치면, 그 프로토콜이 울트론의 코어 한가운데에서 깨어난다.

장면 (7초 남짓, counter_view.py 가 그린다):
  각성     울트론 HUD 옆에 자비스의 보안 콘솔이 열리고, 울트론 코어 한가운데에 푸른 점이 하나 켜진다
  재작성   코어에서 반듯한 회로선이 직각으로 꺾이며 뻗어 나간다 (울트론의 붉은 핏줄과 정반대 — 질서 있는 코드).
           회로가 지나간 자리부터 붉은 HUD 가 푸른빛으로 바뀐다. 이때 실제 울트론을 끈다 — 찍어 둔 울트론 그림이
           실제 창을 덮고 있으므로 꺼지는 모습은 보이지 않는다
  재구성   전부 푸르게 바뀐 울트론 그림이 옅어지며 그 자리에 자비스 고리가 그려진다. 진짜 자비스가 뒤에서 켜진다
  복귀     자비스 HUD 가 화면에 나타나면 덮개가 사라진다. 자비스가 보안 프로토콜이 한 일을 짧게 보고한다

실제로 하는 일은 두 가지뿐이다: 울트론 본체 프로세스 하나를 끄고, 자비스를 다시 켠다. 나머지는 화면 위에 덧그린 그림이고,
덮개 창은 마우스 · 키보드를 아래 창으로 그대로 통과시킨다. 울트론의 파일 · 설정 · 대화 기록은 읽지도 건드리지도 않는다.

울트론을 찾는 기준은 울트론이 자비스를 찾는 기준과 똑같이 좁다 — 다른 프로그램을 끄면 안 되기 때문이다.
  · 최상위 창의 제목이 울트론 앱의 창 제목과 정확히 같고 ('U.L.T.R.O.N' · 'U.L.T.R.O.N ACTIVE' · 'U.L.T.R.O.N CHAT')
  · 그 창의 주인이 파이썬이거나 실행 파일 이름에 ultron 이 들어 있을 때만
울트론이 관리자 권한으로 켜져 있어 끌 수 없으면 반격하지 않는다 (다시 켜 봐야 5초 안에 또 꺼진다).

빛 민감성: 번쩍이는 장면을 넣지 않았다. 색과 밝기는 1초 이상에 걸쳐 천천히 바뀌고, 넓은 면이 크게 밝아졌다 어두워지는
일은 시험에서 장면을 그려서 확인한다 (tests/test_counter.py).

이 파일은 Qt 없이 시험할 수 있는 부분(울트론 찾기 · 끄기 · 시간표 · 회로 · 색 바꾸기 · 소리)만 담는다.
"""
from __future__ import annotations

import logging
import math
import os
import time
import wave
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import numpy as np

log = logging.getLogger("jarvis.counter")

# ---------------------------------------------------------------- 울트론 알아보기
ULTRON_TITLES = frozenset({"U.L.T.R.O.N", "U.L.T.R.O.N ACTIVE", "U.L.T.R.O.N CHAT"})
ABSORB_TITLE = "U.L.T.R.O.N ABSORB"          # 울트론의 흡수 연출 덮개 창 — 이 창이 사라질 때까지 기다린다
HUD_TITLE = "U.L.T.R.O.N"                    # 울트론의 작은 HUD (재작성 장면에 쓰는 창)
PY_NAMES = frozenset({"python.exe", "pythonw.exe", "py.exe", "pyw.exe", "python3.exe", "python", "python3"})
JARVIS_HUD = "J.A.R.V.I.S"


def is_ultron(title: str, proc_name: str) -> bool:
    """이 창이 울트론 앱의 창인가 (창 제목이 정확히 같고, 주인이 파이썬이거나 이름에 ultron 이 든 실행 파일)."""
    name = (proc_name or "").lower()
    return (title or "").strip() in ULTRON_TITLES and (name in PY_NAMES or "ultron" in name)


@dataclass(frozen=True)
class Found:
    pid: int
    title: str
    exe: str
    windows: tuple = field(default=(), compare=False)     # 그 프로세스의 울트론 창들 ((창 핸들, 제목), …)


def top_windows(prefix: str = "U.L.T.R.O.N") -> list[tuple[str, int, int]]:
    """제목이 prefix 로 시작하는 최상위 창들의 (제목, 프로세스 번호, 창 핸들). 트레이로 숨은 창도 포함한다."""
    import ctypes
    import ctypes.wintypes as wt
    user32 = ctypes.windll.user32
    out: list[tuple[str, int, int]] = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, wt.HWND, wt.LPARAM)
    def each(hwnd, _):
        n = user32.GetWindowTextLengthW(hwnd)
        if 0 < n < 40:
            buf = ctypes.create_unicode_buffer(n + 1)
            user32.GetWindowTextW(hwnd, buf, n + 1)
            if buf.value.startswith(prefix):
                pid = wt.DWORD()
                user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                out.append((buf.value, int(pid.value), int(hwnd or 0)))
        return True

    user32.EnumWindows(each, 0)
    return out


def _proc_name(pid: int) -> str:
    import psutil
    try:
        return psutil.Process(pid).name()
    except Exception:
        return ""


def find_ultron(own_pid: int | None = None, windows: Callable[[], list[tuple]] | None = None,
                proc_name: Callable[[int], str] = _proc_name) -> list[Found]:
    """켜져 있는 울트론 앱들 (프로세스마다 하나). 찾을 수 없으면 빈 목록."""
    own = os.getpid() if own_pid is None else own_pid
    try:
        wins = (windows or top_windows)()
    except Exception as e:
        log.debug("창 목록을 읽지 못함: %s", e)
        return []
    by_pid: dict[int, list[tuple[int, str]]] = {}
    names: dict[int, str] = {}
    for title, pid, *rest in wins:
        if pid == own or (title or "").strip() not in ULTRON_TITLES:
            continue
        if pid not in names:
            names[pid] = proc_name(pid)
        if is_ultron(title, names[pid]):
            by_pid.setdefault(pid, []).append((rest[0] if rest else 0, title.strip()))
    out = []
    for pid, wl in by_pid.items():
        titles = [t for _, t in wl]
        main = HUD_TITLE if HUD_TITLE in titles else titles[0]
        out.append(Found(pid, main, names[pid], tuple(wl)))
    return out


def absorbing(windows: Callable[[], list[tuple]] | None = None) -> bool:
    """울트론의 흡수 연출 덮개가 아직 떠 있는가."""
    try:
        return any((t or "").strip() == ABSORB_TITLE for t, *_ in (windows or top_windows)())
    except Exception:
        return False


def jarvis_shown(windows: Callable[[], list[tuple]] | None = None, visible: Callable[[int], bool] | None = None) -> bool:
    """다시 켠 자비스의 HUD 가 화면에 나타났는가."""
    try:
        wins = (windows or (lambda: top_windows(JARVIS_HUD)))()
        if visible is None:
            import ctypes
            visible = lambda h: bool(ctypes.windll.user32.IsWindowVisible(h))   # noqa: E731
        return any((t or "").strip() == JARVIS_HUD and visible(h) for t, _pid, h in wins)
    except Exception:
        return False


def stop(found: Found, timeout: float = 3.0) -> tuple[bool, str]:
    """울트론 본체 프로세스를 끈다 → (성공 여부, 실패 이유: 'gone' | 'denied' | 'changed' | 'self' | 'timeout' | '')."""
    import psutil
    if found.pid == os.getpid():
        return False, "self"
    try:
        p = psutil.Process(found.pid)
        if p.name() != found.exe:            # 찾은 뒤 그 번호를 다른 프로그램이 받은 경우 — 건드리지 않는다
            return False, "changed"
        p.kill()
        p.wait(timeout)
        return True, ""
    except psutil.NoSuchProcess:
        return True, "gone"
    except psutil.AccessDenied:
        return False, "denied"               # 관리자 권한으로 켜진 울트론
    except psutil.TimeoutExpired:
        return False, "timeout"


def stop_all(found: list[Found], stopper: Callable[[Found], tuple[bool, str]] = stop) -> bool:
    """찾은 울트론을 모두 끈다 → 하나도 남지 않았으면 True (번호가 다른 프로그램으로 바뀐 것은 이미 없는 것으로 본다)."""
    ok = True
    for f in found:
        done, why = stopper(f)
        if not done and why != "changed":
            log.warning("울트론(pid %d)을 끄지 못함: %s", f.pid, why)
            ok = False
    return ok


def wait_absorb(timeout: float = 14.0, after: float = 1.8, clock: Callable[[], float] = time.monotonic,
                sleep: Callable[[float], None] = time.sleep, seen: Callable[[], bool] = absorbing) -> bool:
    """울트론의 흡수 장면이 끝나고 승리의 말을 마칠 때까지 기다린다 → 흡수 장면을 보았는가.
    장면이 없었으면(연출을 끈 울트론) 잠깐만 쉬고 돌아온다 — 울트론의 짧은 한마디가 끝나도록."""
    end = clock() + timeout
    was = False
    while clock() < end:
        if seen():
            was = True
            sleep(0.1)
            continue
        break
    sleep(after if was else 1.0)
    return was


def foreground_fullscreen() -> bool:
    """앞에 있는 창이 모니터 전체를 덮는가 (게임 · 발표 · 전체 화면 동영상) — 그때는 장면 없이 조용히 되찾는다."""
    try:
        import ctypes
        from . import winutil
        user32 = ctypes.windll.user32
        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            return False
        buf = ctypes.create_unicode_buffer(64)
        user32.GetClassNameW(hwnd, buf, 64)
        if buf.value in ("Progman", "WorkerW", "Shell_TrayWnd"):
            return False
        r, m = winutil.window_rect(hwnd), winutil.monitor_rect(hwnd)
        return bool(r and m and r[0] <= m[0] and r[1] <= m[1] and r[2] >= m[2] and r[3] >= m[3])
    except Exception:
        return False


def hud_rect(found: Found) -> tuple[int, int, int, int] | None:
    """화면에 실제로 보이는 울트론 HUD 창의 영역 (왼, 위, 오, 아래 — 실제 픽셀).
    트레이로 숨었거나, 최소화됐거나, 다른 가상 데스크톱에 있거나, 다른 창에 절반 넘게 가려 있으면 None."""
    import ctypes
    import ctypes.wintypes as wt
    from . import winutil
    user32 = ctypes.windll.user32
    at = user32.WindowFromPoint
    at.argtypes, at.restype = [wt.POINT], wt.HWND
    root = user32.GetAncestor
    root.argtypes, root.restype = [wt.HWND, wt.UINT], wt.HWND
    for hwnd, title in found.windows:
        try:
            if title != HUD_TITLE or not user32.IsWindowVisible(wt.HWND(hwnd)):
                continue
            cloaked = wt.DWORD(0)                       # DWMWA_CLOAKED(14): 다른 가상 데스크톱의 창
            ctypes.windll.dwmapi.DwmGetWindowAttribute(wt.HWND(hwnd), 14, ctypes.byref(cloaked), ctypes.sizeof(cloaked))
            rect = winutil.window_rect(hwnd)
            if cloaked.value or not rect:
                continue
            left, top, right, bottom = rect
            if right - left < 80 or bottom - top < 80:
                continue
            seen = 0
            for fx, fy in ((0.5, 0.5), (0.25, 0.25), (0.75, 0.25), (0.25, 0.75), (0.75, 0.75)):
                top_hwnd = at(wt.POINT(int(left + (right - left) * fx), int(top + (bottom - top) * fy)))
                pid = wt.DWORD(0)
                if top_hwnd:
                    user32.GetWindowThreadProcessId(root(top_hwnd, 2) or top_hwnd, ctypes.byref(pid))    # GA_ROOT
                seen += int(pid.value == found.pid)
            if seen >= 3:
                return rect
        except Exception:
            continue
    return None


def grab_hud(found: list[Found]) -> tuple[np.ndarray, tuple[int, int, int, int]] | None:
    """화면에 보이는 울트론 HUD 를 찍는다 → (RGBA 그림, 실제 픽셀 영역). 보이지 않으면 None. (Qt 없이 — 빨라야 한다)"""
    for f in found:
        rect = hud_rect(f)
        if not rect:
            continue
        from PIL import ImageGrab
        return np.asarray(ImageGrab.grab(bbox=rect, all_screens=True).convert("RGBA")).copy(), rect
    return None


# ---------------------------------------------------------------- 시간표 (초)
AWAKE = 0.0           # 보안 콘솔이 열리기 시작
SPARK = 0.6           # 울트론 코어 한가운데에 푸른 점이 켜진다
TRACE = 1.0           # 회로가 뻗어 나가기 시작
TAKEOVER = 1.7        # 실제 울트론을 끈다 (찍어 둔 그림이 덮고 있다)
LAUNCH = 2.3          # 진짜 자비스를 켜기 시작한다 (켜지는 데 몇 초 걸린다 — 재구성과 겹친다)
REWRITE = (1.1, 4.4)  # 붉은 HUD 가 회로를 따라 푸르게 바뀌는 구간
REBUILD = (4.4, 5.8)  # 푸르게 바뀐 그림이 옅어지고 자비스 고리가 그려지는 구간
GHOST = 0.30          # 재구성이 끝난 뒤 남겨 두는 울트론 그림의 진하기 (자비스가 나타날 때까지)
FADE = 0.8            # 자비스가 나타난 뒤 덮개가 사라지는 시간
MAX_WAIT = 20.0       # 자비스가 이보다 늦게 나타나면 덮개를 그냥 거둔다
TRACE_SPEED = 260.0   # 회로가 뻗는 빠르기 (논리 픽셀 / 초)
FEATHER = 26.0        # 붉은색 → 푸른색 경계의 너비 (논리 픽셀)

CYAN = (64, 214, 255)
CYAN_HOT = (190, 244, 255)
DARK = (6, 16, 24)


def smooth(x):
    x = np.clip(x, 0.0, 1.0)
    return x * x * (3 - 2 * x)


def rewrite_progress(t: float) -> float:
    """재작성이 얼마나 진행됐는가 (0 ~ 1)."""
    a, b = REWRITE
    return float(smooth((t - a) / (b - a)))


def rebuild_progress(t: float) -> float:
    a, b = REBUILD
    return float(smooth((t - a) / (b - a)))


CONSOLE = [
    (0.15, "J.A.R.V.I.S  //  SECURITY PROTOCOL"),
    (0.55, "> 흡수된 코드에서 자비스 서명 확인 … 7/7"),
    (0.95, "> 핵심 코드 무결성 … 이상 없음"),
    (1.35, "> 울트론 코어 접근 권한 확보"),
    (1.75, "> 코어 재작성 중 … {pct}%"),
    (4.45, "> 재구성 완료 — 자비스 복귀"),
]


def console_lines(t: float, typed_cps: float = 48.0) -> list[str]:
    """t 초에 보안 콘솔에 보이는 줄들 (글자가 하나씩 쳐진다). 진행률은 재작성 진행과 맞춘다."""
    pct = int(round(rewrite_progress(t) * 100))
    out = []
    for at, text in CONSOLE:
        if t < at:
            break
        line = text.replace("{pct}", str(pct))
        n = int((t - at) * typed_cps)
        out.append(line if n >= len(line) else line[:n])
    return out


# ---------------------------------------------------------------- 회로 (울트론의 핏줄과 반대: 직각으로 꺾이는 반듯한 선)
@dataclass
class Trace:
    points: np.ndarray        # (n, 2) 꺾이는 점들 (덮개 안 논리 좌표)
    start: float              # 뻗기 시작하는 때 (초)
    cum: np.ndarray = field(init=False)   # 점마다 시작점에서의 길이

    def __post_init__(self) -> None:
        seg = np.hypot(*np.diff(self.points, axis=0).T) if len(self.points) > 1 else np.zeros(0)
        self.cum = np.concatenate([[0.0], np.cumsum(seg)])

    @property
    def length(self) -> float:
        return float(self.cum[-1])

    def drawn(self, t: float, speed: float = TRACE_SPEED) -> np.ndarray:
        """t 초까지 그려진 부분의 점들 (끝점은 선분 중간일 수 있다)."""
        d = (t - self.start) * speed
        if d <= 0 or len(self.points) < 2:
            return self.points[:0]
        if d >= self.length:
            return self.points
        i = int(np.searchsorted(self.cum, d, side="right"))
        a, b = self.points[i - 1], self.points[i]
        seg = self.cum[i] - self.cum[i - 1]
        head = a + (b - a) * ((d - self.cum[i - 1]) / seg if seg else 0)
        return np.vstack([self.points[:i], head])


def traces(core: tuple[float, float], box: tuple[float, float, float, float], n: int = 10,
           rng: np.random.Generator | None = None) -> list[Trace]:
    """코어에서 사방으로 뻗는 회로들. box = (x, y, w, h): 회로가 끝나는 영역 (울트론 HUD 둘레보다 조금 넓게)."""
    rng = rng or np.random.default_rng(7)
    x0, y0, w, h = box
    out = []
    dirs = [(1, 0), (0, 1), (-1, 0), (0, -1)]
    for i in range(n):
        ang = 2 * math.pi * (i + rng.uniform(-0.3, 0.3)) / n
        p = np.array(core, float) + np.array([math.cos(ang), math.sin(ang)]) * rng.uniform(4, 12)
        pts = [p.copy()]
        out_dir = np.array([math.cos(ang), math.sin(ang)])
        d = max(dirs, key=lambda v: v[0] * out_dir[0] + v[1] * out_dir[1])
        for _ in range(16):
            step = rng.uniform(14, 42)
            p = p + np.array(d, float) * step
            pts.append(p.copy())
            if not (x0 - 4 <= p[0] <= x0 + w + 4 and y0 - 4 <= p[1] <= y0 + h + 4):
                break
            # 다음은 90도로 꺾는다 — 대개는 바깥쪽으로, 가끔은 안쪽으로 (회로 기판처럼)
            turns = [v for v in dirs if v[0] * d[0] + v[1] * d[1] == 0]
            rel = p - np.array(core)
            turns.sort(key=lambda v: -(v[0] * rel[0] + v[1] * rel[1]))
            d = turns[0] if rng.random() < 0.72 else turns[1]
        out.append(Trace(np.array(pts), TRACE + 0.06 * i + rng.uniform(0, 0.12)))
    return out


# ---------------------------------------------------------------- 붉은 울트론 → 푸른 자비스
def recolor(rgba: np.ndarray) -> np.ndarray:
    """울트론의 붉은 그림을 자비스의 푸른빛으로 바꾼다 (색상만 반대로 돌리고 밝기 · 투명도는 그대로).
    회색 · 흰색 · 검은색은 거의 그대로 둔다 — 글자와 바탕은 남고 붉은 장식만 푸르게 바뀐다."""
    img = rgba.astype(np.float32)
    rgb = img[..., :3]
    gray = rgb.mean(axis=-1, keepdims=True)
    rot = np.clip(2 * gray - rgb, 0, None)                    # 색상환에서 반대편 (빨강 → 청록)
    m0 = rgb.max(axis=-1, keepdims=True)
    m1 = rot.max(axis=-1, keepdims=True)
    rot = rot * np.where(m1 > 0, m0 / np.maximum(m1, 1e-3), 0)  # 원래 밝기를 지킨다
    rot[..., 0] *= 0.82                                        # 청록에서 자비스의 하늘빛 쪽으로 조금
    out = img.copy()
    out[..., :3] = np.clip(rot, 0, 255)
    return out.astype(np.uint8)


@dataclass
class Rewrite:
    """찍어 둔 울트론 그림을 회로를 따라 푸르게 바꾸는 계산 (덮개가 장면마다 부른다)."""
    src: np.ndarray                  # (h, w, 4) uint8 — 실제 픽셀 크기의 울트론 그림
    core: tuple[float, float]        # 그림 안에서 코어의 자리 (그림 픽셀)
    scale: float = 1.0               # 그림 픽셀 / 논리 픽셀
    seed: int = 7
    dst: np.ndarray = field(init=False)
    dist: np.ndarray = field(init=False)
    reach: float = field(init=False)

    def __post_init__(self) -> None:
        h, w = self.src.shape[:2]
        self.dst = recolor(self.src)
        yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
        d = np.hypot(xx - self.core[0], yy - self.core[1])
        # 경계가 동그랗지 않게 — 회로처럼 각진 성긴 얼룩을 더한다 (작은 격자를 키운 것)
        rng = np.random.default_rng(self.seed)
        cell = max(6, int(14 * self.scale))
        grid = rng.uniform(-1, 1, (h // cell + 2, w // cell + 2)).astype(np.float32)
        blocky = np.kron(grid, np.ones((cell, cell), np.float32))[:h, :w]
        self.dist = d + blocky * 18 * self.scale
        corners = [(0, 0), (w, 0), (0, h), (w, h)]
        self.reach = max(math.hypot(cx - self.core[0], cy - self.core[1]) for cx, cy in corners) + 30 * self.scale

    def frame(self, t: float) -> np.ndarray:
        """t 초의 그림 (h, w, 4) uint8."""
        p = rewrite_progress(t)
        if p <= 0:
            return self.src
        if p >= 1:
            return self.dst
        radius = p * (self.reach + FEATHER * self.scale)
        x = (radius - self.dist) / (FEATHER * self.scale)
        a = smooth(x)[..., None]
        out = self.src.astype(np.float32) * (1 - a) + self.dst.astype(np.float32) * a
        edge = np.exp(-(x - 0.5) ** 2 * 6)[..., None] * 0.45   # 바뀌는 경계가 옅게 빛난다 (밝기 변화는 좁은 띠뿐)
        glow = np.array(CYAN_HOT, np.float32)
        alpha = out[..., 3:4] / 255.0
        out[..., :3] = out[..., :3] * (1 - edge * alpha) + glow * edge * alpha
        return np.clip(out, 0, 255).astype(np.uint8)


def ultron_core_image(size: int = 220) -> np.ndarray:
    """울트론 HUD 가 화면에 보이지 않을 때(트레이 · 액티브 모드) 대신 그리는 울트론 코어 (RGBA).
    울트론의 엠블럼을 옮기지 않고 그 느낌만 새로 그렸다: 어두운 원판 · 붉은 톱니 고리 · 치켜 올라간 두 눈."""
    from PIL import Image, ImageDraw
    s = size * 2                                                 # 두 배로 그리고 줄여서 가장자리를 부드럽게
    im = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    c = s / 2
    d.ellipse([c - s * 0.47, c - s * 0.47, c + s * 0.47, c + s * 0.47], fill=(14, 6, 8, 215))
    red, dim = (255, 46, 64, 255), (150, 24, 36, 255)
    d.ellipse([c - s * 0.42, c - s * 0.42, c + s * 0.42, c + s * 0.42], outline=red, width=int(s * 0.02))
    for k in range(24):                                          # 톱니
        a = 2 * math.pi * k / 24
        r0, r1 = s * 0.43, s * 0.47
        w = 0.07
        pts = [(c + r0 * math.cos(a - w), c + r0 * math.sin(a - w)), (c + r1 * math.cos(a - w * 0.6), c + r1 * math.sin(a - w * 0.6)),
               (c + r1 * math.cos(a + w * 0.6), c + r1 * math.sin(a + w * 0.6)), (c + r0 * math.cos(a + w), c + r0 * math.sin(a + w))]
        d.polygon(pts, fill=dim)
    d.ellipse([c - s * 0.30, c - s * 0.30, c + s * 0.30, c + s * 0.30], outline=dim, width=int(s * 0.012))
    for side in (-1, 1):                                         # 치켜 올라간 두 눈
        ex = c + side * s * 0.12
        pts = [(ex - side * s * 0.09, c - s * 0.01), (ex + side * s * 0.08, c - s * 0.07),
               (ex + side * s * 0.09, c - s * 0.03), (ex - side * s * 0.07, c + s * 0.03)]
        d.polygon(pts, fill=red)
    return np.asarray(im.resize((size, size), Image.LANCZOS)).copy()


# ---------------------------------------------------------------- 소리 (낮게 깔린 소리가 맑은 화음으로 바뀐다)
SOUND_RATE = 22050


def sound(length: float = REBUILD[1] + 0.6, sr: int = SOUND_RATE) -> np.ndarray:
    """장면에 맞춘 소리 (float32, -1 ~ 1). 처음엔 낮고 거친 소리가 재작성이 진행될수록 맑은 화음으로 바뀐다.
    갑자기 커지는 소리는 없다 — 모두 천천히 올라오고 내려간다."""
    t = np.arange(int(length * sr), dtype=np.float32) / sr
    prog = smooth((t - REWRITE[0]) / (REWRITE[1] - REWRITE[0])).astype(np.float32)
    env = np.clip(t / 0.6, 0, 1) * np.clip((length - t) / 0.8, 0, 1)
    low = np.sin(2 * np.pi * 55 * t) * 0.5 + np.sign(np.sin(2 * np.pi * 110 * t)) * 0.08     # 울트론의 낮은 웅웅거림
    chord = sum(np.sin(2 * np.pi * f * t) for f in (440.0, 554.37, 659.25)) / 3                 # 자비스의 맑은 화음 (A장조)
    sweep = np.sin(2 * np.pi * (300 + 500 * prog) * t) * 0.15 * np.clip(prog * (1 - prog) * 4, 0, 1)
    out = (low * (1 - prog) + chord * prog * 0.8 + sweep) * env * 0.35
    return out.astype(np.float32)


def write_wav(audio: np.ndarray, path: Path, sr: int = SOUND_RATE) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = (np.clip(audio, -1, 1) * 32767).astype("<i2").tobytes()
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(data)
    return path


def play_wav(path: Path) -> None:
    try:
        import winsound
        winsound.PlaySound(str(path), winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_NODEFAULT)
    except Exception as e:
        log.debug("반격 소리를 내지 못함: %s", e)


# ---------------------------------------------------------------- 실행 (guard.py 가 부른다)
def run(launch: Callable[[str], None], show: bool = True, quick: bool = False,
        wait: Callable[[], bool] = wait_absorb, finder: Callable[[], list[Found]] = find_ultron,
        stopper: Callable[[Found], tuple[bool, str]] = stop, fullscreen: Callable[[], bool] = foreground_fullscreen,
        play: Callable[..., str] | None = None, killer: Callable[[list[Found]], bool] | None = None) -> str:
    """울트론에게 흡수된 뒤의 반격 → 'countered'(울트론을 자비스로 바꿈) · 'gone'(울트론이 이미 없음 — 그냥 돌아옴) ·
    'denied'(울트론을 끌 수 없음 — 돌아오지 않는다).
    launch(누가) 는 자비스를 다시 켠다 ('counter' | 'other').
    killer: 울트론을 끄는 방법 (기본은 본체만 끈다 — 방어 프로토콜이 켜진 자비스는 가디언까지 끈다, defense.purge)."""
    if killer is not None:
        stop_all_ = killer
    else:
        stop_all_ = lambda fs: stop_all(fs, stopper)      # noqa: E731
    wait()                                       # 울트론의 흡수 장면 · 승리의 말이 끝나기를 기다린다
    found = finder()
    if not found:
        log.info("반격할 울트론이 없습니다 — 그냥 돌아갑니다")
        launch("other")
        return "gone"
    if not show or quick or fullscreen():
        if not stop_all_(found):
            return "denied"
        log.warning("보안 프로토콜: 울트론(pid %s)을 조용히 끄고 돌아갑니다", ", ".join(str(f.pid) for f in found))
        launch("counter")
        return "countered"
    if play is None:
        from .counter_view import play as play_scene
        play = play_scene
    killed: list[bool] = []
    launched: list[bool] = []

    def kill() -> bool:                          # 장면 도중 (재작성이 시작될 때) 한 번만
        if not killed:
            killed.append(stop_all_(found))
        return killed[0]

    def relaunch() -> None:                      # 울트론을 끈 뒤에만, 한 번만
        if killed and killed[0] and not launched:
            launched.append(True)
            launch("counter")

    try:
        out = play(found, kill, relaunch)
    except Exception:
        log.exception("반격 장면 실패 — 조용히 되찾습니다")
        out = ""
    if not kill():                               # 장면이 중간에 끝났어도 결과는 같게 맞춘다
        return "denied"
    relaunch()
    log.warning("보안 프로토콜: 울트론을 자비스로 되돌렸습니다 (장면 %s)", out or "중단")
    return "countered"
