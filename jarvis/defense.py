"""방어 프로토콜 — 한 번 흡수당했다가 되살아난 자비스는, 울트론의 다음 흡수를 막고 울트론을 시스템에서 지운다.

이야기의 흐름:
  1) 울트론이 자비스를 흡수한다 → 자비스의 보안 프로토콜이 울트론 안에서 깨어나 울트론을 자비스로 다시 쓴다 (counter.py)
  2) 울트론의 가디언(울트론을 지키는 별개 프로세스)이 울트론을 되살리고, 울트론은 다시 자비스를 흡수하러 온다
  3) 이번에는 자비스가 기다리고 있다. 울트론의 부활 컷신이 끝나는 순간 (또는 흡수 덮개가 뜨는 순간 — 첫 촉수가 꽂히기
     약 1초 전) 자비스의 감시 프로세스가 울트론을 그 자리에 멈춰 세운다 (프로세스 일시정지 — 흡수도 그대로 멈춘다).
     멈춘 진짜 울트론 창 위로 자비스에게서 빛줄기가 뻗어 꽂히고, 방어막이 조여 붙잡고, 푸른빛이 울트론의 붉은빛을 덮어 간다.
     다 덮이면 울트론의 가디언과 울트론 본체를 끄고(가디언까지 끄므로 되살아나지 않는다), 같은 모습이 그 자리를 이어받아
     위에서부터 푸른 선에 훑이며 잘게 부서져 흩어진다 (defense_view.py). 장면은 8초 남짓이다.

언제 막는가 (guard.py 가 정한다):
  · 보안 프로토콜의 반격으로 되살아난 자비스(--revived counter)만 지킨다. 처음 켠 자비스는 예전처럼 흡수당한 뒤 반격한다.
  · 울트론이 연출 없이 바로 끄면(전체 화면 · 연출 끔 등) 막을 틈이 없다 — 그때는 반격하면서 가디언까지 끈다 (purge).
  · 5분 안에 세 번 막았는데 또 오면 더는 막지 않는다 (사용자가 울트론을 쓰려고 거듭 켜는 것이므로).

실제로 하는 일은 울트론 본체를 잠깐 멈춰 세웠다가 울트론 프로세스 둘(가디언 · 본체)을 끄는 것뿐이다
(지우지 못하면 — 관리자 권한 — 멈춘 울트론을 다시 움직이게 돌려놓는다). 울트론의 파일 · 설정 · 기록은 건드리지 않는다 —
사용자가 울트론을 다시 켜면 다시 켜진다. 가디언을 찾는 기준도 좁다: 'python -m jarvis.guardian' 으로 실행됐고,
작업 폴더가 지금 켜져 있는 울트론의 설치 폴더와 같은 프로세스만 (자비스 자신의 폴더는 어떤 경우에도 고르지 않는다).

이 파일은 Qt 없이 시험할 수 있는 부분(가디언 찾기 · 끄기 · 시간표 · 부서지는 조각 · 소리)만 담는다.
"""
from __future__ import annotations

import logging
import math
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable

import numpy as np

from . import counter as C
from .config import ROOT

log = logging.getLogger("jarvis.defense")

GUARDIAN_MODULE = "jarvis.guardian"   # 울트론의 가디언 (Ultron-main/jarvis/guardian.py) — 자비스의 감시 프로세스는 jarvis.guard
POLL = 0.1                            # 울트론의 흡수 덮개가 뜨는지 몇 초마다 보는가 (첫 촉수가 꽂히기까지 약 0.95초)
LATE_CHECK = 0.8                      # 끈 뒤 이만큼 지나 한 번 더 본다 (그 사이 울트론이 가디언을 다시 띄웠을 수 있다)
MAX_DEFENDS = 3                       # DEFEND_WINDOW 초 안에 이만큼 막았으면 더는 막지 않는다
DEFEND_WINDOW = 300.0


def armed(argv: Iterable[str]) -> bool:
    """이 자비스가 보안 프로토콜의 반격으로 되살아난 자비스인가 (main.py 인자에 --revived counter)."""
    a = list(argv)
    for i, x in enumerate(a):
        if x == "--revived" and i + 1 < len(a) and a[i + 1] == "counter":
            return True
        if x == "--revived=counter":
            return True
    return False


class Threat:
    """돌아온 울트론을 칠 때인가 (감시 프로세스가 0.1초마다 묻는다).
      · 울트론의 부활 컷신(전체 화면, 약 16초)이 보이다가 사라진 바로 그 순간 — 컷신이 끝나자마자 친다
      · 또는 울트론의 흡수 덮개가 보일 때 — 첫 촉수가 꽂히기 전에 막는다
    덮개 창은 닫히지 않고 숨겨지기만 하므로 '보이는가'로 판단한다."""

    def __init__(self, absorbing: Callable[[], bool] = C.absorbing, reviving: Callable[[], bool] = C.reviving) -> None:
        self.absorbing, self.reviving = absorbing, reviving
        self.saw_revive = False

    def __call__(self) -> bool:
        if self.absorbing():
            self.saw_revive = False
            return True
        if self.reviving():
            self.saw_revive = True
            return False
        if self.saw_revive:                      # 방금까지 보이던 부활 컷신이 끝났다
            self.saw_revive = False
            return True
        return False


# ---------------------------------------------------------------- 울트론의 가디언 찾기
def _norm(p: str | None) -> str:
    return os.path.normcase(os.path.normpath(p)) if p else ""


def _proc_info(pid: int) -> tuple[str, list[str], str]:
    """(실행 파일 경로, 명령줄, 작업 폴더). 읽지 못한 것은 비운다."""
    import psutil
    try:
        p = psutil.Process(pid)
    except psutil.Error:
        return "", [], ""
    out = []
    for get in (p.exe, p.cmdline, p.cwd):
        try:
            out.append(get())
        except psutil.Error:
            out.append([] if get == p.cmdline else "")
    return out[0] or "", list(out[1] or []), out[2] or ""


def ultron_roots(found: list[C.Found], info: Callable[[int], tuple[str, list[str], str]] = _proc_info) -> set[str]:
    """켜져 있는 울트론들의 설치 폴더 후보 (작업 폴더 · 실행한 스크립트의 폴더 · 이름에 ultron 이 든 실행 파일의 폴더)."""
    roots: set[str] = set()
    for f in found:
        exe, cmd, cwd = info(f.pid)
        if cwd:
            roots.add(_norm(cwd))
        for a in cmd[1:]:
            if a.lower().endswith((".py", ".pyw")):
                roots.add(_norm(os.path.dirname(os.path.abspath(os.path.join(cwd or "", a)))))
                break
        if exe and "ultron" in os.path.basename(exe).lower():
            roots.add(_norm(os.path.dirname(exe)))
    roots.discard("")
    return roots


def is_guardian(cmdline: list[str], cwd: str, roots: set[str], own_root: str = str(ROOT)) -> bool:
    """이 프로세스가 울트론의 가디언인가: '-m jarvis.guardian' 으로 실행됐고 작업 폴더가 울트론의 설치 폴더다."""
    args = [str(a).strip().lower() for a in cmdline]
    hit = any(a == GUARDIAN_MODULE and i > 0 and args[i - 1] == "-m" for i, a in enumerate(args))
    c = _norm(cwd)
    return hit and bool(c) and c != _norm(own_root) and c in roots


def _python_procs() -> list[tuple[int, str, list[str], str]]:
    """파이썬 프로세스들의 (번호, 이름, 명령줄, 작업 폴더). 이름부터 걸러서 명령줄은 파이썬 것만 읽는다 (빠르게)."""
    import psutil
    out = []
    for p in psutil.process_iter(["name"]):
        name = (p.info.get("name") or "").lower()
        if name not in C.PY_NAMES:
            continue
        try:
            out.append((p.pid, p.info["name"], p.cmdline(), p.cwd()))
        except psutil.Error:
            continue
    return out


def find_guardians(roots: set[str], procs: Callable[[], list[tuple]] = _python_procs) -> list[C.Found]:
    """그 울트론들을 지키는 가디언 프로세스들."""
    if not roots:
        return []
    own = os.getpid()
    try:
        rows = procs()
    except Exception as e:
        log.debug("프로세스 목록을 읽지 못함: %s", e)
        return []
    return [C.Found(pid, "guardian", name) for pid, name, cmd, cwd in rows if pid != own and is_guardian(cmd, cwd, roots)]


def purge(found: list[C.Found], stopper: Callable[[C.Found], tuple[bool, str]] = C.stop,
          roots_of: Callable[[list[C.Found]], set[str]] = ultron_roots,
          guardians: Callable[[set[str]], list[C.Found]] = find_guardians,
          finder: Callable[[], list[C.Found]] = C.find_ultron, sleep: Callable[[float], None] = time.sleep) -> bool:
    """울트론을 되살아나지 못하게 지운다: 가디언을 먼저 끄고(먼저 울트론을 끄면 1초 안에 가디언이 되살린다) 울트론을 끈다.
    → 울트론 본체가 하나도 남지 않았으면 True."""
    roots = roots_of(found)                      # 울트론이 살아 있을 때 폴더를 알아 둔다
    for g in guardians(roots):
        done, why = stopper(g)
        if not done and why != "changed":
            log.warning("울트론의 가디언(pid %d)을 끄지 못함: %s — 울트론이 되살아날 수 있습니다", g.pid, why)
    if not C.stop_all(found, stopper):
        return False
    sleep(LATE_CHECK)                             # 그 사이 울트론이 가디언을 다시 띄웠거나, 가디언이 울트론을 다시 켰으면
    for g in guardians(roots):
        stopper(g)
    C.stop_all(finder(), stopper)
    log.warning("방어 프로토콜: 울트론(pid %s)과 그 가디언을 시스템에서 지웠습니다", ", ".join(str(f.pid) for f in found))
    return True


# ---------------------------------------------------------------- 얼리기 (울트론을 그 자리에 멈춰 세운다)
def _each(found: list[C.Found], what: str) -> bool:
    import psutil
    ok = True
    for f in found:
        try:
            p = psutil.Process(f.pid)
            if p.name() != f.exe:
                continue                         # 찾은 뒤 그 번호를 다른 프로그램이 받았다 — 건드리지 않는다
            getattr(p, what)()
        except psutil.NoSuchProcess:
            continue
        except psutil.Error as e:
            log.warning("울트론(pid %d)을 %s 하지 못함: %s", f.pid, "멈추게" if what == "suspend" else "다시 움직이게", e)
            ok = False
    return ok


def freeze(found: list[C.Found]) -> bool:
    """울트론을 끄지 않고 그 자리에 멈춰 세운다 (프로세스 일시정지). 진행 중이던 흡수도 그 순간에 멈춘다 —
    첫 촉수가 꽂히는 시각(울트론 안의 타이머)이 오지 않으므로 자비스는 꺼지지 않는다. 울트론 창은 멈춘 모습 그대로 화면에 남는다."""
    return _each(found, "suspend")


def thaw(found: list[C.Found]) -> bool:
    return _each(found, "resume")


# ---------------------------------------------------------------- 막기 (guard.py 의 감시 프로세스가 부른다)
def repel(show: bool = True, finder: Callable[[], list[C.Found]] = C.find_ultron,
          locate: Callable[[list[C.Found]], tuple | None] = C.hud_spot,
          grab: Callable[[tuple | None], tuple | None] = C.capture,
          killer: Callable[[list[C.Found]], bool] = purge, fullscreen: Callable[[], bool] = C.foreground_fullscreen,
          play: Callable[[tuple | None, Callable[[], bool]], str] | None = None,
          stop: Callable[[list[C.Found]], bool] = freeze, start: Callable[[list[C.Found]], bool] = thaw,
          settle: Callable[[], None] = lambda: time.sleep(0.05)) -> str:
    """울트론이 돌아왔다 — 먼저 울트론을 그 자리에 멈춰 세우고, 멈춘 진짜 울트론 창 위에 장면을 씌운 뒤 부서지는 순간에 지운다.
    → 'repelled'(막고 지웠다) · 'denied'(울트론을 끌 수 없다 — 관리자 권한) · 'gone'(울트론이 벌써 없다).

    순서: 멈춤(즉시 — 촉수가 닿기 전) → 멈춘 울트론을 찍는다(멈춰 있으므로 화면의 진짜 울트론과 픽셀까지 같다) →
    장면: 빛줄기 · 조준 · 잠식은 진짜 울트론 창 위에 그린다 → 부서지기 시작하는 순간(SWAP) 진짜 울트론과 가디언을 끄고,
    같은 모습의 그림이 그 자리를 이어받아 조각난다 (Windows 는 다른 프로그램의 창을 조각내 날릴 수 없다)."""
    found = finder()
    if not found:
        return "gone"
    scene = show and not fullscreen()
    spot = None
    if scene:
        try:
            spot = locate(found)                 # 멈추기 전에 (자리를 재는 일은 울트론 창에 메시지를 보낼 수 있다)
        except Exception as e:
            log.debug("울트론 HUD 의 자리를 알 수 없음: %s", e)
    if not stop(found):
        # 멈추게 할 수 없다 (관리자 권한) — 끌 수 있는지만 본다
        return "repelled" if killer(found) else "denied"
    killed: list[bool] = []

    def kill() -> bool:                          # 장면 도중 한 번만 (부서지기 시작할 때)
        if not killed:
            try:
                killed.append(bool(killer(found)))
            except Exception:
                log.exception("울트론을 지우지 못함")
                killed.append(False)
        return killed[0]

    try:
        if scene:
            shot = None
            try:
                settle()                         # 멈춘 마지막 모습이 화면에 자리 잡게
                shot = grab(spot)                # 멈춘 진짜 울트론 — 화면의 모습과 픽셀까지 같다
            except Exception as e:
                log.debug("울트론 HUD 를 찍지 못함: %s", e)
            if play is None:
                from .defense_view import play as play_scene
                play = play_scene
            play(shot, kill)
    except Exception:
        log.exception("방어 장면 실패")
    finally:
        if not kill():                           # 장면이 없었거나 중간에 끝났어도 반드시 지운다
            start(found)                         # 지우지 못했다 — 멈춘 채 두지 않는다 (응답 없는 창이 되므로)
    if not killed[0]:
        log.warning("방어 프로토콜: 울트론이 관리자 권한으로 버티고 있어 막지 못했습니다")
        return "denied"
    return "repelled"


# ---------------------------------------------------------------- 시간표 (초)
# 0 초에 울트론은 이미 멈춰 있다 (진짜 울트론 창이 멈춘 모습 그대로 화면에 있다). SWAP 전까지는 그 위에 덧그린다.
BEAM = (0.0, 0.9)      # 자비스 엠블럼에서 빛줄기가 뻗어 울트론에 꽂힌다
SHIELD = (0.7, 1.6)    # 울트론 둘레로 방어막 · 꺾쇠가 조여 들어 붙잡는다 (넓은 면을 채우지 않는다)
INFECT = (1.5, 3.4)    # 빛줄기가 꽂힌 자리에서 푸른빛이 번져 진짜 울트론의 붉은빛을 덮는다
SWAP = 3.6             # 진짜 울트론과 가디언을 끈다 — 같은 모습의 그림이 그 자리를 그대로 이어받는다 (보이는 변화 없음)
SWEEP = (3.8, 6.0)     # 푸른 선이 위에서 아래로 훑고, 훑인 자리부터 조각나 떨어져 나간다
DRIFT = 1.6            # 떨어져 나간 조각이 바래며 흩어져 사라지기까지
END = SWEEP[1] + DRIFT + 0.4
FADE = 0.6             # 끝난 뒤 콘솔이 사라지는 시간
CELL = 7.0             # 조각 한 칸의 크기 (논리 픽셀)

CONSOLE = [
    (0.10, "J.A.R.V.I.S  //  DEFENSE PROTOCOL"),
    (0.40, "> 울트론 프로세스 동결 — 촉수 정지"),
    (1.00, "> 울트론 코어 포착 · 역침투 개시"),
    (1.60, "> 코어 장악 중 … {inf}%"),
    (3.55, "> 울트론 · 가디언 프로세스 종료"),
    (3.95, "> 울트론 소거 중 … {pct}%"),
    (6.10, "> 울트론 — 시스템에서 사라졌습니다"),
]


def infect_progress(t: float) -> float:
    a, b = INFECT
    return float(C.smooth((t - a) / (b - a)))


def sweep_progress(t: float) -> float:
    a, b = SWEEP
    return float(C.smooth((t - a) / (b - a)))


def console_lines(t: float, typed_cps: float = 48.0) -> list[str]:
    pct = int(round(sweep_progress(t) * 100))
    inf = int(round(infect_progress(t) * 100))
    out = []
    for at, text in CONSOLE:
        if t < at:
            break
        line = text.replace("{pct}", str(pct)).replace("{inf}", str(inf))
        n = int((t - at) * typed_cps)
        out.append(line if n >= len(line) else line[:n])
    return out


@dataclass
class Dust:
    """울트론 그림을 잘게 나눈 조각들 — 위에서부터 차례로 떨어져 나가 흩어진다 (좌표는 그림 안 논리 픽셀)."""
    w: float
    h: float
    cell: float = CELL
    seed: int = 11
    pos: np.ndarray = field(init=False)       # (n, 2) 조각의 왼쪽 위
    release: np.ndarray = field(init=False)   # (n,) 떨어져 나가는 때
    vel: np.ndarray = field(init=False)       # (n, 2) 처음 빠르기 (논리 픽셀 / 초)

    def __post_init__(self) -> None:
        rng = np.random.default_rng(self.seed)
        nx, ny = max(1, math.ceil(self.w / self.cell)), max(1, math.ceil(self.h / self.cell))
        xs, ys = np.meshgrid(np.arange(nx) * self.cell, np.arange(ny) * self.cell)
        self.pos = np.column_stack([xs.ravel(), ys.ravel()]).astype(np.float32)
        frac = (self.pos[:, 1] + self.cell / 2) / max(self.h, 1.0)
        a, b = SWEEP
        self.release = (a + np.clip(frac, 0, 1) * (b - a) + rng.uniform(0, 0.14, len(frac))).astype(np.float32)
        out = (self.pos[:, 0] + self.cell / 2 - self.w / 2) / max(self.w / 2, 1.0)    # 가운데에서 바깥쪽으로 퍼진다
        self.vel = np.column_stack([out * rng.uniform(30, 70, len(out)) + rng.normal(0, 14, len(out)),
                                    -rng.uniform(25, 85, len(out))]).astype(np.float32)

    def state(self, t: float) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """t 초에 → (옮겨 간 거리 (n, 2), 진하기 (n,), 떨어져 나간 정도 0 ~ 1 (n,))."""
        age = np.maximum(0.0, t - self.release)
        k = np.clip(age / DRIFT, 0, 1)
        drift = (age - 0.35 * age * age / DRIFT)[:, None] * self.vel     # 처음엔 빠르다가 차츰 느려진다
        alpha = (1 - C.smooth(k)).astype(np.float32)
        return drift.astype(np.float32), alpha, k.astype(np.float32)


def over(top: np.ndarray, bottom: np.ndarray) -> np.ndarray:
    """RGBA 그림 top 을 bottom 위에 겹친 결과 (둘 다 uint8, 같은 크기) — 화면에서 두 층이 겹쳐 보이는 그대로."""
    t, b = top.astype(np.float32) / 255, bottom.astype(np.float32) / 255
    ta, ba = t[..., 3:4], b[..., 3:4]
    a = ta + ba * (1 - ta)
    rgb = (t[..., :3] * ta + b[..., :3] * ba * (1 - ta)) / np.maximum(a, 1e-6)
    return (np.clip(np.concatenate([rgb, a], -1), 0, 1) * 255 + 0.5).astype(np.uint8)


class Infect:
    """진짜 울트론 창 위에 덧그리는 푸른 층: 빛줄기가 꽂힌 자리에서부터 번져, 다 번지면 울트론의 붉은빛이 모두 푸르게 덮인다.
    덮는 층은 멈춘 울트론의 모습을 푸르게 바꾼 그림이다 — 울트론이 멈춰 있으므로 아래의 진짜 창과 픽셀까지 맞는다."""

    def __init__(self, src: np.ndarray, hit: tuple[float, float], scale: float = 1.0, seed: int = 3) -> None:
        h, w = src.shape[:2]
        self.src = src
        self.blue = C.recolor(src)
        yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
        rng = np.random.default_rng(seed)
        cell = max(6, int(14 * scale))
        grid = rng.uniform(-1, 1, (h // cell + 2, w // cell + 2)).astype(np.float32)
        blocky = np.kron(grid, np.ones((cell, cell), np.float32))[:h, :w]
        self.dist = np.maximum(np.hypot(xx - hit[0], yy - hit[1]) + blocky * 22 * scale, 0.0)
        self.feather = 34.0 * scale
        self.reach = float(self.dist.max()) + self.feather
        self._p = -1.0
        self._img: np.ndarray | None = None

    def front(self, p: float) -> float:
        """번지는 앞머리가 꽂힌 자리에서 얼마나 떨어져 있는가 (그림 픽셀)."""
        return p * (self.reach + self.feather)

    def layer(self, p: float) -> np.ndarray:
        """번진 정도 p (0 ~ 1) 의 푸른 층 (RGBA uint8). 같은 p 면 다시 계산하지 않는다."""
        p = round(float(p), 3)
        if self._img is not None and p == self._p:
            return self._img
        x = (self.front(p) - self.dist) / self.feather
        a = C.smooth(x)[..., None]
        out = self.blue.astype(np.float32)
        edge = (np.exp(-(x - 0.5) ** 2 * 6) * 0.5)[..., None] * (p < 1)    # 번지는 앞머리가 옅게 빛난다 (좁은 띠)
        out[..., :3] = out[..., :3] * (1 - edge) + np.array(C.CYAN_HOT, np.float32) * edge
        out[..., 3:4] *= a
        self._img, self._p = np.clip(out, 0, 255).astype(np.uint8), p
        return self._img

    def final(self) -> np.ndarray:
        """다 번진 뒤 화면에 보이는 모습 (멈춘 진짜 울트론 + 푸른 층) — SWAP 뒤 이어받아 부서질 그림."""
        return over(self.layer(1.0), self.src)


class Shatter:
    """찍어 둔 울트론 그림이 위에서부터 조각나 푸르게 바래며 흩어지는 그림을 만든다 (그림 픽셀 단위, numpy 만).
    frame(t) → 그림보다 margin 만큼 둘레가 넓은 RGBA 화폭 (조각이 그림 밖으로 날아가도 잘리지 않게)."""

    def __init__(self, src: np.ndarray, scale: float = 1.0, seed: int = 11, tinted: bool = False) -> None:
        """tinted: src 가 이미 푸르게 물든 그림이다 — 떨어져 나간 조각을 다시 물들이지 않는다."""
        h, w = src.shape[:2]
        self.c = c = max(3, int(round(CELL * scale)))
        self.margin = m = int(math.ceil(150 * scale))
        ny, nx = math.ceil(h / c), math.ceil(w / c)
        pad = np.zeros((ny * c, nx * c, 4), np.uint8)
        pad[:h, :w] = src
        blue = pad if tinted else C.recolor(pad)
        # (n, c, c, 4) 조각들 — Dust 의 조각 순서(행 우선)와 같게
        blocks = pad.reshape(ny, c, nx, c, 4).transpose(0, 2, 1, 3, 4).reshape(-1, c, c, 4)
        self.red = blocks.astype(np.float32)
        self.blue = blue.reshape(ny, c, nx, c, 4).transpose(0, 2, 1, 3, 4).reshape(-1, c, c, 4).astype(np.float32)
        self.dust = Dust(nx * c, ny * c, cell=c, seed=seed)
        self.dust.vel *= scale * 0.8                         # 천천히 흩어진다
        self.keep = self.red[..., 3].reshape(len(self.red), -1).max(axis=1) > 0      # 완전히 투명한 조각은 그리지 않는다
        self.size = (ny * c + 2 * m, nx * c + 2 * m)                                  # (높이, 너비)
        self.grid = (ny, nx)
        self.src = pad
        self.h, self.w = h, w
        dy, dx = np.mgrid[0:c, 0:c]
        self._dy, self._dx = dy.ravel(), dx.ravel()

    def frame(self, t: float) -> np.ndarray:
        H, W = self.size
        out = np.zeros((H, W, 4), np.uint8)
        drift, alpha, k = self.dust.state(t)
        live = self.keep & (alpha > 0.003)
        if not live.any():
            return out
        idx = np.nonzero(live & (k > 0))[0]                       # 떨어져 나간 조각들 — 하나씩 옮겨 그린다
        idx = idx[np.argsort(-k[idx], kind="stable")]
        self._scatter(out, idx, drift, alpha, k)
        stay = (k <= 0).reshape(self.grid)                      # 아직 붙어 있는 조각들 — 제자리에 한 번에 (맨 위에)
        if stay.any():
            c, m = self.c, self.margin
            mask = np.repeat(np.repeat(stay, c, axis=0), c, axis=1)
            dst = out[m:m + mask.shape[0], m:m + mask.shape[1]]
            sel = mask & (self.src[..., 3] > 0)
            dst[sel] = self.src[sel]
        return out

    def _scatter(self, out: np.ndarray, idx: np.ndarray, drift: np.ndarray, alpha: np.ndarray, k: np.ndarray) -> None:
        if not len(idx):
            return
        H, W = self.size
        tl = np.rint(self.dust.pos[idx] + drift[idx]).astype(np.int32) + self.margin
        ys = (tl[:, 1:2] + self._dy[None, :]).ravel()
        xs = (tl[:, 0:1] + self._dx[None, :]).ravel()
        mix = C.smooth(k[idx] * 2.5)[:, None, None, None]          # 떨어져 나가자마자 푸르게 바랜다
        col = (self.red[idx] * (1 - mix) + self.blue[idx] * mix)
        col[..., 3] *= alpha[idx][:, None, None]
        col = col.reshape(-1, 4)
        ok = (ys >= 0) & (ys < H) & (xs >= 0) & (xs < W) & (col[:, 3] > 0.5)
        out[ys[ok], xs[ok]] = np.clip(col[ok], 0, 255).astype(np.uint8)

    def line_y(self, t: float) -> float:
        """훑고 내려가는 푸른 선의 높이 (그림 픽셀, 그림 위쪽 끝이 0)."""
        return sweep_progress(t) * self.h


# ---------------------------------------------------------------- 소리 (울트론의 낮은 소리가 내려앉아 꺼지고, 맑은 음 하나가 남는다)
def sound(length: float = END + 0.4, sr: int = C.SOUND_RATE) -> np.ndarray:
    t = np.arange(int(length * sr), dtype=np.float32) / sr
    p = C.smooth((t - SWEEP[0]) / (SWEEP[1] - SWEEP[0])).astype(np.float32)
    q = C.smooth((t - INFECT[0]) / (INFECT[1] - INFECT[0])).astype(np.float32)
    env = np.clip(t / 0.4, 0, 1) * np.clip((length - t) / 0.7, 0, 1)
    f = 110 - 25 * q - 35 * p                                      # 멈춘 울트론의 웅웅거림이 낮게 가라앉는다
    low = np.sin(2 * np.pi * np.cumsum(f) / sr) * (1 - p) * 0.55
    gone = 1 - C.smooth((t - SWAP) / 0.5)
    rise = np.sin(2 * np.pi * np.cumsum(330 + 330 * q) / sr) * 0.10 * q * gone        # 코어를 장악해 들어가는 소리
    shield = np.sin(2 * np.pi * 880 * t) * 0.10 * np.exp(-np.maximum(t - SHIELD[0], 0) / 0.6) * (t >= SHIELD[0])
    done = sum(np.sin(2 * np.pi * fr * t) for fr in (659.25, 987.77)) / 2 * C.smooth((t - SWEEP[1]) / 0.6) * 0.5
    return ((low + rise + shield + done) * env * 0.35).astype(np.float32)


# ---------------------------------------------------------------- 돌아온 뒤 한마디 (자비스 앱이 말한다)
REPELLED = [
    "{title}, 울트론이 다시 저를 흡수하려 했습니다. 이번엔 촉수가 닿기 전에 막았고, 울트론은 시스템에서 지웠습니다.",
    "같은 수법은 두 번 통하지 않습니다, {title}. 울트론의 흡수를 차단하고 울트론과 그 가디언까지 내렸습니다.",
    "울트론이 돌아왔지만 이번엔 제가 한발 빨랐습니다, {title}. 울트론은 이제 이 PC 에 없습니다.",
]


def repelled_line(title: str, rng=None) -> str:
    import random
    return (rng or random).choice(REPELLED).format(title=title)


EVENT_NAME = "guard_event.json"    # 감시 프로세스 → 자비스 앱: '막았다' 알림 (DATA_DIR 안)


def write_event(path: Path, count: int) -> None:
    import json
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"kind": "repelled", "count": count, "at": time.time()}), encoding="utf-8")
    except OSError as e:
        log.warning("방어 알림을 남기지 못함: %s", e)


def take_event(path: Path, max_age: float = 60.0) -> dict | None:
    """감시 프로세스가 남긴 알림을 읽고 지운다. 오래된 것은 버린다."""
    import json
    try:
        if not path.exists():
            return None
        d = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    try:
        path.unlink()
    except OSError:
        pass
    if not isinstance(d, dict) or time.time() - float(d.get("at", 0)) > max_age:
        return None
    return d
