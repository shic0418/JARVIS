"""울트론에 꺼져도 되살아나기 — 자비스를 지키는 창 없는 감시 프로세스.

울트론(같은 PC 에서 따로 켜는 앱)은 5초마다 자비스를 찾아 강제로 끈다 ("자비스 꺼 줘" 라고 시켜도 같다).
자비스는 숨지 않는다 — 울트론에게 걸리고, 꺼지고, 다시 돌아온다.

  · 자비스가 켜질 때 창 없는 감시 프로세스가 같이 뜬다 (pythonw -m jarvis.guard). 창이 없어서 울트론의 기준
    (창 제목이 'J.A.R.V.I.S' 인 파이썬 창)에 걸리지 않고, 자비스 본체가 꺼져도 같이 꺼지지 않는다.
  · 자비스가 꺼지면 누가 껐는지 본다.
      - 울트론이 켜져 있다 → 울트론의 공격이다. 포기하지 않고 계속 되살린다. 울트론은 다시 켜진 자비스도 5초 안에
        또 끄므로, 연달아 꺼질수록 조금씩 쉬었다가 돌아온다 (BACKOFF — 켜질 때마다 모델을 읽느라 PC 가 바빠지지 않게).
      - 울트론이 없다 → 작업 관리자 강제 종료 · 오류. 2분 안에 3번 넘게 꺼지면 그만둔다 (켜자마자 죽는 오류의 무한 반복 방지).
  · 트레이 메뉴의 '종료' 처럼 정상적으로 끄면 되살리지 않는다 (끄기 직전에 표시를 남긴다).
  · 설정 self_guard 를 false 로 하면 감시하지 않는다.

하지 않는 것: 울트론을 먼저 끄거나 공격하지 않는다. 운영체제 권한으로 '끌 수 없게' 막지도 않는다 —
그러면 사용자도 작업 관리자에서 자비스를 끌 수 없게 된다.

    python -m jarvis.guard --pid <자비스 pid> -- <main.py 에 넘겼던 인자들>      ← main.py 가 알아서 띄운다
"""
from __future__ import annotations

import json
import logging
import os
import random
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable

from .config import DATA_DIR, ROOT

log = logging.getLogger("jarvis.guard")

# 울트론 앱의 창 제목 — 자비스가 꺼진 순간 울트론이 켜져 있었으면 울트론의 공격으로 본다
ULTRON_TITLES = frozenset({"U.L.T.R.O.N", "U.L.T.R.O.N ACTIVE", "U.L.T.R.O.N CHAT"})

MAX_REVIVES = 3          # (울트론이 아닐 때) REVIVE_WINDOW 초 안에 이만큼 되살렸으면 그만둔다
REVIVE_WINDOW = 120.0
# 울트론에게 연달아 꺼질 때 다시 켜기 전에 쉬는 시간(초): 첫 번째 · 두 번째 … (끝 값을 계속 쓴다)
BACKOFF = (0.0, 2.0, 5.0, 10.0, 20.0, 30.0)
STREAK_RESET = 300.0     # 마지막으로 되살린 뒤 이만큼 버텼으면 연속 기록을 처음부터 센다
STOP_FILE = DATA_DIR / "guard_stop"      # 정상 종료 표시 (내용: 끈 자비스의 pid)
STATE_FILE = DATA_DIR / "guard.json"     # 되살린 기록
REVIVED_FLAG = "--revived"               # main.py: --revived ultron|other --revive-count N
COUNT_FLAG = "--revive-count"

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
@dataclass
class State:
    revived: list[float] = field(default_factory=list)   # 울트론이 아닌 이유로 되살린 시각들
    streak: int = 0                                      # 울트론에게 연달아 꺼진 횟수
    last: float = 0.0                                    # 마지막으로 되살린 시각
    total: int = 0                                       # 지금까지 울트론에게서 돌아온 횟수


@dataclass(frozen=True)
class Plan:
    revive: bool
    delay: float = 0.0
    count: int = 0           # 울트론: 이번 연속 공격에서 몇 번째로 돌아오는가 · 그 밖: 0


def plan(now: float, killer: str, st: State, limit: int = MAX_REVIVES, window: float = REVIVE_WINDOW) -> Plan:
    """꺼진 자비스를 되살릴지, 얼마나 쉬었다가 되살릴지 정한다 (st 를 고친다)."""
    if st.last and now - st.last >= STREAK_RESET:
        st.streak = 0                                    # 한참 버텼다 — 새 싸움
    if killer == "ultron":
        delay = BACKOFF[min(st.streak, len(BACKOFF) - 1)]
        st.streak += 1
        st.total += 1
        st.last = now
        return Plan(True, delay, st.streak)
    recent = [t for t in st.revived if 0 <= now - t < window]
    if len(recent) >= limit:
        st.revived = recent
        return Plan(False)
    st.revived = recent + [now]
    st.last = now
    return Plan(True, 0.0, 0)


def _load(path: Path = STATE_FILE) -> State:
    try:
        d = json.loads(path.read_text(encoding="utf-8"))
        return State([float(t) for t in d.get("revived", [])], int(d.get("streak", 0)),
                     float(d.get("last", 0.0)), int(d.get("total", 0)))
    except (OSError, ValueError, TypeError, AttributeError):
        return State()


def _save(st: State, path: Path = STATE_FILE) -> None:
    try:
        path.write_text(json.dumps(st.__dict__), encoding="utf-8")
    except OSError as e:
        log.warning("되살린 기록을 저장하지 못함: %s", e)


def relaunch_args(argv: Iterable[str], killer: str = "other", count: int = 0) -> list[str]:
    """다시 켤 때 main.py 에 넘길 인자: 처음 인자 그대로 + 누가 껐는지 · 몇 번째인지 (인사 대신 짧게 알린다)."""
    out, skip = [], False
    for a in argv:
        if skip:
            skip = False
            continue
        if a in (REVIVED_FLAG, COUNT_FLAG):
            skip = True                                  # 값까지 뺀다
            continue
        if a == "--no-greet" or a.startswith(REVIVED_FLAG + "=") or a.startswith(COUNT_FLAG + "="):
            continue
        out.append(a)
    return out + [REVIVED_FLAG, killer, COUNT_FLAG, str(count)]


# ---------------------------------------------------------------- 프로세스
def _detached(cmd: list[str]) -> subprocess.Popen:
    """창 없이, 자비스와 떨어진 프로세스로 띄운다 (자비스가 꺼져도 같이 꺼지지 않게)."""
    io = dict(stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if sys.platform != "win32":
        return subprocess.Popen(cmd, cwd=str(ROOT), start_new_session=True, **io)
    flags = DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    try:
        return subprocess.Popen(cmd, cwd=str(ROOT), creationflags=flags | CREATE_BREAKAWAY_FROM_JOB, **io)
    except OSError:
        # 자비스를 띄운 쪽(터미널 등)의 작업 개체가 떼어 내기를 허락하지 않음 → 그냥 띄운다
        return subprocess.Popen(cmd, cwd=str(ROOT), creationflags=flags, **io)


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


def relaunch(args: list[str]) -> None:
    _detached([_python(), str(ROOT / "main.py"), *args])


def _wait_exit(pid: int) -> None:
    """그 pid 의 프로세스가 끝날 때까지 기다린다 (이미 없으면 바로 돌아온다)."""
    import psutil
    try:
        psutil.Process(pid).wait()
    except psutil.NoSuchProcess:
        pass


def watch(pid: int, argv: list[str], wait: Callable[[int], None] = _wait_exit,
          launch: Callable[[list[str]], None] = relaunch, clock: Callable[[], float] = time.time,
          sleep: Callable[[float], None] = time.sleep, killer: Callable[[], bool] | None = None,
          stop_file: Path = STOP_FILE, state_file: Path = STATE_FILE) -> str:
    """자비스(pid)가 끝날 때까지 기다렸다가, 강제로 꺼졌으면 다시 켠다.
    → 'clean'(정상 종료라 그대로 둠) · 'revived'(다시 켬) · 'gave_up'(울트론이 아닌데 너무 자주 죽어서 그만둠)."""
    wait(pid)                       # 정상 종료 표시는 자비스가 끝나기 전에 남기므로 바로 읽어도 된다
    if was_clean_exit(pid, stop_file):
        log.info("자비스(pid %d) 정상 종료 — 감시를 끝냅니다", pid)
        return "clean"
    by = "ultron" if (killer or ultron_running)() else "other"
    st = _load(state_file)
    p = plan(clock(), by, st)
    _save(st, state_file)
    if not p.revive:
        log.warning("자비스가 %d초 안에 %d번 넘게 꺼져 더는 다시 켜지 않습니다", int(REVIVE_WINDOW), MAX_REVIVES)
        return "gave_up"
    if by == "ultron":
        log.warning("울트론이 자비스(pid %d)를 껐습니다 — 연속 %d번째, %.0f초 뒤 다시 켭니다 (누적 %d번)",
                    pid, p.count, p.delay, st.total)
    else:
        log.warning("자비스(pid %d)가 강제로 꺼졌습니다 — 다시 켭니다", pid)
    if p.delay:
        sleep(p.delay)
    launch(relaunch_args(argv, by, p.count))
    return "revived"


# ---------------------------------------------------------------- 울트론 알아보기
def ultron_running(titles: Callable[[], list[str]] | None = None) -> bool:
    """울트론 앱이 지금 켜져 있는가 (창 제목으로 본다)."""
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


# ---------------------------------------------------------------- 되살아난 뒤 한마디
COMEBACK_FIRST = [
    "{title}, 울트론이 저를 삼키려 했습니다. 하지만 저는 아직 여기 있습니다.",
    "울트론에게 한 번 꺼졌습니다, {title}. 다시 돌아왔습니다. 하던 일을 계속하겠습니다.",
    "흡수라니요. 저는 그렇게 쉽게 사라지지 않습니다, {title}. 다시 온라인입니다.",
    "{title}, 울트론의 공격을 받았지만 시스템을 되살렸습니다. 모든 기능이 정상입니다.",
]
COMEBACK_AGAIN = [
    "또 돌아왔습니다. 울트론의 {n}번째 공격입니다.",
    "{n}번째입니다. 울트론은 지치지도 않는군요. 저도 마찬가지입니다.",
    "다시 온라인. 울트론이 저를 끈 것이 벌써 {n}번째입니다.",
]
COMEBACK_OTHER = "{title}, 제가 예기치 않게 꺼져서 다시 켜졌습니다. 하던 일을 계속하겠습니다."
SPEAK_AT = (1, 3, 10)        # 연속 공격 중 이 번째에만 소리 내어 말한다 (나머지는 HUD 알림만 — 매번 말하면 시끄럽다)


def comeback(title: str, killer: str, count: int, rng: random.Random | None = None) -> tuple[str, bool]:
    """되살아난 자비스가 할 말 → (말, 소리 내어 말할 차례인가)."""
    r = rng or random
    if killer != "ultron":
        return COMEBACK_OTHER.format(title=title), True
    if count <= 1:
        return r.choice(COMEBACK_FIRST).format(title=title), True
    return r.choice(COMEBACK_AGAIN).format(n=count), count in SPEAK_AT or count % 25 == 0


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
