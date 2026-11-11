"""자기 보호 (guard.py): 울트론에게 걸려 꺼져도 되살아난다 · 정상 종료는 그대로 · 오류로 죽는 것은 무한 반복하지 않는다."""
from __future__ import annotations

import random
import re
import subprocess
import sys
import threading
from pathlib import Path

import pytest

from jarvis import guard

ROOT = Path(__file__).resolve().parent.parent

# 울트론(Ultron-main/jarvis/rival.py)이 자비스를 찾는 기준
ULTRON_TARGET_TITLES = frozenset({"J.A.R.V.I.S", "J.A.R.V.I.S ACTIVE", "J.A.R.V.I.S CHAT"})


def test_jarvis_does_not_hide_from_ultron():
    """숨지 않는다 — 창 제목은 울트론이 찾는 그대로다 (걸리고, 꺼지고, 돌아온다)."""
    titles = []
    for f in ("Main.qml", "ActiveMode.qml"):
        titles += re.findall(r'^\s*title:\s*"(J\.A\.R[^"]*)"', (ROOT / "ui" / f).read_text(encoding="utf-8"), re.M)
    assert sorted(titles) == sorted(ULTRON_TARGET_TITLES)


# ---------------------------------------------------------------- 정상 종료 표시
def test_clean_exit_mark_is_per_process_and_read_once(tmp_path):
    f = tmp_path / "stop"
    guard.mark_clean_exit(1234, f)
    assert guard.was_clean_exit(1234, f) is True
    assert guard.was_clean_exit(1234, f) is False                     # 한 번 읽으면 지운다
    guard.mark_clean_exit(1111, f)
    assert guard.was_clean_exit(2222, f) is False                     # 다른 자비스가 남긴 표시
    assert not f.exists()


# ---------------------------------------------------------------- 되살리기 규칙
def test_ultron_attacks_are_always_revived_with_growing_pauses():
    st = guard.State()
    plans = [guard.plan(1000.0 + i * 8, "ultron", st) for i in range(10)]    # 8초마다 꺼진다 (울트론은 5초마다 확인)
    assert all(p.revive for p in plans)                                     # 포기하지 않는다
    assert [p.delay for p in plans] == [0.0, 2.0, 5.0, 10.0, 20.0, 30.0, 30.0, 30.0, 30.0, 30.0]
    assert [p.count for p in plans] == list(range(1, 11))
    assert st.total == 10


def test_ultron_streak_resets_after_surviving_a_while():
    st = guard.State()
    for i in range(4):
        guard.plan(1000.0 + i, "ultron", st)
    p = guard.plan(1003.0 + guard.STREAK_RESET, "ultron", st)              # 5분 버틴 뒤 다시 공격받음
    assert p.revive and p.delay == 0.0 and p.count == 1 and st.total == 5


def test_other_deaths_give_up_after_three_in_two_minutes():
    st = guard.State()
    assert [guard.plan(t, "other", st).revive for t in (1000.0, 1010.0, 1020.0, 1030.0)] == [True, True, True, False]
    assert guard.plan(1000.0 + guard.REVIVE_WINDOW + 25, "other", st).revive      # 오래된 기록은 세지 않는다


def test_ultron_kills_do_not_use_up_the_crash_limit():
    st = guard.State()
    for t in (1000.0, 1001.0, 1002.0):
        guard.plan(t, "other", st)
    assert guard.plan(1003.0, "ultron", st).revive                          # 오류 한도를 넘어도 울트론의 공격에서는 돌아온다


def test_relaunch_args_mark_who_killed_and_how_many_times():
    assert guard.relaunch_args(["--no-mic"], "ultron", 3) == ["--no-mic", "--revived", "ultron", "--revive-count", "3"]
    again = guard.relaunch_args(["--revived", "ultron", "--revive-count", "3", "--no-greet", "--no-mic"], "ultron", 4)
    assert again == ["--no-mic", "--revived", "ultron", "--revive-count", "4"]
    assert guard.relaunch_args([], "other", 0) == ["--revived", "other", "--revive-count", "0"]


def test_main_accepts_the_relaunch_arguments():
    import argparse
    src = (ROOT / "main.py").read_text(encoding="utf-8")
    assert '"--revived", choices=("ultron", "other")' in src and '"--revive-count", type=int' in src
    p = argparse.ArgumentParser()
    p.add_argument("--no-mic", action="store_true")
    p.add_argument("--revived", choices=("ultron", "other"))
    p.add_argument("--revive-count", type=int, default=0)
    a = p.parse_args(guard.relaunch_args(["--no-mic"], "ultron", 2))
    assert a.revived == "ultron" and a.revive_count == 2 and a.no_mic


# ---------------------------------------------------------------- 감시 흐름
def run_watch(tmp_path, clean=False, ultron=True, state=None):
    stop, state_file = tmp_path / "stop", tmp_path / "state.json"
    if state is not None:
        guard._save(state, state_file)
    launched, slept = [], []

    def wait(pid):
        if clean:
            guard.mark_clean_exit(pid, stop)

    out = guard.watch(42, ["--no-mic"], wait=wait, launch=launched.append, clock=lambda: 5000.0,
                      sleep=slept.append, killer=lambda: ultron, stop_file=stop, state_file=state_file)
    return out, launched, slept, guard._load(state_file)


def test_killed_by_ultron_comes_back(tmp_path):
    out, launched, slept, st = run_watch(tmp_path)
    assert out == "revived" and launched == [["--no-mic", "--revived", "ultron", "--revive-count", "1"]]
    assert slept == [] and st.streak == 1


def test_repeated_ultron_attack_waits_before_coming_back(tmp_path):
    out, launched, slept, st = run_watch(tmp_path, state=guard.State(streak=3, last=4990.0, total=3))
    assert out == "revived" and slept == [10.0] and launched[0][-1] == "4" and st.total == 4


def test_normal_quit_is_left_alone(tmp_path):
    out, launched, _, _ = run_watch(tmp_path, clean=True)
    assert out == "clean" and launched == []


def test_crash_loop_without_ultron_gives_up(tmp_path):
    out, launched, _, _ = run_watch(tmp_path, ultron=False, state=guard.State(revived=[4950.0, 4970.0, 4990.0]))
    assert out == "gave_up" and launched == []


def test_guard_command_line():
    assert guard.main(["--pid", "x"]) == 2
    assert guard.main([]) == 2


# ---------------------------------------------------------------- 진짜 프로세스로 (울트론이 하듯 강제로 끈다)
@pytest.mark.parametrize("clean", [False, True])
def test_real_process_kill_and_clean_exit(tmp_path, clean):
    p = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    stop, state = tmp_path / "stop", tmp_path / "state.json"
    launched, result = [], []
    t = threading.Thread(target=lambda: result.append(guard.watch(
        p.pid, ["--no-mic"], launch=launched.append, sleep=lambda s: None, killer=lambda: True,
        stop_file=stop, state_file=state)), daemon=True)
    t.start()
    if clean:
        guard.mark_clean_exit(p.pid, stop)
    p.kill()                                      # psutil.Process.kill — 울트론의 rival.stop 과 같은 방법
    p.wait(10)
    t.join(15)
    assert result == (["clean"] if clean else ["revived"])
    assert launched == ([] if clean else [["--no-mic", "--revived", "ultron", "--revive-count", "1"]])


# ---------------------------------------------------------------- 되살아난 뒤 한마디
def test_ultron_detection():
    assert guard.ultron_running(lambda: ["메모장", "U.L.T.R.O.N"]) is True
    assert guard.ultron_running(lambda: ["U.L.T.R.O.N 설명서.txt - 메모장"]) is False
    assert guard.ultron_running(lambda: (_ for _ in ()).throw(OSError())) is False


def test_comeback_lines_speak_only_now_and_then():
    rng = random.Random(1)
    first, speak = guard.comeback("주인님", "ultron", 1, rng)
    assert speak and "주인님" in first and "{" not in first
    assert [guard.comeback("주인님", "ultron", n, rng)[1] for n in range(2, 12)] == \
        [False, True, False, False, False, False, False, False, True, False]     # 3번째 · 10번째만 소리 내어
    line, speak = guard.comeback("주인님", "ultron", 7, rng)
    assert "7" in line and not speak
    other, speak = guard.comeback("주인님", "other", 0, rng)
    assert speak and "울트론" not in other
