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
