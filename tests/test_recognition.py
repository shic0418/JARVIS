"""발음이 뭉개진 말·인식 후보 고르기·주인 목소리 판별 회귀 테스트 (2026-11-10 기록 기준)."""
from __future__ import annotations

import numpy as np
import pytest

import jarvis.brain as bm
from jarvis.config import DEFAULTS
from jarvis.local_router import LocalRouter, find_site, normalize
from jarvis.voiceid import SpeakerGate, Voice


class Cfg(dict):
    def __getitem__(self, k):
        return self.get(k, DEFAULTS.get(k))

    def api_key(self):
        return ""


class Tools:
    """설치된 앱은 크롬·카카오톡뿐, 열린 창은 메모장뿐이라고 가정."""

    def _find_app(self, name, min_score=38):
        return ("Chrome", "id") if name in ("크롬", "카카오톡", "카톡") else None

    def _match_windows(self, name):
        return [{"hwnd": 1}] if name == "메모장" else []

    def schemas(self):
        return []


def brain():
    b = bm.Brain(Cfg(), Tools(), on_action=lambda *a: None, context_fn=lambda: "")
    return b


# ---- 대화 모드: 뭉개진 발음 ----
@pytest.mark.parametrize("text", ["대모 켜 줘", "태화 모드 켜 줘", "데화 모드 시작", "대화 모드 켜줘", "자유 대화 모드로 전환"])
def test_chat_on_fuzzy(text):
    assert bm.CHAT_ON.fullmatch(normalize(text))


@pytest.mark.parametrize("text", ["대모 꺼 줘", "태화 모드 끝", "대화 모드 끝"])
def test_chat_off_fuzzy(text):
    assert bm.CHAT_OFF.fullmatch(normalize(text))


@pytest.mark.parametrize("text", ["다크 모드 켜 줘", "대표 켜 줘", "모드 켜 줘", "게임 모드 켜"])
def test_chat_not_triggered(text):
    assert not bm.CHAT_ON.fullmatch(normalize(text))


def test_chat_off_when_already_off_is_local():
    b = brain()
    assert b._mode_switch("대화 모드 끝") == "대화 모드는 이미 꺼져 있어요."
    assert not b.chat_mode


# ---- HUD 보기 방식 ----
@pytest.mark.parametrize("text,action", [
    ("작게 보기 모드", "small"), ("작게 보기로 바꿔 줘", "small"), ("축소 모드", "small"),
    ("크게 보기", "big"), ("전체 보기로 해 줘", "big"), ("자비스 숨겨", "hide"),
])
def test_hud_commands(text, action):
    b = brain()
    got = []
    b.on_hud = got.append
    assert b._hud_command(text)
    assert got == [action]


@pytest.mark.parametrize("text", ["소리 작게", "작게", "크게 틀어 줘", "화면 크게 보여 줘 사진"])
def test_not_hud(text):
    b = brain()
    assert b._hud_command(text) is None


# ---- 인식 후보 고르기 ----
@pytest.mark.parametrize("text,ok", [
    ("대화 모드 켜 줘", True), ("대모 켜 줘", True),
    ("크롬 열어 줘", True), ("대모 열어 줘", False),          # 없는 앱 이름은 명령으로 치지 않음
    ("메모장 닫아 줘", True), ("엑셀 닫아 줘", False),          # 열린 창이 없으면 아님
    ("핀터레스트 들어가 줘", True), ("볼륨 30으로", True), ("작게 보기 모드", True),
    ("너는 어떻게 생각해", False), ("주사위 파일 열어 줘", False),
])
def test_recognizes(text, ok):
    assert brain().recognizes(text) is ok


def test_recognizes_does_not_execute():
    b = brain()
    ran = []
    b.execute = lambda n, a, c=None: ran.append(n) or ("ok", False)
    b.recognizes("볼륨 30으로")
    assert not ran


# ---- 사이트 이름이 조금 틀려도 ----
@pytest.mark.parametrize("text,label", [("핀터레스", "핀터레스트"), ("나무이키", "나무위키"), ("구글 클래스롬", "구글 클래스룸")])
def test_fuzzy_site(text, label):
    hit = find_site(text)
    assert hit and hit[0] == label


@pytest.mark.parametrize("text", ["보스인", "다음", "포스 인"])
def test_fuzzy_site_no_false_hit(text):
    assert find_site(text) is None


# ---- 주인 목소리: 같은 대화에서 확인된 목소리와 비슷하면 아슬아슬한 점수도 통과 ----
class VID:
    ready = True


class Profile:
    exists = True

    def __init__(self, scores):
        self.scores = scores

    def score(self, voice):
        return self.scores.pop(0)


def emb(seed, noise=0.0):
    rng = np.random.default_rng(seed)
    v = rng.normal(size=192)
    if noise:
        v = v + np.random.default_rng(seed + 100).normal(size=192) * noise
    return v / np.linalg.norm(v)


def gate(scores):
    return SpeakerGate(VID(), Profile(scores), Cfg(owner_only=True, speaker_lock=True, speaker_threshold=0.40))


def test_owner_borderline_passes_within_conversation():
    g = gate([0.66, 0.37])
    assert g.check(Voice(emb(1), 2.0)).ok                     # 확실한 주인 → 대화 기준에 기억
    assert g.check(Voice(emb(1, 0.3), 1.5)).ok                # 0.37: 기준 미달이지만 방금 그 목소리와 같음


def test_owner_borderline_rejected_without_conversation():
    g = gate([0.37])
    assert not g.check(Voice(emb(1), 1.5)).ok


def test_other_person_still_rejected():
    g = gate([0.66, 0.36])
    g.check(Voice(emb(1), 2.0))
    assert not g.check(Voice(emb(2), 1.5)).ok                  # 점수가 비슷해도 목소리가 다르면 거부


def test_far_below_threshold_rejected():
    g = gate([0.66, 0.20])
    g.check(Voice(emb(1), 2.0))
    assert not g.check(Voice(emb(1), 1.5)).ok


# ---- Google 인식 후보 → 고르기 ----
class FakeRec:
    def __init__(self, res):
        self.res = res

    def recognize_google(self, audio, language="ko-KR", show_all=False):
        assert show_all
        return self.res


def listener_with(pick):
    from jarvis.listener import Listener
    lst = Listener("ko-KR", lambda *a: None, lambda: None, lambda *a: None)
    lst.pick = pick
    return lst


def test_listener_passes_alternatives():
    import speech_recognition as sr
    seen = []
    lst = listener_with(lambda alts: seen.append(alts) or alts[1])
    res = {"alternative": [{"transcript": "대모 켜 줘", "confidence": 0.7}, {"transcript": "대화 모드 켜 줘"}], "final": True}
    out = lst._recognize(FakeRec(res), sr, np.zeros(1600, dtype=np.int16))
    assert out == "대화 모드 켜 줘" and seen == [["대모 켜 줘", "대화 모드 켜 줘"]]


def test_listener_nothing_heard():
    import speech_recognition as sr
    lst = listener_with(lambda alts: alts[0])
    assert lst._recognize(FakeRec([]), sr, np.zeros(1600, dtype=np.int16)) is None
