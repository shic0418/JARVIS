"""로컬 명령 처리기 회귀 테스트 — 실제 PC 도구는 부르지 않고 '어떤 도구를 어떤 인자로 부르는지'만 본다."""
from __future__ import annotations

import pytest

from jarvis.local_router import LocalRouter, normalize, parse_duration


class Fake:
    """도구 실행기 가짜: 호출을 기록하고 미리 정한 결과를 돌려준다."""

    def __init__(self, results: dict | None = None) -> None:
        self.calls: list[tuple[str, dict]] = []
        self.results = results or {}

    def __call__(self, name: str, args: dict):
        self.calls.append((name, args))
        return self.results.get(name, ("ok", False))


def route(text: str, results: dict | None = None, fallback: bool = True):
    fake = Fake(results)
    r = LocalRouter(fake, lambda: "주인님")
    return r.try_handle(text, fallback=fallback), fake.calls


# (말, 기대 도구, 기대 인자 일부)
TOOL_CASES = [
    ("메모장 열어줘", "open_app", {"name": "메모장"}),
    ("자비스 크롬 켜", "open_app", {"name": "크롬"}),
    ("카톡 닫아줘", "close_app", {"name": "카톡"}),
    ("볼륨 30으로", "volume", {"action": "set", "level": 30}),
    ("소리 키워줘", "volume", {"action": "up", "level": 10}),
    ("소리 많이 줄여", "volume", {"action": "down", "level": 20}),
    ("음소거", "volume", {"action": "mute"}),
    ("음소거 해제", "volume", {"action": "unmute"}),
    ("볼륨 몇이야", "volume", {"action": "get"}),
    ("다음 곡", "media_control", {"action": "next"}),
    ("이전 곡", "media_control", {"action": "previous"}),
    ("노래 일시정지", "media_control", {"action": "play_pause"}),
    ("유튜브에서 아이유 밤편지 틀어줘", "play_youtube", {"query": "아이유 밤편지"}),
    ("아이유 노래 틀어줘", "play_youtube", {"query": "아이유 노래"}),
    ("네이버에서 맛집 검색", "browser_search", {"query": "맛집", "site": "naver"}),
    ("날씨 어때", "get_weather", {}),
    ("부산 날씨", "get_weather", {"location": "부산"}),
    ("5분 뒤에 알려줘", "set_timer", {"seconds": 300}),
    ("타이머 1시간 30분", "set_timer", {"seconds": 5400}),
    ("다운로드 폴더 열어줘", "open_folder", {"target": "다운로드"}),
    ("바탕화면 보여줘", "window_action", {"action": "show_desktop"}),
    ("화면 잠가줘", "power", {"action": "lock"}),
    ("스크린샷 찍어줘", "save_screenshot", {}),
    ("컴퓨터 상태 어때", "system_status", {}),
    ("화면 밝기 50으로", "brightness", {"action": "set", "level": 50}),
    ("화면 밝기 낮춰줘", "brightness", {"action": "down"}),
    ("화면 좀 밝게 해줘", "brightness", {"action": "up"}),
    # 오프라인 음성 인식(SenseVoice) 표기
    ("카카오톡 열어져", "open_app", {"name": "카카오톡"}),
    ("다운로드 폴더 열어 죠", "open_folder", {"target": "다운로드"}),
    ("다음 꼭 틀어 줘", "media_control", {"action": "next"}),
    ("볼륨 30으로 해줘", "volume", {"action": "set", "level": 30}),
    ("5분 뒤에 알려줘", "set_timer", {"seconds": 300}),
]


@pytest.mark.parametrize("text,tool,args", TOOL_CASES)
def test_tool_routing(text, tool, args):
    reply, calls = route(text)
    assert reply, f"{text!r} 가 로컬에서 처리되지 않음"
    assert calls, f"{text!r} 가 도구를 부르지 않음"
    name, got = calls[0]
    assert name == tool
    for k, v in args.items():
        assert got.get(k) == v, f"{text!r}: {k}={got.get(k)!r}, 기대 {v!r}"


@pytest.mark.parametrize("text", ["몇 시야", "오늘 며칠이야", "고마워", "안녕"])
def test_no_tool_replies(text):
    reply, calls = route(text)
    assert reply and not calls


# Claude 에게 넘겨야 하는 말 (로컬에서 잘못 실행하면 안 됨)
@pytest.mark.parametrize("text", [
    "메모장 열고 오늘 할 일 목록 써줘",
    "내일 서울 날씨 어때",
    "양자역학이 뭐야",
    "구글 클래스룸에서 경제 탭에 들어가 줘",
    "지금 화면에 있는 에러가 뭐야",
    "컴퓨터 꺼줘",
    "내일 며칠이야",
])
def test_goes_to_claude(text):
    reply, calls = route(text)
    assert reply is None, f"{text!r} 는 Claude 로 가야 함 (로컬 답: {reply!r}, 호출 {calls})"
    assert not calls


def test_open_app_failure_falls_back_to_claude():
    reply, _ = route("rdworks 열어줘", {"open_app": ("앱을 찾지 못했습니다", True)})
    assert reply is None


def test_open_app_failure_without_fallback_reports():
    reply, _ = route("rdworks 열어줘", {"open_app": ("앱을 찾지 못했습니다", True)}, fallback=False)
    assert reply == "앱을 찾지 못했습니다"


def test_close_app_not_open():
    reply, _ = route("메모장 닫아", {"close_app": ("메모장: 열린 창이 없습니다", True)})
    assert reply == "열려 있는 메모장 창이 없습니다."


def test_normalize():
    assert normalize("자비스, 메모장 좀 열어 줘요.") == "메모장 좀 열어" or normalize("자비스, 메모장 좀 열어 줘요.") == "메모장 열어"
    assert normalize("볼륨 30으로 해 주세요!") == "볼륨 30으로"


def test_parse_duration():
    assert parse_duration("1시간 30분 10초") == 5410
    assert parse_duration("없음") == 0


def test_volume_speech():
    reply, _ = route("볼륨 30", {"volume": ("볼륨 70% → 30%", False)})
    assert reply == "볼륨을 30퍼센트로 맞췄습니다."
