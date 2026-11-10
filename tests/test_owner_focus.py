"""집중 듣기(주인이 부르면 주인 목소리만) + 2026-11-10 기록에서 나온 문제들의 회귀 테스트."""
from __future__ import annotations

import threading
import time

import numpy as np
import pytest

import jarvis.brain as bm
import jarvis.speech as sp
from jarvis.config import DEFAULTS
from jarvis.listener import FILTERED, RATE, Listener
from jarvis.local_router import normalize
from jarvis.voiceid import SpeakerGate, Voice


class Cfg(dict):
    def __getitem__(self, k):
        return self.get(k, DEFAULTS.get(k))

    def api_key(self):
        return ""


class Tools:
    def _find_app(self, name, min_score=38):
        return ("Chrome", "id") if name in ("크롬",) else None

    def _match_windows(self, name):
        return []

    def schemas(self):
        return []


def brain(**cfg):
    return bm.Brain(Cfg(**cfg), Tools(), on_action=lambda *a: None, context_fn=lambda: "")


class VID:
    ready = True


class Profile:
    exists = True

    def __init__(self, scores):
        self.scores = list(scores)

    def score(self, voice):
        return self.scores.pop(0)


def emb(seed, noise=0.0):
    v = np.random.default_rng(seed).normal(size=192)
    if noise:
        v = v + np.random.default_rng(seed + 100).normal(size=192) * noise
    return v / np.linalg.norm(v)


def gate(scores, **cfg):
    base = dict(owner_only=True, speaker_lock=True, speaker_threshold=0.40)
    base.update(cfg)
    return SpeakerGate(VID(), Profile(scores), Cfg(**base))


# ============================================================ 집중 듣기: 판정
def test_owner_wake_starts_focus_and_remembers_the_voice():
    g = gate([0.45])
    assert not g.focused
    assert g.check(Voice(emb(1), 2.0), wake=True).ok
    assert g.focused and g.session is not None            # 0.45 처럼 아슬아슬하게 통과해도 부른 목소리를 기억


def test_focus_passes_owner_scores_seen_in_log():
    """기록: 통과(0.45) 뒤 같은 사람의 말이 0.32~0.39 로 줄줄이 거부됨."""
    g = gate([0.45, 0.32, 0.34, 0.39])
    g.check(Voice(emb(1), 2.0), wake=True)
    for _ in range(3):
        assert g.check(Voice(emb(1, 0.5), 1.8)).ok


def test_focus_still_rejects_other_voice_and_very_low_scores():
    g = gate([0.45, 0.36, 0.20])
    g.check(Voice(emb(1), 2.0), wake=True)
    assert not g.check(Voice(emb(2), 1.8)).ok             # 프로필 점수는 비슷해도 부른 목소리와 다르면 거부
    assert not g.check(Voice(emb(1), 1.8)).ok             # 같은 목소리라도 프로필과 너무 다르면 거부


def test_no_focus_from_short_wake_or_non_owner():
    g = gate([0.30])
    assert g.check(Voice(emb(1), 0.8), wake=True, wake_only=True).ok     # 짧은 "자비스" → 듣기만 시작
    assert not g.focused
    assert not g.check(Voice(emb(2), 2.0), wake=True).ok                 # 다른 사람이 "자비스" → 거부
    assert not g.focused and g.session is None


def test_reset_ends_focus():
    g = gate([0.60])
    g.check(Voice(emb(1), 2.0), wake=True)
    g.reset()
    assert not g.focused and g.session is None


def test_score_shown_as_threshold_passes():
    """기록: '유사도 0.40 / 기준 0.40 → 거부' — 0.3999 가 0.40 으로 보이면서 거부됨."""
    assert gate([0.3962]).check(Voice(emb(1), 2.0)).ok
    assert not gate([0.3940]).check(Voice(emb(1), 2.0)).ok


def test_prefilter_in_focus():
    g = gate([0.45, 0.30, 0.30, 0.10])
    g.check(Voice(emb(1), 2.0), wake=True)
    assert g.maybe_allowed(Voice(emb(1, 0.5), 2.0)) is True      # 0.30: 부른 목소리와 같으면 인식해 본다
    assert g.maybe_allowed(Voice(emb(2), 2.0)) is False          # 0.30: 다른 목소리 → 인식하지 않음
    assert g.maybe_allowed(Voice(emb(1), 2.0)) is False          # 0.10: 너무 낮음


# ============================================================ 집중 듣기: 주인이 말한 부분만 잘라내기
OWNER = np.array([1, 0, 0, 0], dtype=np.float32)
OTHER = np.array([0, 1, 0, 0], dtype=np.float32)


class MixVID:
    """시험용: 창의 평균값으로 누가 말했는지 흉내 (0 = 남, 1000 = 주인)."""
    ready = True

    def embed(self, pcm):
        mix = float(np.mean(pcm)) / 1000.0
        v = OWNER * mix + OTHER * (1 - mix)
        return Voice(v / np.linalg.norm(v), len(pcm) / RATE)


class MixProfile:
    exists = True

    def score(self, v):
        return float(np.dot(v.emb, OWNER))


def mix_gate():
    return SpeakerGate(MixVID(), MixProfile(), Cfg(owner_only=True, speaker_lock=True, speaker_threshold=0.40))


def seg(owner: bool, seconds: float) -> np.ndarray:
    return np.full(int(seconds * RATE), 1000 if owner else 0, dtype=np.int16)


def test_span_covers_owner_part_only():
    pcm = np.concatenate([seg(False, 4), seg(True, 2.5), seg(False, 3)])     # 남 4초 + 주인 2.5초 + 남 3초
    v = mix_gate().best_voice(pcm)
    assert v.span is not None
    a, b = v.span[0] / RATE, v.span[1] / RATE
    assert a <= 4.0 and b >= 6.5                    # 주인이 말한 부분은 하나도 잘리지 않는다
    assert a >= 1.5 and b <= 9.0                    # 앞뒤 남의 말은 대부분 빠진다


def test_no_span_when_mostly_owner_or_short_or_no_owner():
    g = mix_gate()
    assert g.best_voice(np.concatenate([seg(True, 5), seg(False, 0.5)])).span is None   # 거의 다 주인 말
    assert g.best_voice(seg(True, 2.0)).span is None                                    # 짧은 발화
    assert g.best_voice(seg(False, 6.0)).span is None                                   # 주인이 없으면 자르지 않음(어차피 거부)


# ============================================================ 듣는 쪽: 다른 목소리는 인식하지 않는다
def run_stt_loop(lst: Listener, item, wait=1.5):
    done = threading.Event()
    got = []
    lst.on_utterance = lambda text, voice: (got.append((text, voice)), done.set())
    t = threading.Thread(target=lst._stt_loop, daemon=True)
    t.start()
    lst._stt_pool.put(item)
    done.wait(wait)
    lst._stop.set()
    t.join(2)
    return got


def make_listener(focus: bool, allowed: bool, span=None):
    lst = Listener("ko-KR", lambda *a: None, lambda: None, lambda *a: None)
    heard = []
    lst.stt_engine = "google"
    lst._transcribe = lambda rec, sr, pcm, ai: (heard.append(len(pcm)), "크롬 열어 줘")[1]
    v = Voice(np.zeros(4, dtype=np.float32), 2.0, span)
    lst.embedder = lambda pcm: v
    lst.embedder_babble = lambda pcm: v
    lst.prefilter = lambda voice: allowed
    lst.focus = lambda: focus
    lst.wake_needed = lambda: False
    return lst, heard


def item(seconds=6.0):
    return (np.zeros(int(seconds * RATE), dtype=np.int16), 0, True, (100.0, 50.0, False), None)


def test_focus_skips_stt_for_other_voice():
    lst, heard = make_listener(focus=True, allowed=False)
    got = run_stt_loop(lst, item())
    assert heard == [] and got == [(None, FILTERED)]       # 인식도 외부 전송도 하지 않고, '못 알아들음'과 구분해 알린다


def test_without_focus_quiet_room_is_transcribed_as_before():
    lst, heard = make_listener(focus=False, allowed=False)
    got = run_stt_loop(lst, item())
    assert heard == [6 * RATE] and got[0][0] == "크롬 열어 줘"


def test_focus_transcribes_only_owner_span():
    lst, heard = make_listener(focus=True, allowed=True, span=(2 * RATE, 5 * RATE))
    got = run_stt_loop(lst, item())
    assert heard == [3 * RATE] and got[0][0] == "크롬 열어 줘"


def test_ignored_sounds_are_summarised_not_logged_per_line(caplog):
    lst, _ = make_listener(focus=False, allowed=True)
    lst.wake_needed = lambda: True
    lst.has_wake = lambda t: False
    with caplog.at_level("INFO", logger="jarvis.listener"):
        run_stt_loop(lst, item())
        assert not [r for r in caplog.records if "발화" in r.getMessage()]     # 호출어 없는 소리는 한 줄씩 적지 않는다
        lst._flush_ignored()
    assert any("지나간 소리 1건" in r.getMessage() for r in caplog.records)


# ============================================================ 잘린 말
@pytest.mark.parametrize("text,frag", [
    ("자", True), ("음", True), ("a", True), ("",  True),
    ("너 병", False), ("뉴스", False), ("크롬 열어 줘", False), ("날씨", False),
])
def test_fragment(text, frag):
    assert brain().is_fragment(text) is frag


def test_one_syllable_is_fine_in_chat_or_as_an_answer():
    b = brain()
    b.chat_mode = True
    assert not b.is_fragment("응")
    b.chat_mode = False
    b._last_ai = (time.time(), "크롬 창을 닫을까요?")
    assert not b.is_fragment("응")


@pytest.mark.parametrize("text", ["액티브 모", "액티브", "activer", "active", "액티브 모드", "active mode on", "엑티브 모드 켜"])
def test_clipped_active_on(text):
    got = []
    b = brain()
    b.on_hud = got.append
    assert b._hud_command(text) and got == ["active_on"]
    assert b.recognizes(text)


@pytest.mark.parametrize("text", ["액티브 모드 오프", "active mode off", "액티브 종료", "모드 종료", "모드 꺼 줘"])
def test_active_off_including_bare_mode_off(text):
    got = []
    b = brain()
    b.active_hud = True
    b.on_hud = got.append
    assert b._hud_command(text) == "액티브 모드를 해제합니다." and got == ["active_off"]


def test_bare_mode_off_with_nothing_on_does_not_close_an_app():
    b = brain()
    ran = []
    b.execute = lambda n, a, c=None: ran.append(n) or ("ok", False)
    assert b._hud_command("모드 종료") == "지금 켜져 있는 모드가 없어요."
    assert not ran


@pytest.mark.parametrize("text", ["액티브한 사람이 되고 싶어", "activity monitor 열어 줘", "다크 모드 꺼 줘"])
def test_not_active_command(text):
    b = brain()
    b.active_hud = True
    assert b._hud_command(text) is None


# ============================================================ 대화 모드 끝내기
@pytest.mark.parametrize("text", ["자비스 종료", "종료", "종료해 줘", "끝", "그만", "이제 그만하자", "대화 종료", "모드 종료",
                                  "이제 됐어", "대화 끝", "잘 자"])
def test_chat_mode_ends_with_short_phrases(text):
    b = brain()
    b.chat_mode = True
    ended = []
    b.on_mode = ended.append
    assert b._mode_switch(text) and ended == [False] and not b.chat_mode


@pytest.mark.parametrize("text", ["종료", "끝", "그만", "이제 됐어"])
def test_short_end_phrases_do_nothing_outside_chat_mode(text):
    assert brain()._mode_switch(text) is None


@pytest.mark.parametrize("text", ["그 영화 끝이 어떻게 돼", "종료 버튼은 어디 있어", "그만큼 좋았어"])
def test_chat_continues_on_ordinary_sentences(text):
    b = brain()
    b.chat_mode = True
    assert b._mode_switch(text) is None and b.chat_mode


# ============================================================ 출처 목록은 읽지 않는다
def test_strip_sources_from_log():
    reply = ("로블록스 사이트가 인천광역시교육청 접속 차단으로 막혀 있습니다. 차단 해제를 신청하려면 화면의 신고하기 버튼을 쓰시면 됩니다."
             "  Sources: 화면 캡처 결과(인천광역시교육청 차단 페이지)")
    out = bm.strip_sources(reply)
    assert out.endswith("쓰시면 됩니다.") and "Sources" not in out


@pytest.mark.parametrize("reply", [
    "오늘 서울은 맑습니다.\n\nSources:\n- [기상청](https://weather.go.kr)",
    "오늘 서울은 맑습니다.\n\n**출처:** 기상청",
    "오늘 서울은 맑습니다. (출처: 기상청)",
])
def test_strip_sources_variants(reply):
    assert bm.strip_sources(reply) == "오늘 서울은 맑습니다."


@pytest.mark.parametrize("reply", ["메모장을 열었습니다.", "오픈소스 프로젝트를 찾았습니다.", "리소스: 넉넉합니다", None, ""])
def test_strip_sources_leaves_normal_replies(reply):
    assert bm.strip_sources(reply) == reply


# ============================================================ edge-tts 가 안 되면 한동안 바로 SAPI
def test_edge_failure_skips_edge_for_a_while(monkeypatch):
    calls = []

    def bad_edge(text, voice, rate):
        calls.append(text)
        raise TimeoutError()

    monkeypatch.setattr(sp, "_edge_tts", bad_edge)
    monkeypatch.setattr(sp, "_sapi", lambda text: b"wav")
    monkeypatch.setattr(sp, "_edge_down_until", 0.0)
    assert sp.synthesize("첫 문장입니다.", "v", "+0%") == (b"wav", ".wav")
    assert sp.synthesize("둘째 문장입니다.", "v", "+0%") == (b"wav", ".wav")
    assert calls == ["첫 문장입니다."]                      # 두 번째 문장은 기다리지 않고 바로 SAPI
    monkeypatch.setattr(sp, "_edge_down_until", 0.0)
    monkeypatch.setattr(sp, "_edge_tts", lambda t, v, r: b"mp3")
    assert sp.synthesize("다시 됩니다.", "v", "+0%") == (b"mp3", ".mp3")


# ============================================================ 호출어: '쟈비스' 로 불러도
def test_wake_variants():
    import pathlib
    import re
    src = pathlib.Path(__file__).resolve().parent.parent.joinpath("jarvis", "app.py").read_text(encoding="utf-8")
    body = src.split("_WAKE_LOOSE = re.compile(", 1)[1].split(", re.I)", 1)[0]
    loose = re.compile(eval("(" + body + ")"), re.I)
    for t in ("쟈비스 크롬 열어 줘", "쟈비쓰", "짜비스 날씨", "챠비스 볼륨 올려", "쟈비 크롬 열어"):
        assert loose.search(t), t
    for t in ("서비스 센터 알려 줘", "차비 얼마야", "크롬 열어 줘"):
        assert not loose.search(t), t
    assert normalize("쟈비스 종료") == "종료"
