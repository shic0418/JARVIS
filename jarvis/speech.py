"""음성 합성(TTS)과 재생.

- 합성: Microsoft Edge 신경망 음성(edge-tts, 인터넷 필요) → 실패 시 Windows SAPI(오프라인)
- 다듬기: 합성된 조각마다 앞 ~0.3초·뒤 ~1.1초의 무음이 붙어 오므로 잘라 내고, 문장 사이엔 사람처럼 짧게만 쉰다.
- 재생: 하나의 출력 스트림(sounddevice)에 조각을 끊김 없이 이어 붙인다. 내보내는 소리의 실제 음량으로 HUD 코어를 맥동시킨다.
"""
from __future__ import annotations

import asyncio
import collections
import logging
import queue
import re
import tempfile
import threading
import time
import uuid
from pathlib import Path

import numpy as np
from PySide6.QtCore import QEventLoop, QObject, QTimer, QUrl, Signal, Slot
from PySide6.QtMultimedia import QAudioDecoder, QAudioFormat

log = logging.getLogger("jarvis.speech")
TMP = Path(tempfile.gettempdir()) / "jarvis_tts"
TMP.mkdir(exist_ok=True)
SR = 24000            # edge-tts 원음과 같은 표본율 (SAPI 음성도 이 값으로 맞춰 디코딩)


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


EDGE_TIMEOUT_SEC = 8       # 보통 1~2초면 끝난다. 이보다 오래 걸리면 연결이 안 되는 것
EDGE_RETRY_SEC = 90        # 실패한 뒤 이 시간 동안은 바로 오프라인 음성(SAPI)으로 읽는다
_edge_down_until = 0.0


def synthesize(text: str, voice: str, rate: str) -> tuple[bytes, str]:
    """(오디오 바이트, 확장자) 반환. 워커 스레드에서 호출.
    edge-tts 가 실패하면 한동안은 시도하지 않고 바로 SAPI 로 읽는다
    (기록: 인터넷이 불안할 때 문장마다 15초씩 기다린 뒤에야 소리가 남)."""
    global _edge_down_until
    text = clean_for_speech(text)
    if not text:
        return b"", ".mp3"
    if time.monotonic() >= _edge_down_until:
        try:
            return _edge_tts(text, voice, rate), ".mp3"
        except Exception as e:
            _edge_down_until = time.monotonic() + EDGE_RETRY_SEC
            log.warning("edge-tts 실패 (%s) — %d초 동안 오프라인 음성(SAPI)으로 읽습니다",
                        str(e) or type(e).__name__, EDGE_RETRY_SEC)
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

    data = asyncio.run(asyncio.wait_for(run(), timeout=EDGE_TIMEOUT_SEC))
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


def _buffer_to_mono(buf) -> np.ndarray:
    fmt = buf.format()
    raw = bytes(buf.constData())
    sf = fmt.sampleFormat()
    if sf == QAudioFormat.SampleFormat.Float:
        a = np.frombuffer(raw, np.float32)
    elif sf == QAudioFormat.SampleFormat.Int16:
        a = np.frombuffer(raw, np.int16).astype(np.float32) / 32768.0
    elif sf == QAudioFormat.SampleFormat.Int32:
        a = np.frombuffer(raw, np.int32).astype(np.float32) / 2147483648.0
    else:  # UInt8
        a = (np.frombuffer(raw, np.uint8).astype(np.float32) - 128.0) / 128.0
    ch = max(1, fmt.channelCount())
    if ch > 1:
        a = a[: a.size // ch * ch].reshape(-1, ch).mean(axis=1)
    sr = fmt.sampleRate()
    if sr and sr != SR and a.size:
        n = int(round(a.size * SR / sr))
        a = np.interp(np.linspace(0, a.size - 1, n), np.arange(a.size), a)
    return a.astype(np.float32, copy=True)


def decode(data: bytes, suffix: str) -> np.ndarray:
    """압축된 음성 → 24kHz 모노 float32. 워커 스레드에서 호출 (자체 이벤트 루프를 돌린다)."""
    if not data:
        return np.zeros(0, np.float32)
    path = TMP / f"dec_{uuid.uuid4().hex}{suffix}"
    path.write_bytes(data)
    try:
        loop = QEventLoop()
        dec = QAudioDecoder()
        fmt = QAudioFormat()
        fmt.setSampleRate(SR)
        fmt.setChannelCount(1)
        fmt.setSampleFormat(QAudioFormat.SampleFormat.Float)
        dec.setAudioFormat(fmt)
        dec.setSource(QUrl.fromLocalFile(str(path)))
        parts: list[np.ndarray] = []
        errors: list[str] = []

        def on_buffer() -> None:
            b = dec.read()
            if b.isValid():
                parts.append(_buffer_to_mono(b))

        def on_error(_e) -> None:
            errors.append(dec.errorString())
            loop.quit()

        dec.bufferReady.connect(on_buffer)
        dec.finished.connect(loop.quit)
        dec.error.connect(on_error)
        guard = QTimer()
        guard.setSingleShot(True)
        guard.timeout.connect(loop.quit)
        guard.start(10000)
        dec.start()
        loop.exec()
        dec.stop()
        if not parts:
            raise RuntimeError(errors[0] if errors else "디코딩 결과 없음")
        return np.concatenate(parts)
    finally:
        _try_unlink(path)


def trim_silence(a: np.ndarray, lead: float = 0.02, tail: float = 0.09) -> np.ndarray:
    """앞뒤 무음을 잘라 내고(말소리 앞 lead 초, 뒤 tail 초만 남김) 잘린 자리에 짧은 페이드를 준다."""
    if a.size == 0:
        return a
    hop = SR // 100                                   # 10ms 단위로 음량을 본다
    n = a.size // hop
    if n == 0:
        return a
    rms = np.sqrt(np.mean(a[: n * hop].reshape(n, hop) ** 2, axis=1))
    voiced = np.nonzero(rms > 0.006)[0]
    if voiced.size == 0:
        return np.zeros(0, np.float32)
    start = max(0, int(voiced[0]) * hop - int(lead * SR))
    end = min(a.size, (int(voiced[-1]) + 1) * hop + int(tail * SR))
    out = a[start:end].astype(np.float32, copy=True)
    f = min(out.size // 2, int(0.004 * SR))
    if f:
        ramp = np.linspace(0.0, 1.0, f, dtype=np.float32)
        out[:f] *= ramp
        out[-f:] *= ramp[::-1]
    return out


def pause_after(text: str) -> float:
    """이 조각 다음에 쉴 시간(초). 문장 끝은 숨 한 번, 쉼표에서 끊긴 곳은 아주 짧게."""
    t = text.rstrip(" \"')”’")
    if not t:
        return 0.2
    if t[-1] in ".!?…~。":
        return 0.32
    if t[-1] in ",，、":
        return 0.14
    return 0.22


def render(text: str, voice: str, rate: str) -> np.ndarray:
    """텍스트 → 재생할 PCM (앞뒤 무음 정리 완료). 워커 스레드에서 호출."""
    data, suffix = synthesize(text, voice, rate)
    if not data:
        return np.zeros(0, np.float32)
    return trim_silence(decode(data, suffix))


class Speaker(QObject):
    """하나의 출력 스트림에 음성 조각을 끊김 없이 이어 재생한다. 공개 메서드는 메인 스레드 전용."""
    level = Signal(float)
    started = Signal()
    finished = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._lock = threading.Lock()
        self._q: collections.deque[np.ndarray] = collections.deque()   # 아직 내보내지 않은 조각
        self._cur: np.ndarray | None = None
        self._pos = 0
        self._dry_since: float | None = None   # 출력 콜백이 마지막 소리를 다 내보낸 시각
        self._stream = None
        self._latency = 0.2
        self._holding = False      # 스트리밍 중: 조각이 더 올 수 있으니 대기열이 비어도 끝내지 않음
        self._session = False      # started 를 보낸 뒤 아직 finished 를 보내지 않음
        self._gap = 0.0            # 다음 조각 앞에 둘 쉼(초)
        self._out_lvl = 0.0
        self._timer = QTimer(self)
        self._timer.setInterval(33)
        self._timer.timeout.connect(self._tick)

    @property
    def playing(self) -> bool:
        """말하는 중 (스트리밍 중 다음 조각을 기다리는 동안도 포함)."""
        return self._session

    @Slot(object, float)
    def play(self, pcm, gap: float = 0.0) -> None:
        self.stop()
        if pcm is None or not len(pcm):
            self.finished.emit()
            return
        self.enqueue(pcm, gap)

    # ---- 스트리밍: 문장 조각을 차례로 이어서 재생 ----
    def begin_stream(self) -> None:
        self.stop()
        self._holding = True

    def enqueue(self, pcm, gap: float = 0.0) -> None:
        if pcm is None or not len(pcm):
            return
        pcm = np.asarray(pcm, dtype=np.float32)
        if not self._session:
            with self._lock:
                self._q.clear()
                self._cur, self._pos, self._dry_since = None, 0, None
                self._q.append(pcm)
            if not self._open():
                with self._lock:
                    self._q.clear()
                if not self._holding:
                    self.finished.emit()
                return
            self._session = True
            self._timer.start()
            self.started.emit()
        else:
            with self._lock:
                dry = self._dry_since
                waited = time.monotonic() - dry if dry is not None else 0.0
                lead = self._gap - waited      # 다음 조각을 기다리느라 이미 쉰 만큼은 빼고
                if lead > 0.01:
                    self._q.append(np.zeros(int(lead * SR), np.float32))
                self._q.append(pcm)
                self._dry_since = None
        self._gap = gap

    def end_stream(self) -> None:
        self._holding = False
        if not self._session:
            self.finished.emit()     # 읽을 것이 없었음 → 끝 (읽는 중이면 다 읽은 뒤 _tick 이 끝낸다)

    @Slot()
    def stop(self) -> None:
        self._holding = False
        with self._lock:
            self._q.clear()
            self._cur = None
        if self._session:
            self._end()

    # ---- 내부 ----
    def _open(self) -> bool:
        try:
            import sounddevice as sd
            self._stream = sd.OutputStream(samplerate=SR, channels=1, dtype="float32",
                                           callback=self._callback)
            self._latency = float(getattr(self._stream, "latency", 0.2) or 0.2)
            self._stream.start()
            return True
        except Exception as e:
            log.error("스피커를 열 수 없습니다: %s", e)
            self._close()
            return False

    def _close(self) -> None:
        st, self._stream = self._stream, None
        if st is not None:
            try:
                st.abort()
                st.close()
            except Exception:
                pass

    def _end(self) -> None:
        self._close()
        self._timer.stop()
        self._session = False
        self._out_lvl = 0.0
        self.level.emit(0.0)
        self.finished.emit()

    def _callback(self, outdata, frames, time_info, status) -> None:
        out = outdata[:, 0]
        filled = 0
        with self._lock:
            while filled < frames:
                if self._cur is None:
                    if not self._q:
                        break
                    self._cur, self._pos = self._q.popleft(), 0
                n = min(frames - filled, self._cur.size - self._pos)
                out[filled:filled + n] = self._cur[self._pos:self._pos + n]
                filled += n
                self._pos += n
                if self._pos >= self._cur.size:
                    self._cur = None
            if filled < frames:
                out[filled:] = 0.0
                if self._dry_since is None:
                    self._dry_since = time.monotonic()
        if filled:
            seg = out[:filled]
            rms = float(np.sqrt(np.mean(seg * seg)))
            self._out_lvl = max(self._out_lvl * 0.6, min(1.0, rms * 2.8))

    def _tick(self) -> None:
        self.level.emit(self._out_lvl)
        self._out_lvl *= 0.85
        if not self._session:
            return
        st = self._stream
        if st is None or not st.active:            # 장치가 빠지는 등 스트림이 멈춤 → 끝낸 것으로
            self._holding = False
            self._end()
            return
        if self._holding:
            return
        with self._lock:
            idle = self._cur is None and not self._q
            dry = self._dry_since
        # 마지막 소리가 장치 버퍼를 다 빠져나갈 때까지 기다렸다가 닫는다 (끝음절 잘림 방지)
        if idle and dry is not None and time.monotonic() - dry > self._latency + 0.08:
            self._end()


class TTS(QObject):
    """텍스트 → (워커에서 합성·디코딩) → 메인 스레드 재생."""
    _ready = Signal(object, float)
    _chunk = Signal(int, object, float)
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
                    pcm = render(text, voice, rate)
                except Exception as e:
                    log.exception("TTS 실패: %s", e)
                    continue
                if gen == self._gen:
                    self._chunk.emit(gen, pcm, pause_after(text))

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

    @Slot(int, object, float)
    def _on_chunk(self, gen: int, pcm, gap: float) -> None:
        if gen == self._gen:
            self.speaker.enqueue(pcm, gap)

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
                pcm = render(text, voice, rate)
            except Exception as e:
                log.exception("TTS 실패: %s", e)
                pcm = np.zeros(0, np.float32)
            if gen == self._gen:  # 그 사이 새 발화/중단이 없을 때만 재생
                self._ready.emit(pcm, 0.0)

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
