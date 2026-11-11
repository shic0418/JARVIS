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
from jarvis.hud_feed import PROTECTED, display_name  # noqa: E402
from jarvis.local_router import LocalRouter  # noqa: E402
from jarvis.tools import _weather_ko  # noqa: E402


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
