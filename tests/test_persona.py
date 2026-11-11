"""마블 자비스 성격 (persona.py) · 자비스 음색 (speech.jarvis_tone)."""
from __future__ import annotations

import random
import re

import numpy as np
import pytest

from jarvis import persona, speech
from jarvis.config import DEFAULTS, _OLD_DEFAULTS


def all_lines():
    for name in dir(persona):
        v = getattr(persona, name)
        if name.isupper() and isinstance(v, str) and name != "PERSONA":
            yield name, v
        elif name.isupper() and isinstance(v, (list, tuple)):
            for x in v:
                yield name, x
        elif name == "GREET":
            for lines in v.values():
                for x in lines:
                    yield name, x


def test_every_line_fills_in_cleanly():
    for name, line in all_lines():
        out = line.format(title="주인님", label="라면", msg="렌더링이 끝났습니다", action="PowerShell 실행")
        assert "{" not in out and "}" not in out, name


def test_lines_are_formal_like_jarvis():
    """하십시오체 — 들뜬 반말 · '~요' 체 · 이모티콘을 쓰지 않는다."""
    for name, line in all_lines():
        assert not re.search(r"(?:어요|아요|예요|게요|네요)[.!?]?$", line.strip()), (name, line)
        assert not re.search(r"[!]{2,}|ㅋ|ㅎㅎ|[\U0001F300-\U0001FAFF]", line), (name, line)


@pytest.mark.parametrize("hour, part", [(7, "morning"), (13, "afternoon"), (20, "evening"), (2, "night"), (23, "night")])
def test_greeting_follows_the_time_of_day(hour, part):
    assert persona.part_of_day(hour) == part
    msg = persona.greeting("주인님", "pro", True, hour=hour, rng=random.Random(0))
    assert msg in [x.format(title="주인님") for x in persona.GREET[part]]


def test_greeting_explains_limited_modes():
    assert persona.GREET_LOCAL in persona.greeting("주인님", "local", True, hour=9)
    assert persona.GREET_NO_CLAUDE in persona.greeting("주인님", "pro", False, hour=9)
    assert persona.GREET_NO_KEY in persona.greeting("주인님", "api", False, hour=9)


def test_confirm_says_what_needs_approval():
    for line in persona.CONFIRM:
        out = line.format(title="주인님", action="PowerShell 실행")
        assert "PowerShell 실행" in out and "주인님" in out


def test_persona_reaches_claude_prompts():
    import jarvis.brain as bm

    class Cfg(dict):
        def __getitem__(self, k):
            return self.get(k, DEFAULTS.get(k))

    b = bm.Brain.__new__(bm.Brain)
    b.cfg = Cfg(user_title="선생님")
    for chat in (False, True):
        text = b._build_system(chat=chat)
        assert "JUST A RATHER VERY INTELLIGENT SYSTEM".lower() in text.lower() and "하십시오체" in text
        assert "선생님" in text and "{title}" not in text


def test_old_default_speed_moves_to_the_jarvis_voice():
    assert "+8%" in _OLD_DEFAULTS["tts_rate"] and DEFAULTS["tts_rate"] != "+8%"
    assert DEFAULTS["tts_pitch"].endswith("Hz") and DEFAULTS["voice_fx"] is True


# ---------------------------------------------------------------- 자비스 음색
def voice(seconds=1.0):
    t = np.arange(int(speech.SR * seconds)) / speech.SR
    env = 0.5 + 0.5 * np.sin(2 * np.pi * 3 * t)
    return (0.6 * env * (np.sin(2 * np.pi * 140 * t) + 0.4 * np.sin(2 * np.pi * 2800 * t))).astype(np.float32)


def test_tone_off_returns_the_original():
    a = voice()
    assert speech.jarvis_tone(a, 0.0) is a
    short = a[:1000]
    assert speech.jarvis_tone(short, 1.0) is short


def test_tone_keeps_loudness_and_adds_a_short_tail():
    a = voice()
    y = speech.jarvis_tone(a, 1.0)
    assert y.dtype == np.float32 and np.isfinite(y).all()
    assert abs(float(np.max(np.abs(y))) - float(np.max(np.abs(a)))) < 1e-3          # 음량(최대값)은 그대로
    assert 0 < y.size - a.size <= int(0.1 * speech.SR)                              # 짧은 꼬리만
    assert not np.allclose(y[:a.size], a, atol=1e-3)                                # 실제로 바뀌었다


def test_tone_removes_rumble():
    t = np.arange(speech.SR) / speech.SR
    rumble = (0.5 * np.sin(2 * np.pi * 40 * t)).astype(np.float32)
    mix = voice() + rumble
    y = speech.jarvis_tone(mix, 1.0)[:mix.size]
    spec_in, spec_out = np.abs(np.fft.rfft(mix)), np.abs(np.fft.rfft(y))
    k40 = 40
    assert spec_out[k40] / spec_out.max() < 0.5 * spec_in[k40] / spec_in.max()      # 40Hz 웅웅거림이 크게 줄었다
