"""data/jarvis.log 와 Claude 대화 기록에서 실패했던 말들의 회귀 테스트 (2026-11-09 기록 기준)."""
from __future__ import annotations

import pytest

from jarvis.brain import CHAT_OFF, CHAT_ON
from jarvis.local_ai import to_command
from jarvis.local_router import LocalRouter, dedupe, normalize
from jarvis.speech import split_sentences


class Fake:
    def __init__(self, results: dict | None = None) -> None:
        self.calls: list[tuple[str, dict]] = []
        self.results = results or {}

    def __call__(self, name: str, args: dict):
        self.calls.append((name, args))
        r = self.results.get(name)
        if callable(r):
            return r(args)
        if r is not None:
            return r
        if name == "volume":
            return ("볼륨 50% → 40%", False)
        if name == "brightness":
            return ("밝기 50% → 30%", False)
        return ("ok", False)


def router(results=None, chat=False):
    fake = Fake(results)
    r = LocalRouter(fake, lambda: "주인님")
    r.chat = chat
    return r, fake


# ---- 음성 인식이 같은 말을 두 번 적음 ----
@pytest.mark.parametrize("text,out", [
    ("카카오톡 열어 줘 카카오톡 열어 줘", "카카오톡 열어 줘"),
    ("클로드 열어 줘   클로드 열어 줘", "클로드 열어 줘"),
    ("클래스룸 열어 줘   구글 클래스룸 열어 줘", "구글 클래스룸 열어 줘"),
    ("유튜브 틀어 줘 우리 학교에서", "유튜브 틀어 줘 우리 학교에서"),     # 반복이 아니면 그대로
    ("메모장 열어   볼륨 30으로", "메모장 열어   볼륨 30으로"),           # 다른 말 두 개는 그대로
])
def test_dedupe(text, out):
    assert dedupe(text) == out


# ---- 사이트 이름 (매번 Claude 로 넘어가 3~8초 걸리던 것) ----
@pytest.mark.parametrize("text,url", [
    ("핀터레스트 들어가줘", "https://www.pinterest.com"),
    ("ebs 들어가줘", "https://www.ebs.co.kr"),
    ("리로스쿨", "https://riroschool.kr"),
    ("구글 클래스룸 열어줘", "https://classroom.google.com"),
    ("클래스룸 열어 줘   구글 클래스룸 열어 줘", "https://classroom.google.com"),
    ("유튜브 홈화면", "https://www.youtube.com"),
    ("유튜브 기본화면 열어줘", "https://www.youtube.com"),
    ("제미나이 들어가 줘", "https://gemini.google.com"),
])
def test_sites(text, url):
    r, fake = router()
    assert r.try_handle(text)
    assert fake.calls == [("open_url", {"url": url})]


def test_claude_app_first_then_site():
    r, fake = router({"open_app": ("'Claude' 실행함", False)})
    assert r.try_handle("클로드 열어") == "클로드를 열었습니다."
    assert fake.calls[0] == ("open_app", {"name": "클로드"})
    r, fake = router({"open_app": ("못 찾음", True)})
    assert r.try_handle("클로드 열어")
    assert fake.calls[-1] == ("open_url", {"url": "https://claude.ai"})


@pytest.mark.parametrize("text", ["잉크스페이스", "inkspace", "rdworks"])
def test_bare_app_name(text):
    r, fake = router()
    assert r.try_handle(text)
    assert fake.calls == [("open_app", {"name": text, "min_score": 70})]


@pytest.mark.parametrize("text", ["다음", "숲", "포스 인에 접속해 줘", "구글 클래스룸에서 경제 탭에 들어가 줘", "왜"])
def test_not_sites(text):
    r, fake = router({"open_app": ("못 찾음", True)})
    assert r.try_handle(text) is None
    assert all(n != "open_url" for n, _ in fake.calls)


# ---- 직전 조절 이어서 / 바로잡기 ----
def test_more_after_brightness():
    r, fake = router()
    r.try_handle("화면이 너무 밝아")
    assert r.try_handle("더 줄ㅇ져ㅝ")             # 기록: 키보드 오타 그대로
    assert fake.calls[-1] == ("brightness", {"action": "down", "level": 20})
    r.try_handle("조금 더")
    assert fake.calls[-1] == ("brightness", {"action": "down", "level": 20})


def test_more_needs_recent_adjust():
    r, fake = router()
    assert r.try_handle("더 줄여줘") is None and not fake.calls


def test_volume_then_correct_to_brightness():
    r, fake = router()
    r.try_handle("소리 줄여")
    reply = r.try_handle("볼륨 말고 밝기")
    assert fake.calls[-2:] == [("volume", {"action": "up", "level": 10}),
                               ("brightness", {"action": "down", "level": 20})]
    assert "되돌렸" in reply


def test_correction_without_history_goes_to_claude():
    r, fake = router()
    assert r.try_handle("볼륨 말고 밝기") is None and not fake.calls


# ---- 파일 열기 (기록: 로컬 AI 가 파일 이름을 앱으로 실행하려 함, Claude 는 열기 창에 경로를 타이핑하다 실패) ----
PATH = r"C:\Users\user\Desktop\주술회전 주사위.rld"


def test_open_file_in_app():
    r, fake = router({"find_files": (PATH, False)})
    assert r.try_handle("rdworks에서 주술회전 주사위.rld 파일을 열어줘")
    assert fake.calls == [("find_files", {"query": "주술회전 주사위.rld"}),
                          ("open_path", {"path": PATH, "app": "rdworks"})]


def test_open_file_many_hits_goes_to_claude():
    r, fake = router({"find_files": (PATH + "\n" + PATH.replace(".rld", " (2).rld"), False)})
    assert r.try_handle("주술회전 주사위 파일 열어") is None


def test_local_ai_never_opens_file_as_app():
    o = {"intent": "open_app", "target": "주술회전 주사위", "number": 0}
    assert to_command(o, "rdworks에서 주술회전 주사위.rld 파일을 열어") is None
    o = {"intent": "open_folder", "target": "주술회전 주사위", "number": 0}
    assert to_command(o, "주술회전 주사위.rld 파일을 여기에서 열어") is None


# ---- 자유 대화 모드 ----
@pytest.mark.parametrize("text", ["대화 모드 켜줘", "자유 대화 모드", "대화 모드 시작", "우리 얘기 좀 하자",
                                  "나랑 수다 떨자", "심심한데 이야기하자", "대화하자"])
def test_chat_on(text):
    assert CHAT_ON.fullmatch(normalize(text))


@pytest.mark.parametrize("text", ["대화 모드 꺼줘", "대화 끝", "이제 그만 얘기하자", "잘 자", "대화 모드 끝"])
def test_chat_off(text):
    assert CHAT_OFF.fullmatch(normalize(text))


@pytest.mark.parametrize("text", ["메모장 열어줘", "오늘 대화 내용 정리해줘", "얘기 좀 해 줘 봐 그 영화"])
def test_chat_switch_not_triggered(text):
    c = normalize(text)
    assert not CHAT_ON.fullmatch(c) and not CHAT_OFF.fullmatch(c)


def test_chat_mode_skips_canned_replies():
    r, _ = router(chat=True)
    assert r.try_handle("안녕") is None          # 대화 모드에서는 AI 가 자연스럽게 받는다
    assert r.try_handle("고마워") is None
    r, _ = router(chat=True)
    assert r.try_handle("볼륨 30으로")             # 분명한 명령은 대화 중에도 바로 처리


# ---- 답을 문장 단위로 끊어 바로 읽기 ----
def test_split_sentences_streaming():
    buf, spoken = "", []
    for piece in ["안녕", "하세요! 오늘", " 기온은 3.", "5도예요. 산책", "하기 좋겠네요"]:
        out, buf = split_sentences(buf + piece)
        spoken += out
    out, buf = split_sentences(buf, final=True)
    spoken += out
    assert spoken == ["안녕하세요! 오늘 기온은 3.5도예요.", "산책하기 좋겠네요"] or \
        spoken == ["안녕하세요!", "오늘 기온은 3.5도예요.", "산책하기 좋겠네요"]
    assert buf == ""
    assert "".join(spoken).replace(" ", "") == "안녕하세요!오늘기온은3.5도예요.산책하기좋겠네요"


def test_split_sentences_merges_tiny():
    out, rest = split_sentences("네. 알겠습니다. 바로 할게요 ")
    assert out and all(len(o) >= 8 for o in out)
