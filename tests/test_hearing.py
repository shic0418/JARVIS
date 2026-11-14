"""받아 적은 글 다듬기 (hearing.py): 뭉개진 호출어 찾기 · 흔한 오표기 바로잡기 · 한글 수 읽기."""
from __future__ import annotations

import pytest

from jarvis import approval, hearing
from jarvis.config import DEFAULTS
from jarvis.local_router import LocalRouter, normalize

W = DEFAULTS["wake_words"]


# ---------------------------------------------------------------- 호출어
@pytest.mark.parametrize("text, rest", [
    ("자비스, 아이유 노래 틀어 줘", "아이유 노래 틀어 줘"),        # 예전에는 '이유 노래 틀어 줘' 로 잘렸다
    ("자비스 볼륨 몇이야", "볼륨 몇이야"),                           # 예전에는 '볼륨 몇이'
    ("자비스 크롬 닫아", "크롬 닫아"),
    ("자비스야 크롬 열어", "크롬 열어"),
    ("자비스 야놀자 열어", "야놀자 열어"),
    ("어 자비스 크롬 열어", "크롬 열어"),                            # 호출어 앞의 군말은 버린다
    ("크롬 열어 줘 자비스", "크롬 열어 줘"),                         # 뒤에 말이 없으면 앞의 말이 명령
    ("야 자비스", ""), ("자비스", ""), ("헤이 자비스야", ""),
    ("쟈비스 날씨 알려 줘", "날씨 알려 줘"),
    ("jarvis open chrome", "open chrome"),
])
def test_strip_wake_leaves_the_command_intact(text, rest):
    assert hearing.strip_wake(text, W) == rest


@pytest.mark.parametrize("text, rest", [
    ("잠비스 크롬 열어줘", "크롬 열어줘"), ("잡비스 그럼 열어줘", "그럼 열어줘"), ("재비스 볼륨 올려", "볼륨 올려"),
    ("자비크롬 열어줘", "크롬 열어줘"), ("잡비 스크롬 열어줘", "크롬 열어줘"), ("미스크롬 열어줘", "크롬 열어줘"),
    ("쟈비쓰 크롬 열어", "크롬 열어"), ("짜비스 날씨", "날씨"),
])
def test_garbled_wake_word_is_still_a_call(text, rest):
    w = hearing.find_wake(text, W)
    assert w is not None and not w.exact
    assert hearing.strip_wake(text, W) == rest


@pytest.mark.parametrize("text", [
    "크롬 열어 줘", "오늘 날씨 어때", "서비스 센터 알려 줘", "버스 시간 알려 줘", "그 비스 뭐야",
    "크롬에서 자비 검색해 줘", "내일 회사비 정산", "차비 얼마야",
])
def test_similar_words_are_not_a_call(text):
    assert hearing.find_wake(text, W) is None


def test_wake_at_start():
    assert hearing.wake_at_start("자비스 크롬 열어", W)
    assert hearing.wake_at_start("어 자비스 크롬 열어", W)
    assert not hearing.wake_at_start("아이언맨에 나오는 자비스를 만들 수 있을까", W)


def test_typed_wake_prefix_keeps_first_syllable():
    assert normalize("자비스 아이유 노래 틀어 줘") == "아이유 노래 틀어"
    assert normalize("자비스야 크롬 열어 줘") == "크롬 열어"
    assert normalize("자비스, 야놀자 열어") == "야놀자 열어"


# ---------------------------------------------------------------- 명령 문장 바로잡기
@pytest.mark.parametrize("heard, fixed", [
    ("유튜브 들어가죠", "유튜브 들어가 줘"),
    ("화면 잠가죠", "화면 잠가 줘"),
    ("네이버에서 맛집 검색해죠", "네이버에서 맛집 검색해 줘"),
    ("타이머 십분 맞춰죠", "타이머 십분 맞춰 줘"),
    ("크롬 열어져", "크롬 열어 줘"),
    ("다음 꼭 틀줘", "다음 곡 틀어 줘"),
    ("다음 꼭 틀 어 줘", "다음 곡 틀어 줘"),
    ("다음콕 틀어줘", "다음 곡 틀어줘"),
    ("크롬 열 어 줘", "크롬 열어 줘"),
    ("창 닫 아", "창 닫아"),
    ("파일 찾줘", "파일 찾아 줘"),
    ("화면 좀 어둡 게 해줘", "화면 좀 어둡게 해줘"),
    ("하면 밝기 50으로 해줘", "화면 밝기 50으로 해줘"),
    ("바탕화 보여줘", "바탕화면 보여줘"),
    ("바탕 하면 보여줘", "바탕화면 보여줘"),
    ("음소가 해줘", "음소거 해줘"),
    ("음속거 해줘", "음소거 해줘"),
    ("크린샷 찍어줘", "스크린샷 찍어줘"),
    ("다운로드드 폴더 열어줘", "다운로드 폴더 열어줘"),
    ("네이버 열죠", "네이버 열어 줘"),
    ("소리 키워져", "소리 키워 줘"),
    ("음소거 해져", "음소거 해 줘"),
    ("다음 꼭 틀 줘", "다음 곡 틀어 줘"),
    ("밝기묘이야", "밝기 몇이야"),
])
def test_repair_fixes_common_mistranscriptions(heard, fixed):
    assert hearing.repair(heard) == fixed


@pytest.mark.parametrize("text", [
    "오늘 날씨 좋죠", "맞죠", "그렇죠", "가시죠", "한번 보죠",        # 진짜 '-죠' 로 끝나는 말
    "물줘", "물 좀 줘",                                              # '물' 은 동사 줄기가 아니다
    "타이어 검색해 줘", "타이밍 알려 줘",                             # '타이머' 로 바꾸지 않는다
    "스크린샷을 찍어 줘", "다운로드한 파일 열어 줘",                  # 조사 · 어미가 붙은 말은 그대로
    "하면 된다", "다음 폭탄 영상 틀어 줘", "바탕화면으로", "크롬 열어 줘", "볼륨 30으로 해 줘",
    "우산 가져", "국민 체조", "가열죠", "물 줘",
])
def test_repair_leaves_ordinary_sentences_alone(text):
    assert hearing.repair(text) == text


# ---------------------------------------------------------------- 한글 수
@pytest.mark.parametrize("heard, fixed", [
    ("볼륨 삼십으로", "볼륨 30으로"),
    ("볼륨3십으로 해줘", "볼륨30으로 해줘"),
    ("화면 밝기5십으로", "화면 밝기50으로"),
    ("밝기 오십", "밝기 50"),
    ("볼륨 백으로", "볼륨 100으로"),
    ("십분 맞춰", "10분 맞춰"),
    ("오분 알려", "5분 알려"),
    ("타이머 십 분 맞춰", "타이머 10 분 맞춰"),
    ("이십오 분 타이머", "25 분 타이머"),
    ("2십5분", "25분"),
    ("삼 분 삼십 초", "3 분 30 초"),
    ("한 시간 뒤에 알려", "1시간 뒤에 알려"),
    ("두 시간 반 뒤에 알려", "2시간 30분 뒤에 알려"),
    ("볼륨 30으로", "볼륨 30으로"),
    ("5분 뒤에", "5분 뒤에"),
    ("십25분", "십25분"),
    ("크롬 열어", "크롬 열어"),
])
def test_digits(heard, fixed):
    assert hearing.digits(heard) == fixed


# ---------------------------------------------------------------- 명령 처리기까지 이어서
class Exec:
    def __init__(self):
        self.calls = []

    def __call__(self, name, args):
        self.calls.append((name, args))
        if name == "volume":
            return ("현재 볼륨 40%" if args.get("action") == "get" else "볼륨 50% → 40%", False)
        if name == "brightness":
            return ("밝기 50% → 30%", False)
        return ("ok", False)


def run(text):
    ex = Exec()
    reply = LocalRouter(ex, lambda: "주인님").try_handle(text, fallback=True)
    return reply, ex.calls


@pytest.mark.parametrize("heard, call", [
    ("볼륨 삼십으로 해 줘", ("volume", {"action": "set", "level": 30})),
    ("볼륨3십으로 해줘", ("volume", {"action": "set", "level": 30})),
    ("소리 오십 프로로 맞춰 줘", ("volume", {"action": "set", "level": 50})),
    ("화면 밝기5십으로 해줘", ("brightness", {"action": "set", "level": 50})),
    ("볼륨 몇 이야", ("volume", {"action": "get"})),
    ("타이머 십 분 맞춰 줘", ("set_timer", {"seconds": 600, "label": "타이머"})),
    ("오분 알려줘", ("set_timer", {"seconds": 300, "label": "타이머"})),
    ("한 시간 뒤에 알려 줘", ("set_timer", {"seconds": 3600, "label": "타이머"})),
    ("두 시간 반 뒤에 알려 줘", ("set_timer", {"seconds": 9000, "label": "타이머"})),
    ("뽀모도로 이십 분", ("set_timer", {"seconds": 1200, "label": "집중 시간 끝"})),
    ("유튜브 들어가죠", ("open_url", {"url": "https://www.youtube.com"})),
    ("다음 꼭 틀줘", ("media_control", {"action": "next"})),
    ("음소가 해줘", ("volume", {"action": "mute"})),
    ("화면 잠가죠", ("power", {"action": "lock"})),
    ("바탕화 보여줘", ("window_action", {"action": "show_desktop"})),
    ("좀 어둡게 해줘", ("brightness", {"action": "down", "level": 20})),
    ("많이 밝게 해 줘", ("brightness", {"action": "up", "level": 30})),
    ("하면 밝기 50으로 해줘", ("brightness", {"action": "set", "level": 50})),
    ("네이버 열죠", ("open_url", {"url": "https://www.naver.com"})),
    ("소리 키워져", ("volume", {"action": "up", "level": 10})),
    ("다음 꼭 틀 줘", ("media_control", {"action": "next"})),
    ("타이머십 분 맞춰죠", ("set_timer", {"seconds": 600, "label": "타이머"})),
    ("잠가 줘", ("power", {"action": "lock"})),
    ("화면 캡쳐 해줘", ("save_screenshot", {})),
    ("기터브 열어줘", ("open_url", {"url": "https://github.com"})),
    ("밝기묘이야", ("brightness", {"action": "get"})),
    # 같은 글자가 한 번 더 적힌 것 — 못 알아들었을 때만 줄여서 다시 본다
    ("볼륨 올려려줘", ("volume", {"action": "up", "level": 10})),
    ("음악악 멈춰져", ("media_control", {"action": "play_pause"})),
])
def test_misheard_commands_reach_the_right_tool(heard, call):
    reply, calls = run(heard)
    assert reply is not None and calls[0] == call


def test_doubled_syllables_are_only_collapsed_as_a_last_resort():
    _reply, calls = run("유튜브에서 코코 노래 틀어 줘")              # 원래 알아듣는 문장은 건드리지 않는다
    assert calls == [("play_youtube", {"query": "코코 노래"})]
    _reply, calls = run("구글에서 뽀뽀뽀 검색해 줘")
    assert calls == [("browser_search", {"query": "뽀뽀뽀", "site": "google"})]


def test_numbers_are_only_read_inside_level_and_timer_commands():
    _reply, calls = run("구글에서 십분 발휘 검색해 줘")            # 검색어 속의 '십분' 은 그대로
    assert calls == [("browser_search", {"query": "십분 발휘", "site": "google"})]
    _reply, calls = run("유튜브에서 오 분 명상 틀어 줘")
    assert calls == [("play_youtube", {"query": "오 분 명상"})]
    assert run("이 분 누구야") == (None, [])


def test_repair_does_not_turn_other_words_into_approval():
    assert approval.answer("실행해죠") is True              # '실행해 줘' 를 인식기가 다르게 적은 것
    assert approval.answer("네 해죠") is True
    assert approval.answer("그렇게 하죠") is None            # 승인 표현으로 보지 않는다 — 카드는 그대로
    assert approval.answer("취소해죠") is False
    assert approval.answer("잘 모르겠죠") is None


# ---------------------------------------------------------------- 호출어가 끝나는 시각
def test_wake_end_time_from_token_timestamps():
    tokens = ["자", "비", "스", " 줄", "여", "줘"]
    stamps = [0.70, 0.85, 1.00, 1.92, 2.04, 2.22]
    assert hearing.wake_end_time(tokens, stamps, W) == pytest.approx(1.22)        # 뒤가 비어 있으면 마지막 글자 + 0.22초
    quick = ["자", "비", "스", " 크", "롬"]
    assert hearing.wake_end_time(quick, [0.5, 0.65, 0.8, 0.95, 1.1], W) == pytest.approx(0.89)   # 바로 이어 말함
    garbled = ["잠", "비", "스", " 크", "롬"]
    assert hearing.wake_end_time(garbled, [0.5, 0.65, 0.8, 1.4, 1.6], W) == pytest.approx(1.02)
    assert hearing.wake_end_time(["크", "롬", " 열어"], [0.5, 0.7, 0.9], W) is None             # 호출어 없음
    assert hearing.wake_end_time([" 크", "롬", " 열어", "줘", " 자", "비", "스"],
                                 [0.1, 0.2, 0.4, 0.6, 1.2, 1.3, 1.4], W) is None             # 호출어가 맨 앞이 아님
    assert hearing.wake_end_time(tokens, stamps[:-1], W) is None                               # 시각 정보가 맞지 않음
    assert hearing.wake_end_time([], [], W) is None


# ---------------------------------------------------------------- 승인 카드에 대한 음성 대답
@pytest.mark.parametrize("text, verdict", [
    ("네", True), ("승인", True), ("응 실행해 줘", True), ("네 승인합니다", True), ("자비스, 승인해 줘", True),
    ("취소", False), ("아니", False), ("하지 마", False), ("아니 실행하지 마", False),
    ("그게 뭔지 잘 모르겠네", None), ("예약 확인해 봐", None), ("오늘 날씨 어때", None), ("", None),
])
def test_approval_needs_a_short_whole_answer(text, verdict):
    assert approval.answer(text) is verdict
