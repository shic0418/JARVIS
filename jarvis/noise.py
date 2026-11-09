"""시끄러운 환경에서 작은 목소리 듣기 — 음성 감지 AI + 소음 제거 AI (오프라인, CPU).

- Silero VAD : 소리 '크기'가 아니라 '사람 말소리 모양'으로 판단한다.
               선풍기·에어컨·차 소리·키보드보다 작게 말해도 잡아낸다.
- GTCRN      : 배경 소음을 지운다. ① 실시간으로 지운 소리로 한 번 더 음성 감지(소음보다 작은 목소리용)
               ② 원본 인식이 실패했을 때 지운 소리로 다시 인식

두 모델(합계 약 1.2MB)은 sherpa-onnx 공식 배포본이며 data/models/ 에 저장된다.
없으면 처음 실행 때 내려받고 SHA-256 으로 검증한다. 준비 전·실패 시에는 기존 에너지 방식으로 동작한다.
"""
from __future__ import annotations

import hashlib
import logging
import threading
import time
import urllib.request

import numpy as np

from .config import DATA_DIR

log = logging.getLogger("jarvis.noise")

RATE = 16000
MODELS_DIR = DATA_DIR / "models"
_BASE = "https://github.com/k2-fsa/sherpa-onnx/releases/download"
VAD_FILE = ("silero_vad.onnx", f"{_BASE}/asr-models/silero_vad.onnx",
            "9e2449e1087496d8d4caba907f23e0bd3f78d91fa552479bb9c23ac09cbb1fd6")
DENOISE_FILE = ("gtcrn_simple.onnx", f"{_BASE}/speech-enhancement-models/gtcrn_simple.onnx",
                "e77603ac0c23dac3227dd2d7135b3a585cbee2679048aecfa886657d3ae1b534")

PRE_GAIN_PEAK = 12000.0      # 소음 제거 전에 작은 목소리를 이 정도까지 키워 둔다 (작은 말이 소음으로 지워지지 않도록)
PRE_GAIN_MAX = 8.0


def vad_threshold(sensitivity: float) -> float:
    """감도 1.0 → 0.45, 2.0 → 0.30, 3.0 → 0.25(하한). 낮을수록 작은/흐린 말소리도 말로 본다."""
    return float(min(0.65, max(0.25, 0.45 - 0.15 * (sensitivity - 1.0))))


def _short_path(p) -> str:
    s = str(p)
    if s.isascii():
        return s
    try:
        import win32api
        return win32api.GetShortPathName(s)
    except Exception:
        return s


def _ensure(name: str, url: str, sha256: str):
    path = MODELS_DIR / name
    if path.exists():
        return path
    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    part = path.with_suffix(".part")
    last: Exception | None = None
    for attempt in range(4):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "jarvis-noise"})
            h = hashlib.sha256()
            with urllib.request.urlopen(req, timeout=30) as r, open(part, "wb") as f:
                while chunk := r.read(1 << 16):
                    f.write(chunk)
                    h.update(chunk)
            if h.hexdigest() != sha256:
                raise RuntimeError("체크섬 불일치")
            part.replace(path)
            log.info("모델 다운로드 완료: %s", name)
            return path
        except Exception as e:
            last = e
            part.unlink(missing_ok=True)
            log.warning("모델 다운로드 실패 (%s, %d/4): %s", name, attempt + 1, e)
            time.sleep(1 + attempt * 2)
    raise RuntimeError(f"{name} 다운로드 실패: {last}")


class StreamVad:
    """30ms 블록 단위로 넣으면 '지금 말소리가 들리는지'를 알려 준다. VAD 스레드 전용.

    두 갈래로 판단해 하나라도 말소리면 True:
      ① 원본 소리 → 음성 감지 AI          (소음이 작을 때 가장 정확)
      ② 실시간 소음 제거 → 음성 감지 AI   (목소리가 소음보다 작을 때도 잡음, 블록당 약 2ms)
    """

    def __init__(self, model_path: str, threshold: float, denoise_path: str | None = None) -> None:
        self.threshold = threshold
        self._raw = self._make(model_path, threshold)
        self._clean = None
        self._den = None
        if denoise_path:
            import sherpa_onnx
            cfg = sherpa_onnx.OnlineSpeechDenoiserConfig(
                model=sherpa_onnx.OfflineSpeechDenoiserModelConfig(
                    gtcrn=sherpa_onnx.OfflineSpeechDenoiserGtcrnModelConfig(model=denoise_path),
                    num_threads=1))
            if cfg.validate():
                self._den = sherpa_onnx.OnlineSpeechDenoiser(cfg)
                self._clean = self._make(model_path, threshold)

    @staticmethod
    def _make(model_path: str, threshold: float):
        import sherpa_onnx
        c = sherpa_onnx.VadModelConfig()
        c.silero_vad.model = model_path
        c.silero_vad.threshold = threshold
        c.silero_vad.min_speech_duration = 0.1    # 짧은 '자비스' 도 놓치지 않게
        c.silero_vad.min_silence_duration = 0.15  # 발화 끝 판단은 listener 가 따로 한다
        c.silero_vad.max_speech_duration = 30
        c.sample_rate = RATE
        c.num_threads = 1
        if not c.validate():
            raise RuntimeError("VAD 설정 오류")
        return sherpa_onnx.VoiceActivityDetector(c, buffer_size_in_seconds=60)

    @staticmethod
    def _step(v, x: np.ndarray) -> bool:
        if len(x):
            v.accept_waveform(x)
        speech = bool(v.is_speech_detected())
        while not v.empty():           # 잘라 둔 구간은 쓰지 않으므로 버려서 메모리 누적 방지
            v.pop()
        return speech

    def feed(self, block: np.ndarray) -> bool:
        x = block.astype(np.float32) / 32768.0
        speech = self._step(self._raw, x)
        if self._den is not None:
            y = np.asarray(self._den.run(x, RATE).samples, dtype=np.float32)
            speech = self._step(self._clean, y) or speech
        return speech

    def reset(self) -> None:
        self._raw.reset()
        if self._den is not None:
            self._den.reset()
            self._clean.reset()


class NoiseModels:
    """백그라운드에서 두 모델을 준비한다. ready 전에는 vad_path/denoise 가 None/원본을 돌려준다."""

    def __init__(self) -> None:
        self.state = "off"           # off | loading | ready | error
        self.error = ""
        self.vad_path: str | None = None
        self.denoise_path: str | None = None
        self._den = None
        self._den_lock = threading.Lock()

    @property
    def ready(self) -> bool:
        return self.state == "ready"

    def start_loading(self) -> None:
        if self.state in ("loading", "ready"):
            return
        self.state = "loading"
        threading.Thread(target=self._load, daemon=True, name="noise-load").start()

    def _load(self) -> None:
        try:
            import sherpa_onnx
            vad = _ensure(*VAD_FILE)
            den = _ensure(*DENOISE_FILE)
            StreamVad(_short_path(vad), 0.5, _short_path(den))   # 열리는지 확인
            cfg = sherpa_onnx.OfflineSpeechDenoiserConfig(
                model=sherpa_onnx.OfflineSpeechDenoiserModelConfig(
                    gtcrn=sherpa_onnx.OfflineSpeechDenoiserGtcrnModelConfig(model=_short_path(den)),
                    num_threads=2))
            if not cfg.validate():
                raise RuntimeError("소음 제거 설정 오류")
            self._den = sherpa_onnx.OfflineSpeechDenoiser(cfg)
            self.vad_path = _short_path(vad)
            self.denoise_path = _short_path(den)
            self.state = "ready"
            log.info("소음 환경 모델 준비 완료 (음성 감지 + 소음 제거)")
        except Exception as e:
            self.state, self.error = "error", str(e)[:160]
            log.warning("소음 환경 모델 준비 실패 — 기존 방식으로 동작: %s", e)

    def denoise(self, pcm: np.ndarray) -> np.ndarray:
        """int16 PCM → 소음을 지운 int16 PCM (같은 길이). 준비 전/실패 시 원본."""
        if not self.ready or self._den is None or len(pcm) < RATE // 4:
            return pcm
        x = pcm.astype(np.float32)
        peak = float(np.percentile(np.abs(x), 99.9))
        if peak >= 1.0:
            x *= min(PRE_GAIN_MAX, max(1.0, PRE_GAIN_PEAK / peak))
        try:
            with self._den_lock:
                out = self._den(np.clip(x, -32767, 32767) / 32768.0, RATE)
            y = np.asarray(out.samples, dtype=np.float32) * 32768.0
        except Exception as e:
            log.warning("소음 제거 실패: %s", e)
            return pcm
        if len(y) < len(pcm):
            y = np.pad(y, (0, len(pcm) - len(y)))
        return np.clip(y[:len(pcm)], -32767, 32767).astype(np.int16)
