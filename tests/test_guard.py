"""자기 보호 (guard.py): 울트론이 찾지 못하는 창 제목 · 강제 종료되면 다시 켜기 · 정상 종료는 그대로."""
from __future__ import annotations

import re
import subprocess
import sys
import threading
from pathlib import Path

import pytest

from jarvis import guard

ROOT = Path(__file__).resolve().parent.parent

# 울트론(Ultron-main/jarvis/rival.py)이 자비스를 찾는 기준을 그대로 옮긴 것
ULTRON_TARGET_TITLES = frozenset({"J.A.R.V.I.S", "J.A.R.V.I.S ACTIVE", "J.A.R.V.I.S CHAT"})
PY_NAMES = frozenset({"python.exe", "pythonw.exe", "py.exe", "pyw.exe", "python3.exe", "python", "python3"})


def ultron_sees_jarvis(title: str, proc_name: str) -> bool:
    name = (proc_name or "").lower()
    return (title or "").strip() in ULTRON_TARGET_TITLES and (name in PY_NAMES or "jarvis" in name)


def qml_titles() -> list[str]:
    out = []
    for f in ("Main.qml", "ActiveMode.qml"):
        # 창 제목만 (패널 머리글의 title 속성은 빼고)
        out += re.findall(r'^\s*title:\s*"(J\.A\.R[^"]*)"', (ROOT / "ui" / f).read_text(encoding="utf-8"), re.M)
    return out


# ---------------------------------------------------------------- 1) 울트론이 찾지 못한다
def test_window_titles_are_not_what_ultron_looks_for():
    for t in guard.WINDOW_TITLES.values():
        assert not ultron_sees_jarvis(t, "pythonw.exe"), t
    assert ultron_sees_jarvis("J.A.R.V.I.S", "pythonw.exe")          # 예전 제목이었다면 찾혔다


def test_qml_windows_use_the_guarded_titles():
    titles = qml_titles()
    assert sorted(titles) == sorted(guard.WINDOW_TITLES.values())
    assert not any(ultron_sees_jarvis(t, "python.exe") for t in titles)


# ---------------------------------------------------------------- 2) 되살리기 규칙
def test_clean_exit_mark_is_per_process_and_read_once(tmp_path):
    f = tmp_path / "stop"
    guard.mark_clean_exit(1234, f)
    assert guard.was_clean_exit(1234, f) is True
    assert guard.was_clean_exit(1234, f) is False                     # 한 번 읽으면 지운다
    guard.mark_clean_exit(1111, f)
    assert guard.was_clean_exit(2222, f) is False                     # 다른 자비스가 남긴 표시
    assert not f.exists()


def test_revive_limit_within_the_window():
    ok, h = guard.allow_revive(1000.0, [])
    assert ok and h == [1000.0]
    ok, h = guard.allow_revive(1010.0, [800.0, 1000.0, 1005.0])       # 800 은 2분이 지나 세지 않는다
    assert ok and h == [1000.0, 1005.0, 1010.0]
    ok, h = guard.allow_revive(1010.0, [950.0, 1000.0, 1005.0])       # 2분 안에 이미 3번
    assert not ok and h == [950.0, 1000.0, 1005.0]
    ok, h = guard.allow_revive(1200.0, [950.0, 1000.0, 1005.0])       # 오래된 기록은 세지 않는다
    assert ok and h == [1200.0]


def test_relaunch_args_keep_options_and_mark_revived():
    assert guard.relaunch_args(["--no-mic"]) == ["--no-mic", "--revived"]
    assert guard.relaunch_args(["--revived", "--no-greet", "--no-mic"]) == ["--no-mic", "--revived"]
    assert guard.relaunch_args([]) == ["--revived"]


def run_watch(tmp_path, clean: bool, history=()):
    stop, state = tmp_path / "stop", tmp_path / "state.json"
    if history:
        guard._save_history(list(history), state)
    launched = []

    def wait(pid):
        if clean:
            guard.mark_clean_exit(pid, stop)

    out = guard.watch(42, ["--no-mic"], wait=wait, launch=launched.append, clock=lambda: 5000.0,
                      stop_file=stop, state_file=state)
    return out, launched, guard._load_history(state)


def test_forced_kill_is_revived(tmp_path):
    out, launched, hist = run_watch(tmp_path, clean=False)
    assert out == "revived" and launched == [["--no-mic"]] and hist == [5000.0]


def test_normal_quit_is_left_alone(tmp_path):
    out, launched, _ = run_watch(tmp_path, clean=True)
    assert out == "clean" and launched == []


def test_gives_up_when_it_keeps_dying(tmp_path):
    out, launched, _ = run_watch(tmp_path, clean=False, history=(4950.0, 4970.0, 4990.0))
    assert out == "gave_up" and launched == []


def test_guard_command_line():
    assert guard.main(["--pid", "x"]) == 2
    assert guard.main([]) == 2


# ---------------------------------------------------------------- 진짜 프로세스로
def _sleeper() -> subprocess.Popen:
    return subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])


@pytest.mark.parametrize("clean", [False, True])
def test_real_process_kill_and_clean_exit(tmp_path, clean):
    p = _sleeper()
    stop, state = tmp_path / "stop", tmp_path / "state.json"
    launched, result = [], []
    t = threading.Thread(target=lambda: result.append(guard.watch(
        p.pid, ["--no-mic"], launch=launched.append, stop_file=stop, state_file=state)), daemon=True)
    t.start()
    if clean:
        guard.mark_clean_exit(p.pid, stop)        # 정상 종료: 표시를 남기고 끝난다
    p.kill()                                      # 울트론이 하는 것처럼 강제로 끈다
    p.wait(10)
    t.join(15)
    assert result == (["clean"] if clean else ["revived"])
    assert launched == ([] if clean else [["--no-mic"]])


# ---------------------------------------------------------------- 되살아난 뒤 한마디
def test_ultron_detection_and_line():
    assert guard.ultron_running(lambda: ["메모장", "U.L.T.R.O.N"]) is True
    assert guard.ultron_running(lambda: ["U.L.T.R.O.N 설명서.txt - 메모장"]) is False
    assert guard.ultron_running(lambda: (_ for _ in ()).throw(OSError())) is False
    assert "울트론" in guard.revived_line("주인님", True)
    assert "울트론" not in guard.revived_line("주인님", False)
