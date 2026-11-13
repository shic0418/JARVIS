"""못 알아들은 말 다루기: 원인 짐작, Google 이 놓친 명령을 오프라인 인식으로 받기."""
from __future__ import annotations

import numpy as np

from jarvis import persona
from jarvis.listener import RATE, Listener, miss_reason


def test_miss_reason_cases():
    assert miss_reason(3.0, 4000, 1000, False, online=False) == "offline"
    assert miss_reason(10.5, 97, 12, False) == "long"            # 기록: 10.5초 발화 인식 실패
    assert miss_reason(4.0, 545, 844, True) == "noisy"           # 주변 대화 상태
    assert miss_reason(3.0, 1200, 1000, False) == "noisy"        # 배경보다 겨우 큼
    assert miss_reason(3.0, 150, 20, False) == "quiet"
    assert miss_reason(3.0, 5000, 800, False) == ""              # 원인을 모름 → 평범한 안내
    for why in ("offline", "long", "noisy", "quiet"):
        assert why in persona.MISHEARD_WHY


class FakeLocal:
    ready = True

    def __init__(self, text):
        self.text = text

    def recognize(self, pcm):
        return self.text


def listener(local_text, understands):
    li = Listener("ko-KR", on_level=lambda x: None, on_speech_start=lambda: None, on_utterance=lambda *a: None)
    li.local_stt = FakeLocal(local_text)
    li.understands = understands
    li.wake_needed = lambda: False
    li.stt_engine = "auto"
    li._google = lambda rec, sr, pcm, ai: (None, True)            # Google 연결은 됐지만 받아 적지 못함
    return li


PCM = np.zeros(RATE * 2, dtype=np.int16)


def test_google_miss_falls_back_to_local_only_for_known_commands():
    li = listener("볼륨 30", lambda t: t == "볼륨 30")
    assert li._transcribe(None, None, PCM, True) == "볼륨 30"
    assert li.last_engine == "local"
    li = listener("어 그러니까 저기", lambda t: False)           # 알 수 없는 글은 쓰지 않는다
    assert li._transcribe(None, None, PCM, True) is None


def test_google_engine_never_falls_back():
    li = listener("볼륨 30", lambda t: True)
    li.stt_engine = "google"
    assert li._transcribe(None, None, PCM, True) is None


def test_offline_marks_online_false_without_local():
    li = listener("", lambda t: False)
    li.local_stt = None
    li._google = lambda rec, sr, pcm, ai: (None, False)
    li._online = True
    assert li._transcribe(None, None, PCM, True) is None
    assert li._online is False
