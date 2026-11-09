"""오프라인 음성 인식 — PC 안에서 한국어 말을 글자로 바꾼다 (인터넷 불필요, 소리가 밖으로 나가지 않음).

모델: SenseVoice Small (int8, 약 230MB, sherpa-onnx 공식 배포본). 처음 쓸 때 data/models/ 로 자동 다운로드.
이 PC 시험(명령 문장 60개, 목소리 3종): 글자 오류율 6.5%, 한 문장 약 0.15초.
Google 웹 인식(오류율 0%, 약 0.6초)보다 덜 정확하지만 빠르고 오프라인으로 동작한다.

listener.py 가 쓰는 방식 ('자동' 모드):
  - 호출어 대기 중: 로컬로만 듣고 '자비스'가 들렸을 때만 Google 로 정확하게 다시 받아 적는다
    → 주변 대화는 PC 밖으로 나가지 않는다
  - 인터넷이 끊기면 로컬 결과를 그대로 쓴다
"""
from __future__ import annotations

import hashlib
import logging
import re
import tarfile
import threading
import time
import urllib.request

import numpy as np

from .noise import MODELS_DIR, _short_path

log = logging.getLogger("jarvis.local_stt")

RATE = 16000
_DIR = MODELS_DIR / "sensevoice"
_URL = ("https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/"
        "sherpa-onnx-sense-voice-zh-en-ja-ko-yue-int8-2024-07-17.tar.bz2")
# 압축 안의 파일 → (저장 이름, sha256)
_FILES = {
    "model.int8.onnx": "c71f0ce00bec95b07744e116345e33d8cbbe08cef896382cf907bf4b51a2cd51",
    "tokens.txt": "f449eb28dc567533d7fa59be34e2abca8784f771850c78a47fb731a31429a1dc",
}
_TAG = re.compile(r"<\|[^|]*\|>")


def _sha256(path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(1 << 20):
            h.update(chunk)
    return h.hexdigest()


def _present() -> bool:
    return all((_DIR / n).exists() for n in _FILES)


def _download() -> None:
    """tar.bz2 를 받으면서 바로 풀어 필요한 두 파일만 꺼낸다 (임시 파일 없이)."""
    _DIR.mkdir(parents=True, exist_ok=True)
    last: Exception | None = None
    for attempt in range(3):
        try:
            req = urllib.request.Request(_URL, headers={"User-Agent": "jarvis-stt"})
            with urllib.request.urlopen(req, timeout=60) as r, tarfile.open(fileobj=r, mode="r|bz2") as tar:
                for m in tar:
                    name = m.name.rsplit("/", 1)[-1]
                    if name not in _FILES or not m.isfile():
                        continue
                    src = tar.extractfile(m)
                    part = _DIR / (name + ".part")
                    with open(part, "wb") as f:
                        while chunk := src.read(1 << 20):
                            f.write(chunk)
                    if _sha256(part) != _FILES[name]:
                        part.unlink(missing_ok=True)
                        raise RuntimeError(f"체크섬 불일치: {name}")
                    part.replace(_DIR / name)
            if not _present():
                raise RuntimeError("압축 파일에 모델이 없습니다")
            log.info("오프라인 음성 인식 모델 다운로드 완료")
            return
        except Exception as e:
            last = e
            log.warning("오프라인 음성 인식 모델 다운로드 실패 (%d/3): %s", attempt + 1, e)
            time.sleep(2 + attempt * 3)
    raise RuntimeError(f"다운로드 실패: {last}")


class LocalSTT:
    """백그라운드에서 모델을 준비한다. ready 전에는 recognize 가 None."""

    def __init__(self, language: str = "ko") -> None:
        self.language = language
        self.state = "off"          # off | loading | ready | error
        self.error = ""
        self.last_ms = 0
        self._rec = None
        self._lock = threading.Lock()

    @property
    def ready(self) -> bool:
        return self.state == "ready"

    def start_loading(self) -> None:
        if self.state in ("loading", "ready"):
            return
        self.state = "loading"
        threading.Thread(target=self._load, daemon=True, name="stt-load").start()

    def _load(self) -> None:
        try:
            import sherpa_onnx
            if not _present():
                log.info("오프라인 음성 인식 모델 내려받는 중 (약 160MB)…")
                _download()
            self._rec = sherpa_onnx.OfflineRecognizer.from_sense_voice(
                model=_short_path(_DIR / "model.int8.onnx"), tokens=_short_path(_DIR / "tokens.txt"),
                language=self.language, use_itn=True, num_threads=4)
            self.recognize(np.zeros(RATE // 2, np.int16))      # 예열
            self.state = "ready"
            log.info("오프라인 음성 인식 준비 완료 (SenseVoice)")
        except Exception as e:
            self.state, self.error = "error", str(e)[:160]
            log.warning("오프라인 음성 인식 준비 실패 — Google 인식만 사용: %s", e)

    def recognize(self, pcm: np.ndarray) -> str | None:
        """int16 16kHz PCM → 텍스트 (못 알아들으면 None)."""
        rec = self._rec
        if rec is None or len(pcm) < RATE // 5:
            return None
        t0 = time.perf_counter()
        # 앞뒤 무음을 조금 붙이면 첫 글자·끝 글자를 덜 놓친다
        x = np.concatenate([np.zeros(RATE // 8, np.float32), pcm.astype(np.float32) / 32768.0,
                            np.zeros(RATE // 8, np.float32)])
        with self._lock:
            s = rec.create_stream()
            s.accept_waveform(RATE, x)
            rec.decode_stream(s)
            text = s.result.text
        self.last_ms = int((time.perf_counter() - t0) * 1000)
        return clean(text)


def clean(text: str) -> str | None:
    t = _TAG.sub("", text or "")
    t = re.sub(r"[.。,!?~]+$", "", t.strip()).strip()
    # 한글·영문·숫자가 하나도 없으면(잡음을 다른 언어 글자로 적은 경우) 버린다
    if not re.search(r"[가-힣A-Za-z0-9]", t):
        return None
    return t
