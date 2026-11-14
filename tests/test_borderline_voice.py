"""목소리가 기준을 겨우 넘은 호출어 없는 말은 되묻고(borderline), 확실한 주인 목소리로 프로필을 조금씩 보강한다."""
from __future__ import annotations

import json

import numpy as np

from jarvis import approval
from jarvis.voiceid import (ADAPT_EVERY, ADAPT_KEEP, MODEL_NAME, SpeakerGate, Voice, VoiceProfile,
                            _normalize)


class VID:
    ready = True


class FixedProfile:
    exists = True

    def __init__(self, s):
        self.s = s
        self.adapted = []

    def score(self, voice):
        return self.s

    def adapt(self, emb):
        self.adapted.append(emb)
        return True


def emb(seed):
    v = np.random.default_rng(seed).normal(size=192)
    return (v / np.linalg.norm(v)).astype(np.float32)


def gate(score, **cfg):
    c = {"owner_only": True, "speaker_lock": True, "speaker_threshold": 0.35, **cfg}
    prof = FixedProfile(score)
    return SpeakerGate(VID(), prof, c), prof


def test_barely_passing_ambient_speech_is_borderline():
    # 기록: 주변 대화 중 혼잣말 '신기하다 피넛버터' 가 0.36 / 기준 0.35 로 통과해 Claude 가 대답함
    g, _ = gate(0.36)
    v = g.check(Voice(emb(1), 3.0))
    assert v.ok and v.borderline


def test_clear_owner_is_not_borderline():
    g, _ = gate(0.55)
    v = g.check(Voice(emb(1), 3.0))
    assert v.ok and not v.borderline


def test_wake_word_utterance_is_never_borderline():
    g, _ = gate(0.36)
    v = g.check(Voice(emb(1), 3.0), wake=True)
    assert v.ok and not v.borderline


def test_same_voice_as_confirmed_call_is_not_borderline():
    g, _ = gate(0.60)
    e = emb(7)
    assert g.check(Voice(e, 2.0), wake=True).ok        # 주인이 불러 집중 듣기 시작
    g.profile.s = 0.36
    v = g.check(Voice(e, 3.0))                          # 같은 목소리가 이어서 — 방금 확인한 사람
    assert v.ok and not v.borderline


def test_session_lock_borderline():
    g, _ = gate(0.0, owner_only=False, speaker_threshold=0.40)
    e = emb(3)
    assert g.check(Voice(e, 2.0), wake=True).ok
    near = _normalize(e * 0.42 + emb(4) * np.sqrt(1 - 0.42 ** 2))
    v = g.check(Voice(near, 2.0))
    assert v.ok == (round(float(np.dot(near, g.session)), 2) >= 0.40)
    if v.ok:
        assert v.borderline == (v.score < 0.45)


def test_strong_wake_adapts_profile_but_weak_or_short_does_not():
    g, prof = gate(0.60)
    g.check(Voice(emb(1), 2.5), wake=True)
    assert len(prof.adapted) == 1
    g, prof = gate(0.50)                                # 기준 + 0.20 에 못 미침
    g.check(Voice(emb(1), 2.5), wake=True)
    assert prof.adapted == []
    g, prof = gate(0.60)                                # 너무 짧음
    g.check(Voice(emb(1), 1.3), wake=True)
    assert prof.adapted == []
    g, prof = gate(0.60)                                # 호출어 없는 말로는 보강하지 않는다
    g.check(Voice(emb(1), 3.0))
    assert prof.adapted == []


def test_profile_adapt_is_rate_limited_bounded_and_persisted(tmp_path):
    path = tmp_path / "voice_profile.json"
    owner = emb(10)
    prof = VoiceProfile(path)
    prof.save([owner, owner])
    before = prof.centroid.copy()
    other = emb(11)
    assert prof.adapt(other, now=1000.0)
    assert not prof.adapt(other, now=1000.0 + ADAPT_EVERY - 1)     # 너무 자주
    moved = prof.centroid
    # 등록 샘플이 늘 70% — 보강 샘플이 프로필을 덮어쓰지 못한다
    assert float(np.dot(moved, before)) > float(np.dot(moved, other))
    t = 1000.0
    for _ in range(ADAPT_KEEP + 5):
        t += ADAPT_EVERY
        prof.adapt(other, now=t)
    assert len(prof.adapted) == ADAPT_KEEP
    d = json.loads(path.read_text(encoding="utf-8"))
    assert d["model"] == MODEL_NAME and len(d["adapted"]) == ADAPT_KEEP
    again = VoiceProfile(path)
    assert np.allclose(again.centroid, prof.centroid, atol=1e-4)
    again.save([owner])                                             # 다시 등록하면 보강 샘플은 버린다
    assert again.adapted == [] and np.allclose(again.centroid, owner, atol=1e-4)


def test_old_profile_without_adapted_still_loads(tmp_path):
    path = tmp_path / "voice_profile.json"
    path.write_text(json.dumps({"model": MODEL_NAME, "samples": [emb(1).tolist()]}), encoding="utf-8")
    prof = VoiceProfile(path)
    assert prof.exists and prof.adapted == []


def test_yes_no_answers_for_ask_back():
    assert approval.answer("응") is True
    assert approval.answer("네 맞아요") is True
    assert approval.answer("아니") is False
    assert approval.answer("크롬 열어 줘") is None          # 다른 말 → 되물음을 접고 평소처럼 처리
