"""받아쓴 글자 다듬기 — 호출어 찾기와, 음성 인식이 자주 틀리게 적는 말 바로잡기.

마이크 → 인식기를 거친 글자는 소음·거리·말버릇에 따라 조금씩 뭉개진다. 여기서는 소리를 다시 듣지 않고
'글자' 단계에서 할 수 있는 보정만 한다 (순수 함수 — 다른 모듈을 쓰지 않는다).

  find_wake / strip_wake : 호출어 찾기. 인식기가 '자비스'를 잠비스 · 잡비스 · 쟈비쓰처럼 적어도 호출로 받는다
  repair                 : 명령 문장의 흔한 오표기 ('들어가죠' → '들어가 줘', '틀 어 줘' → '틀어 줘', '음소가' → '음소거')
  digits                 : 한글로 적힌 수를 숫자로 ('삼십' · '3십' → 30) — 음량 · 밝기 · 타이머 명령을 볼 때만 쓴다
"""
from __future__ import annotations

import difflib
import functools
import re
from dataclasses import dataclass
from typing import Iterable

_EDGE = " \t\r\n,.!?~"
_CALL = ("야", "아", "어이", "헤이", "저기", "hey")       # 호출어 앞뒤에 붙는 부름말 — 명령이 아니다

# ---------------------------------------------------------------- 호출어
# 소음 속에서는 오프라인 인식이 '잠비스·다비스·잡비스·잠이스' 로 적기도 한다 (교실 소음 시험에서 확인)
# 첫 음절이 소음에 묻히면 문장 맨 앞이 '비스 …', '아미스 …', '미스 …' 로 적힌다 → 맨 앞에 있을 때만 호출로 본다
# 실제 녹음(교실)에서 "자비스, 크롬 열어 줘" 가 오프라인 인식에 적힌 모양:
#   자비크롬 열어줘 · 잡비크롬 열어줘 · 잡비 스크롬 열어줘 · 사비 스크롬 열어줘 · 미스크롬 열어줘
# '스' 가 뒤 단어에 붙거나 사라진다 → 문장 맨 앞의 '자비/잡비/사비' 는 '스' 없이도 호출로 본다
# '쟈비스' 처럼 부르면 '쟈비쓰·짜비스·챠비스·자비쯔' 로도 적힌다
WAKE_LOOSE = re.compile(r"[자쟈재저잠잡다사짜쨔챠]\s*[비빗삐]\s*[스즈수쓰쯔]|잠\s*이\s*스|jarvis"
                        r"|^\s*[자쟈재저잠잡사짜쨔챠]\s*[비빗삐]"
                        r"|^\s*[아어]?\s*[비미]\s*스", re.I)


@dataclass(frozen=True)
class Wake:
    start: int
    end: int            # 호출어에 붙은 부름말('자비스야')까지 포함한 끝
    exact: bool         # 설정된 호출어 그대로 적혔는가 (False = 뭉개진 모양을 호출로 받아 줌)


def _tail(text: str, end: int, chars: str) -> int:
    """호출어에 바로 붙은 한 글자(부름말)를 포함한 끝 위치. 뒤가 띄어져 있을 때만 붙은 것으로 본다
    ('자비스야 크롬 열어' ✓ — '자비스 아이유 틀어' 의 '아' 는 명령의 일부라 건드리지 않는다)."""
    if end < len(text) and text[end] in chars and (end + 1 == len(text) or text[end + 1] in _EDGE):
        return end + 1
    return end


@functools.lru_cache(maxsize=64)
def _word_re(word: str) -> re.Pattern:
    """설정된 호출어 한 개를 찾는 식 (글자 사이 띄어쓰기 허용). 발화마다 여러 번 불리므로 만들어 둔 것을 다시 쓴다.
    끝에 붙은 부름말('자비스야')은 떼고 찾는다 — 부름말은 _tail 이 붙여 준다. 그대로 두면 띄어쓰기 허용 때문에
    '자비스 야놀자 열어' 의 '야' 까지 호출어로 먹어 '놀자 열어' 가 됐다."""
    word = word.replace(" ", "")
    if len(word) >= 3 and word[-1] in "아야":
        word = word[:-1]
    return re.compile(r"\s*".join(re.escape(ch) for ch in word), re.I)


def find_wake(text: str, words: Iterable[str]) -> Wake | None:
    """글 안의 호출어 위치. 설정된 호출어(글자 사이 띄어쓰기 허용)를 먼저 찾고, 없으면 뭉개진 모양을 찾는다."""
    text = text or ""
    for w in sorted((w for w in (words or []) if w), key=len, reverse=True):
        m = _word_re(w).search(text)
        if m:
            return Wake(m.start(), _tail(text, m.end(), "아야"), True)
    m = WAKE_LOOSE.search(text)
    if m is None:
        return None
    return Wake(m.start(), _tail(text, m.end(), "아야"), False)


def strip_wake(text: str, words: Iterable[str]) -> str | None:
    """호출어를 떼어 낸 명령 (호출어만 말했으면 ''). 호출어가 없으면 None.

    호출어 뒤에 말이 있으면 그 말이 명령이다 — 호출어 앞에 적힌 것('어 자비스 크롬 열어', 주변 사람 말이 섞인
    '대기업 자비스 화면 캡처해 줘')은 버린다. 뒤에 말이 없을 때만 앞의 말을 명령으로 본다 ('크롬 열어 줘 자비스').
    나머지에서는 문장 부호만 다듬는다 — 예전에는 양 끝의 '야 · 아' 글자까지 지워서
    '아이유 노래 틀어 줘' 가 '이유 노래 틀어 줘' 로, '볼륨 몇이야' 가 '볼륨 몇이' 로 바뀌었다."""
    text = text or ""
    w = find_wake(text, words)
    if w is None:
        return None
    before = text[:w.start].strip(_EDGE)
    after = text[w.end:].strip(_EDGE)
    if before.lower() in _CALL:          # '야 자비스' · '헤이 자비스'
        before = ""
    rest = after if len(after) >= 2 else f"{before} {after}".strip()
    return "" if rest.lower() in _CALL else rest


def wake_at_start(text: str, words: Iterable[str]) -> bool:
    """호출어가 문장 맨 앞(부름말 한두 글자 뒤까지)에 있는가."""
    w = find_wake(text, words)
    return w is not None and w.start <= 3


def wake_end_time(tokens: list[str], stamps: list[float], words: Iterable[str]) -> float | None:
    """인식기가 준 글 조각(tokens)과 각 조각이 시작된 시각(stamps, 초)으로 호출어가 끝나는 시각을 어림한다.
    호출어가 문장 맨 앞에 없거나 시각 정보가 맞지 않으면 None.
    (오프라인 인식은 호출어 바로 뒤의 낱말을 통째로 빠뜨리곤 한다 — 그 뒤쪽 소리만 다시 받아 적을 때 쓴다)"""
    if not tokens or len(tokens) != len(stamps):
        return None
    w = find_wake("".join(tokens), words)
    if w is None or w.start > 3:
        return None
    pos, last, nxt = 0, None, None
    for i, tok in enumerate(tokens):
        if pos < w.end:
            last = i
        elif nxt is None and tok.strip(_EDGE):
            nxt = i
        pos += len(tok)
    if last is None:
        return None
    t = stamps[last] + 0.22                         # 마지막 글자가 소리 나는 동안 (한 음절 약 0.2초)
    if nxt is not None:                             # 바로 이어 말했으면 다음 낱말이 시작되기 직전까지만
        t = min(t, max(stamps[last] + 0.06, stamps[nxt] - 0.06))
    return max(0.0, t)


# ---------------------------------------------------------------- 명령 문장 바로잡기
_JUNG = "ㅏㅐㅑㅒㅓㅔㅕㅖㅗㅘㅙㅚㅛㅜㅝㅞㅟㅠㅡㅢㅣ"
_CHO = "ㄱㄲㄴㄷㄸㄹㅁㅂㅃㅅㅆㅇㅈㅉㅊㅋㅌㅍㅎ"
_JONG = " ㄱㄲㄳㄴㄵㄶㄷㄹㄺㄻㄼㄽㄾㄿㅀㅁㅂㅄㅅㅆㅇㅈㅊㅋㅌㅍㅎ"
_CONNECTIVE = set("ㅏㅓㅕㅐㅔㅘㅝㅙㅞ")      # '-아/어' 꼴로 끝나는 모음: 가 · 서 · 켜 · 해 · 봐 · 춰 · 돼


def jamo(s: str) -> str:
    """한글을 자모로 풀어 쓴다 ('위' → 'ㅇㅟ'). 발음이 조금 다른 말을 비교할 때 글자 단위보다 정확하다."""
    out = []
    for ch in s:
        o = ord(ch) - 0xAC00
        out.append(_CHO[o // 588] + _JUNG[(o % 588) // 28] + _JONG[o % 28].strip() if 0 <= o < 11172 else ch)
    return "".join(out)


def _connective(ch: str) -> bool:
    """받침 없이 '-아/어' 꼴로 끝나는 글자인가 (뒤에 '줘'가 올 수 있는 자리)."""
    o = ord(ch) - 0xAC00
    return 0 <= o < 11172 and o % 28 == 0 and _JUNG[(o % 588) // 28] in _CONNECTIVE


def _jwo(m: re.Match) -> str:
    """문장 끝의 '죠 · 져' 를 '줘' 로: 앞 글자가 '-아/어' 꼴이거나('들어가죠', '키워져') 받침 있는 동사 줄기일 때('열죠')만."""
    ch, end = m.group(1), m.group(2)
    if ch in _STEMS and end == "죠" and (m.start() == 0 or not "가" <= m.string[m.start() - 1] <= "힣"):
        return f"{ch}{_STEMS[ch]} 줘"                     # 크롬 열죠 → 크롬 열어 줘
    if _connective(ch) and not (end == "져" and ch == "가"):   # '가져' 는 다른 낱말
        return f"{ch} 줘"
    return m.group(0)


# 줄기가 받침으로 끝나는 동사 — 인식기가 이음 글자를 띄어 적거나('틀 어 줘') 빠뜨린다('틀줘')
_STEMS = {"틀": "어", "열": "어", "찍": "어", "읽": "어", "적": "어", "넣": "어", "닫": "아", "찾": "아"}
_GIVE = r"(?:줘|줘요|주세요|줄래|줄래요|주라)"
_STEM_SPLIT = re.compile(rf"([{''.join(_STEMS)}])\s+([어아])(?=\s*(?:{_GIVE}|봐|$))")
_STEM_BARE = re.compile(rf"(?<![가-힣])([{''.join(_STEMS)}])\s*(?={_GIVE}$)")
_FIXES = [
    (re.compile(r"([어아])\s*조$"), r"\1 줘"),                             # 닫아조 → 닫아 줘
    (re.compile(r"(다음|이전|앞|전)\s*꼭"), r"\1 곡"),                      # 다음 꼭 → 다음 곡
    (re.compile(r"(다음|이전)\s*[콕폭](?=\s*(?:틀|재생|넘겨|으로)|$)"), r"\1 곡"),   # 다음콕 틀어 줘
    (re.compile(r"(어둡|밝|크|작)\s+게(?![가-힣])"), r"\1게"),              # 어둡 게 → 어둡게
    (re.compile(r"(볼륨|소리|음량|밝기)\s*(?:묘이야|묘지야|며치야)$"), r"\1 몇이야"),   # 밝기묘이야 → 밝기 몇이야
    (re.compile(r"^(?:하면|가면)\s*(?=(?:좀\s*)?(?:밝기|밝게|어둡게))"), "화면 "),   # 하면 밝기 50으로 → 화면 밝기 …
    (re.compile(r"바탕\s*화?(?:\s*(?:하면|면))?(?:은|는)?(?=\s*(?:보여|보기))"), "바탕화면"),   # 바탕화 · 바탕 하면 보여 줘
]
# 조금 틀리게 적혀도 뜻이 하나뿐인 명령어 (비슷한 다른 낱말이 없는 것만: '타이머'는 '타이어'와 헷갈려 넣지 않는다)
_KEYWORDS = ("음소거", "일시정지", "스크린샷", "바탕화면", "다운로드")
_KEYWORD_RATIO = 0.85


def _keyword(token: str) -> str:
    if len(token) < 3 or not re.fullmatch(r"[가-힣]+", token):
        return token
    for k in _KEYWORDS:
        if token.startswith(k):           # 명령어 그대로이거나 조사가 붙은 것('스크린샷을')은 건드리지 않는다
            return k if token[len(k):] == k[-1] else token     # 끝 글자가 한 번 더 적힌 것만 고친다 ('다운로드드')
    jt = jamo(token)
    for k in _KEYWORDS:
        # 글자 수가 같을 때만 본다. 네 글자 이상은 한 글자 빠지거나 더 적힌 것까지 ('크린샷', '다운로드드')
        if abs(len(k) - len(token)) <= (1 if len(k) >= 4 else 0) \
                and difflib.SequenceMatcher(None, jt, jamo(k)).ratio() >= _KEYWORD_RATIO:
            return k
    return token


def repair(text: str) -> str:
    """오프라인 인식이 명령 문장을 자주 다르게 적는 모양을 바로잡는다 (끝의 문장 부호는 뗀 글을 받는다).
    로컬 명령을 알아볼 때만 쓰는 글이다 — AI 에게 넘길 때는 사용자가 말한 원문을 그대로 보낸다."""
    t = text or ""
    t = re.sub(r"([가-힣])\s*(죠|져)$", _jwo, t)                            # 들어가죠 · 검색해죠 · 키워져 · 열죠 → … 줘
    for pat, rep in _FIXES:
        t = pat.sub(rep, t)
    t = _STEM_SPLIT.sub(lambda m: m.group(1) + _STEMS[m.group(1)], t)       # 틀 어 줘 → 틀어 줘
    t = _STEM_BARE.sub(lambda m: m.group(1) + _STEMS[m.group(1)] + " ", t)  # 틀줘 → 틀어 줘
    if any(len(tok) >= 3 for tok in t.split()):
        t = " ".join(_keyword(tok) for tok in t.split(" "))
    return t


# ---------------------------------------------------------------- 한글 수 → 숫자
_SINO = {"일": 1, "이": 2, "삼": 3, "사": 4, "오": 5, "육": 6, "칠": 7, "팔": 8, "구": 9}
_NATIVE = {"한": 1, "두": 2, "세": 3, "네": 4, "다섯": 5, "여섯": 6, "일곱": 7, "여덟": 8, "아홉": 9, "열": 10}
_D = r"(?:\d+|[일이삼사오육칠팔구])"
_NUM = re.compile(rf"(?:(?P<h>{_D})?(?P<hb>백))?\s?(?:(?P<t>{_D})?(?P<tb>십))?\s?(?P<o>{_D})?")
_NUM_CHARS = r"[일이삼사오육칠팔구십백\d][일이삼사오육칠팔구십백\d ]{0,6}"
_UNIT = r"(?:시간|분|초|퍼센트|프로|%)"
_BEFORE_UNIT = re.compile(rf"(?<![가-힣\d])({_NUM_CHARS}?)(?=\s*{_UNIT})")
_AFTER_LEVEL = re.compile(rf"((?:볼륨|소리|음량|밝기|타이머)\s*(?:을|를)?\s*)({_NUM_CHARS}?)(?=\s*(?:으로|로|{_UNIT}|$))")
_NATIVE_HOUR = re.compile(rf"(?<![가-힣])({'|'.join(sorted(_NATIVE, key=len, reverse=True))})\s*(?=시간)")
_HALF = re.compile(r"(\d+)\s*시간\s*반(?![가-힣])")


def _value(s: str) -> int | None:
    """'삼십' · '3십' · '이십오' · '백' → 수. 수로 읽을 수 없으면 None."""
    s = s.strip()
    m = _NUM.fullmatch(s)
    if not m or not s:
        return None

    def one(g: str | None) -> int | None:
        if g is None:
            return None
        return int(g) if g.isdigit() else _SINO[g]

    total = 0
    if m.group("hb"):
        total += (one(m.group("h")) or 1) * 100
    if m.group("tb"):
        total += (one(m.group("t")) or 1) * 10
    o = one(m.group("o"))
    if o is not None:
        if o >= 10 and (m.group("hb") or m.group("tb")):
            return None                       # '십25' 같은 모양은 수가 아니다
        total += o
    return total if total > 0 else None


def _to_digits(s: str) -> str | None:
    if s.strip().isdigit():
        return None                           # 이미 숫자
    v = _value(s)
    return None if v is None else str(v)


def digits(text: str) -> str:
    """단위(분 · 초 · 시간 · 퍼센트) 앞이나 '볼륨/밝기' 뒤에 한글로 적힌 수를 숫자로 바꾼다.
    '타이머 십 분' → '타이머 10 분', '볼륨3십으로' → '볼륨30으로', '한 시간 반' → '1시간 30분'.
    ('이 분', '십분' 은 다른 뜻일 수 있어 문장 전체를 바꾸지 않고, 타이머 · 음량 · 밝기 명령인지 볼 때만 쓴다)"""
    t = text or ""

    def unit(m: re.Match) -> str:
        return _to_digits(m.group(1)) or m.group(0)

    def level(m: re.Match) -> str:
        d = _to_digits(m.group(2))
        return m.group(1) + d if d else m.group(0)

    t = _NATIVE_HOUR.sub(lambda m: str(_NATIVE[m.group(1)]), t)
    t = _BEFORE_UNIT.sub(unit, t)
    t = _AFTER_LEVEL.sub(level, t)
    return _HALF.sub(r"\1시간 30분", t)
