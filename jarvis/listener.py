"""마이크 입력 → 음성 구간 감지(VAD) → 음성 인식(STT).

sounddevice 로 16kHz 모노 PCM 을 받아 에너지 기반으로 발화를 잘라내고,
SpeechRecognition 의 Google 웹 음성 API 로 한국어 텍스트로 변환한다.
STT 요청이 오가는 동안 같은 오디오로 화자 임베딩(누가 말했는지)을 로컬에서 계산한다.

작은 목소리 대응:
- 음성 대역(150~4000Hz) 에너지만 보고 판단 → 팬·웅웅거림 같은 저주파 잡음이 기준값을 끌어올리지 않음
- 소음 추정은 '최솟값 추적' 방식 → 작게 말하는 동안 소음 추정치가 따라 올라가 기준이 높아지는 문제 방지
- STT 로 보내기 전에 저주파 제거 + 자동 증폭(최대 +20dB) → 작게 녹음된 말도 인식률 향상

시끄러운 환경 대응 (noise.py, '소음 환경 모드'):
- 음성 감지 AI(Silero VAD) 가 소리 크기 대신 말소리 모양으로 판단 → 소음보다 작은 목소리도 감지
- 실시간 소음 제거 AI(GTCRN) 를 거친 소리로도 음성 감지 → 목소리가 소음보다 작아도(-5~-10dB) 감지
- 인식은 원본 먼저, 실패하면 소음을 지운 소리로 재시도
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

# STT 전처리
STT_HPF_HZ = 80            # 이 아래 저주파(험·진동) 제거
STT_TARGET_PEAK = 16000.0  # 약 -6dBFS 까지 증폭
STT_MAX_GAIN = 10.0        # 최대 +20dB (잡음만 과하게 키우지 않도록 제한)

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

    # ---------- lifecycle ----------
    def start(self) -> bool:
        try:
            import sounddevice as sd
            self._stream = sd.InputStream(samplerate=RATE, channels=1, dtype="int16",
                                          blocksize=BLOCK, device=self.device,
                                          callback=self._callback)
            self._stream.start()
        except Exception as e:  # 마이크 없음/권한 없음
            self.error = f"마이크를 열 수 없습니다: {e}"
            log.error(self.error)
            return False
        threading.Thread(target=self._vad_loop, daemon=True, name="vad").start()
        threading.Thread(target=self._stt_loop, daemon=True, name="stt").start()
        return True

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
            self._q.put_nowait(indata[:, 0].copy())
        except queue.Full:
            pass

    # ---------- VAD ----------
    def _vad_loop(self) -> None:
        noise = 60.0                      # 주변 소음(음성 대역) RMS 추정치 (int16 스케일)
        smooth: float | None = None
        floor_win: collections.deque = collections.deque(maxlen=NOISE_WIN_BLOCKS)
        pre_roll: collections.deque = collections.deque(maxlen=PRE_ROLL_BLOCKS)
        speech: list[np.ndarray] = []
        in_speech = False
        loud_run = 0
        silent_run = 0
        voiced = 0
        ai_voiced = 0                     # 음성 감지 AI 가 말소리라고 본 블록 수
        last_level_emit = 0.0
        svad = None                       # 음성 감지 AI (준비되면 생성, 감도 바뀌면 다시 생성)
        was_muted = False
        while not self._stop.is_set():
            try:
                block = self._q.get(timeout=0.5)
            except queue.Empty:
                continue
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
            ai = False
            if svad is not None:
                try:
                    ai = svad.feed(block)
                except Exception as ex:
                    log.warning("음성 감지 AI 오류 — 기존 방식으로 전환: %s", ex)
                    self.noise_robust = False
                    svad = None

            e = band_rms(block)
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

            if not in_speech:
                pre_roll.append(block)
                loud_run = loud_run + 1 if loud else 0
                if loud_run >= START_BLOCKS:
                    in_speech = True
                    speech = list(pre_roll)
                    silent_run = 0
                    voiced = loud_run
                    ai_voiced = int(ai)
                    log.debug("발화 시작: 레벨 %.0f / 기준 %.0f / 소음 %.0f / AI %s", e, start_th, noise, ai)
                    self.on_speech_start()
            else:
                speech.append(block)
                if sounding:
                    silent_run = 0
                    voiced += 1
                    ai_voiced += int(ai)
                else:
                    silent_run += 1
                if silent_run >= SILENCE_END_BLOCKS or len(speech) >= MAX_UTTER_BLOCKS:
                    in_speech = False
                    loud_run = 0
                    pre_roll.clear()
                    if voiced >= MIN_SPEECH_BLOCKS:
                        # (전체 PCM, 끝 무음 길이, AI가 말소리를 들었는지) — 화자 판별에는 끝 무음을 뺀 부분만 쓴다
                        self._stt_pool.put((np.concatenate(speech), silent_run * BLOCK,
                                            ai_voiced >= MIN_SPEECH_BLOCKS // 2))
                    else:
                        self.on_utterance(None, None)
                    speech = []

    # ---------- STT ----------
    def _recognize(self, rec, sr, pcm: np.ndarray) -> str | None:
        try:
            text = rec.recognize_google(sr.AudioData(pcm.tobytes(), RATE, 2), language=self.language)
            return None if isinstance(text, (list, dict)) else text
        except sr.UnknownValueError:
            return None
        except sr.RequestError as e:
            log.error("STT 요청 실패: %s", e)
            self.error = "음성 인식 서버에 연결할 수 없습니다 (인터넷 확인)"
            raise
        except OSError as e:   # 네트워크 순간 끊김
            log.warning("STT 연결 끊김: %s", e)
            raise

    def _stt_loop(self) -> None:
        import speech_recognition as sr
        rec = sr.Recognizer()
        while not self._stop.is_set():
            try:
                pcm, tail, ai_heard = self._stt_pool.get(timeout=0.5)
            except queue.Empty:
                continue
            emb_job = None
            if self.embedder is not None:
                emb_job = self._emb_pool.submit(self.embedder, pcm[:max(0, len(pcm) - tail)])
            nm = self.noise_models if self.noise_robust else None
            text = None
            try:
                # 구글 인식기는 소음에 강하게 학습되어 있어 보통은 원본이 더 잘 된다 (시험: 0dB 에서 원본 우세).
                # 원본이 실패했는데 음성 감지 AI 가 분명히 말소리를 들었으면 → 소음을 지워서 한 번 더 시도
                text = self._recognize(rec, sr, prepare_for_stt(pcm))
                if text is None and ai_heard and nm is not None and nm.ready:
                    clean = nm.denoise(pcm)
                    if clean is not pcm:
                        text = self._recognize(rec, sr, prepare_for_stt(clean))
            except (sr.RequestError, OSError):
                text = None
            except Exception as e:
                log.exception("STT 오류: %s", e)
                text = None
            voice = None
            if emb_job is not None:
                try:
                    voice = emb_job.result(timeout=5)
                except Exception as e:
                    log.warning("화자 임베딩 실패: %s", e)
            self.on_utterance(text.strip() if text else None, voice)
