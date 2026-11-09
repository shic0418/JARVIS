"""음성 합성(TTS)과 재생.

- 합성: Microsoft Edge 신경망 음성(edge-tts, 인터넷 필요) → 실패 시 Windows SAPI(오프라인)
- 재생: QMediaPlayer (메인 스레드). QAudioBufferOutput 으로 실제 음량을 읽어 HUD 코어를 맥동시킨다.
"""
from __future__ import annotations

import asyncio
import logging
import re
import tempfile
import threading
import uuid
from pathlib import Path

import numpy as np
from PySide6.QtCore import QObject, QTimer, QUrl, Signal, Slot
from PySide6.QtMultimedia import (QAudioBufferOutput, QAudioFormat, QAudioOutput,
                                  QMediaPlayer)

log = logging.getLogger("jarvis.speech")
TMP = Path(tempfile.gettempdir()) / "jarvis_tts"
TMP.mkdir(exist_ok=True)


def _try_unlink(p: Path) -> None:
    try:
        p.unlink(missing_ok=True)
    except OSError:
        pass   # 아직 사용 중이면 다음 실행 때 정리


for _old in TMP.glob("*"):   # 지난 실행에서 남은 음성 파일 정리
    _try_unlink(_old)


def clean_for_speech(text: str) -> str:
    """마크다운/URL/이모지 등 읽기 어색한 것 제거."""
    text = re.sub(r"https?://\S+", "링크", text)
    text = re.sub(r"[*_`#>|~]+", "", text)
    text = re.sub(r"\[(.*?)\]\(.*?\)", r"\1", text)
    text = re.sub(r"[\U0001F000-\U0001FAFF☀-➿]", "", text)
    return re.sub(r"\s+", " ", text).strip()


def synthesize(text: str, voice: str, rate: str) -> tuple[bytes, str]:
    """(오디오 바이트, 확장자) 반환. 워커 스레드에서 호출."""
    text = clean_for_speech(text)
    if not text:
        return b"", ".mp3"
    try:
        return _edge_tts(text, voice, rate), ".mp3"
    except Exception as e:
        log.warning("edge-tts 실패, SAPI로 대체: %s", e)
    return _sapi(text), ".wav"


def _edge_tts(text: str, voice: str, rate: str) -> bytes:
    import edge_tts

    async def run() -> bytes:
        comm = edge_tts.Communicate(text, voice, rate=rate)
        buf = bytearray()
        async for chunk in comm.stream():
            if chunk.get("type") == "audio":
                buf += chunk["data"]
        return bytes(buf)

    data = asyncio.run(asyncio.wait_for(run(), timeout=15))
    if not data:
        raise RuntimeError("빈 오디오")
    return data


def _sapi(text: str) -> bytes:
    import pythoncom
    import win32com.client

    pythoncom.CoInitialize()
    try:
        sp = win32com.client.Dispatch("SAPI.SpVoice")
        for v in sp.GetVoices():
            desc = v.GetDescription()
            if "Korean" in desc or "한국어" in desc or "Heami" in desc:
                sp.Voice = v
                break
        path = TMP / f"sapi_{uuid.uuid4().hex}.wav"
        stream = win32com.client.Dispatch("SAPI.SpFileStream")
        stream.Open(str(path), 3)
        sp.AudioOutputStream = stream
        sp.Speak(text)
        stream.Close()
        data = path.read_bytes()
        path.unlink(missing_ok=True)
        return data
    finally:
        pythoncom.CoUninitialize()


class Speaker(QObject):
    """메인 스레드 전용 재생기."""
    level = Signal(float)
    started = Signal()
    finished = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.player = QMediaPlayer(self)
        self.output = QAudioOutput(self)
        self.output.setVolume(1.0)
        self.player.setAudioOutput(self.output)
        self._has_buffer = False
        try:
            fmt = QAudioFormat()
            fmt.setSampleRate(16000)
            fmt.setChannelCount(1)
            fmt.setSampleFormat(QAudioFormat.SampleFormat.Float)
            self.buf_out = QAudioBufferOutput(fmt, self)
            self.player.setAudioBufferOutput(self.buf_out)
            self.buf_out.audioBufferReceived.connect(self._on_buffer)
            self._has_buffer = True
        except Exception as e:  # 구버전 Qt
            log.warning("QAudioBufferOutput 사용 불가: %s", e)
        self.player.mediaStatusChanged.connect(self._on_status)
        self.player.errorOccurred.connect(self._on_error)
        self._playing = False
        self._current: Path | None = None
        self._decay = QTimer(self)
        self._decay.setInterval(33)
        self._decay.timeout.connect(self._tick)
        self._lvl = 0.0
        self._fake_phase = 0.0

    @property
    def playing(self) -> bool:
        return self._playing

    def play(self, data: bytes, suffix: str) -> None:
        self.stop()
        if not data:
            self.finished.emit()
            return
        path = TMP / f"say_{uuid.uuid4().hex}{suffix}"
        path.write_bytes(data)
        self._current = path
        self._playing = True
        self.player.setSource(QUrl.fromLocalFile(str(path)))
        self.player.play()
        self._decay.start()
        self.started.emit()

    @Slot()
    def stop(self) -> None:
        if self._playing:
            self.player.stop()
            self._finish()

    def _finish(self) -> None:
        if not self._playing:
            return
        self._playing = False
        self._decay.stop()
        self.level.emit(0.0)
        old = self._current
        self._current = None
        if old:
            self.player.setSource(QUrl())   # 파일 잠금 해제 (새 재생은 이후 play()에서 설정)
            QTimer.singleShot(2000, lambda p=old: _try_unlink(p))
        self.finished.emit()

    def _on_status(self, status) -> None:
        if status in (QMediaPlayer.MediaStatus.EndOfMedia, QMediaPlayer.MediaStatus.InvalidMedia):
            self._finish()

    def _on_error(self, err, msg="") -> None:
        log.error("재생 오류: %s %s", err, msg)
        self._finish()

    def _on_buffer(self, buf) -> None:
        try:
            raw = buf.constData()
            arr = np.frombuffer(bytes(raw), dtype=np.float32)
            if arr.size:
                rms = float(np.sqrt(np.mean(arr * arr)))
                self._lvl = max(self._lvl * 0.6, min(1.0, rms * 2.8))
        except Exception:
            self._has_buffer = False

    def _tick(self) -> None:
        if not self._has_buffer:  # 실제 레벨을 못 읽으면 자연스러운 가짜 파형
            self._fake_phase += 0.33
            self._lvl = 0.35 + 0.3 * abs(np.sin(self._fake_phase)) * abs(np.sin(self._fake_phase * 0.37))
        self.level.emit(self._lvl)
        self._lvl *= 0.85


class TTS(QObject):
    """텍스트 → (워커에서 합성) → 메인 스레드 재생."""
    _ready = Signal(bytes, str)

    def __init__(self, speaker: Speaker, voice_getter, parent=None) -> None:
        super().__init__(parent)
        self.speaker = speaker
        self.voice_getter = voice_getter   # () -> (voice, rate)
        self._ready.connect(self.speaker.play)
        self._gen = 0

    def say(self, text: str) -> None:
        self._gen += 1
        gen = self._gen
        voice, rate = self.voice_getter()

        def work():
            try:
                data, suffix = synthesize(text, voice, rate)
            except Exception as e:
                log.exception("TTS 실패: %s", e)
                data, suffix = b"", ".mp3"
            if gen == self._gen:  # 그 사이 새 발화/중단이 없을 때만 재생
                self._ready.emit(data, suffix)

        threading.Thread(target=work, daemon=True, name="tts").start()

    def cancel(self) -> None:
        self._gen += 1
        self.speaker.stop()
