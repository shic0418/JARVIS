"""울트론에 제거되지 않게 — 두 겹으로 자비스를 지킨다.

울트론(같은 PC 에서 따로 켜는 앱)은 5초마다 자비스를 찾아 강제로 끈다. 찾는 기준은 좁다:
최상위 창의 제목이 정확히 'J.A.R.V.I.S' · 'J.A.R.V.I.S ACTIVE' · 'J.A.R.V.I.S CHAT' 이고 그 창의 주인이 파이썬일 때.
"자비스 꺼 줘" 라고 시켜도 같은 기준으로 찾는다.

1) 안 보이기: 자비스의 창 제목을 그 목록과 다르게 쓴다 (WINDOW_TITLES — 화면에 보이는 글자는 그대로).
   그러면 울트론은 자비스를 찾지 못하고, 시켜도 "이미 꺼져 있다" 고 한다.
2) 되살아나기: 그래도 강제로 꺼지면(울트론의 다른 버전 · 작업 관리자 강제 종료 · 오류로 죽음) 창 없는 작은 감시 프로세스가
   알아채고 자비스를 다시 켠다. 감시 프로세스에는 창이 없어 울트론의 기준에 걸리지 않는다.
   · 트레이 메뉴의 '종료' 처럼 정상적으로 끄면 되살리지 않는다 (끄기 직전에 표시를 남긴다)
   · 2분 안에 3번 넘게 죽으면 더는 되살리지 않는다 (켜자마자 죽는 오류로 끝없이 되풀이하지 않게)
   · 설정 self_guard 를 false 로 하면 감시하지 않는다

하지 않는 것: 울트론을 먼저 끄거나 공격하지 않는다. 운영체제 권한으로 '끌 수 없게' 막지도 않는다 —
그러면 사용자도 작업 관리자에서 자비스를 끌 수 없게 된다.

    python -m jarvis.guard --pid <자비스 pid> -- <main.py 에 넘겼던 인자들>      ← main.py 가 알아서 띄운다
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Callable, Iterable

from .config import DATA_DIR, ROOT

log = logging.getLogger("jarvis.guard")

# 자비스의 최상위 창 제목. 울트론이 찾는 제목('J.A.R.V.I.S' …)과 정확히 같으면 안 된다 — 끝에 마침표를 붙였다
# (엠블럼의 워드마크와 같은 표기). 화면에 보이는 글자는 QML 의 Text 라서 바뀌지 않는다.
WINDOW_TITLES = {"hud": "J.A.R.V.I.S.", "active": "J.A.R.V.I.S. ACTIVE", "chat": "J.A.R.V.I.S. CHAT"}
# 울트론 앱의 창 제목 (되살아난 뒤 '누가 껐는지' 짐작할 때만 쓴다)
ULTRON_TITLES = frozenset({"U.L.T.R.O.N", "U.L.T.R.O.N ACTIVE", "U.L.T.R.O.N CHAT"})

MAX_REVIVES = 3          # REVIVE_WINDOW 초 안에 이만큼 되살렸으면 더는 되살리지 않는다
REVIVE_WINDOW = 120.0
STOP_FILE = DATA_DIR / "guard_stop"      # 정상 종료 표시 (내용: 끈 자비스의 pid)
STATE_FILE = DATA_DIR / "guard.json"     # 최근에 되살린 시각들
REVIVED_FLAG = "--revived"

DETACHED_PROCESS = 0x00000008
CREATE_NEW_PROCESS_GROUP = 0x00000200
CREATE_BREAKAWAY_FROM_JOB = 0x01000000


# ---------------------------------------------------------------- 정상 종료 표시
def mark_clean_exit(pid: int | None = None, path: Path = STOP_FILE) -> None:
    """(자비스가 정상적으로 끝날 때) 감시 프로세스에게 '되살리지 마라' 고 알린다."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(str(os.getpid() if pid is None else pid), encoding="utf-8")
    except OSError as e:
        log.warning("정상 종료 표시를 남기지 못함: %s", e)


def was_clean_exit(pid: int, path: Path = STOP_FILE) -> bool:
    """그 pid 의 자비스가 정상적으로 끝났는가. 표시는 읽은 뒤 지운다."""
    try:
        mark = path.read_text(encoding="utf-8").strip()
    except OSError:
        return False
    try:
        path.unlink()
    except OSError:
        pass
    return mark == str(pid)


# ---------------------------------------------------------------- 되살릴지 정하기
def allow_revive(now: float, history: Iterable[float], limit: int = MAX_REVIVES,
                 window: float = REVIVE_WINDOW) -> tuple[bool, list[float]]:
    """(되살려도 되는가, 오래된 기록을 지운 새 기록). 되살리기로 했으면 새 기록에 now 가 들어 있다."""
    recent = [t for t in history if 0 <= now - t < window]
    if len(recent) >= limit:
        return False, recent
    return True, recent + [now]


def _load_history(path: Path = STATE_FILE) -> list[float]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return [float(t) for t in data.get("revived", [])]
    except (OSError, ValueError, TypeError, AttributeError):
        return []


def _save_history(history: list[float], path: Path = STATE_FILE) -> None:
    try:
        path.write_text(json.dumps({"revived": history}), encoding="utf-8")
    except OSError as e:
        log.warning("되살린 기록을 저장하지 못함: %s", e)


def relaunch_args(argv: Iterable[str]) -> list[str]:
    """다시 켤 때 main.py 에 넘길 인자: 처음 인자 그대로 + '되살아났음' 표시 (인사는 짧게 바꾼다)."""
    out = [a for a in argv if a not in (REVIVED_FLAG, "--no-greet")]
    return out + [REVIVED_FLAG]


# ---------------------------------------------------------------- 프로세스
def _detached(cmd: list[str]) -> subprocess.Popen:
    """창 없이, 자비스와 떨어진 프로세스로 띄운다 (자비스가 꺼져도 같이 꺼지지 않게)."""
    if sys.platform != "win32":
        return subprocess.Popen(cmd, cwd=str(ROOT), start_new_session=True,
                                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    flags = DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    try:
        return subprocess.Popen(cmd, cwd=str(ROOT), creationflags=flags | CREATE_BREAKAWAY_FROM_JOB,
                                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError:
        # 자비스를 띄운 쪽(터미널 등)의 작업 개체가 떼어 내기를 허락하지 않음 → 그냥 띄운다
        return subprocess.Popen(cmd, cwd=str(ROOT), creationflags=flags,
                                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _python() -> str:
    """창 없는 파이썬 (pythonw) 이 있으면 그것을 쓴다."""
    exe = Path(sys.executable)
    w = exe.with_name("pythonw.exe")
    return str(w) if sys.platform == "win32" and exe.name.lower() == "python.exe" and w.exists() else str(exe)


def spawn(pid: int, argv: Iterable[str]) -> subprocess.Popen | None:
    """(자비스가 켜질 때) 감시 프로세스를 띄운다. 실패해도 자비스는 그대로 돈다."""
    cmd = [_python(), "-m", "jarvis.guard", "--pid", str(pid), "--", *argv]
    try:
        p = _detached(cmd)
        log.info("자기 보호: 감시 프로세스 시작 (pid %d)", p.pid)
        return p
    except OSError as e:
        log.warning("감시 프로세스를 띄우지 못함: %s", e)
        return None


def relaunch(argv: Iterable[str]) -> None:
    _detached([_python(), str(ROOT / "main.py"), *relaunch_args(argv)])


def _wait_exit(pid: int) -> None:
    """그 pid 의 프로세스가 끝날 때까지 기다린다 (이미 없으면 바로 돌아온다)."""
    import psutil
    try:
        psutil.Process(pid).wait()
    except psutil.NoSuchProcess:
        pass


def watch(pid: int, argv: list[str], wait: Callable[[int], None] = _wait_exit,
          launch: Callable[[list[str]], None] = relaunch, clock: Callable[[], float] = time.time,
          stop_file: Path = STOP_FILE, state_file: Path = STATE_FILE) -> str:
    """자비스(pid)가 끝날 때까지 기다렸다가, 강제로 꺼졌으면 다시 켠다.
    → 'clean'(정상 종료라 그대로 둠) · 'revived'(다시 켬) · 'gave_up'(너무 자주 죽어서 그만둠)."""
    wait(pid)                       # 정상 종료 표시는 자비스가 끝나기 전에 남기므로 바로 읽어도 된다
    if was_clean_exit(pid, stop_file):
        log.info("자비스(pid %d) 정상 종료 — 감시를 끝냅니다", pid)
        return "clean"
    ok, history = allow_revive(clock(), _load_history(state_file))
    _save_history(history, state_file)
    if not ok:
        log.warning("자비스가 %d초 안에 %d번 넘게 꺼져 더는 다시 켜지 않습니다", int(REVIVE_WINDOW), MAX_REVIVES)
        return "gave_up"
    log.warning("자비스(pid %d)가 강제로 꺼졌습니다 — 다시 켭니다", pid)
    launch(argv)
    return "revived"


# ---------------------------------------------------------------- 되살아난 뒤
def ultron_running(titles: Callable[[], list[str]] | None = None) -> bool:
    """울트론 앱이 지금 켜져 있는가 (창 제목으로 본다). 되살아난 뒤 한마디를 고를 때만 쓴다."""
    try:
        names = titles() if titles is not None else _top_titles()
    except Exception:
        return False
    return any((t or "").strip() in ULTRON_TITLES for t in names)


def _top_titles() -> list[str]:
    import ctypes
    import ctypes.wintypes as wt
    user32 = ctypes.windll.user32
    out: list[str] = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, wt.HWND, wt.LPARAM)
    def each(hwnd, _):
        n = user32.GetWindowTextLengthW(hwnd)
        if 0 < n < 40:
            buf = ctypes.create_unicode_buffer(n + 1)
            user32.GetWindowTextW(hwnd, buf, n + 1)
            out.append(buf.value)
        return True

    user32.EnumWindows(each, 0)
    return out


def revived_line(title: str, ultron: bool) -> str:
    if ultron:
        return f"{title}, 울트론이 저를 끄려 했지만 다시 돌아왔습니다. 하던 일을 계속하겠습니다."
    return f"{title}, 제가 예기치 않게 꺼져서 다시 켜졌습니다. 하던 일을 계속하겠습니다."


# ---------------------------------------------------------------- 실행
def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if "--" in args:
        i = args.index("--")
        own, rest = args[:i], args[i + 1:]
    else:
        own, rest = args, []
    if len(own) != 2 or own[0] != "--pid" or not own[1].isdigit():
        print("사용법: python -m jarvis.guard --pid <pid> -- <main.py 인자>", file=sys.stderr)
        return 2
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(filename=str(DATA_DIR / "guard.log"), level=logging.INFO, encoding="utf-8",
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    try:
        watch(int(own[1]), rest)
    except Exception:
        log.exception("감시 중 오류")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
