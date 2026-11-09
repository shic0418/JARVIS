"""음성 합성(TTS)과 재생.

- 합성: Microsoft Edge 신경망 음성(edge-tts, 인터넷 필요) → 실패 시 Windows SAPI(오프라인)
- 재생: QMediaPlayer (메인 스레드). QAudioBufferOutput 으로 실제 음량을 읽어 HUD 코어를 맥동시킨다.
"""
from __future__ import annotations

import asyncio
import collections
import logging
import queue
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
        self._q: collections.deque[tuple[bytes, str]] = collections.deque()   # 이어서 재생할 조각
        self._holding = False      # 스트리밍 중: 조각이 더 올 수 있으니 대기열이 비어도 끝내지 않음
        self._session = False      # started 를 보낸 뒤 아직 finished 를 보내지 않음
        self._decay = QTimer(self)
        self._decay.setInterval(33)
        self._decay.timeout.connect(self._tick)
        self._lvl = 0.0
        self._fake_phase = 0.0

    @property
    def playing(self) -> bool:
        """말하는 중 (스트리밍 중 다음 조각을 기다리는 동안도 포함)."""
        return self._playing or self._session

    def play(self, data: bytes, suffix: str) -> None:
        self.stop()
        if not data:
            self.finished.emit()
            return
        self.enqueue(data, suffix)

    # ---- 스트리밍: 문장 조각을 차례로 이어서 재생 ----
    def begin_stream(self) -> None:
        self.stop()
        self._holding = True

    @Slot(bytes, str)
    def enqueue(self, data: bytes, suffix: str) -> None:
        if not data:
            return
        if self._playing:
            self._q.append((data, suffix))
        else:
            self._start(data, suffix)

    def end_stream(self) -> None:
        self._holding = False
        if not self._playing and not self._q:
            self._session = False
            self.finished.emit()     # 이미 다 읽었거나(또는 읽을 것이 없었음) → 끝

    def _start(self, data: bytes, suffix: str) -> None:
        path = TMP / f"say_{uuid.uuid4().hex}{suffix}"
        path.write_bytes(data)
        self._current = path
        self._playing = True
        self.player.setSource(QUrl.fromLocalFile(str(path)))
        self.player.play()
        self._decay.start()
        if not self._session:
            self._session = True
            self.started.emit()

    @Slot()
    def stop(self) -> None:
        self._q.clear()
        self._holding = False
        if self._playing:
            self.player.stop()
            self._finish()
        elif self._session:
            self._session = False
            self.finished.emit()

    def _finish(self) -> None:
        if not self._playing:
            return
        self._playing = False
        self._decay.stop()
        self.level.emit(0.0)
        old = self._current
        self._current = None
        if old:
            self.player.setSource(QUrl())   # 파일 잠금 해제 (새 재생은 이후 _start()에서 설정)
            QTimer.singleShot(2000, lambda p=old: _try_unlink(p))
        if self._q:                         # 다음 조각을 바로 이어서
            data, suffix = self._q.popleft()
            self._start(data, suffix)
            return
        if self._holding:                   # 다음 조각이 아직 합성 중 → 말하는 상태 유지
            return
        self._session = False
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
    _chunk = Signal(int, bytes, str)
    _chunks_done = Signal(int)

    def __init__(self, speaker: Speaker, voice_getter, parent=None) -> None:
        super().__init__(parent)
        self.speaker = speaker
        self.voice_getter = voice_getter   # () -> (voice, rate)
        self._ready.connect(self.speaker.play)
        self._chunk.connect(self._on_chunk)
        self._chunks_done.connect(self._on_chunks_done)
        self._gen = 0
        self._sq: queue.Queue | None = None   # 스트리밍 중인 문장 대기열

    # ---- 스트리밍 (메인 스레드에서 호출) ----
    def stream_begin(self) -> None:
        """문장이 하나씩 도착할 때마다 합성해 이어서 읽는다. 합성은 순서대로 한 번에 하나씩."""
        self._gen += 1
        gen = self._gen
        self.speaker.begin_stream()
        q: queue.Queue = queue.Queue()
        self._sq = q
        voice, rate = self.voice_getter()

        def work():
            while gen == self._gen:
                try:
                    text = q.get(timeout=0.5)
                except queue.Empty:
                    continue
                if text is None:
                    self._chunks_done.emit(gen)
                    return
                try:
                    data, suffix = synthesize(text, voice, rate)
                except Exception as e:
                    log.exception("TTS 실패: %s", e)
                    continue
                if gen == self._gen:
                    self._chunk.emit(gen, data, suffix)

        threading.Thread(target=work, daemon=True, name="tts-stream").start()

    def stream_feed(self, text: str) -> None:
        if self._sq is not None and text.strip():
            self._sq.put(text)

    def stream_end(self) -> None:
        if self._sq is not None:
            self._sq.put(None)
            self._sq = None

    @property
    def streaming(self) -> bool:
        return self._sq is not None

    @Slot(int, bytes, str)
    def _on_chunk(self, gen: int, data: bytes, suffix: str) -> None:
        if gen == self._gen:
            self.speaker.enqueue(data, suffix)

    @Slot(int)
    def _on_chunks_done(self, gen: int) -> None:
        if gen == self._gen:
            self.speaker.end_stream()

    def say(self, text: str) -> None:
        self._sq = None
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
        self._sq = None
        self.speaker.stop()


_SENT_END = re.compile(r"(.+?[.!?…~]+[\"')]?)(?=\s)|(.+?\n)", re.S)   # 뒤에 공백이 와야 문장 끝 ('3.5' 보호)


def split_sentences(buf: str, final: bool = False) -> tuple[list[str], str]:
    """흘러 들어오는 답에서 완성된 문장만 떼어 낸다 → (문장들, 남은 조각).
    너무 짧은 문장('네.')은 다음 문장과 붙여 합성 횟수를 줄이고, 긴 문장은 쉼표에서 끊어 첫 소리를 빨리 낸다."""
    out: list[str] = []
    pending = ""
    pos = 0
    for m in _SENT_END.finditer(buf):
        piece = m.group(0)
        pos = m.end()
        pending += piece
        if len(pending.strip()) >= 8:
            out.append(pending.strip())
            pending = ""
    rest = pending + buf[pos:]
    if not out and len(rest) > 90:            # 마침표 없이 길어지면 쉼표에서 끊기
        cut = max(rest.rfind(", ", 0, 90), rest.rfind("，", 0, 90))
        if cut > 20:
            out.append(rest[:cut + 1].strip())
            rest = rest[cut + 1:]
    if final and rest.strip():
        out.append(rest.strip())
        rest = ""
    return [o for o in out if clean_for_speech(o)], rest
