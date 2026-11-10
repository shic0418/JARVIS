"""액티브 모드(전체 화면 HUD) 음성 명령 인식."""
from __future__ import annotations

import pytest

from jarvis.brain import ACTIVE_OFF, ACTIVE_ON, CHAT_ON, HUD_BIG
from jarvis.local_router import normalize


@pytest.mark.parametrize("text", [
    "액티브 모드", "자비스 액티브 모드 켜줘", "액티브 모드로 전환해", "엑티브 모드 가동",
    "액티비 모드 켜", "active mode", "액티브 모드 시작해 줘", "액티브 화면 켜",
])
def test_active_on(text):
    c = normalize(text)
    assert ACTIVE_ON.fullmatch(c) and not ACTIVE_OFF.fullmatch(c)


@pytest.mark.parametrize("text", [
    "액티브 모드 꺼줘", "액티브 모드 해제", "액티브 모드 종료해 줘", "엑티브 모드 끝", "active mode off",
])
def test_active_off(text):
    c = normalize(text)
    assert ACTIVE_OFF.fullmatch(c) and not ACTIVE_ON.fullmatch(c)


@pytest.mark.parametrize("text", ["대화 모드 켜줘", "크게 보기", "메모장 열어줘", "다크 모드 켜줘", "액티브 하게 살자"])
def test_active_not_triggered(text):
    c = normalize(text)
    assert not ACTIVE_ON.fullmatch(c) and not ACTIVE_OFF.fullmatch(c)


def test_other_modes_untouched():
    assert CHAT_ON.fullmatch(normalize("대화 모드 켜줘"))
    assert HUD_BIG.fullmatch(normalize("크게 보기"))
    assert not CHAT_ON.fullmatch(normalize("액티브 모드"))
    assert not HUD_BIG.fullmatch(normalize("액티브 모드"))


# ---------------------------------------------------------------- 실용 기능
from types import SimpleNamespace  # noqa: E402

from jarvis.brain import Brain  # noqa: E402
from jarvis.hud_feed import PROTECTED, display_name, parse_kill_index  # noqa: E402
from jarvis.local_router import LocalRouter  # noqa: E402
from jarvis.tools import _weather_ko  # noqa: E402


@pytest.mark.parametrize("text,n", [
    ("1번 꺼줘", 1), ("자비스 2번 종료해 줘", 2), ("첫 번째 거 꺼줘", 1), ("3번 프로그램 강제 종료", 3),
    ("다섯 번째 거 닫아줘", 5), ("사번 정리해줘", 4),
])
def test_kill_index(text, n):
    assert parse_kill_index(normalize(text)) == n


@pytest.mark.parametrize("text", ["한 번 더", "1번 틀어줘", "6번 꺼줘", "볼륨 꺼줘", "2번 트랙 재생"])
def test_kill_index_not_triggered(text):
    assert parse_kill_index(normalize(text)) is None


def _brain_stub(procs, result=("ok", False)):
    calls = []
    stub = SimpleNamespace(hud_procs=procs, execute=lambda n, a: (calls.append((n, a)) or result))
    return stub, calls


def test_kill_listed_uses_exe_from_list():
    stub, calls = _brain_stub([{"exe": "chrome.exe", "name": "크롬"}, {"exe": "Code.exe", "name": "VS Code"}])
    reply = Brain._kill_listed(stub, 2)
    assert calls == [("end_process", {"name": "Code.exe"})]
    assert "VS Code" in reply


def test_kill_listed_out_of_range_and_refused():
    stub, calls = _brain_stub([{"exe": "chrome.exe", "name": "크롬"}])
    assert "없어요" in Brain._kill_listed(stub, 3) and calls == []
    stub, _ = _brain_stub([{"exe": "chrome.exe", "name": "크롬"}], ("사용자가 실행을 거부했습니다.", True))
    assert "그대로" in Brain._kill_listed(stub, 1)


def test_system_processes_protected():
    for exe in ("explorer.exe", "svchost.exe", "csrss.exe", "dwm.exe", "memcompression"):
        assert exe in PROTECTED
    assert display_name("chrome.exe") == "크롬" and display_name("Foo.exe") == "Foo"


def _route(text):
    calls = []
    r = LocalRouter(lambda n, a: (calls.append((n, a)) or ("ok", False)), lambda: "주인님")
    return r.try_handle(text, fallback=True), calls


@pytest.mark.parametrize("text,secs", [("뽀모도로 시작", 1500), ("포모도로 50분 시작해줘", 3000), ("집중 타이머 켜줘", 1500)])
def test_pomodoro(text, secs):
    _, calls = _route(text)
    assert calls == [("set_timer", {"seconds": secs, "label": "집중 시간 끝"})]


@pytest.mark.parametrize("text", ["타이머 취소", "타이머 다 꺼줘", "알람 취소해"])
def test_cancel_timer(text):
    _, calls = _route(text)
    assert calls == [("cancel_timer", {})]


def test_plain_timer_still_works():
    _, calls = _route("5분 뒤에 알려줘")
    assert calls == [("set_timer", {"seconds": 300, "label": "타이머"})]


@pytest.mark.parametrize("en,ko", [("Clear ", "맑음"), ("Partly cloudy", "구름 조금"), ("Light rain shower", "약한 비"),
                                   ("Overcast", "흐림"), ("맑음", "맑음")])
def test_weather_ko(en, ko):
    assert _weather_ko(en) == ko
