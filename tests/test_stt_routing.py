"""음성 인식 엔진 선택 규칙 테스트 — 특히 '호출어 대기 중 주변 대화는 Google 로 보내지 않는다'."""
from __future__ import annotations

import numpy as np
import pytest
import speech_recognition as sr

from jarvis.listener import Listener
from jarvis.local_stt import clean

PCM = (np.sin(np.arange(16000) / 5) * 3000).astype(np.int16)


class FakeLocal:
    def __init__(self, text, ready=True):
        self.text, self.ready, self.calls = text, ready, 0

    def recognize(self, pcm):
        self.calls += 1
        return self.text


def make(engine="auto", local_text="자비스 크롬 열어", google=("자비스 크롬 열어 줘",), wake_needed=True,
         local_ready=True):
    lis = Listener("ko-KR", on_level=lambda *_: None, on_speech_start=lambda: None, on_utterance=lambda *_: None)
    lis.stt_engine = engine
    lis.local_stt = FakeLocal(local_text, local_ready)
    lis.wake_needed = lambda: wake_needed
    lis.has_wake = lambda t: "자비스" in t
    sent = []

    def fake_google(rec, sr_, pcm):
        sent.append(len(pcm))
        g = google[0]
        if isinstance(g, Exception):
            raise g
        return g

    lis._recognize = fake_google
    return lis, sent


def run(lis):
    return lis._transcribe(sr.Recognizer(), sr, PCM, False)


def test_standby_background_talk_stays_local():
    lis, sent = make(local_text="오늘 저녁 뭐 먹지")
    assert run(lis) is None
    assert sent == [], "호출어가 없는 주변 대화가 Google 로 전송됨"


def test_standby_wake_word_uses_google_for_accuracy():
    lis, sent = make()
    assert run(lis) == "자비스 크롬 열어 줘"
    assert len(sent) == 1 and lis.last_engine == "google"


def test_standby_wake_google_misheard_gets_prefix():
    lis, _ = make(google=("크롬 열어 줘",))
    assert run(lis) == "자비스 크롬 열어 줘"


def test_standby_wake_offline_uses_local():
    lis, _ = make(google=(sr.RequestError("getaddrinfo failed"),))
    assert run(lis) == "자비스 크롬 열어"
    assert lis.last_engine == "local"


def test_active_conversation_google_first():
    lis, sent = make(wake_needed=False, google=("볼륨 30으로 해 줘",))
    assert run(lis) == "볼륨 30으로 해 줘"
    assert lis.local_stt.calls == 0


def test_active_offline_falls_back_to_local_and_skips_google_for_a_while():
    lis, sent = make(wake_needed=False, local_text="볼륨 30으로", google=(OSError("net down"),))
    assert run(lis) == "볼륨 30으로"
    assert run(lis) == "볼륨 30으로"
    assert len(sent) == 1, "끊긴 뒤 바로 다시 Google 을 기다리면 안 됨"


def test_local_engine_never_uses_google():
    lis, sent = make(engine="local", wake_needed=False)
    assert run(lis) == "자비스 크롬 열어" and sent == []


def test_google_engine_never_uses_local():
    lis, _ = make(engine="google")
    assert run(lis) == "자비스 크롬 열어 줘" and lis.local_stt.calls == 0


def test_model_not_ready_behaves_like_before():
    lis, sent = make(local_ready=False, google=("오늘 저녁 뭐 먹지",))
    assert run(lis) == "오늘 저녁 뭐 먹지" and len(sent) == 1


@pytest.mark.parametrize("raw,out", [
    ("<|ko|><|NEUTRAL|><|Speech|><|withitn|>크롬 열어 줘.", "크롬 열어 줘"),
    ("볼륨 30으로 해 줘?", "볼륨 30으로 해 줘"),
    ("<|ko|>我", None),
    ("", None),
])
def test_clean(raw, out):
    assert clean(raw) == out
