"""마이크 입력 앞단 처리 — 빔포밍(정면 목소리 강조) + 자동 음량 조절(AGC).

- Beamformer : 마이크가 2개 이상(노트북·웹캠 마이크 배열)일 때, 정면에서 온 소리만 남긴다.
               정면에서 온 소리는 모든 마이크에 '동시에' 도착하고, 옆·뒤에서 온 소리는 마이크마다 도착 시간이 다르다.
               주파수별로 마이크 사이 도착 시간차를 재서, 시간차가 큰(= 정면이 아닌) 성분을 줄인다.
               마이크가 1개뿐이거나 채널이 복사본이면 아무것도 바꾸지 않는다(30ms 지연만 생김).
- Agc        : 멀리서 작게 들어오는 목소리를 실시간으로 키운다. 조용할수록 미리 키워 두고(작은 말도 감지되게),
               말소리 크기를 따라가며 목표 크기에 맞춘다. 소음만 커지지 않게 상한을 두고, 큰 소리는 즉시 줄인다.

둘 다 numpy 만 쓰고 30ms 블록 단위로 동작한다 (블록당 1ms 미만). VAD 스레드 전용.
"""
from __future__ import annotations

import numpy as np

RATE = 16000
BLOCK = 480

# ---- 빔포밍 ----
MAX_CHANNELS = 4
BEAM_PASS_SEC = 90e-6        # 마이크 간 도착 시간차가 이 안이면 정면으로 보고 그대로 통과 (경로차 약 3cm)
BEAM_STOP_SEC = 160e-6       # 이 이상이면 정면이 아님 → 최대로 줄임 (그 사이는 부드럽게)
BEAM_FLOOR = 0.1             # 정면이 아닌 성분에 곱하는 최소 배율 (-20dB). 0 으로 지우면 소리가 깨져 인식이 나빠진다
# 값 근거 (합성 음성 2명을 실제 인식 파이프라인에 넣어 비교): 0.25/220us 는 옆 사람과 겹친 구간에서 정면 말이
# 묻혔고, 0.1/160us 부터 정면 말("내일 아침 7시 알람을 맞춰줘")이 살아남았다. 더 세게 해도 차이는 작았다.
# 실측 (교실, 노트북 마이크 2개 · 간격 약 4.5cm): 앉은 자리의 주인 목소리는 시간차 0±16us, 주변 대화는 -90~-125us.
# 40/90us 로 좁혀 봤지만 이득은 +0.3~0.5dB 뿐이었고(일치도 필터를 더해도 같음), 좁힌 채로 쓴 날 주인 목소리
# 유사도가 0.17~0.39 로 떨어져 거부가 늘었다(넓을 때 0.40~0.69). 몸을 조금만 틀어도 목소리가 깎이는 것으로 보여 되돌렸다.
BEAM_MIN_HZ = 400            # 이 아래는 파장이 길어 방향을 구분할 수 없으므로 건드리지 않음
BEAM_ALIAS_HZ = 3000         # 이 위는 위상이 한 바퀴 돌아 옆 소리가 정면처럼 보일 수 있다 → 아래 대역의 판단을 함께 쓴다
BEAM_SMOOTH = 0.6            # 채널 간 스펙트럼 평균 계수 (클수록 안정적, 느림)
PROBE_BLOCKS = 34            # 처음 약 1초 동안 채널 구성을 살핀다 (무음·복사 채널 제외)
DUP_DIFF = 1.5               # 두 채널의 차이가 계속 이 안이면 같은 신호의 복사본 (가짜 스테레오).
                             # 상관계수로 보면 조용한 방에서 정면으로 말할 때 진짜 마이크 2개도 복사본처럼 보인다

# ---- AGC ----
AGC_TARGET = 2500.0          # 말소리(음성 대역 RMS, int16)를 이 크기로 맞춘다 (약 -22dBFS)
AGC_MAX_GAIN = 31.6          # 최대 +30dB
AGC_NOISE_CEIL = 150.0       # 증폭 후 배경 소음이 이 크기를 넘지 않게 한다 (소음만 키우는 것 방지)
AGC_PEAK = 20000.0           # 증폭 후 순간 최댓값 상한 — 넘으면 즉시 줄인다
AGC_UP = 1.02                # 블록당 증폭 상승 한도 (약 +5.7dB/초 — 말 중간 쉼에서 출렁이지 않게 천천히)
AGC_DOWN = 0.7               # 블록당 증폭 하강 한도 (약 -3dB/블록 — 큰 소리에는 빨리 반응)
AGC_HOLD_BLOCKS = 100        # 말이 끝나고 3초 동안은 그 사람 목소리 크기를 기억


def _sqrt_hann(n: int) -> np.ndarray:
    return np.sqrt(0.5 - 0.5 * np.cos(2 * np.pi * np.arange(n) / n)).astype(np.float32)


class Beamformer:
    """(BLOCK, 채널) int16 → 정면을 강조한 (BLOCK,) int16. 출력은 입력보다 한 블록(30ms) 늦다."""

    def __init__(self, channels: int) -> None:
        self.channels = channels
        n = 2 * BLOCK
        self._win = _sqrt_hann(n)
        self._prev = np.zeros((BLOCK, channels), dtype=np.float32)
        self._tail = np.zeros(BLOCK, dtype=np.float32)
        f = np.fft.rfftfreq(n, 1.0 / RATE)
        self._w = 2 * np.pi * np.maximum(f, 1.0)
        self._steer = f >= BEAM_MIN_HZ
        self._safe = self._steer & (f < BEAM_ALIAS_HZ)
        self._high = f >= BEAM_ALIAS_HZ
        self._use: list[int] | None = None       # 실제로 쓰는 채널 (살펴본 뒤 정해짐)
        self._probe_n = 0
        self._var = np.zeros(channels, dtype=np.float64)
        self._diff = np.zeros((channels, channels), dtype=np.float32)   # 채널 쌍의 최대 차이
        self._cross: np.ndarray | None = None    # 기준 채널과 나머지 채널의 평균 교차 스펙트럼
        self._pow: np.ndarray | None = None      # 채널별 장기 평균 세기 (채널 감도 차이 보정용)
        self._mask = np.ones(len(f), dtype=np.float32)
        self.front = 1.0                         # 방금 블록에서 '정면·가까운 소리'로 통과한 에너지 비율 (0~1)

    @property
    def state(self) -> str:
        """probing | mono | beam"""
        if self._use is None:
            return "probing"
        return "beam" if len(self._use) >= 2 else "mono"

    @property
    def mics(self) -> int:
        return len(self._use) if self._use else 1

    def _probe(self, x: np.ndarray) -> None:
        """무음 채널과 복사 채널을 빼고 실제 마이크만 고른다."""
        if float(np.abs(x).max()) < 4.0:         # 완전 무음 블록(장치 준비 중)은 세지 않음
            return
        self._var += x.var(axis=0)
        self._diff = np.maximum(self._diff, np.abs(x[:, :, None] - x[:, None, :]).max(axis=0))
        self._probe_n += 1
        if self._probe_n < PROBE_BLOCKS:
            return
        var = self._var / self._probe_n
        live = [c for c in range(self.channels) if var[c] > 1.0 and var[c] > 1e-3 * var.max()]
        use: list[int] = []
        for c in live:
            if not any(self._diff[c, k] <= DUP_DIFF for k in use):
                use.append(c)
        self._use = use or [0]
        self._cross = None
        self._pow = None

    def process(self, block: np.ndarray) -> np.ndarray:
        x = block.astype(np.float32)
        if self._use is None:
            self._probe(x)
        use = self._use or [0]
        frame = np.concatenate([self._prev[:, use], x[:, use]], axis=0)
        self._prev = x
        spec = np.fft.rfft(frame * self._win[:, None], axis=0)          # (주파수, 채널)

        if len(use) >= 2:
            # 채널 감도 차이 보정 — 마이크마다 음량이 조금씩 달라도 합이 한쪽으로 치우치지 않게
            p = (spec.real ** 2 + spec.imag ** 2).sum(axis=0) + 1e-3
            self._pow = p if self._pow is None else 0.995 * self._pow + 0.005 * p
            g = np.clip(np.sqrt(self._pow.mean() / self._pow), 0.5, 2.0)
            spec = spec * g
            # 기준 채널 대비 도착 시간차 = 위상차 / 각주파수. 프레임 몇 개를 평균해 안정시킨다
            cross = spec[:, :1] * np.conj(spec[:, 1:])
            self._cross = cross if self._cross is None else BEAM_SMOOTH * self._cross + (1 - BEAM_SMOOTH) * cross
            tau = np.abs(np.angle(self._cross)) / self._w[:, None]
            t = np.clip((tau.max(axis=1) - BEAM_PASS_SEC) / (BEAM_STOP_SEC - BEAM_PASS_SEC), 0.0, 1.0)
            m = BEAM_FLOOR + (1 - BEAM_FLOOR) * 0.5 * (1 + np.cos(np.pi * t))
            m = np.where(self._steer, m, 1.0)
            # 고주파는 시간차가 조금만 커도 위상이 한 바퀴 돌아 구분이 안 된다.
            # 같은 순간 중간 대역(방향이 분명한 대역)이 '정면 아님'이면 고주파도 그만큼 줄인다 (세기 가중 평균)
            pw = (spec.real[self._safe] ** 2 + spec.imag[self._safe] ** 2).sum(axis=1) + 1e-3
            front = float((m[self._safe] * pw).sum() / pw.sum())
            m = np.where(self._high, np.minimum(m, front), m)
            band = self._steer
            pb = (spec.real[band] ** 2 + spec.imag[band] ** 2).sum(axis=1) + 1e-3
            self.front = float(((m[band] ** 2) * pb).sum() / pb.sum())
            m = np.convolve(m, (0.25, 0.5, 0.25), mode="same")         # 주파수 방향으로 다듬어 삑삑거림 방지
            m[0], m[-1] = 1.0, m[-2]
            self._mask = (0.5 * self._mask + 0.5 * m).astype(np.float32)
            out_spec = spec.mean(axis=1) * self._mask                   # 정면 기준 지연-합 + 방향 마스크
        else:
            out_spec = spec[:, 0]

        y = np.fft.irfft(out_spec, 2 * BLOCK).astype(np.float32) * self._win
        out = self._tail + y[:BLOCK]
        self._tail = y[BLOCK:]
        return np.clip(out, -32767, 32767).astype(np.int16)


class Agc:
    """블록 단위 자동 음량 조절. 줄이지는 않고(1배 이상) 작은 소리만 키운다."""

    def __init__(self) -> None:
        self.gain = 1.0
        self._level: float | None = None     # 최근 말소리 크기 (음성 대역 RMS)
        self._quiet = 0

    def reset(self) -> None:
        self.gain, self._level, self._quiet = 1.0, None, 0

    def process(self, block: np.ndarray, level: float, noise: float, speech: bool) -> np.ndarray:
        """level: 이 블록의 음성 대역 RMS, noise: 배경 소음 추정치, speech: 지금 말소리로 보고 있는가."""
        if speech:
            self._quiet = 0
            if self._level is None or level > self._level:
                self._level = level if self._level is None else 0.5 * self._level + 0.5 * level
            else:
                self._level = 0.98 * self._level + 0.02 * level
        else:
            self._quiet += 1
            if self._quiet > AGC_HOLD_BLOCKS:
                self._level = None           # 말한 지 오래됨 → 다음 사람은 더 멀리 있을 수 있다
        want = min(AGC_MAX_GAIN, AGC_NOISE_CEIL / max(noise, 1.0))
        if self._level:
            want = min(want, AGC_TARGET / self._level)
        want = max(1.0, want)
        new = min(max(want, self.gain * AGC_DOWN), self.gain * AGC_UP)
        x = block.astype(np.float32)
        peak = float(np.abs(x).max())
        if peak * new > AGC_PEAK:            # 갑자기 큰 소리 → 이 블록부터 바로 줄인다
            new = max(1.0, AGC_PEAK / peak)
        old, self.gain = self.gain, new
        if old == new == 1.0:
            return block
        y = x * np.linspace(old, new, len(x), dtype=np.float32)   # 블록 안에서 서서히 바꿔 '툭' 소리 방지
        over = np.abs(y) > AGC_PEAK          # 상한 근처는 부드럽게 눌러 찢어지는 소리 방지
        if over.any():
            room = 32767.0 - AGC_PEAK
            y[over] = np.sign(y[over]) * (AGC_PEAK + room * np.tanh((np.abs(y[over]) - AGC_PEAK) / room))
        return y.astype(np.int16)
