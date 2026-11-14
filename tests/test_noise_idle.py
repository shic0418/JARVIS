"""StreamVad 의 소음 제거 갈래 쉬기 — 오래 조용할 때만 쉬고, 다시 켤 때는 상태를 비운다."""
import numpy as np

from jarvis import noise


class _Vad:
    def __init__(self):
        self.fed = 0
        self.resets = 0

    def accept_waveform(self, x):
        self.fed += 1

    def is_speech_detected(self):
        return False

    def empty(self):
        return True

    def reset(self):
        self.resets += 1


class _Den:
    def __init__(self):
        self.runs = 0
        self.resets = 0

    def run(self, x, rate):
        self.runs += 1
        return type("R", (), {"samples": x})()

    def reset(self):
        self.resets += 1


def _svad():
    s = noise.StreamVad.__new__(noise.StreamVad)
    s.threshold = 0.5
    s._raw, s._clean, s._den = _Vad(), _Vad(), _Den()
    s._quiet_run = 0
    s._den_idle = True
    return s


BLOCK = np.zeros(480, dtype=np.int16)


def test_short_quiet_gaps_keep_denoiser_running():
    s = _svad()
    for i in range(60):                       # 소리 · 조용함이 번갈아 와도 계속 돈다
        s.feed(BLOCK, quiet=i % 3 == 0)
    assert s._den.runs == 60
    assert s._den.resets == 1                 # 처음 켤 때 한 번만 비운다


def test_long_quiet_idles_then_resets_on_resume():
    s = _svad()
    s.feed(BLOCK)
    for _ in range(noise.DENOISE_HOLD + 30):
        s.feed(BLOCK, quiet=True)
    assert s._den.runs == 1 + noise.DENOISE_HOLD   # 머무는 동안만 돌고 그 뒤로 쉰다
    resets = s._den.resets
    s.feed(BLOCK)                                    # 말소리가 다시 오면
    assert s._den.resets == resets + 1 and s._clean.resets >= 1
    assert s._den.runs == 2 + noise.DENOISE_HOLD


def test_raw_branch_always_runs():
    s = _svad()
    for _ in range(100):
        s.feed(BLOCK, quiet=True)
    assert s._raw.fed == 100
