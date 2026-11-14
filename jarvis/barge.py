"""말 끊기 — 자비스가 말하는 도중에 "그만" · "멈춰" · "자비스, …" 라고 하면 멈추고 듣는다.

말하는 동안 마이크에는 스피커에서 나온 자비스 자신의 목소리(에코)가 들어온다. 그래서 세 겹으로 거른다.
1. 크기 (EchoGate · BargeDetector): 지금 내보내는 소리에 비해 마이크 소리가 얼마나 되돌아오는지를 말하는 동안 계속 배우고,
   그 예상 에코보다 확실히 큰 소리가 이어질 때만 '사람이 끼어들었다'고 본다. 스피커가 꺼져 있거나 이어폰이면 에코가 거의
   없으니 기준이 저절로 낮아지고, 스피커 소리가 크면 기준이 올라간다. 끼어든 소리가 잡히면 자비스 목소리를 줄여(앱이 한다)
   사용자 말이 잘 들리게 한다.
2. 낱말 (classify): PC 안의 오프라인 인식으로 받아 적은 글이 중지어 · 호출어일 때만 받는다. 인식기는 조용한 소리에서
   '그' 를 지어내므로 '그만' 을 글자 일부로 찾지 않고 낱말 전체로만 본다. 또 그 말이 자비스가 지금 읽는 문장 안에
   들어 있으면 에코로 보고 무시한다.
3. 목소리 (앱이 voiceid 로): 주인 전용 · 세션 잠금이 켜져 있으면 확실히 다른 목소리(자비스 목소리 포함)는 받지 않는다.

크기 판단은 순수 계산이라 시험할 수 있게 여기 둔다. 소리를 다루는 일은 listener.py, 멈추는 일은 app.py 가 한다.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field

BLOCK_SECONDS = 0.03          # listener 의 한 블록 (30ms)
REF_ACTIVE = 300.0            # 내보내는 소리가 이보다 커야 에코 비율을 배운다 (int16 스케일 RMS)
GAIN_INIT = 1.0               # 처음 쓰는 에코 비율 추정 — 모를 때는 크게 잡는다 (노트북 스피커는 마이크 바로 옆). 쓰면서 내려간다
GAIN_MIN, GAIN_MAX = 0.002, 4.0
LEARN_UP = 0.35               # 에코 비율이 더 크게 보이면 빨리 따라 올라간다 (로그 크기)
LEARN_DOWN = 0.02             # 작게 보이면 천천히 내려간다 — 문장 사이 쉬는 틈의 작은 비율에 끌려 내려가지 않게
EXCESS = 2.0                  # 예상 에코(최댓값 쪽으로 배운 비율)의 이 배수(+6dB)를 넘어야 사람 말로 본다
FLOOR = 120.0                 # 이보다 작은 소리는 사람 말로 보지 않는다 (int16 스케일, 음성 대역)
START_BLOCKS = 4              # 기준을 120ms 연속 넘으면 시작
END_BLOCKS = 12               # 360ms 동안 기준 밑이면 끝
MIN_VOICED = 7                # 기준을 넘은 블록이 210ms 미만이면 버린다 (딸깍 · 기침)
MAX_BLOCKS = 80               # 2.4초까지만 듣는다 (중지어는 짧다)
END_RATIO = 0.7               # 끝 기준 = 시작 기준의 이 비율

# 받아 적은 글이 이것뿐일 때 멈춘다 (앞뒤에 '좀' · '요' 정도는 허용)
# 오프라인 인식기는 '멈춰' 를 '멈쳐' · '멈처' 로 적기도 한다 (시뮬레이션)
# 문장 끝에 와도 받는 확실한 중지어 ('잡비스 멈춰' · 앞에 에코가 섞인 '…기온 그만')
_STRONG = (r"그만(?:\s*해|\s*하(?:세요|자))?|그만\s*말해|그만\s*읽어|멈[춰쳐처](?:\s*봐)?|멈추(?:세요|라)|"
           r"잠깐(?:만)?|잠시만|스톱|스탑|stop|조용히?(?:\s*해)?")
# 그것만 말했을 때만 받는 말 — '이건 취소' · '다 됐어' 같은 평범한 문장 끝에서는 멈추지 않는다.
# '알았어' · '됐다' 처럼 맞장구로 흔한 말은 넣지 않는다 (대화 중 맞장구에 멈추지 않게)
_STOP = _STRONG + r"|쉿|됐어|중지|취소"
_TAIL = r"(?:\s*(?:좀|요|줘|해\s*줘|봐))*"
STOP_RE = re.compile(r"^(?:(?:아|어|야|음)\s*)?(?:" + _STOP + r")" + _TAIL + r"$", re.I)
# 끝이 중지어인 글: '잡비스 멈춰'(호출어가 뭉개짐) · '오늘 날씨는 맑고 기온 그만'(구간 앞에 에코가 섞임)
END_STOP_RE = re.compile(r"(?:^|\s)(?P<stop>" + _STRONG + r")" + _TAIL + r"$", re.I)


def _norm(s: str) -> str:
    s = re.sub(r"[\"'“”‘’.,!?~…·\-]+", " ", s or "")
    return re.sub(r"\s+", " ", s).strip().lower()


def _squash(s: str) -> str:
    return re.sub(r"\s+", "", _norm(s))


@dataclass
class EchoGate:
    """마이크 소리 / 내보내는 소리 의 비율(에코 비율)을 배우고, 그 위로 확실히 큰 소리인지 판단한다."""
    gain: float = GAIN_INIT
    learned: int = 0              # 배운 블록 수 (처음 몇 블록은 조심스럽게)

    def learn(self, mic: float, ref: float) -> None:
        """사람 말이 없다고 보는 동안(감지 중이 아닐 때)만 부른다.
        ref 는 '최근 0.5초쯤 내보낸 소리의 최댓값'이라 쉬는 틈에는 마이크보다 훨씬 크다 — 평균을 내면 비율을 낮게 배워
        자비스 자신의 목소리를 끼어든 말로 잘못 잡는다(시뮬레이션에서 확인). 그래서 최댓값 쪽을 따라간다."""
        if ref < REF_ACTIVE or mic <= 0:
            return
        ratio = min(GAIN_MAX, max(GAIN_MIN, mic / ref))
        if ratio > self.gain:
            rate = LEARN_UP
        else:
            # 쉬는 틈에는 비율이 수백 분의 1로 보인다 — 그대로 따라가면 0.5초 만에 1.0 → 0.2 로 떨어져 다음 문장의
            # 에코를 사람 말로 잡는다 (시뮬레이션). 한 블록에 내려가는 폭을 반으로 묶는다 (1초에 약 37%)
            ratio, rate = max(ratio, self.gain * 0.5), LEARN_DOWN
        lg = math.log(self.gain) + rate * (math.log(ratio) - math.log(self.gain))
        self.gain = min(GAIN_MAX, max(GAIN_MIN, math.exp(lg)))
        self.learned += 1

    def threshold(self, ref: float, floor: float = FLOOR) -> float:
        """지금 내보내는 소리가 ref 일 때 '사람이 끼어들었다'고 볼 마이크 크기."""
        warm = 1.0 if self.learned >= 30 else 1.5      # 첫 1초쯤은 더 엄격하게
        return max(floor, EXCESS * warm * self.gain * ref)


@dataclass
class BargeDetector:
    """블록마다 (마이크 크기, 내보내는 소리 크기)를 받아 '끼어든 말' 구간을 잘라 낸다.
    feed 는 사건을 돌려준다: 'start' (끼어들기 시작 — 소리를 줄일 때), 'end' (구간 완성 — 인식할 때), 'drop' (너무 짧음)."""
    gate: EchoGate = field(default_factory=EchoGate)
    active: bool = False
    run: int = 0
    silent: int = 0
    voiced: int = 0
    blocks: int = 0
    th: float = 0.0               # 시작할 때의 기준 (소리를 줄인 뒤에도 같은 기준으로 끝을 본다)

    def reset(self) -> None:
        self.active, self.run, self.silent, self.voiced, self.blocks = False, 0, 0, 0, 0

    def feed(self, mic: float, ref: float, floor: float = FLOOR) -> str | None:
        if not self.active:
            th = self.gate.threshold(ref, floor)
            if mic > th:
                self.run += 1
                if self.run >= START_BLOCKS:
                    self.active, self.silent, self.voiced, self.blocks, self.th = True, 0, self.run, self.run, th
                    return "start"
            else:
                self.run = 0
                self.gate.learn(mic, ref)               # 사람 말이 아닌 동안 에코 비율을 배운다
            return None
        self.blocks += 1
        # 끝은 '지금 내보내는 소리' 기준의 END_RATIO 밑으로 내려갈 때 (예상 에코의 1.4배 — 에코만 남으면 끝난다).
        # 시작 기준에 묶어 두면 그 뒤 자비스 목소리가 커질 때 그 에코가 사람 말로 세어져 구간이 끝나지 않는다.
        # 소리를 줄이면 에코와 기준이 같이 내려간다
        end_th = END_RATIO * self.gate.threshold(ref, floor)
        if mic > end_th:
            self.voiced += 1
            self.silent = 0
        else:
            self.silent += 1
        if self.silent >= END_BLOCKS or self.blocks >= MAX_BLOCKS:
            ok = self.voiced >= MIN_VOICED
            self.reset()
            return "end" if ok else "drop"
        return None


def is_echo(text: str | None, spoken: str) -> bool:
    """받아 적은 글이 자비스가 지금 읽고 있는 글 안에 그대로 들어 있다 — 스피커에서 되돌아온 소리일 수 있다."""
    t = _squash(text or "")
    return bool(t) and t in _squash(spoken)


def classify(text: str | None, spoken: str = "", wake_words: tuple[str, ...] | list[str] = ("자비스",)) -> tuple[str, str] | None:
    """받아 적은 글 → ('stop', '') · ('wake', 호출어 뒤의 말) · None (끼어든 말이 아니다).
    spoken: 자비스가 지금 읽고 있는 글 — 그 안에 든 말이면 에코로 보고 무시한다."""
    t = _norm(text or "")
    if not t:
        return None
    sq_spoken = _squash(spoken)
    for w in sorted((_norm(w) for w in wake_words if w), key=len, reverse=True):
        m = re.match(r"^(?:(?:아|어|야|음)\s*)?" + re.escape(w) + r"(?:야|아)?(?=\s|$)\s*(.*)$", t)
        if m:
            if _squash(w) in sq_spoken:
                return None                              # 자비스가 제 이름을 말하는 중이다
            rest = m.group(1).strip()
            return ("stop", "") if not rest or STOP_RE.match(rest) else ("wake", rest)
    if STOP_RE.match(t):
        if _squash(t) in sq_spoken:
            return None                                  # 읽고 있는 문장에 같은 말이 있다 — 에코
        return "stop", ""
    m = END_STOP_RE.search(t)
    if m and _squash(m.group("stop")) not in sq_spoken:
        # 앞부분은 뭉개진 호출어이거나 구간 앞에 섞인 자비스의 에코다. 끝의 중지어는 자비스가 지금 읽는 글에 없으니
        # 에코에서 나올 수 없다 — 사람이 한 말이다
        return "stop", ""
    return None
