"""방어 프로토콜 — 한 번 흡수당했다가 되살아난 자비스는, 울트론의 다음 흡수를 막고 울트론을 시스템에서 지운다.

이야기의 흐름:
  1) 울트론이 자비스를 흡수한다 → 자비스의 보안 프로토콜이 울트론 안에서 깨어나 울트론을 자비스로 다시 쓴다 (counter.py)
  2) 울트론의 가디언(울트론을 지키는 별개 프로세스)이 울트론을 되살리고, 울트론은 다시 자비스를 흡수하러 온다
  3) 이번에는 자비스가 기다리고 있다. 울트론의 흡수 덮개 창('U.L.T.R.O.N ABSORB')이 뜨는 순간 —
     첫 촉수가 꽂히기(울트론이 실제로 자비스를 끄기) 약 1초 전 — 자비스의 감시 프로세스가 그것을 알아채고
     울트론의 가디언과 울트론 본체를 차례로 끈다. 가디언까지 끄므로 울트론은 되살아나지 않는다.
     화면에는 울트론 HUD 가 위에서부터 푸른 선에 훑이며 잘게 부서져 흩어지는 장면이 그려진다 (defense_view.py).

언제 막는가 (guard.py 가 정한다):
  · 보안 프로토콜의 반격으로 되살아난 자비스(--revived counter)만 지킨다. 처음 켠 자비스는 예전처럼 흡수당한 뒤 반격한다.
  · 울트론이 연출 없이 바로 끄면(전체 화면 · 연출 끔 등) 막을 틈이 없다 — 그때는 반격하면서 가디언까지 끈다 (purge).
  · 5분 안에 세 번 막았는데 또 오면 더는 막지 않는다 (사용자가 울트론을 쓰려고 거듭 켜는 것이므로).

실제로 하는 일은 울트론 프로세스 둘(가디언 · 본체)을 끄는 것뿐이다. 울트론의 파일 · 설정 · 기록은 건드리지 않는다 —
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


# ---------------------------------------------------------------- 막기 (guard.py 의 감시 프로세스가 부른다)
def repel(show: bool = True, finder: Callable[[], list[C.Found]] = C.find_ultron,
          grab: Callable[[list[C.Found]], tuple | None] = C.grab_hud,
          killer: Callable[[list[C.Found]], bool] = purge, fullscreen: Callable[[], bool] = C.foreground_fullscreen,
          play: Callable[[tuple | None], str] | None = None) -> str:
    """울트론의 흡수가 시작됐다 — 촉수가 닿기 전에 울트론을 지운다.
    → 'repelled'(막고 지웠다) · 'denied'(울트론을 끌 수 없다 — 관리자 권한) · 'gone'(울트론이 벌써 없다).
    시간이 빠듯하므로(첫 촉수까지 약 1초) 울트론의 모습만 재빨리 찍어 두고 먼저 끈 다음에 장면을 보여 준다."""
    found = finder()
    if not found:
        return "gone"
    scene = show and not fullscreen()
    shot = None
    if scene:
        try:
            shot = grab(found)
        except Exception as e:
            log.debug("울트론 HUD 를 찍지 못함: %s", e)
    if not killer(found):
        log.warning("방어 프로토콜: 울트론이 관리자 권한으로 버티고 있어 막지 못했습니다")
        return "denied"
    if scene:
        try:
            if play is None:
                from .defense_view import play as play_scene
                play = play_scene
            play(shot)
        except Exception:
            log.exception("방어 장면 실패")
    return "repelled"


# ---------------------------------------------------------------- 시간표 (초)
SHIELD = (0.0, 0.5)    # 푸른 방어막이 울트론 둘레에 닫힌다 (촉수가 끊긴다)
SWEEP = (0.45, 2.1)    # 푸른 선이 위에서 아래로 훑고, 훑인 자리부터 조각나 떨어져 나간다
DRIFT = 1.25           # 떨어져 나간 조각이 푸르게 바래며 흩어져 사라지기까지
END = SWEEP[1] + DRIFT + 0.35
FADE = 0.6             # 끝난 뒤 콘솔이 사라지는 시간
CELL = 7.0             # 조각 한 칸의 크기 (논리 픽셀)

CONSOLE = [
    (0.10, "J.A.R.V.I.S  //  DEFENSE PROTOCOL"),
    (0.35, "> 흡수 시도 감지 — 촉수 접속 차단"),
    (0.75, "> 울트론 가디언 프로세스 종료"),
    (1.10, "> 울트론 소거 중 … {pct}%"),
    (2.70, "> 울트론 — 시스템에서 사라졌습니다"),
]


def sweep_progress(t: float) -> float:
    a, b = SWEEP
    return float(C.smooth((t - a) / (b - a)))


def console_lines(t: float, typed_cps: float = 48.0) -> list[str]:
    pct = int(round(sweep_progress(t) * 100))
    out = []
    for at, text in CONSOLE:
        if t < at:
            break
        line = text.replace("{pct}", str(pct))
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


class Shatter:
    """찍어 둔 울트론 그림이 위에서부터 조각나 푸르게 바래며 흩어지는 그림을 만든다 (그림 픽셀 단위, numpy 만).
    frame(t) → 그림보다 margin 만큼 둘레가 넓은 RGBA 화폭 (조각이 그림 밖으로 날아가도 잘리지 않게)."""

    def __init__(self, src: np.ndarray, scale: float = 1.0, seed: int = 11) -> None:
        h, w = src.shape[:2]
        self.c = c = max(3, int(round(CELL * scale)))
        self.margin = m = int(math.ceil(150 * scale))
        ny, nx = math.ceil(h / c), math.ceil(w / c)
        pad = np.zeros((ny * c, nx * c, 4), np.uint8)
        pad[:h, :w] = src
        blue = C.recolor(pad)
        # (n, c, c, 4) 조각들 — Dust 의 조각 순서(행 우선)와 같게
        blocks = pad.reshape(ny, c, nx, c, 4).transpose(0, 2, 1, 3, 4).reshape(-1, c, c, 4)
        self.red = blocks.astype(np.float32)
        self.blue = blue.reshape(ny, c, nx, c, 4).transpose(0, 2, 1, 3, 4).reshape(-1, c, c, 4).astype(np.float32)
        self.dust = Dust(nx * c, ny * c, cell=c, seed=seed)
        self.dust.vel *= scale
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
    env = np.clip(t / 0.4, 0, 1) * np.clip((length - t) / 0.7, 0, 1)
    f = 110 - 60 * p                                               # 울트론의 웅웅거림이 낮게 가라앉는다
    low = np.sin(2 * np.pi * np.cumsum(f) / sr) * (1 - p) * 0.55
    shield = np.sin(2 * np.pi * 880 * t) * 0.10 * np.exp(-t / 0.5)  # 방어막이 닫히는 맑은 소리 (천천히 잦아든다)
    done = sum(np.sin(2 * np.pi * fr * t) for fr in (659.25, 987.77)) / 2 * C.smooth((t - SWEEP[1]) / 0.6) * 0.5
    return ((low + shield + done) * env * 0.35).astype(np.float32)


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
