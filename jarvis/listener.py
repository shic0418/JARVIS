"""마이크 입력 → 음성 구간 감지(VAD) → 음성 인식(STT).

sounddevice 로 16kHz 모노 PCM 을 받아 에너지 기반으로 발화를 잘라내고 한국어 텍스트로 변환한다.

인식 엔진 (stt_engine):
- auto  : 호출어 대기 중에는 오프라인 인식(local_stt.py)으로만 듣고, '자비스'가 들렸을 때만
          Google 웹 음성 API 로 정확하게 다시 받아 적는다 → 주변 대화는 PC 밖으로 나가지 않음.
          대화 중(호출 직후·이어 말하기·승인 대기)에는 Google 우선. 인터넷이 끊기면 오프라인 인식으로 대체.
- local : 항상 오프라인 인식 (인터넷 불필요, 소리가 밖으로 나가지 않음)
- google: 항상 Google (오프라인 모델을 받지 않음. 인터넷이 끊기면 인식 불가)
STT 요청이 오가는 동안 같은 오디오로 화자 임베딩(누가 말했는지)을 로컬에서 계산한다.

작은 목소리 대응:
- 음성 대역(150~4000Hz) 에너지만 보고 판단 → 팬·웅웅거림 같은 저주파 잡음이 기준값을 끌어올리지 않음
- 소음 추정은 '최솟값 추적' 방식 → 작게 말하는 동안 소음 추정치가 따라 올라가 기준이 높아지는 문제 방지
- STT 로 보내기 전에 저주파 제거 + 자동 증폭(최대 +20dB) → 작게 녹음된 말도 인식률 향상

시끄러운 환경 대응 (noise.py, '소음 환경 모드'):
- 음성 감지 AI(Silero VAD) 가 소리 크기 대신 말소리 모양으로 판단 → 소음보다 작은 목소리도 감지
- 실시간 소음 제거 AI(GTCRN) 를 거친 소리로도 음성 감지 → 목소리가 소음보다 작아도(-5~-10dB) 감지
- 인식은 원본 먼저, 실패하면 소음을 지운 소리로 재시도

앞단 처리 (frontend.py) — 감지·인식·화자 판별이 모두 이 처리를 거친 소리를 쓴다:
- 빔포밍: 마이크가 2개 이상이면 정면에서 온 소리만 남긴다 (옆 사람·TV 소리를 줄임)
- 자동 음량 조절(AGC): 멀리서 작게 들어오는 목소리를 실시간으로 키운다 (최대 +30dB)
"""
from __future__ import annotations

import collections
import logging
import queue
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable

import numpy as np

from .frontend import MAX_CHANNELS, Agc, Beamformer
from .local_stt import LocalSTT
from .noise import NoiseModels, StreamVad, vad_threshold

log = logging.getLogger("jarvis.listener")

RATE = 16000
BLOCK = 480                # 30ms
PRE_ROLL_BLOCKS = 15       # 발화 시작 전 450ms 포함 (음성 감지 AI 의 판단 지연 보완)
MIN_SPEECH_BLOCKS = 7      # 실제 소리가 난 블록이 210ms 미만이면 무시 (키보드 딸깍 등)
START_BLOCKS = 3           # 기준을 90ms 연속 넘으면 발화 시작
SILENCE_END_BLOCKS = 27    # 810ms 무음이면 발화 종료
MAX_UTTER_BLOCKS = 500     # 최대 15초

# VAD 기준 (음성 대역 RMS, int16 스케일)
NOISE_FACTOR = 2.5         # 소음 대비 이 배수를 넘으면 말소리로 봄 (감도로 나눔)
NOISE_FACTOR_ACTIVE = 1.8  # 호출 직후/이어 말하기 중에는 더 낮은 기준
ABS_FLOOR = 60.0           # 아주 조용한 방에서도 이 밑은 말소리로 보지 않음 (감도로 나눔)
END_RATIO = 0.55           # 시작 기준의 이 비율 밑으로 내려가야 무음으로 봄 (말끝 흐림 보존)
NOISE_MIN = 15.0
NOISE_WIN_BLOCKS = 80      # 소음 추정 창 2.4초

# 주변이 말소리로 가득한 곳 (교실·카페·TV) — 음성 감지 AI 가 주변 대화를 계속 '말소리'로 보므로 쓸 수 없다.
# (기록: 교실에서 AI 가 93~96% 를 말소리로 판단 → 발화가 끝나지 않고 15초씩 주변 대화와 한 덩어리로 인식됨)
# 이때는 '배경 대화보다 확실히 큰 = 마이크 가까이에서 난' 소리만 발화로 잘라낸다.
BABBLE_WIN_BLOCKS = 200    # 최근 6초 동안
BABBLE_RATIO = 0.7         # AI 가 이 비율 이상 말소리라고 하면 '주변 대화' 상태
BABBLE_LONG_BLOCKS = 150   # 발화가 4.5초를 넘으면 그 구간도 주변 대화 판단에 넣는다
BG_WIN_BLOCKS = 266        # 배경 크기 = 최근 8초 에너지의 40% 지점 (가까운 말 2~4초가 섞여도 배경에 머묾)
BG_PERCENTILE = 40
FG_START = 1.5             # 배경의 이 배수(+3.5dB)를 넘으면 가까운 목소리 (감도가 높으면 더 낮게)
FG_END = 1.3               # 이 배수 밑으로 내려가면 말이 끝난 것 (낮추면 주변 말이 길게 붙어 응답이 늦어진다)
FG_SILENCE_END_BLOCKS = 20 # 주변 대화 상태에서는 600ms 만 조용해도 종료 (뒤에 주변 말이 붙지 않게)
BABBLE_EXIT_RATIO = 0.4    # 한번 들어가면 이 비율 밑으로 내려가야 해제 (들락날락하면 그 사이 발화가 8초씩 묶여 응답이 늦다)
FG_MAX_UTTER_BLOCKS = 270  # 주변 대화 상태에서 최대 8초
FG_PRE_ROLL_BLOCKS = 66    # 주변 대화 상태에서는 시작 전 2초 포함 — 기준을 넘기 전의 작은 첫 음절("자비…") 보존

# STT 전처리
STT_HPF_HZ = 80            # 이 아래 저주파(험·진동) 제거
STT_TARGET_PEAK = 16000.0  # 약 -6dBFS 까지 증폭
STT_MAX_GAIN = 10.0        # 최대 +20dB (잡음만 과하게 키우지 않도록 제한)
GOOGLE_RETRY_SEC = 30      # Google 연결 실패 후 이 시간 동안은 오프라인 인식만 사용

_WIN = np.hanning(BLOCK).astype(np.float32)
_WIN_POW = float(np.mean(_WIN ** 2))
_FREQS = np.fft.rfftfreq(BLOCK, 1.0 / RATE)
_BAND = (_FREQS >= 150) & (_FREQS <= 4000)


def band_rms(block: np.ndarray) -> float:
    """블록의 음성 대역(150~4000Hz) RMS. 저주파 험·고주파 잡음은 빼고 본다."""
    x = block.astype(np.float32)
    x -= x.mean()
    spec = np.fft.rfft(x * _WIN)
    p = (spec.real[_BAND] ** 2 + spec.imag[_BAND] ** 2).sum()
    return float(np.sqrt(2.0 * p / (BLOCK * BLOCK * _WIN_POW)) + 1e-6)


def prepare_for_stt(pcm: np.ndarray) -> np.ndarray:
    """저주파 제거 후 작게 녹음된 발화를 증폭한다 (줄이지는 않음)."""
    x = pcm.astype(np.float32)
    n = len(x)
    if n < BLOCK:
        return pcm
    spec = np.fft.rfft(x - x.mean())
    f = np.fft.rfftfreq(n, 1.0 / RATE)
    spec *= np.clip((f - STT_HPF_HZ / 2) / (STT_HPF_HZ / 2), 0.0, 1.0)   # 40→80Hz 완만한 경사
    y = np.fft.irfft(spec, n)
    peak = float(np.percentile(np.abs(y), 99.9))   # 순간 튀는 소리 하나에 끌려가지 않도록
    if peak < 1.0:
        return pcm
    gain = min(STT_MAX_GAIN, STT_TARGET_PEAK / peak)
    if gain > 1.0:
        y *= gain
    return np.clip(y, -32767, 32767).astype(np.int16)


def voice_part(pcm: np.ndarray, tail: int, near: np.ndarray | None) -> np.ndarray:
    """화자 판별에 쓸 부분. 보통은 끝 무음만 뺀다.
    주변 대화 상태(near 있음)에서는 배경보다 큰 블록만 이어 붙인다 — 앞뒤에 붙은 남의 말이 섞이면
    주인도 유사도가 기준 밑으로 떨어진다 (기록: 교실에서 주인 0.36·0.38 로 거부)."""
    if near is not None and len(near) * BLOCK == len(pcm):
        lv = np.asarray(near, dtype=np.float32)          # 블록별 '배경 대비 크기' (가까운 목소리가 아니면 0)
        idx = np.flatnonzero(lv > 0)
        if len(idx) * BLOCK >= RATE * 0.8:
            return pcm.reshape(-1, BLOCK)[idx].ravel()
    return pcm[:max(0, len(pcm) - tail)]


class Listener:
    """백그라운드에서 계속 마이크를 듣는다.

    on_level(level 0..1)      : 실시간 입력 레벨 (UI 파형용)
    on_speech_start()         : 발화 시작 감지
    on_utterance(text|None, voice|None)
                              : 발화 인식 결과 (인식 실패 시 None) + 화자 임베딩 (embedder 미설정/실패 시 None)
    embedder(pcm) -> voice    : (선택) 발화 PCM 으로 화자 임베딩 계산
    """

    def __init__(self, language: str, on_level: Callable[[float], None],
                 on_speech_start: Callable[[], None],
                 on_utterance: Callable[[str | None, Any], None],
                 device=None, sensitivity: float = 1.0) -> None:
        self.language = language
        self.on_level = on_level
        self.on_speech_start = on_speech_start
        self.on_utterance = on_utterance
        self.device = device
        self.sensitivity = max(0.3, min(3.0, float(sensitivity or 1.0)))
        self.muted = False            # TTS 재생 중에는 자기 목소리를 듣지 않도록 음소거
        self.enabled = True           # False 면 아무것도 인식하지 않음
        self._q: queue.Queue[np.ndarray] = queue.Queue(maxsize=400)
        self._stop = threading.Event()
        self._stream = None
        self._stt_pool = queue.Queue()
        self.error: str | None = None
        self.force_capture = False    # 수동 활성화 시 낮은 임계값으로 즉시 캡처
        self.embedder: Callable[[np.ndarray], Any] | None = None
        self._emb_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="voiceid")
        self.noise_models: NoiseModels | None = None   # 시끄러운 환경용 AI (app 이 넣어 줌)
        self.noise_robust = True      # False 면 음성 감지 AI·소음 제거를 쓰지 않음
        self.beamforming = True       # 마이크가 2개 이상이면 정면 목소리 강조
        self.agc = True               # 작은 목소리 자동 증폭
        self.channels = 1             # 실제로 연 마이크 채널 수
        self._beam: Beamformer | None = None
        self._agc = Agc()
        # (선택) 인식 전에 목소리 지문만으로 '확실히 받지 않을 목소리'를 걸러낸다. False 를 돌려주면 인식하지 않음
        self.prefilter: Callable[[Any], bool] | None = None
        # (선택) 주변 대화 상태에서 쓸 화자 임베딩 계산 — 발화 전체를 받아 가장 믿을 만한 부분을 고른다. None 이면 평소 방식
        self.embedder_babble: Callable[[np.ndarray], Any] | None = None
        self.last_note = ""
        self.babble = False           # 주변이 말소리로 가득한 상태인가 (교실·카페)
        self._utt_info = (0.0, 0.0, False)
        self.stt_engine = "auto"      # auto | local | google
        self.local_stt: LocalSTT | None = None
        self.wake_needed: Callable[[], bool] = lambda: False   # 지금 호출어 없이는 명령을 받지 않는 상태인가
        self.has_wake: Callable[[str], bool] = lambda t: True   # 텍스트에 호출어가 있는가
        self.wake_prefix = "자비스"
        self.last_engine = ""         # 마지막 발화를 인식한 엔진 (HUD 표시·로그용)
        # Google 이 준 인식 후보들 중 하나를 고른다 (기본: 첫 번째). app 이 '알아들을 수 있는 명령'을 고르게 바꾼다
        self.pick: Callable[[list[str]], str] = lambda alts: alts[0]
        self._google_down_until = 0.0

    # ---------- lifecycle ----------
    def start(self) -> bool:
        try:
            import sounddevice as sd
            self._stream = self._open(sd)
            self._stream.start()
        except Exception as e:  # 마이크 없음/권한 없음
            self.error = f"마이크를 열 수 없습니다: {e}"
            log.error(self.error)
            return False
        threading.Thread(target=self._vad_loop, daemon=True, name="vad").start()
        threading.Thread(target=self._stt_loop, daemon=True, name="stt").start()
        return True

    def _open(self, sd):
        """장치가 여러 채널을 주면 여러 채널로 연다 (빔포밍용 — 설정에서 바로 켜고 끌 수 있게 항상). 안 되면 1채널."""
        try:
            want = max(1, min(MAX_CHANNELS, int(sd.query_devices(self.device, "input")["max_input_channels"])))
        except Exception:
            want = 1
        for ch in dict.fromkeys((want, 2, 1)):
            if ch < 1 or ch > max(want, 1):
                continue
            try:
                stream = sd.InputStream(samplerate=RATE, channels=ch, dtype="int16", blocksize=BLOCK,
                                        device=self.device, callback=self._callback)
                self.channels = ch
                return stream
            except Exception as e:
                if ch == 1:
                    raise
                log.warning("마이크를 %d채널로 열 수 없음 — 채널 수를 줄여 재시도: %s", ch, e)
        raise RuntimeError("입력 채널이 없습니다")

    def frontend_status(self) -> str:
        """설정 화면에 보여 줄 앞단 처리 상태."""
        b = self._beam
        if not self.beamforming:
            beam = "빔포밍 꺼짐"
        elif b is None or b.state == "probing":
            beam = "마이크 확인 중…" if self.channels > 1 else "마이크 1개 · 빔포밍 불가"
        elif b.state == "beam":
            beam = f"마이크 {b.mics}개 · 정면 빔포밍 동작 중"
        else:
            beam = "마이크 1개 · 빔포밍 불가"
        agc = f"자동 음량 +{20 * np.log10(max(self._agc.gain, 1.0)):.0f}dB" if self.agc else "자동 음량 꺼짐"
        crowd = " · 주변 대화 감지됨 — 가까이서 또렷하게 말해 주세요" if self.babble else ""
        return f"{beam} · {agc}{crowd}"

    def stop(self) -> None:
        self._stop.set()
        self._emb_pool.shutdown(wait=False, cancel_futures=True)
        try:
            if self._stream:
                self._stream.stop()
                self._stream.close()
        except Exception:
            pass

    def _callback(self, indata, frames, time_info, status) -> None:
        try:
            self._q.put_nowait(indata.copy() if indata.shape[1] > 1 else indata[:, 0].copy())
        except queue.Full:
            pass

    # ---------- VAD ----------
    def _vad_loop(self) -> None:
        noise = 60.0                      # 주변 소음(음성 대역) RMS 추정치 (int16 스케일)
        smooth: float | None = None
        floor_win: collections.deque = collections.deque(maxlen=NOISE_WIN_BLOCKS)
        pre_roll: collections.deque = collections.deque(maxlen=FG_PRE_ROLL_BLOCKS)
        speech: list[np.ndarray] = []
        near: list[float] = []            # 블록별: 배경 대비 크기 (가까운 목소리가 아니면 0) — 화자 판별에 큰 부분만 쓴다
        in_speech = False
        loud_run = 0
        silent_run = 0
        voiced = 0
        ai_voiced = 0                     # 음성 감지 AI 가 말소리라고 본 블록 수
        last_level_emit = 0.0
        svad = None                       # 음성 감지 AI (준비되면 생성, 감도 바뀌면 다시 생성)
        was_muted = False
        ai_hist: collections.deque = collections.deque(maxlen=BABBLE_WIN_BLOCKS)
        bg_win: collections.deque = collections.deque(maxlen=BG_WIN_BLOCKS)
        bg = 0.0
        tick = 0
        while not self._stop.is_set():
            try:
                block = self._q.get(timeout=0.5)
            except queue.Empty:
                continue
            if block.ndim == 2:
                # 여러 마이크 → 정면 강조한 한 채널 (꺼져 있으면 첫 번째 마이크만)
                if self.beamforming:
                    if self._beam is None or self._beam.channels != block.shape[1]:
                        self._beam = Beamformer(block.shape[1])
                    block = self._beam.process(block)
                else:
                    block = np.ascontiguousarray(block[:, 0])
            rms = float(np.sqrt(np.mean(block.astype(np.float32) ** 2)) + 1e-6)

            now = time.monotonic()
            if now - last_level_emit > 0.033:
                last_level_emit = now
                lvl = 0.0 if self.muted else min(1.0, (rms / 3000.0) ** 0.7)
                self.on_level(lvl)

            if self.muted or not self.enabled:
                in_speech, speech, loud_run, silent_run = False, [], 0, 0
                pre_roll.clear()
                was_muted = True
                continue

            # ---- 음성 감지 AI 준비/갱신 ----
            nm = self.noise_models if self.noise_robust else None
            if nm is None or not nm.ready:
                svad = None
            else:
                th = vad_threshold(self.sensitivity)
                if svad is None or abs(svad.threshold - th) > 1e-3:
                    try:
                        svad = StreamVad(nm.vad_path, th, nm.denoise_path)
                    except Exception as ex:
                        log.warning("음성 감지 AI 생성 실패: %s", ex)
                        self.noise_robust = False
                        svad = None
                elif was_muted:
                    svad.reset()          # 자기 목소리(TTS) 들은 상태를 끌고 오지 않도록
            was_muted = False
            e = band_rms(block)
            # 자동 음량 조절: 감지 AI·인식·화자 판별에는 키운 소리를 쓴다.
            # 에너지 기준(e, noise)은 키우기 전 소리로 계산한다 — 증폭이 바뀔 때 기준이 흔들리지 않게
            if self.agc:
                block = self._agc.process(block, e, noise, in_speech and silent_run == 0 or loud_run > 0)
            ai = False
            if svad is not None:
                try:
                    ai = svad.feed(block)
                except Exception as ex:
                    log.warning("음성 감지 AI 오류 — 기존 방식으로 전환: %s", ex)
                    self.noise_robust = False
                    svad = None

            # 소음 추정 = 최근 2.4초 동안 (부드럽게 한) 에너지의 최솟값.
            # 말소리에는 음절 사이 틈이 있어 최솟값은 소음 수준에 머문다 → 작게 말해도 기준이 올라가지 않고,
            # 시끄러운 곳에서 켜거나 선풍기를 틀어도 2~3초 안에 기준이 따라온다 (말하는 도중에도 갱신).
            smooth = e if smooth is None else 0.7 * smooth + 0.3 * e
            floor_win.append(smooth)
            noise = max(NOISE_MIN, min(floor_win))
            factor = (NOISE_FACTOR_ACTIVE if self.force_capture else NOISE_FACTOR) / self.sensitivity
            start_th = max(noise * factor, ABS_FLOOR / self.sensitivity)
            end_th = start_th * END_RATIO
            # 말소리 판단: AI 가 말소리라고 하거나(시끄러운 곳의 작은 목소리) 소리가 기준보다 크면(조용한 곳).
            # AI 가 있을 때 무음 판단은 '시작 기준'으로 한다 — 들쑥날쑥한 소음 때문에 발화가 끝나지 않는 문제 방지
            loud = ai or e > start_th
            sounding = ai or e > (start_th if svad is not None else end_th)

            # ---- 주변 대화 상태 판단 ----
            tick += 1
            bg_win.append(smooth)
            if tick % 8 == 0 or bg <= 0:
                bg = float(np.percentile(bg_win, BG_PERCENTILE))
            if svad is None:
                ai_hist.clear()
            elif not in_speech or len(speech) > BABBLE_LONG_BLOCKS:
                ai_hist.append(ai)
            babble = (len(ai_hist) >= BABBLE_WIN_BLOCKS // 2
                      and sum(ai_hist) > (BABBLE_EXIT_RATIO if self.babble else BABBLE_RATIO) * len(ai_hist))
            if babble != self.babble:
                self.babble = babble
                log.info("주변 대화 상태 %s (배경 크기 %.0f)", "진입 — 가까운 큰 목소리만 듣습니다" if babble else "해제", bg)
            if babble:
                k = (0.85 if self.force_capture else 1.0) / self.sensitivity ** 0.5
                loud = smooth > max(bg * (1 + (FG_START - 1) * k), ABS_FLOOR)
                sounding = smooth > max(bg * (1 + (FG_END - 1) * k), end_th)
            end_blocks = FG_SILENCE_END_BLOCKS if babble else SILENCE_END_BLOCKS
            max_blocks = FG_MAX_UTTER_BLOCKS if babble else MAX_UTTER_BLOCKS

            if not in_speech:
                pre_roll.append(block)
                loud_run = loud_run + 1 if loud else 0
                if loud_run >= START_BLOCKS:
                    in_speech = True
                    speech = list(pre_roll) if babble else list(pre_roll)[-PRE_ROLL_BLOCKS:]
                    near = [0.0] * (len(speech) - loud_run) + [smooth / max(bg, 1.0)] * loud_run
                    silent_run = 0
                    voiced = loud_run
                    ai_voiced = int(ai)
                    self._utt_info = (e, bg, babble)
                    log.debug("발화 시작: 레벨 %.0f / 기준 %.0f / 소음 %.0f / AI %s", e, start_th, noise, ai)
                    self.on_speech_start()
            else:
                speech.append(block)
                near.append(smooth / max(bg, 1.0) if sounding else 0.0)
                if sounding:
                    silent_run = 0
                    voiced += 1
                    ai_voiced += int(ai)
                else:
                    silent_run += 1
                if silent_run >= end_blocks or len(speech) >= max_blocks:
                    in_speech = False
                    loud_run = 0
                    pre_roll.clear()
                    if babble:
                        # 주변 소리로 시작된 구간이 방금 끝났을 때 바로 이어 말하면 첫 음절이 앞 구간에 들어가 버린다
                        # → 끝부분을 다음 구간 앞에 겹쳐 둔다 (기록: 두 번째 명령의 '자비스' 가 잘려 호출 실패)
                        pre_roll.extend(speech[-FG_PRE_ROLL_BLOCKS:])
                    if voiced >= MIN_SPEECH_BLOCKS:
                        # (전체 PCM, 끝 무음 길이, AI가 말소리를 들었는지) — 화자 판별에는 끝 무음을 뺀 부분만 쓴다
                        self._stt_pool.put((np.concatenate(speech), silent_run * BLOCK,
                                            ai_voiced >= MIN_SPEECH_BLOCKS // 2, self._utt_info,
                                            np.array(near, dtype=np.float32) if self._utt_info[2] else None))
                    else:
                        self.on_utterance(None, None)
                    speech = []

    # ---------- STT ----------
    def _recognize(self, rec, sr, pcm: np.ndarray) -> str | None:
        try:
            res = rec.recognize_google(sr.AudioData(pcm.tobytes(), RATE, 2), language=self.language, show_all=True)
            alts = [a["transcript"].strip() for a in (res.get("alternative", []) if isinstance(res, dict) else [])
                    if isinstance(a, dict) and str(a.get("transcript", "")).strip()]
            if not alts:
                return None
            try:
                return self.pick(alts) or alts[0]
            except Exception as e:
                log.warning("인식 후보 고르기 실패: %s", e)
                return alts[0]
        except sr.UnknownValueError:
            return None
        except sr.RequestError as e:
            log.error("STT 요청 실패: %s", e)
            self.error = "음성 인식 서버에 연결할 수 없습니다 (인터넷 확인)"
            raise
        except OSError as e:   # 네트워크 순간 끊김
            log.warning("STT 연결 끊김: %s", e)
            raise

    def _with_denoise(self, fn: Callable[[np.ndarray], str | None], pcm: np.ndarray, ai_heard: bool) -> str | None:
        """원본으로 먼저 인식하고, 실패했는데 음성 감지 AI 가 분명히 말소리를 들었으면 소음을 지워서 한 번 더.
        (인식기는 소음에 강하게 학습되어 있어 보통은 원본이 더 잘 된다. 시험: 0dB 에서 원본 우세)"""
        text = fn(prepare_for_stt(pcm))
        nm = self.noise_models if self.noise_robust else None
        if text is None and ai_heard and nm is not None and nm.ready:
            clean = nm.denoise(pcm)
            if clean is not pcm:
                text = fn(prepare_for_stt(clean))
        return text

    def _google(self, rec, sr, pcm: np.ndarray, ai_heard: bool) -> tuple[str | None, bool]:
        """(텍스트, 연결 성공 여부). 연결이 안 되면 잠시 Google 을 건너뛴다."""
        if time.monotonic() < self._google_down_until:
            return None, False
        try:
            text = self._with_denoise(lambda x: self._recognize(rec, sr, x), pcm, ai_heard)
            self.error = None
            return text, True
        except (sr.RequestError, OSError):
            self._google_down_until = time.monotonic() + GOOGLE_RETRY_SEC
            return None, False

    def _local(self, pcm: np.ndarray, ai_heard: bool) -> str | None:
        return self._with_denoise(self.local_stt.recognize, pcm, ai_heard)

    def _transcribe(self, rec, sr, pcm: np.ndarray, ai_heard: bool) -> str | None:
        engine = self.stt_engine
        local_ok = self.local_stt is not None and self.local_stt.ready
        if engine == "local" and local_ok:
            self.last_engine = "local"
            return self._local(pcm, ai_heard)
        if engine == "auto" and local_ok and self.wake_needed():
            # 호출어 대기: 로컬로 먼저 듣고, 호출어가 없으면 여기서 끝 (외부 전송 없음)
            lt = self._local(pcm, ai_heard)
            if not lt or not self.has_wake(lt):
                self.last_engine = "local"
                self.last_note = f"호출어 없음({len(lt)}자, 보내지 않음)" if lt else ""
                return None
            gt, online = self._google(rec, sr, pcm, ai_heard)
            if gt:
                self.last_engine = "google"
                # 로컬은 '자비스'를 들었는데 Google 이 다르게 적었으면 호출어를 붙여 준다
                return gt if self.has_wake(gt) else f"{self.wake_prefix} {gt}"
            self.last_engine = "local"
            return lt
        gt, online = self._google(rec, sr, pcm, ai_heard)
        if online or not local_ok or engine == "google":
            self.last_engine = "google"
            return gt
        self.last_engine = "local"     # 인터넷 끊김 → 오프라인 인식으로 대체
        return self._local(pcm, ai_heard)

    def _embed(self, pcm: np.ndarray, tail: int, near: np.ndarray | None):
        if near is not None and self.embedder_babble is not None:
            v = self.embedder_babble(pcm[:max(0, len(pcm) - tail)])
            if v is not None:
                return v
        return self.embedder(voice_part(pcm, tail, near))

    def _stt_loop(self) -> None:
        import speech_recognition as sr
        rec = sr.Recognizer()
        while not self._stop.is_set():
            try:
                pcm, tail, ai_heard, info, near = self._stt_pool.get(timeout=0.5)
            except queue.Empty:
                continue
            self.last_note = ""
            emb_job = None
            if self.embedder is not None:
                emb_job = self._emb_pool.submit(self._embed, pcm, tail, near)
            if near is not None and emb_job is not None and self.prefilter is not None:
                # 주변 대화 상태: 큰 소리마다 구간이 잘리므로, 인식(느림)보다 목소리 지문(빠름)을 먼저 본다.
                # 확실히 받지 않을 목소리면 인식도, 외부 전송도 하지 않는다
                # (기록: 교실에서 2~4초마다 남의 말이 인식기에 들어가 주인의 말이 몇 초씩 밀림)
                try:
                    v = emb_job.result(timeout=5)
                    if not self.prefilter(v):
                        log.info("발화 %.1f초 · 주변 대화 상태 · 받지 않는 목소리 → 인식 생략", len(pcm) / RATE)
                        self.on_utterance(None, None)
                        continue
                except Exception as e:
                    log.warning("목소리 사전 확인 실패: %s", e)
            text = None
            try:
                text = self._transcribe(rec, sr, pcm, ai_heard)
            except Exception as e:
                log.exception("STT 오류: %s", e)
                text = None
            voice = None
            if emb_job is not None:
                try:
                    voice = emb_job.result(timeout=5)
                except Exception as e:
                    log.warning("화자 임베딩 실패: %s", e)
            # 진단용 기록 — 말의 내용은 남기지 않는다 (주변 대화가 로그에 쌓이지 않게)
            log.info("발화 %.1f초 · 크기 %.0f / 배경 %.0f%s · %s · %s", len(pcm) / RATE, info[0], info[1],
                     " · 주변 대화 상태" if info[2] else "", self.last_engine or "-",
                     (self.last_note or "인식 실패") if not text else ("호출어 있음" if self.has_wake(text) else f"호출어 없음({len(text)}자)"))
            self.on_utterance(text.strip() if text else None, voice)
