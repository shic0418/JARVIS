"""로컬 AI 출력 → 표준 명령 변환 테스트 (모델 없이, 모델이 낸 JSON 을 가정)."""
from __future__ import annotations

import pytest

from jarvis.local_ai import to_command


def o(intent, target="", number=0):
    return {"intent": intent, "target": target, "number": number}


@pytest.mark.parametrize("text,out,cmd", [
    ("좀 시끄럽네", o("volume_down"), "볼륨 내려"),
    ("좀 시끄럽네", o("volume_up"), "볼륨 내려"),          # 방향은 말 속 단서가 우선
    ("TV 소리 때문에 잘 안 들려", o("volume_down"), "볼륨 올려"),
    ("소리 반으로 해", o("volume_set", number=50), "볼륨 50"),
    ("소리 70 정도로", o("volume_set", number=70), "볼륨 70"),
    ("소리 좀 그렇게", o("volume_set", number=70), None),   # 숫자를 지어냄
    ("크롬 좀 띄워 줄래", o("open_app", "크롬"), "크롬 열어"),
    ("인터넷 좀 띄워 줄래", o("open_app", "크롬"), None),   # 말에 없는 앱 이름
    ("뉴진스 하입보이 듣고 싶어", o("youtube", "뉴진스 하입보이"), "유튜브에서 뉴진스 하입보이 틀어"),
    ("김치찌개 끓이는 법 네이버에 찾아봐", o("search_google", "김치찌개 끓이는 법"), "네이버에서 김치찌개 끓이는 법 검색"),
    ("다운받은 거 모아둔 데 열어", o("open_folder", "다운로드"), "다운로드 폴더 열어"),
    ("부산은 지금 비 와?", o("weather", "부산"), "부산 날씨"),
    ("내일 부산 비 와?", o("weather", "부산"), None),
    ("라면 3분 재야 돼", o("timer", "3분"), "3분 뒤에 알려"),
    ("계란 7분 삶을 거야", o("timer", "5분"), None),          # 시간을 바꿔 말함
    ("양자역학이 뭐야", o("claude"), None),
    ("화면이 너무 밝아", o("brightness_down"), "화면 밝기 낮춰"),
    ("눈부셔", o("brightness_down"), "화면 밝기 낮춰"),
    ("화면이 너무 어두워", o("brightness_up"), "화면 밝기 올려"),
])
def test_to_command(text, out, cmd):
    assert to_command(out, text) == cmd
