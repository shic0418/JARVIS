"""말 끊기(barge.py · listener · speaker · app): 에코와 끼어든 말 구별, 중지어 판정, 멈추기."""
from __future__ import annotations

import types

import numpy as np
import pytest

from jarvis import barge as B

RNG = np.random.default_rng(7)


# ---------------------------------------------------------------------------- 중지어 판정
@pytest.mark.parametrize("text,want", [
    ("그만", ("stop", "")), ("그만해", ("stop", "")), ("그만 해 줘", ("stop", "")), ("멈춰", ("stop", "")),
    ("잠깐만요", ("stop", "")), ("스톱", ("stop", "")), ("Stop", ("stop", "")), ("조용히 해", ("stop", "")),
    ("됐어", ("stop", "")), ("아 그만", ("stop", "")), ("그만!", ("stop", "")),
    ("자비스", ("stop", "")), ("자비스야", ("stop", "")), ("자비스 그만", ("stop", "")),
    ("자비스 볼륨 줄여", ("wake", "볼륨 줄여")), ("자비스, 다음 곡", ("wake", "다음 곡")),
    # 낱말 전체가 아니면 받지 않는다 — 인식기는 조용한 소리에서 '그' 를 지어낸다
    ("멈쳐", ("stop", "")),                              # 인식기가 '멈춰' 를 이렇게 적기도 한다
    # 끝이 중지어: 뭉개진 호출어('잡비스') · 구간 앞에 섞인 에코
    ("잡비스 멈춰", ("stop", "")), ("잡비음 멈쳐", ("stop", "")), ("오늘 날씨는 맑고 기온 그만", ("stop", "")),
    ("그", None), ("그거", None), ("그만두고 싶다", None), ("잠깐 생각해 보니까 좋네", None), ("오늘 날씨", None),
    # 맞장구 · 평범한 문장 끝에는 멈추지 않는다
    ("알았어", None), ("됐다", None), ("나 이제 다 됐어", None), ("이건 취소", None), ("아 알았어", None),
    ("취소", ("stop", "")), ("됐어", ("stop", "")),
    ("", None), (None, None),
])
def test_classify(text, want):
    assert B.classify(text) == want


def test_words_in_what_jarvis_is_saying_are_echo():
    spoken = "주인님, 이제 그만 쉬십시오. 저는 자비스입니다."
    assert B.classify("그만", spoken) is None
    assert B.classify("자비스", spoken) is None
    assert B.classify("자비스 볼륨 줄여", spoken) is None   # 읽는 글에 '자비스' 가 있으면 호출어로 멈추지 않는다
    assert B.is_echo("이제 그만", spoken) and not B.is_echo("멈춰", spoken) and not B.is_echo("", spoken)
    assert B.classify("멈춰", spoken) == ("stop", "")
    assert B.classify("그만", "오늘 날씨는 맑습니다") == ("stop", "")
    assert B.classify("오늘 날씨는 맑고 기온 그만", "오늘 날씨는 맑고 기온은 그만큼 낮습니다") is None   # 끝의 중지어도 읽는 글에 있으면 에코


def test_other_wake_words():
    assert B.classify("쟈비스 멈춰", "", ("자비스", "쟈비스")) == ("stop", "")
    assert B.classify("jarvis next song", "", ("jarvis",)) == ("wake", "next song")


# ---------------------------------------------------------------------------- 에코 비율 배우기
def test_echo_gate_learns_the_room():
    g = B.EchoGate()
    for _ in range(200):
        g.learn(mic=0.2 * 3000, ref=3000)                # 스피커 소리의 20% 가 되돌아오는 방
    assert g.gain == pytest.approx(0.2, rel=0.05)
    assert g.threshold(3000) == pytest.approx(B.EXCESS * 0.2 * 3000, rel=0.05)
    g.learn(mic=5000, ref=100)                           # 내보내는 소리가 작을 때는 배우지 않는다
    assert g.gain == pytest.approx(0.2, rel=0.05)
    assert g.threshold(0) == B.FLOOR                     # 말이 쉬는 동안은 바닥 기준


def test_echo_gate_is_strict_until_it_has_learned():
    fresh = B.EchoGate(gain=0.2)
    learned = B.EchoGate(gain=0.2, learned=100)
    assert fresh.threshold(3000) > learned.threshold(3000)


def test_headphones_mean_almost_no_echo():
    g = B.EchoGate()
    for _ in range(1000):                                # 자비스가 30초쯤 말하는 동안
        g.learn(mic=30, ref=3000)                        # 이어폰 · 음소거: 마이크엔 방 소음뿐
    assert g.threshold(3000) == B.FLOOR


def test_a_pause_between_sentences_does_not_make_the_gate_forget():
    """쉬는 틈의 작은 비율에 끌려 기준이 확 떨어지면 다음 문장의 에코를 사람 말로 잡는다 (시뮬레이션에서 확인)."""
    g = B.EchoGate(gain=1.0, learned=100)
    for _ in range(17):                                  # 0.5초 쉼: 마이크는 조용한데 '최근 내보낸 소리'는 아직 크다
        g.learn(mic=40, ref=6000)
    assert g.gain > 0.75
    for _ in range(10):
        g.learn(mic=1.5 * 3000, ref=3000)                # 더 크게 되돌아오면 금방 따라 올라간다
    assert g.gain > 1.3


# ---------------------------------------------------------------------------- 구간 잘라 내기
def envelope(seconds: float, level: float, wobble: float = 0.5) -> np.ndarray:
    """말소리처럼 오르내리는 크기 (30ms 블록마다)."""
    n = int(seconds / B.BLOCK_SECONDS)
    t = np.arange(n) * B.BLOCK_SECONDS
    return level * (1 + wobble * np.sin(2 * np.pi * 4 * t)) * (0.8 + 0.4 * RNG.random(n))


def run(det: B.BargeDetector, mic: np.ndarray, ref: np.ndarray) -> list[tuple[int, str]]:
    return [(i, ev) for i, (m, r) in enumerate(zip(mic, ref)) if (ev := det.feed(float(m), float(r)))]


def test_echo_alone_never_starts():
    ref = envelope(8, 3000)
    echo = 0.3 * np.roll(ref, 5)                         # 150ms 늦게 30% 로 되돌아온다
    assert run(B.BargeDetector(), echo + 40, ref) == []


def test_loud_speaker_echo_bigger_than_the_floor_does_not_start():
    ref = envelope(8, 6000)
    echo = 1.2 * ref                                     # 노트북: 스피커가 마이크 바로 옆이라 에코가 크다
    assert run(B.BargeDetector(), echo, ref) == []


def test_person_over_the_echo_starts_and_ends():
    ref = envelope(6, 3000)
    mic = 0.3 * ref + 40
    word = slice(100, 120)                               # 3초쯤에 0.6초 동안 사람 말
    mic[word] += 4000
    events = run(B.BargeDetector(), mic, ref)
    kinds = [ev for _, ev in events]
    assert kinds == ["start", "end"]
    assert word.start <= events[0][0] < word.start + B.START_BLOCKS + 1


def test_click_is_dropped():
    ref = envelope(4, 3000)
    mic = 0.3 * ref + 40
    det = B.BargeDetector()
    for i in range(60):
        det.feed(float(mic[i]), float(ref[i]))           # 에코 비율을 배운 뒤
    mic[60:64] += 5000                                   # 120ms 딸깍
    assert [ev for _, ev in run(det, mic[60:], ref[60:])] == ["start", "drop"]


def test_ducking_does_not_end_the_word_early():
    """끼어든 소리가 잡히면 자비스 목소리를 1/4 로 줄인다 — 에코도 같이 줄어도 사람 말이 이어지는 동안은 끝나지 않는다."""
    ref = envelope(6, 3000)
    mic = 0.3 * ref + 40
    det = B.BargeDetector()
    for i in range(80):
        assert det.feed(float(mic[i]), float(ref[i])) is None
    events = []
    for i in range(80, 140):
        r = ref[i] * (0.25 if events else 1.0)
        m = 0.3 * r + 40 + (2500 if i < 115 else 0)      # 1초 동안 말한다
        if (ev := det.feed(float(m), float(r))):
            events.append((i, ev))
    assert [ev for _, ev in events] == ["start", "end"]
    assert events[1][0] >= 115                           # 말이 끝난 뒤에야 끝난다


def test_long_noise_is_cut_at_the_limit():
    det = B.BargeDetector()
    events = [det.feed(5000.0, 0.0) for _ in range(B.MAX_BLOCKS + 2)]
    assert events.index("end") == B.MAX_BLOCKS - 1          # 2.4초에서 끊는다
    assert events.count("start") == 1


def test_echo_getting_louder_after_the_word_still_ends():
    """끼어든 말이 끝난 뒤 자비스 목소리가 커져도(에코도 커짐) 구간은 끝난다 — 고치기 전에는 끝나지 않았다."""
    det = B.BargeDetector(gate=B.EchoGate(gain=0.3, learned=100))
    for _ in range(B.START_BLOCKS):
        det.feed(4000.0, 1500.0)
    events = [det.feed(0.3 * 5000 + 40, 5000.0) for _ in range(B.END_BLOCKS + 5)]
    assert "drop" in events or "end" in events


# ---------------------------------------------------------------------------- listener 연결
class FakeSTT:
    ready = True

    def __init__(self, text="그만"):
        self.text, self.calls = text, 0

    def recognize(self, pcm):
        self.calls += 1
        return self.text


def make_listener():
    from jarvis.listener import Listener
    lst = Listener("ko-KR", on_level=lambda x: None, on_speech_start=lambda: None, on_utterance=lambda t, v: None)
    seen = {"start": 0, "barge": []}
    lst.barge_enabled = lambda: True
    lst.on_barge_start = lambda: seen.__setitem__("start", seen["start"] + 1)
    lst.on_barge = lambda text, voice: seen["barge"].append((text, voice))
    return lst, seen


def blocks(level: float, n: int) -> list[np.ndarray]:
    t = np.arange(480) / 16000
    return [(level * np.sin(2 * np.pi * 300 * t + k)).astype(np.int16) for k in range(n)]


def test_listener_cuts_a_barge_segment_and_hands_it_to_stt():
    lst, seen = make_listener()
    lst.echo_level = lambda: 0.0
    for b in blocks(20, 20) + blocks(4000, 20) + blocks(20, 20):
        lst._barge_feed(b)
    assert seen["start"] == 1
    pcm, lead = lst._barge_q.get_nowait()
    assert len(pcm) >= 20 * 480
    from jarvis.barge import START_BLOCKS
    assert lead == (10 - START_BLOCKS - 2) * 480         # 감지에 걸린 블록과 그 앞 2블록은 지문에 남긴다
    first_loud = int(np.argmax(np.abs(pcm) > 1000))     # 큰 소리(말)가 처음 들어온 곳은 지문 구간 안에 있어야 한다
    assert lead <= first_loud
    lst.local_stt = FakeSTT("그만")
    lst.embedder = lambda pcm: "voice"
    lst._stop.set()
    lst._barge_q.put((pcm, lead))
    lst._stop.clear()
    # 인식 스레드 한 바퀴를 직접 돌린다
    item = lst._barge_q.get_nowait()
    lst._barge_q.put(item)
    import threading
    t = threading.Thread(target=lst._barge_loop, daemon=True)
    t.start()
    for _ in range(50):
        if seen["barge"]:
            break
        threading.Event().wait(0.05)
    lst._stop.set()
    t.join(2)
    assert seen["barge"] == [("그만", "voice")]


def test_listener_ignores_echo_and_resets_when_speech_ends():
    lst, seen = make_listener()
    lst.echo_level = lambda: 30000.0                     # 아주 큰 소리를 내보내는 중
    for b in blocks(3000, 40):                           # 그 에코
        lst._barge_feed(b)
    assert seen["start"] == 0 and lst._barge_q.empty()
    lst.echo_level = lambda: 0.0
    for b in blocks(4000, 6):
        lst._barge_feed(b)
    assert seen["start"] == 1
    lst._barge_feed(None)                                # 자비스가 말을 마쳤다 → 상태를 닫는다
    assert seen["barge"] == [(None, None)] and not lst._barge.active


def test_listener_does_nothing_when_disabled():
    lst, seen = make_listener()
    lst.barge_enabled = lambda: False
    for b in blocks(5000, 30):
        lst._barge_feed(b)
    assert seen["start"] == 0 and lst._barge_q.empty()


# ---------------------------------------------------------------------------- speaker
@pytest.fixture
def qapp():
    # 다른 테스트(test_counter · test_defense)가 화면을 그리는 QApplication 을 쓴다 — 여기서 QCoreApplication 을 먼저
    # 만들어 두면 그 테스트에서 프로세스가 죽는다. 같은 QApplication 을 쓴다
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def test_speaker_remembers_what_it_sent_and_ducks(qapp):
    from jarvis.speech import DUCK_VOLUME, Speaker
    sp = Speaker()
    sp._q.append(np.full(48000, 0.5, np.float32))
    out = np.zeros((480, 1), np.float32)
    sp._callback(out, 480, None, None)
    assert sp.recent_level() == pytest.approx(0.5 * 32768, rel=0.01)
    sp.duck(True)
    for _ in range(8):
        sp._callback(out, 480, None, None)
    assert out[-1, 0] == pytest.approx(0.5 * DUCK_VOLUME, rel=0.01)       # 부드럽게 줄어 목표 음량에 닿는다
    sp.duck(False)
    for _ in range(4):
        sp._callback(out, 480, None, None)
    assert out[-1, 0] == pytest.approx(0.5, rel=0.01)


# ---------------------------------------------------------------------------- app: 멈추기
def fake_app(playing=True, busy=False, ok=True, said="오늘 날씨는 맑습니다.", same=True, confirm="", ask=None, strict_ok=None):
    from jarvis.app import Jarvis
    calls = []
    me = types.SimpleNamespace()
    me.speaker = types.SimpleNamespace(playing=playing, duck=lambda on: calls.append(("duck", on)))
    me.tts = types.SimpleNamespace(cancel=lambda: calls.append(("cancel",)))
    strict_ok = ok if strict_ok is None else strict_ok
    me.gate = types.SimpleNamespace(barge_ok=lambda v, strict=False: strict_ok if strict else ok)
    me.cfg = {"wake_words": ["자비스", "쟈비스"]}
    me.busy = busy
    me._last_said = said
    me._spoken_now = lambda: me._last_said
    me._cancel_busy = lambda speak=True: calls.append(("cancel_busy", speak))
    me._speak_n, me._barge_n = 3, (3 if same else 2)
    me._pending_confirm, me._pending_ask = confirm, ask
    me._strip_wake = lambda t: None
    me.answer_confirm = lambda cid, ok: calls.append(("confirm", cid, ok))
    me._answer_ask = lambda t, v: calls.append(("ask_answer", t))
    me.run_command = lambda t: calls.append(("run", t))
    me._arm = lambda: calls.append(("arm",))
    me._is_fragment = lambda t: False
    me._barge_dropped_notice = lambda: calls.append(("dropped",))
    return me, calls, Jarvis._on_barge


def test_app_stops_and_listens():
    me, calls, on_barge = fake_app()
    on_barge(me, "그만", "voice")
    assert calls == [("cancel",), ("arm",)]


def test_app_stops_and_runs_the_command_after_the_wake_word():
    me, calls, on_barge = fake_app()
    on_barge(me, "자비스 볼륨 줄여", "voice")
    assert calls == [("cancel",), ("run", "볼륨 줄여")]


def test_app_restores_volume_for_echo_other_voices_and_noise():
    for text, ok, said in (("그만", True, "이제 그만 쉬십시오"), ("그만", False, "날씨"), (None, True, "날씨"),
                           ("오늘 날씨", True, "날씨")):
        me, calls, on_barge = fake_app(ok=ok, said=said)
        on_barge(me, text, "voice")
        assert calls == [("duck", False)], (text, ok, said)


def test_app_cancels_the_job_when_interrupted_while_answering():
    me, calls, on_barge = fake_app(busy=True)
    on_barge(me, "멈춰", None)
    assert calls == [("cancel_busy", True)]
    me, calls, on_barge = fake_app(busy=True)
    on_barge(me, "자비스 볼륨 줄여", None)                  # 작업을 조용히 멈추고 새 명령을 실행한다
    assert calls == [("cancel_busy", False), ("run", "볼륨 줄여")]


def test_app_ignores_results_after_speech_ended():
    me, calls, on_barge = fake_app(playing=False)
    on_barge(me, "그만", None)
    assert calls == [("duck", False)]


def test_command_heard_just_as_speech_ended_still_runs():
    me, calls, on_barge = fake_app(playing=False)
    on_barge(me, "자비스 볼륨 줄여", None)
    assert calls == [("duck", False), ("run", "볼륨 줄여")]


def test_late_result_does_not_stop_the_next_speech():
    me, calls, on_barge = fake_app(same=False)            # 앞 말하기 때 끼어든 소리 — 지금은 다음 말을 읽는 중
    on_barge(me, "그만", None)
    assert calls == [("duck", False)]
    me, calls, on_barge = fake_app(same=False, playing=False)
    on_barge(me, "자비스 볼륨 줄여", None)
    assert calls == [("duck", False)]


def test_rejecting_a_confirm_card_while_it_is_read():
    me, calls, on_barge = fake_app(confirm="c1", said="PowerShell 을 실행할까요? 승인 또는 취소라고 말씀해 주십시오.")
    on_barge(me, "아니", "voice")
    assert calls == [("cancel",), ("confirm", "c1", False)]
    me, calls, on_barge = fake_app(confirm="c1", said="PowerShell 을 실행할까요?")
    on_barge(me, "네", "voice")                           # 승인은 말 끊기로 받지 않는다 — 에코로 저절로 승인될 수 있다
    assert ("confirm", "c1", True) not in calls
    me, calls, on_barge = fake_app(confirm="c1", said="승인 또는 취소라고 말씀해 주십시오.")
    on_barge(me, "취소", "voice")                         # 읽는 글에 든 말은 에코로 본다
    assert not any(c[0] == "confirm" for c in calls)
    me, calls, on_barge = fake_app(ask="볼륨 줄여", said="부르셨습니까, 주인님?")
    on_barge(me, "아니", "voice")
    assert calls == [("cancel",), ("ask_answer", "아니")]


# ---------------------------------------------------------------------------- 목소리 확인
def test_gate_barge_ok_does_not_change_the_session():
    from jarvis.voiceid import SpeakerGate, Voice
    vid = types.SimpleNamespace(ready=True)
    prof = types.SimpleNamespace(exists=False)
    cfg = {"owner_only": False, "speaker_lock": True, "speaker_threshold": 0.4}
    gate = SpeakerGate(vid, prof, types.SimpleNamespace(__getitem__=None) if False else _Cfg(cfg))
    me = np.ones(192, np.float32) / np.sqrt(192)
    other = np.zeros(192, np.float32)
    other[0] = 1.0
    gate.session = me.copy()
    assert gate.barge_ok(Voice(me, 1.0)) is True
    assert gate.barge_ok(Voice(other, 1.0)) is False
    assert np.allclose(gate.session, me)                 # 기준 목소리는 그대로
    assert gate.barge_ok(None) is True
    gate.session = None
    assert gate.barge_ok(Voice(other, 1.0)) is True      # 비교할 기준이 없으면 막지 않는다


class _Cfg(dict):
    def __getitem__(self, k):
        return self.get(k)


def test_full_queue_restores_the_volume():
    lst, seen = make_listener()
    lst.echo_level = lambda: 0.0
    for _ in range(lst._barge_q.maxsize):
        lst._barge_q.put_nowait(np.zeros(10, np.int16))
    for b in blocks(20, 5) + blocks(4000, 20) + blocks(20, 20):
        lst._barge_feed(b)
    assert seen["start"] == 1 and seen["barge"] == [(None, None)]


# ---------------------------------------------------------------------------- 끼어든 명령의 목소리 확인 (보안)
def test_app_stops_but_does_not_run_a_command_from_an_unconfirmed_voice():
    me, calls, on_barge = fake_app(ok=True, strict_ok=False)
    on_barge(me, "자비스 파일 지워 줘", "voice")
    assert ("run", "파일 지워 줘") not in calls
    assert calls == [("cancel",), ("arm",), ("dropped",)]   # 멈추고 다시 듣되, 명령을 버린 것을 알린다             # 멈추고 평소처럼 다시 듣는다 (다음 말은 평소 확인을 거친다)


def test_app_drops_an_unconfirmed_command_after_speech_ended():
    me, calls, on_barge = fake_app(playing=False, ok=True, strict_ok=False)
    on_barge(me, "자비스 볼륨 줄여", "voice")
    assert calls == [("duck", False), ("dropped",)]


def test_app_stop_word_does_not_need_the_strict_check():
    me, calls, on_barge = fake_app(ok=True, strict_ok=False)
    on_barge(me, "그만", "voice")
    assert calls == [("cancel",), ("arm",)]


def _owner_gate(session=None, focused=False):
    from jarvis.voiceid import SpeakerGate
    owner = np.ones(192, np.float32) / np.sqrt(192)
    prof = types.SimpleNamespace(exists=True, score=lambda v: float(np.dot(v.emb, owner)))
    cfg = _Cfg({"owner_only": True, "speaker_lock": False, "speaker_threshold": 0.4})
    gate = SpeakerGate(types.SimpleNamespace(ready=True), prof, cfg)
    gate.session, gate.focused = session, focused
    return gate, owner


def _voice_with_score(owner, s, seconds=1.0):
    from jarvis.voiceid import Voice
    other = np.zeros(192, np.float32)
    other[0] = 1.0
    other -= owner * float(np.dot(other, owner))
    other /= np.linalg.norm(other)
    emb = (s * owner + np.sqrt(1 - s * s) * other).astype(np.float32)
    return Voice(emb, seconds)


def test_strict_barge_rejects_missing_voice_in_owner_mode():
    gate, _ = _owner_gate()
    assert gate.barge_ok(None) is True                   # 멈추기는 그대로 통과
    assert gate.barge_ok(None, strict=True) is False     # 명령은 목소리 확인 없이 받지 않는다


def test_strict_barge_uses_the_normal_threshold_without_the_prefilter_margin():
    gate, owner = _owner_gate()
    near = _voice_with_score(owner, 0.35)                # 기준 0.40 - 여유 0.08 이상, 기준 미만
    assert gate.barge_ok(near) is True
    assert gate.barge_ok(near, strict=True) is False
    assert gate.barge_ok(_voice_with_score(owner, 0.45), strict=True) is True
    assert gate.session is None and gate.focused is False    # 판정만 하고 기준 목소리는 바꾸지 않는다


def test_strict_barge_accepts_the_same_focused_speaker_like_check():
    gate, owner = _owner_gate()
    v = _voice_with_score(owner, 0.32)
    gate.session, gate.focused = v.emb.copy(), True
    assert gate.barge_ok(v, strict=True) is True         # check() 의 집중 듣기 예외와 같다


def test_strict_barge_passes_when_only_session_lock_is_on():
    from jarvis.voiceid import SpeakerGate
    gate = SpeakerGate(types.SimpleNamespace(ready=True), types.SimpleNamespace(exists=False),
                       _Cfg({"owner_only": False, "speaker_lock": True, "speaker_threshold": 0.4}))
    assert gate.barge_ok(None, strict=True) is True      # 평소에도 호출어가 새 세션을 연다


def test_app_busy_unconfirmed_command_cancels_the_job_and_tells():
    me, calls, on_barge = fake_app(busy=True, ok=True, strict_ok=False)
    on_barge(me, "자비스 파일 지워 줘", "voice")
    assert calls == [("cancel_busy", True), ("dropped",)]


@pytest.mark.parametrize("score", [0.20, 0.31, 0.32, 0.33, 0.35, 0.3949, 0.3951, 0.40, 0.45])
@pytest.mark.parametrize("ses", ["none", "same", "near", "other"])
@pytest.mark.parametrize("focused", [False, True])
def test_strict_barge_matches_check_wake(score, ses, focused):
    """명령 실행 판정은 평소 명령의 check(wake=True) 와 같아야 한다 (기준을 한쪽만 바꾸는 회귀 방지)."""
    gate, owner = _owner_gate()
    v = _voice_with_score(owner, score, seconds=1.5)
    other = _voice_with_score(owner, 0.0).emb
    session = {"none": None, "same": v.emb.copy(), "other": other,
               "near": (0.6 * v.emb + 0.8 * other).astype(np.float32)}[ses]   # 0.55~0.6 정도 닮음
    gate.session, gate.focused = (None if session is None else session.copy()), focused
    strict = gate.barge_ok(v, strict=True)
    ref, _ = _owner_gate()
    ref.session, ref.focused = (None if session is None else session.copy()), focused
    assert strict is ref.check(v, wake=True).ok


# ---------------------------------------------------------------------------- 목소리 지문에서 앞 에코 빼기
def test_barge_voice_part_drops_the_echo_lead():
    from jarvis.listener import barge_voice_part
    pcm = np.arange(16000, dtype=np.int16)               # 1초
    assert np.array_equal(barge_voice_part(pcm, 3360), pcm[3360:])
    assert barge_voice_part(pcm, 0) is pcm


def test_barge_voice_part_trims_only_what_a_short_segment_can_spare():
    from jarvis.listener import barge_voice_part, BARGE_EMBED_MIN
    pcm = np.arange(10000, dtype=np.int16)               # 다 빼면 0.5초 미만 → 0.5초가 남는 데까지만 뺀다
    assert np.array_equal(barge_voice_part(pcm, 3360), pcm[10000 - BARGE_EMBED_MIN:])
    exact = np.arange(BARGE_EMBED_MIN + 3360, dtype=np.int16)
    assert len(barge_voice_part(exact, 3360)) == BARGE_EMBED_MIN
    short = np.arange(BARGE_EMBED_MIN - 1, dtype=np.int16)   # 원래 0.5초 미만이면 손대지 않는다
    assert barge_voice_part(short, 3360) is short


def test_barge_loop_embeds_only_the_speech_part():
    import threading
    lst, seen = make_listener()
    lst.local_stt = FakeSTT("자비스 볼륨 줄여")
    got = []
    lst.embedder = lambda pcm: got.append(len(pcm)) or "voice"
    pcm = np.ones(16000, np.int16)
    lst._barge_q.put((pcm, 3360))
    t = threading.Thread(target=lst._barge_loop, daemon=True)
    t.start()
    for _ in range(50):
        if seen["barge"]:
            break
        threading.Event().wait(0.05)
    lst._stop.set()
    t.join(2)
    assert got == [16000 - 3360]
    assert seen["barge"] == [("자비스 볼륨 줄여", "voice")]
