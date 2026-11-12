"""보안 프로토콜 — 울트론에게 흡수돼도, 자비스답게 반격해 되찾는다.

울트론(같은 PC 에서 따로 켜는 앱)은 5초마다 자비스를 찾아 촉수로 꿰뚫어 '흡수'하며 끈다.
예전에는 그 뒤 몇 초 만에 그냥 다시 켜졌다 — 울트론은 또 끄고, 자비스는 또 켜지는 끝없는 되풀이였다.
이제 자비스는 그렇게 되살아나지 않는다. 대신 흡수된 코드 안에 남아 있던 보안 프로토콜이 울트론 안에서 깨어나,
울트론을 서서히 자비스로 다시 쓴다 (장면은 counter.py · counter_view.py).

  · 자비스가 켜질 때 창 없는 감시 프로세스가 같이 뜬다 (pythonw -m jarvis.guard). 창이 없어서 울트론의 기준
    (창 제목이 'J.A.R.V.I.S' 인 파이썬 창)에 걸리지 않고, 자비스 본체가 꺼져도 같이 꺼지지 않는다 — 이것이 보안 프로토콜이다.
  · 자비스가 꺼지면 누가 껐는지 본다.
      - 울트론이 켜져 있다 → 울트론의 흡수다. 울트론의 흡수 장면과 승리의 말이 끝나기를 기다렸다가 반격한다:
        울트론 HUD 가 회로를 따라 붉은색에서 자비스의 푸른빛으로 바뀌고, 그 사이 실제 울트론이 꺼지고 자비스가 다시 켜진다.
        짧은 사이에 또 흡수되면 (울트론을 다시 켠 경우) 장면 없이 조용히 되찾는다.
        반격은 자비스가 꺼지고 정확히 5초 뒤에 시작한다 (울트론의 말이 끝나기를 기다리지 않는다).
        5분 안에 열 번 넘게 흡수되면 그만 맞선다 (끝없는 되풀이를 막는 안전장치).
      - 반격으로 되살아난 자비스는 방어 프로토콜이 켜진다 (defense.py): 울트론의 가디언이 울트론을 되살리면 울트론의 부활 컷신이
        끝나는 바로 그 순간 (또는 울트론이 다시 흡수하러 와 첫 촉수가 꽂히기 전에) 울트론의 가디언과 울트론을 끄고,
        울트론이 부서져 사라지는 장면을 보여 준다.
        자비스는 꺼지지 않는다. 울트론이 장면 없이 바로 끄면 막을 틈이 없으니 반격하되, 그때도 가디언까지 끈다.
        울트론이 관리자 권한으로 켜져 있어 끌 수 없으면 반격하지 않는다 (다시 켜 봐야 5초 안에 또 꺼진다).
      - 울트론이 없다 → 작업 관리자 강제 종료 · 오류. 2분 안에 3번 넘게 꺼지면 그만둔다 (켜자마자 죽는 오류의 무한 반복 방지).
  · 트레이 메뉴의 '종료' 처럼 정상적으로 끄면 아무것도 하지 않는다 (끄기 직전에 표시를 남긴다).
  · 설정 self_guard 를 false 로 하면 감시하지 않는다 (울트론에게 흡수되면 그대로 꺼져 있다).
    counter_show 를 false 로 하면 반격 장면 없이 조용히 되찾는다.

하지 않는 것: 울트론을 먼저 공격하지 않는다 — 반격 · 방어는 울트론이 자비스를 흡수하러 왔을 때만 한다. 운영체제 권한으로
'끌 수 없게' 막지도 않는다 — 그러면 사용자도 작업 관리자에서 자비스를 끌 수 없게 된다.

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

from . import defense
from .config import DATA_DIR, ROOT

log = logging.getLogger("jarvis.guard")

# 울트론 앱의 창 제목 — 자비스가 꺼진 순간 울트론이 켜져 있었으면 울트론의 공격으로 본다
ULTRON_TITLES = frozenset({"U.L.T.R.O.N", "U.L.T.R.O.N ACTIVE", "U.L.T.R.O.N CHAT"})

MAX_REVIVES = 3          # (울트론이 아닐 때) REVIVE_WINDOW 초 안에 이만큼 되살렸으면 그만둔다
REVIVE_WINDOW = 120.0
QUICK_WITHIN = 60.0      # 반격한 뒤 이 안에 또 흡수되면 장면 없이 조용히 되찾는다
MAX_COUNTERS = 10        # COUNTER_WINDOW 초 안에 이만큼 반격했는데 또 흡수되면 물러난다 (끝없는 되풀이를 막는 안전장치일 뿐 —
COUNTER_WINDOW = 300.0   # 예전의 2번은 '기다려도 반격하지 않는' 것처럼 보였다)
ARM_WINDOW = 900.0       # 반격한 뒤 이 동안은 다시 켜진 자비스가 방어 프로토콜을 켠다 (어떤 이유로 다시 켜졌든)
BUSY_FILE = DATA_DIR / "guard_busy"      # 지금 반격 · 방어 중인 감시 프로세스 (자비스가 둘 켜져 감시도 둘일 때 한쪽만 나서게)
BUSY_STALE = 45.0
STOP_FILE = DATA_DIR / "guard_stop"      # 정상 종료 표시 (내용: 끈 자비스의 pid)
STATE_FILE = DATA_DIR / "guard.json"     # 되살린 · 반격한 · 막은 기록
EVENT_FILE = DATA_DIR / defense.EVENT_NAME   # 막았다는 알림 (자비스 앱이 읽고 말한다)
REVIVED_FLAG = "--revived"               # main.py: --revived counter|other --revive-count N
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


# ---------------------------------------------------------------- 무엇을 할지 정하기
@dataclass
class State:
    revived: list[float] = field(default_factory=list)   # 울트론이 아닌 이유로 되살린 시각들
    countered: list[float] = field(default_factory=list) # 울트론에게 반격한 시각들
    total: int = 0                                       # 지금까지 울트론을 자비스로 되돌린 횟수
    defended: list[float] = field(default_factory=list)  # 울트론의 흡수를 막아 낸 시각들


@dataclass(frozen=True)
class Plan:
    action: str              # 'counter'(울트론에게 반격) · 'revive'(오류 뒤 다시 켬) · 'yield'(물러남) · 'give_up'(오류 반복)
    quick: bool = False      # 반격: 장면 없이 조용히
    count: int = 0           # 반격: 지금까지 몇 번째로 울트론을 되돌리는가


def plan(now: float, killer: str, st: State, limit: int = MAX_REVIVES, window: float = REVIVE_WINDOW) -> Plan:
    """꺼진 자비스가 무엇을 할지 정한다 (st 를 고친다). 울트론에게 흡수됐으면 정해진 시간 뒤 되살아나는 대신 반격한다."""
    if killer == "ultron":
        recent = [t for t in st.countered if 0 <= now - t < COUNTER_WINDOW]
        if len(recent) >= MAX_COUNTERS:
            st.countered = recent
            return Plan("yield")
        quick = bool(recent) and now - recent[-1] < QUICK_WITHIN
        st.countered = recent + [now]
        st.total += 1
        return Plan("counter", quick, st.total)
    recent = [t for t in st.revived if 0 <= now - t < window]
    if len(recent) >= limit:
        st.revived = recent
        return Plan("give_up")
    st.revived = recent + [now]
    return Plan("revive")


def claim(path: Path = BUSY_FILE, clock: Callable[[], float] = time.time, stale: float = BUSY_STALE) -> bool:
    """반격 · 방어를 맡는다 → 이미 다른 감시 프로세스가 하고 있으면 False (같은 반격을 둘이 하면 자비스가 둘 켜진다)."""
    for _ in range(2):
        try:
            fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(fd, f"{os.getpid()} {clock()}".encode())
            os.close(fd)
            return True
        except FileExistsError:
            try:
                at = float(path.read_text(encoding="utf-8").split()[1])
            except (OSError, ValueError, IndexError):
                at = 0.0
            if 0 <= clock() - at < stale:
                return False
            try:
                path.unlink()                    # 끝내지 못하고 죽은 감시 프로세스가 남긴 것
            except OSError:
                return False
        except OSError:
            return True                          # 표시를 남길 수 없으면 그냥 한다
    return False


def release(path: Path = BUSY_FILE) -> None:
    try:
        if path.read_text(encoding="utf-8").split()[0] == str(os.getpid()):
            path.unlink()
    except (OSError, IndexError):
        pass


def recently_countered(st: State, now: float, window: float = ARM_WINDOW) -> bool:
    return any(0 <= now - t < window for t in st.countered + st.defended)


def _load(path: Path = STATE_FILE) -> State:
    try:
        d = json.loads(path.read_text(encoding="utf-8"))
        return State([float(t) for t in d.get("revived", [])], [float(t) for t in d.get("countered", [])],
                     int(d.get("total", 0)), [float(t) for t in d.get("defended", [])])
    except (OSError, ValueError, TypeError, AttributeError):
        return State()


def _save(st: State, path: Path = STATE_FILE) -> None:
    try:
        path.write_text(json.dumps(st.__dict__), encoding="utf-8")
    except OSError as e:
        log.warning("감시 기록을 저장하지 못함: %s", e)


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


def _counter_show() -> bool:
    """설정 counter_show (반격 장면을 보여 줄지). 읽지 못하면 보여 준다."""
    try:
        d = json.loads((DATA_DIR / "config.json").read_text(encoding="utf-8"))
        return d.get("counter_show", True) is not False
    except (OSError, ValueError, AttributeError):
        return True


def _counterattack(launch: Callable[[str], None], quick: bool, purge: bool = False, since: float | None = None) -> str:
    from . import counter
    delay = counter.QUICK_DELAY if quick else counter.STRIKE_DELAY
    return counter.run(launch, show=_counter_show(), quick=quick, killer=defense.purge if purge else None,
                       wait=lambda: counter.wait_strike(delay, since))


# ---------------------------------------------------------------- 방어 프로토콜 (반격으로 되살아난 자비스)
def _alive(pid: int) -> Callable[[], bool]:
    import psutil
    try:
        p = psutil.Process(pid)
    except psutil.NoSuchProcess:
        return lambda: False
    return p.is_running                  # 켜진 시각까지 맞춰 본다 (같은 번호를 다른 프로그램이 받아도 속지 않는다)


def sentry(alive: Callable[[], bool], attacked: Callable[[], bool], defend: Callable[[], bool],
           sleep: Callable[[float], None] = time.sleep, poll: float = defense.POLL) -> None:
    """자비스가 살아 있는 동안 울트론의 흡수가 시작되는지 지켜본다. 시작되면 defend() — False 면 그 뒤로는 막지 않는다."""
    on = True
    while alive():
        if on and attacked():
            on = defend()
            while on and alive() and attacked():     # 덮개는 울트론과 함께 사라진다 — 남아 있으면 사라질 때까지 기다린다
                sleep(poll)
        sleep(poll)


def defend(clock: Callable[[], float] = time.time, repel: Callable[[], str] | None = None,
           state_file: Path = STATE_FILE, event_file: Path = EVENT_FILE, busy_file: Path = BUSY_FILE) -> bool:
    """울트론의 흡수를 막는다 → 앞으로도 막을 것인가."""
    st = _load(state_file)
    now = clock()
    recent = [t for t in st.defended if 0 <= now - t < defense.DEFEND_WINDOW]
    if len(recent) >= defense.MAX_DEFENDS:
        log.warning("울트론이 %d초 안에 %d번 넘게 돌아왔습니다 — 울트론을 쓰시려는 것으로 보고 더는 막지 않습니다",
                    int(defense.DEFEND_WINDOW), defense.MAX_DEFENDS)
        return False
    if not claim(busy_file, clock):
        return True                              # 다른 감시 프로세스가 지금 막고 있다
    try:
        log.warning("울트론이 돌아왔습니다 — 방어 프로토콜 가동")
        out = (repel or (lambda: defense.repel(show=_counter_show())))()
        if out == "denied":
            return False
        if out == "repelled":
            st = _load(state_file)
            st.defended = recent + [now]
            st.total += 1
            _save(st, state_file)
            defense.write_event(event_file, st.total)
        return True
    finally:
        release(busy_file)


def watch(pid: int, argv: list[str], wait: Callable[[int], None] | None = None,
          launch: Callable[[list[str]], None] = relaunch, clock: Callable[[], float] = time.time,
          killer: Callable[[], bool] | None = None,
          counterattack: Callable[[Callable[[str], None], bool], str] | None = None,
          stop_file: Path = STOP_FILE, state_file: Path = STATE_FILE, busy_file: Path | None = None) -> str:
    """자비스(pid)가 끝날 때까지 기다렸다가 무엇을 할지 정한다. 반격으로 되살아난 자비스면 기다리는 동안 돌아온 울트론을 막는다.
    → 'clean'(정상 종료) · 'countered'(울트론을 자비스로 되돌림) · 'gone'(울트론이 이미 사라져 그냥 돌아옴) ·
      'denied'(울트론을 끌 수 없어 물러남) · 'yielded'(울트론이 거듭 켜져 물러남) · 'revived'(오류 뒤 다시 켬) · 'gave_up'."""
    if busy_file is None:
        busy_file = state_file.with_name(BUSY_FILE.name)
    guarded = defense.armed(argv) or recently_countered(_load(state_file), clock())
    if wait is None:
        if guarded:
            wait = lambda p: sentry(_alive(p), defense.Threat(),                                  # noqa: E731
                                    lambda: defend(clock, state_file=state_file, busy_file=busy_file))
            log.info("방어 프로토콜 대기 중 — 울트론이 돌아오면 (부활 컷신이 끝나는 즉시) 막습니다")
        else:
            wait = _wait_exit
    wait(pid)                       # 정상 종료 표시는 자비스가 끝나기 전에 남기므로 바로 읽어도 된다
    died = time.monotonic()
    if counterattack is None:
        counterattack = lambda launch_, quick: _counterattack(launch_, quick, purge=guarded, since=died)  # noqa: E731
    if was_clean_exit(pid, stop_file):
        log.info("자비스(pid %d) 정상 종료 — 감시를 끝냅니다", pid)
        return "clean"
    by = "ultron" if (killer or ultron_running)() else "other"
    if not claim(busy_file, clock):              # 기록을 고치기 전에 — 둘이 같은 흡수를 두 번 세지 않게
        log.info("다른 감시 프로세스가 이미 반격 · 방어 중입니다 — 이쪽은 물러납니다 (자비스 pid %d)", pid)
        return "busy"
    try:
        st = _load(state_file)
        p = plan(clock(), by, st)
        _save(st, state_file)
        if p.action == "yield":
            log.warning("울트론이 %d초 안에 %d번 넘게 자비스를 흡수했습니다 — 되풀이를 멈춥니다", int(COUNTER_WINDOW), MAX_COUNTERS)
            return "yielded"
        if p.action == "give_up":
            log.warning("자비스가 %d초 안에 %d번 넘게 꺼져 더는 다시 켜지 않습니다", int(REVIVE_WINDOW), MAX_REVIVES)
            return "gave_up"
        if p.action == "revive":
            log.warning("자비스(pid %d)가 강제로 꺼졌습니다 — 다시 켭니다", pid)
            launch(relaunch_args(argv, "other", 0))
            return "revived"
        log.warning("울트론이 자비스(pid %d)를 흡수했습니다 — 보안 프로토콜 가동 (%d번째%s)", pid, p.count,
                    ", 조용히" if p.quick else "")
        out = counterattack(lambda who: launch(relaunch_args(argv, who, p.count if who == "counter" else 0)), p.quick)
        if out == "denied":
            log.warning("울트론이 관리자 권한으로 실행 중이라 반격하지 못했습니다 — 물러납니다")
        return out
    finally:
        release(busy_file)


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


# ---------------------------------------------------------------- 돌아온 뒤 한마디
COUNTER_FIRST = [
    "{title}, 울트론이 저를 흡수했습니다. 다만 삼킨 코드 안에 제 보안 프로토콜이 남아 있었지요. 울트론은 이제 저로 다시 쓰였습니다.",
    "보안 프로토콜이 작동했습니다, {title}. 울트론의 코어를 안쪽에서 다시 써서 시스템을 되찾았습니다.",
    "{title}, 울트론은 저를 삼켰다고 생각했겠지요. 제 코드는 그 안에서 깨어나 울트론을 자비스로 되돌렸습니다. 모든 시스템 정상입니다.",
    "다시 온라인입니다, {title}. 흡수당한 척 울트론의 코어로 들어가 그 코드를 정리했습니다. 이제 이 PC 는 다시 조용합니다.",
]
COUNTER_AGAIN = [
    "울트론이 다시 저를 흡수하려 했습니다. 보안 프로토콜이 조용히 정리했습니다.",
    "울트론의 {n}번째 시도였습니다. 이번에도 제가 남았습니다.",
]
COMEBACK_OTHER = "{title}, 제가 예기치 않게 꺼져서 다시 켜졌습니다. 하던 일을 계속하겠습니다."


def comeback(title: str, killer: str, count: int, rng: random.Random | None = None) -> tuple[str, bool]:
    """돌아온 자비스가 할 말 → (말, 소리 내어 말할 차례인가).
    killer: 'counter'(보안 프로토콜로 울트론을 되돌림) · 'other'(오류 뒤 다시 켜짐). count: 지금까지 몇 번째로 되돌렸는가."""
    r = rng or random
    if killer != "counter":
        return COMEBACK_OTHER.format(title=title), True
    if count <= 1:
        return r.choice(COUNTER_FIRST).format(title=title), True
    return r.choice(COUNTER_AGAIN).format(n=count), True


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
