"""보안 프로토콜 (guard.py): 울트론에게 흡수되면 반격해 되찾는다 · 정상 종료는 그대로 · 오류로 죽는 것은 무한 반복하지 않는다."""
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
    """숨지 않는다 — 창 제목은 울트론이 찾는 그대로다 (흡수당하고, 안에서 깨어나 되찾는다)."""
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


# ---------------------------------------------------------------- 무엇을 할지 정하는 규칙
def test_ultron_absorption_is_answered_with_a_counterattack_not_a_timed_revive():
    st = guard.State()
    p = guard.plan(1000.0, "ultron", st)
    assert p.action == "counter" and not p.quick and p.count == 1 and st.total == 1
    assert not hasattr(guard, "BACKOFF")                                  # 몇 초 뒤 되살아나는 규칙은 없다


def test_a_second_absorption_soon_after_is_taken_back_quietly():
    st = guard.State()
    guard.plan(1000.0, "ultron", st)
    p = guard.plan(1000.0 + 30, "ultron", st)                             # 울트론을 금방 다시 켰다
    assert p.action == "counter" and p.quick and p.count == 2
    later = guard.State(countered=[1000.0])
    assert not guard.plan(1000.0 + guard.QUICK_WITHIN + 5, "ultron", later).quick     # 한참 뒤면 장면을 다시 보여 준다


def test_jarvis_steps_aside_when_ultron_keeps_being_started():
    st = guard.State()
    acts = [guard.plan(1000.0 + i * 20, "ultron", st).action for i in range(guard.MAX_COUNTERS + 1)]
    assert acts == ["counter"] * guard.MAX_COUNTERS + ["yield"]           # 끝없는 되풀이만 막는다 (세 번째에 물러나지 않는다)
    assert guard.MAX_COUNTERS >= 10
    assert guard.plan(1000.0 + guard.COUNTER_WINDOW + 100, "ultron", st).action == "counter"   # 오래 지나면 다시 맞선다


def test_other_deaths_give_up_after_three_in_two_minutes():
    st = guard.State()
    assert [guard.plan(t, "other", st).action for t in (1000.0, 1010.0, 1020.0, 1030.0)] == ["revive"] * 3 + ["give_up"]
    assert guard.plan(1000.0 + guard.REVIVE_WINDOW + 25, "other", st).action == "revive"      # 오래된 기록은 세지 않는다


def test_ultron_absorptions_do_not_use_up_the_crash_limit():
    st = guard.State()
    for t in (1000.0, 1001.0, 1002.0):
        guard.plan(t, "other", st)
    assert guard.plan(1003.0, "ultron", st).action == "counter"


def test_state_survives_a_save_and_old_files_still_load(tmp_path):
    f = tmp_path / "state.json"
    guard._save(guard.State(revived=[1.0], countered=[2.0, 3.0], total=5), f)
    assert guard._load(f) == guard.State([1.0], [2.0, 3.0], 5)
    f.write_text('{"revived": [], "streak": 4, "last": 9.0, "total": 7}', encoding="utf-8")   # 예전 형식
    assert guard._load(f) == guard.State([], [], 7)


def test_relaunch_args_mark_who_killed_and_how_many_times():
    assert guard.relaunch_args(["--no-mic"], "counter", 3) == ["--no-mic", "--revived", "counter", "--revive-count", "3"]
    again = guard.relaunch_args(["--revived", "counter", "--revive-count", "3", "--no-greet", "--no-mic"], "counter", 4)
    assert again == ["--no-mic", "--revived", "counter", "--revive-count", "4"]
    assert guard.relaunch_args([], "other", 0) == ["--revived", "other", "--revive-count", "0"]


def test_main_accepts_the_relaunch_arguments():
    import argparse
    src = (ROOT / "main.py").read_text(encoding="utf-8")
    assert '"--revived", choices=("counter", "other")' in src and '"--revive-count", type=int' in src
    p = argparse.ArgumentParser()
    p.add_argument("--no-mic", action="store_true")
    p.add_argument("--revived", choices=("counter", "other"))
    p.add_argument("--revive-count", type=int, default=0)
    a = p.parse_args(guard.relaunch_args(["--no-mic"], "counter", 2))
    assert a.revived == "counter" and a.revive_count == 2 and a.no_mic


# ---------------------------------------------------------------- 감시 흐름
def run_watch(tmp_path, clean=False, ultron=True, state=None, result="countered"):
    stop, state_file = tmp_path / "stop", tmp_path / "state.json"
    if state is not None:
        guard._save(state, state_file)
    launched, attacks = [], []

    def wait(pid):
        if clean:
            guard.mark_clean_exit(pid, stop)

    def counterattack(launch, quick):
        attacks.append(quick)
        if result == "countered":
            launch("counter")
        elif result == "gone":
            launch("other")
        return result

    out = guard.watch(42, ["--no-mic"], wait=wait, launch=launched.append, clock=lambda: 5000.0,
                      killer=lambda: ultron, counterattack=counterattack, stop_file=stop, state_file=state_file)
    return out, launched, attacks, guard._load(state_file)


def test_absorbed_by_ultron_counterattacks_and_comes_back_as_jarvis(tmp_path):
    out, launched, attacks, st = run_watch(tmp_path)
    assert out == "countered" and attacks == [False]
    assert launched == [["--no-mic", "--revived", "counter", "--revive-count", "1"]] and st.total == 1


def test_repeat_absorption_is_quiet_and_a_third_one_is_not_fought(tmp_path):
    out, launched, attacks, _ = run_watch(tmp_path, state=guard.State(countered=[4980.0], total=1))
    assert out == "countered" and attacks == [True] and launched[0][-1] == "2"
    out, launched, attacks, _ = run_watch(tmp_path, state=guard.State(countered=[4900.0, 4930.0], total=2))
    assert out == "countered" and attacks == [False] and launched[0][-1] == "3"      # 세 번째도 반격한다
    storm = guard.State(countered=[4990.0 - i for i in range(guard.MAX_COUNTERS)], total=guard.MAX_COUNTERS)
    out, launched, attacks, _ = run_watch(tmp_path, state=storm)
    assert out == "yielded" and attacks == [] and launched == []


def test_two_guards_never_fight_the_same_absorption_twice(tmp_path):
    busy = tmp_path / "guard_busy"
    assert guard.claim(busy, lambda: 5000.0) is True
    out, launched, attacks, st = run_watch(tmp_path)                    # 다른 감시 프로세스가 이미 반격 중
    assert out == "busy" and launched == [] and attacks == [] and st.total == 0
    guard.release(busy)
    assert not busy.exists()
    out, launched, _, st = run_watch(tmp_path)
    assert out == "countered" and st.total == 1 and not busy.exists()    # 끝나면 표시를 치운다
    busy.write_text("999999 100.0", encoding="utf-8")                   # 끝내지 못하고 죽은 감시가 남긴 오래된 표시
    assert guard.claim(busy, lambda: 5000.0) is True


def test_a_jarvis_restarted_after_a_counterattack_stays_on_guard():
    st = guard.State(countered=[1000.0])
    assert guard.recently_countered(st, 1000.0 + 60) and not guard.recently_countered(st, 1000.0 + guard.ARM_WINDOW + 1)
    assert guard.recently_countered(guard.State(defended=[1000.0]), 1100.0)
    assert not guard.recently_countered(guard.State(), 1000.0)


def test_ultron_that_cannot_be_stopped_is_left_alone_and_jarvis_stays_off(tmp_path):
    out, launched, _, _ = run_watch(tmp_path, result="denied")
    assert out == "denied" and launched == []


def test_ultron_already_gone_just_comes_back(tmp_path):
    out, launched, _, _ = run_watch(tmp_path, result="gone")
    assert out == "gone" and launched == [["--no-mic", "--revived", "other", "--revive-count", "0"]]


def test_normal_quit_is_left_alone(tmp_path):
    out, launched, attacks, _ = run_watch(tmp_path, clean=True)
    assert out == "clean" and launched == [] and attacks == []


def test_crash_comes_back_and_a_crash_loop_gives_up(tmp_path):
    out, launched, _, _ = run_watch(tmp_path, ultron=False)
    assert out == "revived" and launched == [["--no-mic", "--revived", "other", "--revive-count", "0"]]
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

    def counterattack(launch, quick):
        launch("counter")
        return "countered"

    t = threading.Thread(target=lambda: result.append(guard.watch(
        p.pid, ["--no-mic"], launch=launched.append, killer=lambda: True, counterattack=counterattack,
        stop_file=stop, state_file=state)), daemon=True)
    t.start()
    if clean:
        guard.mark_clean_exit(p.pid, stop)
    p.kill()                                      # psutil.Process.kill — 울트론의 rival.stop 과 같은 방법
    p.wait(10)
    t.join(15)
    assert result == (["clean"] if clean else ["countered"])
    assert launched == ([] if clean else [["--no-mic", "--revived", "counter", "--revive-count", "1"]])


# ---------------------------------------------------------------- 울트론 알아보기 · 돌아온 뒤 한마디
def test_ultron_detection():
    assert guard.ultron_running(lambda: ["메모장", "U.L.T.R.O.N"]) is True
    assert guard.ultron_running(lambda: ["U.L.T.R.O.N 설명서.txt - 메모장"]) is False
    assert guard.ultron_running(lambda: (_ for _ in ()).throw(OSError())) is False


def test_comeback_lines_report_what_the_security_protocol_did():
    rng = random.Random(1)
    first, speak = guard.comeback("주인님", "counter", 1, rng)
    assert speak and "주인님" in first and "울트론" in first and "{" not in first
    again, speak = guard.comeback("주인님", "counter", 2, rng)
    assert speak and "울트론" in again and "{" not in again
    other, speak = guard.comeback("주인님", "other", 0, rng)
    assert speak and "울트론" not in other
    for line in guard.COUNTER_FIRST + guard.COUNTER_AGAIN:                 # 자비스 말투: 하십시오체 존댓말
        assert line.rstrip().endswith(("다.", "요.")), line
