"""빔포밍 · 자동 음량 조절 (frontend.py) — 합성 신호로 확인."""
import numpy as np

from jarvis.frontend import AGC_PEAK, BLOCK, RATE, Agc, Beamformer
from jarvis.listener import band_rms


def _voice(seconds: float, seed: int, lo=300, hi=3400) -> np.ndarray:
    """음성 대역 잡음 (말소리 대역을 채우는 시험 신호)."""
    n = int(seconds * RATE)
    spec = np.fft.rfft(np.random.default_rng(seed).standard_normal(n))
    f = np.fft.rfftfreq(n, 1.0 / RATE)
    spec[(f < lo) | (f > hi)] = 0
    x = np.fft.irfft(spec, n)
    return x / np.sqrt(np.mean(x ** 2))


def _delay(x: np.ndarray, sec: float) -> np.ndarray:
    f = np.fft.rfftfreq(len(x), 1.0 / RATE)
    return np.fft.irfft(np.fft.rfft(x) * np.exp(-2j * np.pi * f * sec), len(x))


def _run(bf: Beamformer, x: np.ndarray) -> np.ndarray:
    out = [bf.process(x[i:i + BLOCK]) for i in range(0, len(x) - BLOCK + 1, BLOCK)]
    return np.concatenate(out).astype(np.float64)


def _stereo(a: np.ndarray, b: np.ndarray, amp=3000.0) -> np.ndarray:
    """두 마이크 신호 + 마이크마다 다른 미세한 자체 잡음 (실제 마이크처럼)."""
    hiss = np.random.default_rng(99).standard_normal((len(a), 2)) * 0.01
    return ((np.stack([a, b], axis=1) + hiss) * amp).astype(np.int16)


def _rms(x) -> float:
    return float(np.sqrt(np.mean(np.asarray(x, dtype=np.float64) ** 2)))


def test_front_source_passes_unchanged():
    v = _voice(4, 1)
    bf = Beamformer(2)
    y = _run(bf, _stereo(v, v * 0.8))          # 정면: 두 마이크에 동시에 도착 (감도만 조금 다름)
    assert bf.state == "beam" and bf.mics == 2
    ref = v * 3000 * 0.9
    gain_db = 20 * np.log10(_rms(y[RATE * 2:]) / _rms(ref))
    assert abs(gain_db) < 1.0


def test_side_source_is_attenuated():
    v = _voice(4, 2)
    bf = Beamformer(2)
    y = _run(bf, _stereo(v, _delay(v, 250e-6)))   # 옆: 한쪽 마이크에 0.25ms 늦게 도착 (경로차 약 8.6cm)
    drop_db = 20 * np.log10(_rms(y[RATE * 2:]) / (3000.0))
    assert drop_db < -8.0


def test_front_voice_over_side_noise_improves_snr():
    front, side = _voice(4, 3), _voice(4, 4)
    a, b = _stereo(front, front), _stereo(side, _delay(side, 250e-6))
    bf_f, bf_s, bf_mix = Beamformer(2), Beamformer(2), Beamformer(2)
    out_f, out_s = _run(bf_f, a), _run(bf_s, b)
    # 따로 넣었을 때: 정면은 그대로, 옆은 줄어든다 → 섞였을 때도 (마스크가 겹치지 않는 만큼) 좋아진다
    assert _rms(out_f[RATE:]) / _rms(out_s[RATE:]) > 2.5
    mixed = _run(bf_mix, (a.astype(np.int32) + b).clip(-32767, 32767).astype(np.int16))
    assert np.isfinite(mixed).all()


def test_duplicate_or_silent_channels_fall_back_to_mono():
    v = (_voice(3, 5) * 3000).astype(np.int16)
    quad = np.stack([v, v, np.zeros_like(v), np.zeros_like(v)], axis=1)   # 가짜 스테레오 + 무음 채널
    bf = Beamformer(4)
    y = _run(bf, quad)
    assert bf.state == "mono" and bf.mics == 1
    # 30ms 늦을 뿐 같은 소리
    assert np.allclose(y[RATE + BLOCK:RATE * 2 + BLOCK], v[RATE:RATE * 2], atol=2)


def test_real_array_with_two_dead_channels_uses_two_mics():
    v = _voice(3, 6)
    a = (v * 3000).astype(np.int16)
    b = (_delay(v, 20e-6) * 2900).astype(np.int16)
    quad = np.stack([a, b, np.zeros_like(a), np.zeros_like(a)], axis=1)
    bf = Beamformer(4)
    _run(bf, quad)
    assert bf.state == "beam" and bf.mics == 2


def _feed_agc(agc: Agc, x: np.ndarray, noise: float, speech: bool) -> np.ndarray:
    out = []
    for i in range(0, len(x) - BLOCK + 1, BLOCK):
        blk = x[i:i + BLOCK]
        out.append(agc.process(blk, band_rms(blk), noise, speech))
    return np.concatenate(out)


def test_agc_boosts_far_quiet_voice_toward_target():
    quiet = (_voice(6, 7) * 120).astype(np.int16)        # 멀리서 말하는 작은 목소리
    agc = Agc()
    y = _feed_agc(agc, quiet, noise=15.0, speech=True)
    assert 6.0 < agc.gain <= 31.6
    assert _rms(y[-RATE:]) > 6 * _rms(quiet[-RATE:])


def test_agc_leaves_normal_voice_alone_and_never_reduces():
    loud = (_voice(3, 8) * 4000).astype(np.int16)
    agc = Agc()
    y = _feed_agc(agc, loud, noise=15.0, speech=True)
    assert agc.gain == 1.0
    assert np.array_equal(y[-RATE:], loud[-RATE:][:len(y[-RATE:])])


def test_agc_does_not_amplify_noisy_room():
    agc = Agc()
    noise = (_voice(4, 9) * 300).astype(np.int16)
    _feed_agc(agc, noise, noise=300.0, speech=False)
    assert agc.gain == 1.0


def test_agc_ducks_immediately_on_loud_sound_without_clipping():
    agc = Agc()
    _feed_agc(agc, (_voice(5, 10) * 20).astype(np.int16), noise=15.0, speech=False)   # 조용 → 미리 키워 둠
    assert agc.gain > 5.0
    bang = (_voice(0.3, 11) * 5000).astype(np.int16)
    y = _feed_agc(agc, bang, noise=15.0, speech=False)
    assert np.abs(y.astype(np.int32)).max() <= 32767
    assert np.mean(np.abs(y[BLOCK:].astype(np.int32)) > AGC_PEAK) < 0.01


# ---------------------------------------------------------------- 주변 대화(교실) 상태에서 발화 자르기
def test_babble_mode_cuts_out_the_near_loud_voice(monkeypatch):
    """음성 감지 AI 가 주변 대화를 계속 말소리로 볼 때: 15초 덩어리가 아니라 배경보다 큰 구간만 잘라낸다."""
    import threading
    import time

    import jarvis.listener as L

    class AlwaysSpeech:                       # 교실: AI 는 항상 '말소리'
        threshold = L.vad_threshold(1.0)

        def __init__(self, *a): pass
        def feed(self, block, quiet=False): return True
        def reset(self): pass

    class Models:
        ready, vad_path, denoise_path = True, "x", None

    monkeypatch.setattr(L, "StreamVad", AlwaysSpeech)
    lis = L.Listener("ko-KR", lambda *_: None, lambda: None, lambda *_: None)
    lis.noise_models, lis.agc = Models(), False
    threading.Thread(target=lis._vad_loop, daemon=True).start()

    rng = np.random.default_rng(0)
    crowd = _voice(30, 21) * 3000 * (0.8 + 0.4 * rng.random(30 * RATE))     # 들쑥날쑥한 배경 대화
    near = _voice(2.0, 22) * 9000                                            # 가까이서 2초 말함 (+9dB)
    s = 22 * RATE
    crowd[s:s + len(near)] += near
    pcm = np.clip(crowd, -32767, 32767).astype(np.int16)
    for i in range(0, len(pcm) - BLOCK + 1, BLOCK):
        lis._q.put(pcm[i:i + BLOCK])
    deadline = time.time() + 5
    while not lis._q.empty() and time.time() < deadline:
        time.sleep(0.02)
    time.sleep(0.2)
    lis._stop.set()

    assert lis.babble
    chunks = []
    while not lis._stt_pool.empty():
        chunks.append(lis._stt_pool.get())
    last = chunks[-1][0]
    assert 2.0 <= len(last) / RATE <= 5.0              # 2초 말 + 앞 1.5초 + 끝 무음, 주변 대화는 붙지 않음
    assert chunks[-1][3][2] is True                    # 주변 대화 상태에서 잘린 발화로 기록됨
    # 시작 직후(상태 판단 전) 덩어리 말고는 배경만으로 발화가 만들어지지 않는다
    assert len(chunks) <= 2


def test_voice_part_uses_only_near_blocks_in_babble():
    from jarvis.listener import voice_part
    pcm = np.arange(BLOCK * 100, dtype=np.int32).astype(np.int16)
    near = np.zeros(100, dtype=bool)
    near[40:80] = True                                   # 1.2초만 가까운 목소리
    assert np.array_equal(voice_part(pcm, BLOCK * 10, near), pcm[BLOCK * 40:BLOCK * 80])
    assert len(voice_part(pcm, BLOCK * 10, None)) == BLOCK * 90          # 평소: 끝 무음만 뺀다
    near[:] = False
    near[:10] = True                                     # 가까운 부분이 너무 짧으면 평소처럼
    assert len(voice_part(pcm, BLOCK * 10, near)) == BLOCK * 90


def test_prefilter_only_blocks_clearly_different_voice():
    from jarvis.voiceid import SpeakerGate, Voice

    class VID:
        ready = True

    class Profile:
        exists = True

        def __init__(self): self.s = 0.0
        def score(self, v): return self.s

    prof = Profile()
    v = Voice(np.zeros(4, dtype=np.float32), 2.0)
    gate = SpeakerGate(VID(), prof, {"owner_only": True, "speaker_lock": True, "speaker_threshold": 0.40})
    for score, ok in ((0.10, False), (0.30, False), (0.33, True), (0.38, True), (0.70, True)):
        prof.s = score
        assert gate.maybe_allowed(v) is ok
    assert gate.maybe_allowed(None) is True              # 판별 불가 → 인식은 해 본다
    prof.s = 0.05
    assert gate.maybe_allowed(Voice(np.zeros(4, dtype=np.float32), 0.9)) is True   # 짧은 호출 한 마디는 거르지 않는다
    gate.cfg["owner_only"] = False
    prof.s = 0.0
    assert gate.maybe_allowed(v) is True                 # 주인 전용이 아니면 거르지 않는다


def test_loose_wake_word_matches_noisy_transcripts():
    import re
    import pathlib
    from jarvis.hearing import WAKE_LOOSE as loose
    for t in ("잠비스 크롬 열어줘", "잡비스 그럼 열어줘", "다비스 크롬 열어줘", "비스 크롬 열어 줘", "아미스 크롬 열어 줘", "재비스",
              # 실제 녹음(교실)에서 나온 모양
              "자비크롬 열어줘", "잡비크롬 열어줘", "잡비 스크롬 열어줘", "사비 스크롬 열어줘", "미스크롬 열어줘", "사비크롬 열어"):
        assert loose.search(t), t
    for t in ("크롬 열어 줘", "오늘 날씨 어때", "서비스 센터 알려 줘", "버스 시간 알려 줘", "그 비스 뭐야",
              "크롬에서 자비 검색해 줘", "내일 회사비 정산"):
        assert not loose.search(t), t


def test_best_voice_picks_the_window_where_owner_speaks():
    """한 구간에 남의 소리(앞)와 주인 말(뒤)이 같이 있을 때, 주인과 가장 닮은 창으로 판별한다."""
    from jarvis.voiceid import RATE as VR, SpeakerGate, Voice

    owner = np.array([1, 0, 0, 0], dtype=np.float32)
    other = np.array([0, 1, 0, 0], dtype=np.float32)

    class VID:
        ready = True

        def embed(self, pcm):                       # 시험용: 창의 평균값으로 누가 말했는지 흉내
            mix = float(np.mean(pcm)) / 1000.0      # 0 = 남, 1 = 주인
            v = owner * mix + other * (1 - mix)
            return Voice(v / np.linalg.norm(v), len(pcm) / VR)

    class Profile:
        exists = True

        def score(self, v): return float(np.dot(v.emb, owner))

    pcm = np.concatenate([np.zeros(3 * VR), np.full(2 * VR, 1000.0)]).astype(np.int16)   # 남 3초 + 주인 2초
    gate = SpeakerGate(VID(), Profile(), {"owner_only": True, "speaker_lock": True, "speaker_threshold": 0.40})
    whole = Profile().score(VID().embed(pcm))
    best = gate.best_voice(pcm)
    assert whole < 0.6 and Profile().score(best) > 0.99
    assert best.seconds == 2.0
    assert gate.check(best, wake=True).ok
    all_other = np.zeros(5 * VR, dtype=np.int16)
    assert not gate.check(gate.best_voice(all_other), wake=True).ok       # 주인이 없으면 여전히 거부
    gate.cfg["owner_only"] = False
    assert gate.best_voice(pcm) is None                                    # 주인 전용이 아니면 평소 방식
