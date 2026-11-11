"""오케스트레이터: 음성 → 두뇌 → 행동 → 음성 흐름과 HUD/트레이/단축키를 연결한다."""
from __future__ import annotations

import json
import logging
import math
import os
import re
import sys
import tempfile
import threading
import time
import uuid
import wave
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import psutil
from PySide6.QtCore import (Property, QObject, QPointF, QRect, QTimer, QUrl, Signal,
                            Slot)
from PySide6.QtGui import (QAction, QColor, QGuiApplication, QIcon, QPainter, QPen,
                           QPixmap, QRadialGradient)
from PySide6.QtMultimedia import QSoundEffect
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuick import QQuickWindow  # noqa: F401  (루트 객체를 QQuickWindow 로 받기 위해 필요)
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

from . import approval, hearing, hud_feed, winutil
from .brain import _SOURCES, Brain, situation_text
from .config import DATA_DIR, ROOT, UI_DIR, Config
from .hotkey import GlobalHotkey
from .listener import FILTERED, Listener
from .local_stt import LocalSTT
from .noise import NoiseModels
from .speech import TTS, Speaker, split_sentences
from .tools import Hooks, PCTools
from .toolserver import ToolServer
from .voiceid import Enrollment, SpeakerGate, VoiceID, VoiceProfile

log = logging.getLogger("jarvis.app")

EXPANDED = (420, 724)
COMPACT = (230, 356)     # 엠블럼 + 상태 + 채팅 입력 + 마지막 대답
MARGIN = 14

CANCEL_RE = re.compile(r"(취소|그만|멈춰|중지|스톱|stop)", re.I)


def _ro(name: str, typ, sig):
    return Property(typ, lambda self: getattr(self, "_" + name), notify=sig)


class Bridge(QObject):
    """QML 에 노출되는 객체 (QML 에서는 `jarvis`)."""
    stateChanged = Signal()
    statusTextChanged = Signal()
    micLevelChanged = Signal()
    voiceLevelChanged = Signal()
    userTextChanged = Signal()
    replyTextChanged = Signal()
    wakeEnabledChanged = Signal()
    compactChanged = Signal()
    hasApiKeyChanged = Signal()
    statsJsonChanged = Signal()
    hotkeyTextChanged = Signal()
    modelNameChanged = Signal()
    linkTextChanged = Signal()
    voiceStatusChanged = Signal()
    voiceEnrolledChanged = Signal()
    chatModeChanged = Signal()
    activeModeChanged = Signal()
    timersJsonChanged = Signal()
    weatherJsonChanged = Signal()
    targetJsonChanged = Signal()

    actionEvent = Signal(str, str, str, str)     # id, label, status(run|ok|error), detail
    confirmRequest = Signal(str, str, str)       # id, title, detail
    confirmClosed = Signal(str)
    toast = Signal(str, str)                     # level(info|warn|error), text

    state = _ro("state", str, stateChanged)
    statusText = _ro("statusText", str, statusTextChanged)
    micLevel = _ro("micLevel", float, micLevelChanged)
    voiceLevel = _ro("voiceLevel", float, voiceLevelChanged)
    userText = _ro("userText", str, userTextChanged)
    replyText = _ro("replyText", str, replyTextChanged)
    wakeEnabled = _ro("wakeEnabled", bool, wakeEnabledChanged)
    compact = _ro("compact", bool, compactChanged)
    hasApiKey = _ro("hasApiKey", bool, hasApiKeyChanged)
    statsJson = _ro("statsJson", str, statsJsonChanged)
    hotkeyText = _ro("hotkeyText", str, hotkeyTextChanged)
    modelName = _ro("modelName", str, modelNameChanged)
    linkText = _ro("linkText", str, linkTextChanged)
    voiceStatus = _ro("voiceStatus", str, voiceStatusChanged)
    voiceEnrolled = _ro("voiceEnrolled", bool, voiceEnrolledChanged)
    chatMode = _ro("chatMode", bool, chatModeChanged)
    activeMode = _ro("activeMode", bool, activeModeChanged)
    timersJson = _ro("timersJson", str, timersJsonChanged)      # 돌고 있는 타이머 [{label, end(ms), total(s)}]
    weatherJson = _ro("weatherJson", str, weatherJsonChanged)   # 액티브 모드: 날씨
    targetJson = _ro("targetJson", str, targetJsonChanged)      # 액티브 모드: 추적 박스 (지금 창 / 짚은 위치)

    def __init__(self, core: "Jarvis") -> None:
        super().__init__()
        self.core = core
        self._state = "boot"
        self._statusText = "INITIALIZING"
        self._micLevel = 0.0
        self._voiceLevel = 0.0
        self._userText = ""
        self._replyText = ""
        self._wakeEnabled = True
        self._compact = False
        self._hasApiKey = False
        self._statsJson = "{}"
        self._hotkeyText = ""
        self._modelName = ""
        self._linkText = ""
        self._voiceStatus = ""
        self._voiceEnrolled = False
        self._chatMode = False
        self._activeMode = False
        self._timersJson = "[]"
        self._weatherJson = "{}"
        self._targetJson = "{}"

    def set(self, name: str, value) -> None:
        if getattr(self, "_" + name) != value:
            setattr(self, "_" + name, value)
            getattr(self, name + "Changed").emit()

    # ---- QML → Python ----
    @Slot(str, result=bool)
    def submitText(self, text: str) -> bool:
        """글로 친 명령. 받아들였으면 True (처리 중이라 못 받았으면 False → 입력창이 글을 남겨 둔다)."""
        return self.core.run_command(text)

    @Slot()
    def releaseFocus(self) -> None:
        """입력창에서 Esc: 키보드 포커스를 사용자의 작업 창으로 돌려준다."""
        self.core.focus.restore()

    @Slot()
    def activate(self) -> None:
        self.core.activate()

    @Slot(bool)
    def setWake(self, on: bool) -> None:
        self.core.set_wake(on)

    @Slot(str, bool)
    def answerConfirm(self, cid: str, approved: bool) -> None:
        self.core.answer_confirm(cid, approved)

    @Slot(result=str)
    def settingsJson(self) -> str:
        out = self.core.cfg.public()
        out["stt_status"] = self.core.stt_status()
        out["mic_status"] = self.core.listener.frontend_status() if self.core.mic_ok else ""
        return json.dumps(out, ensure_ascii=False)

    @Slot(str)
    def saveSettings(self, payload: str) -> None:
        self.core.save_settings(json.loads(payload))

    @Slot()
    def startEnroll(self) -> None:
        self.core.start_enroll()

    @Slot()
    def clearVoice(self) -> None:
        self.core.clear_voice()

    @Slot(bool)
    def setCompact(self, on: bool) -> None:
        self.core.set_compact(on)

    @Slot()
    def hideHud(self) -> None:
        self.core.toggle_visible(False)

    @Slot()
    def quitApp(self) -> None:
        self.core.quit()

    @Slot()
    def toggleChat(self) -> None:
        self.core.toggle_chat()

    @Slot()
    def clearConversation(self) -> None:
        self.core.brain.reset()
        self.set("userText", "")
        self.set("replyText", "")
        self.toast.emit("info", "새 대화를 시작합니다")


class Jarvis(QObject):
    # 다른 스레드 → 메인 스레드 전달용 시그널 (반드시 @Slot 메서드에 연결)
    sig_mic = Signal(float)
    sig_speech_start = Signal()
    sig_utterance = Signal(object, object)
    sig_voice = Signal()
    sig_reply = Signal(object, int)
    sig_action = Signal(str, str, str, str)
    sig_confirm = Signal(str, str, str)
    sig_confirm_close = Signal(str)
    sig_timer = Signal(int, str)
    sig_hotkey = Signal()
    sig_stream = Signal(int, str)      # (명령 번호, 답 조각) — 대화 모드에서 답이 만들어지는 대로
    sig_mode = Signal(bool)            # 자유 대화 모드 켜짐/꺼짐
    sig_notify = Signal(str)           # 백그라운드 작업(작업 감시 등)의 알림
    sig_hud = Signal(str)              # 말로 HUD 보기 방식 바꾸기 (small | big | hide | active_on | active_off)
    sig_feed = Signal(str, str)        # 백그라운드 → 액티브 모드 화면 정보 (속성 이름, JSON)
    sig_timer_cancel = Signal()
    sig_point = Signal(int, int, int, int, str)   # 화면 위치 짚기 (실제 픽셀 x, y, w, h, 라벨)

    def __init__(self, app: QApplication, args) -> None:
        super().__init__()
        self.app = app
        self.args = args
        self.cfg = Config()
        self.focus = winutil.FocusTracker()
        self.bridge = Bridge(self)
        self.bridge.set("wakeEnabled", bool(self.cfg["wake_word_enabled"]))
        self.bridge.set("compact", bool(self.cfg["compact"]))
        self.bridge.set("hasApiKey", bool(self.cfg.api_key()))
        self.bridge.set("hotkeyText", self.cfg["hotkey"].upper())
        self.bridge.set("modelName", self.cfg["model"])

        self.busy = False
        self.active_until = 0.0
        self._speech_while_active = False
        self._gen = 0
        self._cancel = threading.Event()
        self._confirms: dict[str, list] = {}
        self._pending_confirm: str | None = None
        self._enroll: Enrollment | None = None
        self._enroll_when_ready = False
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="brain")
        self._hwnd = 0
        self.overlay = None            # 액티브 모드 전체 화면 HUD (처음 켤 때 불러옴)
        self._overlay_hwnd = 0
        self._timers: dict[str, dict] = {}     # 돌고 있는 타이머 (id → label, end, total, qt)
        self._feed_stop = threading.Event()
        self._feed_stop.set()
        self._proc_watch: hud_feed.ProcWatch | None = None
        self._weather_at = 0.0
        self._point_until = 0.0
        self._target_hwnd = 0
        self._hud_before_active = False   # 액티브 모드 켜기 전에 작은 HUD 가 보였는지
        self._hud_for_confirm = False     # 액티브 모드 중 승인 카드 때문에 작은 HUD 를 잠깐 띄웠는지
        self._stream_gen = -1          # 지금 흘러 들어오는 답의 명령 번호
        self._stream_buf = ""          # 아직 문장이 덜 끝난 조각
        self._stream_cut = False       # 흘러 들어오는 답에서 출처 목록이 시작되었는가
        self._until_before = None      # 지금 들리는 소리 때문에 듣기 시간을 늘리기 전의 만료 시각
        self._stream_text = ""         # 지금까지 받은 답 전체 (HUD 표시용)

        for sig, slot in ((self.sig_mic, self._on_mic), (self.sig_speech_start, self._on_speech_start),
                          (self.sig_utterance, self._on_utterance), (self.sig_reply, self._on_reply),
                          (self.sig_action, self._on_action), (self.sig_confirm, self._on_confirm),
                          (self.sig_confirm_close, self._on_confirm_close), (self.sig_timer, self._on_timer_req),
                          (self.sig_hotkey, self.activate), (self.sig_voice, self._on_voice_status),
                          (self.sig_stream, self._on_stream), (self.sig_mode, self._on_mode),
                          (self.sig_notify, self._on_notify), (self.sig_hud, self._on_hud),
                          (self.sig_feed, self._on_feed), (self.sig_timer_cancel, self._cancel_timers),
                          (self.sig_point, self._on_point)):
            sig.connect(slot)

        # ---- 음성 출력 ----
        self.speaker = Speaker(self)
        self.speaker.level.connect(self._on_voice_level)
        self.speaker.started.connect(self._on_speak_start)
        self.speaker.finished.connect(self._on_speak_end)
        self.tts = TTS(self.speaker, lambda: (self.cfg["tts_voice"], self.cfg["tts_rate"]), self)
        self.chime = self._make_chime()

        # ---- 손 + 두뇌 ----
        self.tools = PCTools(self.cfg, self.focus, Hooks(
            confirm=self._confirm_blocking,
            schedule_timer=lambda s, l: self.sig_timer.emit(int(s), str(l)),
            hud_hwnd=lambda: [h for h in (self._hwnd, self._overlay_hwnd) if h],
            notify=lambda msg: self.sig_notify.emit(str(msg)),
            cancel_timers=self._cancel_timers_hook,
            point_at=self._point_hook,
        ))
        self.brain = Brain(self.cfg, self.tools,
                           on_action=lambda *a: self.sig_action.emit(*a),
                           context_fn=lambda: situation_text(self.focus.last_title))
        # Pro 계정 모드: Claude Code 가 MCP 로 부르는 로컬 도구 서버
        self.toolserver = ToolServer(self.brain.mcp_tools, lambda n, a: self.brain.execute(n, a))
        self.brain.tool_server = self.toolserver
        self.brain.on_mode = lambda on: self.sig_mode.emit(bool(on))
        self.brain.on_hud = lambda action: self.sig_hud.emit(str(action))
        self._refresh_link()
        # 로컬 AI 모델을 미리 메모리에 올려 둠 (없으면 조용히 건너뜀)
        threading.Thread(target=self.brain.local_ai.warmup, daemon=True, name="local-ai-warmup").start()

        # ---- HUD ----
        self.engine = QQmlApplicationEngine()
        self.engine.rootContext().setContextProperty("jarvis", self.bridge)
        self.engine.load(QUrl.fromLocalFile(str(UI_DIR / "Main.qml")))
        if not self.engine.rootObjects():
            raise RuntimeError("UI(QML) 로드 실패 — data/jarvis.log 를 확인하세요")
        self.win = self.engine.rootObjects()[0]
        self._place(initial=True)
        self._hwnd = int(self.win.winId())
        self.focus.own_hwnds.add(self._hwnd)

        self._make_tray()

        # ---- 마이크 ----
        self.listener = Listener(
            self.cfg["stt_language"],
            on_level=self.sig_mic.emit,
            on_speech_start=self.sig_speech_start.emit,
            on_utterance=self.sig_utterance.emit,
            device=self.cfg["mic_device"],
            sensitivity=self.cfg["mic_sensitivity"],
        )
        # ---- 시끄러운 환경용 AI (음성 감지 + 소음 제거) ----
        self.noise_models = NoiseModels()
        self.listener.noise_models = self.noise_models
        self.listener.noise_robust = bool(self.cfg["noise_robust"])
        self.listener.beamforming = bool(self.cfg["beamforming"])
        self.listener.agc = bool(self.cfg["agc"])
        if self.listener.noise_robust and not args.no_mic:
            self.noise_models.start_loading()
        # ---- 오프라인 음성 인식 (호출어 대기 중 주변 소리를 밖으로 보내지 않음, 인터넷 끊겨도 동작) ----
        self.local_stt = LocalSTT()
        self.listener.local_stt = self.local_stt
        self.listener.wake_needed = self._wake_needed
        self.listener.has_wake = self._has_wake
        self.listener.retry_cut = self._retry_cut
        self.listener.understands = self.brain.recognizes
        self.listener.pick = self._pick_alt
        self._apply_stt_engine(start=not args.no_mic)
        # ---- 화자 인식 (누가 말했는지) ----
        self.voiceid = VoiceID(on_status=self.sig_voice.emit)
        self.profile = VoiceProfile()
        self.gate = SpeakerGate(self.voiceid, self.profile, self.cfg)
        self.listener.embedder = self.voiceid.embed
        self.listener.prefilter = self.gate.maybe_allowed
        # 주인이 불러서 확인된 대화 중에는 그 목소리에만 집중한다 (목소리 등록 중에는 쓰지 않음)
        self.listener.focus = lambda: self.gate.focused and not self._enroll
        self.listener.embedder_babble = self.gate.best_voice
        if self.cfg["owner_only"] and not self.profile.exists:
            self.cfg.update({"owner_only": False})
        self._on_voice_status()
        self.mic_ok = False
        if not args.no_mic:
            self.mic_ok = self.listener.start()
            if self.cfg["speaker_lock"] or self.cfg["owner_only"]:
                self.voiceid.start_loading()

        # ---- 전역 단축키 ----
        # 개발용 화면 캡처·데모 실행은 이미 떠 있는 자비스의 단축키를 건드리지 않는다
        self.hotkey = GlobalHotkey(self.cfg["hotkey"], self.sig_hotkey.emit)
        if not (getattr(args, "shot", None) or getattr(args, "demo", False)):
            self.hotkey.start()
            self._show_hotkey()

        # ---- 주기 작업 ----
        self._tick = QTimer(self)
        self._tick.setInterval(200)
        self._tick.timeout.connect(self._on_tick)
        self._tick.start()
        self._stats_timer = QTimer(self)
        self._stats_timer.setInterval(1000)
        self._stats_timer.timeout.connect(self._update_stats)
        self._stats_timer.start()
        self._net_last = (psutil.net_io_counters(), time.monotonic())
        self._stat_n = 0
        self._bat = None
        self._disk = 0.0
        psutil.cpu_percent(None)

        QTimer.singleShot(2300, self._boot_done)

    def _hotkeyText(self) -> str:
        return (self.hotkey.active or self.cfg["hotkey"]).upper()

    def _show_hotkey(self) -> None:
        self.bridge.set("hotkeyText", self._hotkeyText())

    # ================================================================== 부팅
    def _boot_done(self) -> None:
        self._to_idle()
        if not self.mic_ok and not self.args.no_mic:
            self.bridge.toast.emit("error", self.listener.error or "마이크를 사용할 수 없습니다")
        if self.hotkey._tid and not self.hotkey.ok:
            self.bridge.toast.emit("warn", f"단축키 {self.cfg['hotkey']} 등록 실패 — 다른 앱이 사용 중")
        elif self.hotkey.ok and self.hotkey.active != self.cfg["hotkey"]:
            self.bridge.toast.emit("warn", f"{self.cfg['hotkey'].upper()} 는 다른 앱이 사용 중이라 "
                                           f"{self.hotkey.active.upper()} 로 대신 부릅니다")
        if getattr(self.args, "revived", False):
            # 강제로 꺼졌다가 감시 프로세스가 다시 켰다 (guard.py) — 긴 인사 대신 짧게 알린다
            from . import guard
            ultron = guard.ultron_running() if sys.platform == "win32" else False
            msg = guard.revived_line(self.cfg["user_title"] or "주인님", ultron)
            log.warning("강제 종료 뒤 다시 켜짐 (울트론 %s)", "켜져 있음" if ultron else "없음")
            self.bridge.set("replyText", msg)
            self.say(msg, follow_up=False)
            return
        if self.args.no_greet:
            return
        hour = time.localtime().tm_hour
        part = "좋은 아침입니다" if 5 <= hour < 12 else "좋은 오후입니다" if hour < 18 else "좋은 저녁입니다"
        title = self.cfg["user_title"] or "주인님"
        if self.cfg["brain"] == "local":
            msg = f"{part}, {title}. 자비스 온라인. 로컬 모드로 기본 명령을 처리합니다."
        elif self.bridge._hasApiKey:
            msg = f"{part}, {title}. 자비스 온라인. 모든 시스템이 정상입니다."
        elif self.cfg["brain"] == "pro":
            msg = f"{part}, {title}. 자비스 온라인. Claude Code를 찾을 수 없어 기본 명령만 가능합니다."
        else:
            msg = f"{part}, {title}. 자비스 온라인. 설정에서 Claude API 키를 등록해 주세요."
        self.bridge.set("replyText", msg)
        self.say(msg, follow_up=False)

    # ================================================================== 상태
    def _set_state(self, state: str, status: str | None = None) -> None:
        self.bridge.set("state", state)
        if status is None:
            status = {
                "listening": "듣고 있습니다…",
                "thinking": "분석 중…",
                "speaking": "응답 중",
            }.get(state, "")
        self.bridge.set("statusText", status)
        self._sync_listener()

    def _to_idle(self) -> None:
        if self.busy:
            self._set_state("thinking")
            return
        self.gate.reset()   # 대기 상태로 돌아가면 세션 종료 → 다음에 부르는 사람이 새 주인
        if not self.mic_ok:
            self._set_state("offline", "마이크 꺼짐 · 텍스트로 명령하세요")
        elif self.bridge._wakeEnabled:
            self._set_state("standby", "“자비스”라고 불러주세요")
        else:
            self._set_state("standby", f"{self._hotkeyText()} 또는 코어 클릭")

    def _active(self) -> bool:
        return time.monotonic() < self.active_until

    def _sync_listener(self) -> None:
        if hasattr(self, "listener"):
            self.listener.enabled = bool(self.bridge._wakeEnabled or self._active() or self._pending_confirm
                                         or self._enroll)

    def _arm(self, seconds: float = 8.0, chime: bool = True) -> None:
        self.active_until = time.monotonic() + seconds
        self.listener.force_capture = True
        if chime:
            self.chime.play()
        self._set_state("listening")
        self.brain.prewarm()   # 말하는 동안 Claude Code 를 미리 띄워 둔다

    # ================================================================== 입력 처리
    @Slot()
    def activate(self) -> None:
        """코어 클릭 / 단축키."""
        if not self.win.isVisible():
            self.toggle_visible(True)
        if self._enroll:
            self.cancel_enroll()
            return
        if self.speaker.playing:
            self.tts.cancel()
            self.gate.reset()
            self._arm()
            return
        if self.busy:
            self.bridge.toast.emit("info", "처리 중입니다… (‘취소’라고 말하면 중단)")
            return
        if not self.mic_ok:
            self.bridge.toast.emit("warn", "마이크를 사용할 수 없어 텍스트 입력만 가능합니다")
            return
        if self._active() and self.bridge._state == "listening":
            self.active_until = 0
            self._to_idle()
            return
        self.gate.reset()   # 버튼/단축키로 부르면 처음 말하는 사람이 이번 대화의 주인
        self._arm()

    @Slot(float)
    def _on_mic(self, level: float) -> None:
        self.bridge.set("micLevel", round(level, 3))

    @Slot(float)
    def _on_voice_level(self, level: float) -> None:
        self.bridge.set("voiceLevel", round(level, 3))

    @Slot()
    def _on_speech_start(self) -> None:
        self._speech_while_active = self._active()
        self._until_before = self.active_until if self._speech_while_active else None
        if self._speech_while_active:
            self.active_until = time.monotonic() + 16   # 말하는 도중 만료되지 않도록

    def _undo_extend(self) -> None:
        """방금 끝난 소리가 받을 목소리가 아니었다 → 그 소리 때문에 늘려 둔 듣기 시간을 되돌린다
        (다른 사람이 계속 말하면 듣기 상태가 끝없이 이어지던 문제). 주인이 이어 말할 틈은 조금 남긴다."""
        before, self._until_before = self._until_before, None
        if before is not None and not self.busy and not self.speaker.playing:
            self.active_until = min(self.active_until, max(before, time.monotonic() + 2.0))

    def _is_fragment(self, text: str) -> bool:
        """말이 잘려 들어온 조각인가: 호출어의 일부('자', '자비', '비스')이거나 뜻을 알 수 없는 한 글자."""
        c = re.sub(r"[\s.,!?~]", "", text or "").lower()
        if not c:
            return True
        if len(c) <= 2 and any(c in w.lower() and c != w.lower() for w in (self.cfg["wake_words"] or []) if w):
            return True
        return self.brain.is_fragment(text)

    @Slot(object, object)
    def _on_utterance(self, text, voice=None) -> None:
        if self._enroll:
            self._enroll_feed(text, voice)
            return
        was_active = self._speech_while_active or self._active()
        self._speech_while_active = False
        if voice is FILTERED:
            # 목소리가 달라 인식하지 않은 소리 — 못 알아들은 것이 아니므로 "다시 말씀해 주세요" 도, 듣기 시간 연장도 없다
            self._undo_extend()
            return
        if self._pending_confirm:
            # 문장 전체가 승인/거부 표현일 때만 대답으로 받는다 (approval.py). 그 밖의 말은 무시 — 카드는 그대로
            verdict = approval.answer(text) if text else None
            if verdict is not None and self._voice_ok(voice):
                self.answer_confirm(self._pending_confirm, verdict)
            return
        if not text:
            if was_active and not self.busy and not self.speaker.playing:
                self.active_until = time.monotonic() + 5
                self._set_state("listening", "잘 못 들었습니다. 다시 말씀해 주세요")
            return
        if self.speaker.playing:
            return
        if self.busy:
            if CANCEL_RE.search(text) and self._voice_ok(voice):
                self._cancel_busy()
            return
        cmd = self._strip_wake(text)
        if cmd is not None and was_active and not self._wake_at_start(text):
            # 이미 대화 중에 문장 가운데 '자비스'가 나오면 호출이 아니라 말의 일부
            # (기록: '아이언맨에 나오는 자비스를 만들 수 있을까' → '나오는  를'로 잘림)
            cmd = None
        if cmd is not None:
            if cmd and self._is_fragment(cmd):
                # '자비스' 뒤에 잘린 조각만 붙어 있다 → 호출만 한 것으로 보고 명령을 기다린다
                log.info("호출어 뒤 잘린 조각(%d자) → 호출만 한 것으로 처리", len(cmd))
                cmd = ""
            if not self._voice_ok(voice, wake=True, wake_only=not cmd):
                return
            if cmd:
                self.run_command(cmd)
            else:
                self._arm()
            return
        if was_active and self._voice_ok(voice):
            if self._is_fragment(text):
                log.info("잘린 조각(%d자) → 다시 듣기", len(text))
                if not self.brain.chat_mode:
                    self.active_until = time.monotonic() + 6
                self._set_state("listening", "말씀이 끊겨 들렸습니다. 다시 말씀해 주세요")
                return
            self.run_command(text)

    def _voice_ok(self, voice, wake: bool = False, wake_only: bool = False) -> bool:
        """명령을 실행하기 직전에 목소리 확인 (주인 전용 / 세션 잠금)."""
        v = self.gate.check(voice, wake=wake, wake_only=wake_only)
        if v.score is not None:   # 발화 내용은 남기지 않고 점수만 기록 (기준값 조정용)
            log.info("화자 확인(%s): 유사도 %.2f / 기준 %.2f → %s", v.mode, v.score, v.threshold,
                     "통과" if v.ok else "거부")
        if v.ok:
            return True
        self._undo_extend()
        if v.reason == "short":
            msg = "목소리를 확인하기에 너무 짧습니다. 조금 길게 말씀해 주세요"
        elif v.reason == "owner":
            msg = f"등록된 목소리가 아니라서 무시했습니다 (유사도 {v.score:.2f})"
        else:
            msg = f"호출한 분의 목소리가 아니라서 무시했습니다 (유사도 {v.score:.2f})"
        if self.bridge._state == "listening":
            self.bridge.set("statusText", msg)
        else:
            self.bridge.toast.emit("warn", msg)
        return False

    def _wake_needed(self) -> bool:
        """(인식 스레드에서 호출) 지금 들린 말이 호출어 없이는 무시되는 상태인가."""
        return not (self._active() or self._speech_while_active or self._pending_confirm
                    or self._enroll or self.busy)

    def _has_wake(self, text: str) -> bool:
        # 오프라인 인식은 '자비스'를 '잠비스 · 잡비스'처럼 적기도 하므로 조금 느슨하게 본다 (hearing.py)
        return hearing.find_wake(text or "", self.cfg["wake_words"]) is not None

    def _apply_stt_engine(self, start: bool = True) -> None:
        engine = self.cfg["stt_engine"] or "auto"
        self.listener.stt_engine = engine
        self.listener.wake_prefix = (self.cfg["wake_words"] or ["자비스"])[0]
        if engine != "google" and start:
            self.local_stt.start_loading()

    def stt_status(self) -> str:
        st = self.local_stt.state
        if (self.cfg["stt_engine"] or "auto") == "google":
            return "말소리를 Google 서버로 보내 인식합니다. 인터넷이 끊기면 알아듣지 못합니다."
        if st == "ready":
            return "오프라인 인식 준비됨 — 인터넷이 끊겨도 알아듣습니다."
        if st == "loading":
            return "오프라인 인식 모델 준비 중 (처음 한 번 약 160MB 다운로드)… 그동안은 Google 로 인식합니다."
        if st == "error":
            return f"오프라인 인식 준비 실패 — Google 로 인식합니다 ({self.local_stt.error})"
        return ""

    def _wake_at_start(self, text: str) -> bool:
        return hearing.wake_at_start(text or "", self.cfg["wake_words"])

    def _pick_alt(self, alts: list[str]) -> str:
        """(인식 스레드) Google 이 준 후보 중 자비스가 알아들을 수 있는 명령을 고른다.
        발음이 뭉개지면 첫 후보는 '대모 켜 줘', 다음 후보가 '대화 모드 켜 줘'인 경우가 있다."""
        if len(alts) == 1:
            return alts[0]
        cands = alts
        if self.listener.wake_needed():
            cands = [a for a in alts if self._has_wake(a)] or alts
        for a in cands[:5]:
            cmd = self._strip_wake(a)
            if self.brain.recognizes(cmd if cmd else a):
                if a != alts[0]:
                    log.info("인식 후보 %r 대신 %r 사용 (후보 %d개)", alts[0], a, len(alts))
                return a
        return alts[0]

    def _retry_cut(self, text: str, tokens: list, stamps: list) -> float | None:
        """(인식 스레드) 오프라인 인식이 호출어는 들었는데 명령은 못 알아들은 경우, 호출어가 끝나는 시각.
        listener 가 그 뒤쪽 소리만 다시 받아 적는다. 다시 볼 필요가 없으면 None."""
        cmd = self._strip_wake(text)
        if not cmd or self.brain.recognizes(cmd):
            return None
        return hearing.wake_end_time(tokens, stamps, self.cfg["wake_words"])

    def _strip_wake(self, text: str) -> str | None:
        """호출어를 뗀 명령 (호출어만 말했으면 ''), 호출어가 없으면 None. 뭉개져 적힌 호출어도 받는다.
        양 끝의 '야 · 아' 는 지우지 않는다 ('자비스, 아이유 노래 틀어 줘' 가 '이유 노래…' 로 바뀌던 문제)."""
        return hearing.strip_wake(text or "", self.cfg["wake_words"])

    def run_command(self, text: str) -> bool:
        """명령을 실행에 넘긴다. 넘겼으면 True, 빈 글이거나 처리 중이라 못 받았으면 False."""
        text = (text or "").strip()
        if not text:
            return False
        if self.busy:
            self.bridge.toast.emit("info", "이전 명령을 처리 중입니다")
            return False
        self._enroll = None          # 등록 도중 입력창으로 명령하면 등록은 조용히 중단
        self.tts.cancel()
        self.active_until = 0
        self.listener.force_capture = False
        log.info("명령: %s", text)   # 자비스에게 한 명령만 기록 (주변 대화는 기록하지 않음)
        self.bridge.set("userText", text)
        self.bridge.set("replyText", "")
        self.busy = True
        self._gen += 1
        gen = self._gen
        self._cancel = threading.Event()
        cancel = self._cancel
        self._set_state("thinking")
        self._executor.submit(self._work, text, gen, cancel)
        return True

    def _work(self, text: str, gen: int, cancel: threading.Event) -> None:
        try:
            reply = self.brain.handle(text, cancel, on_text=lambda d: self.sig_stream.emit(gen, d))
        except Exception as e:
            log.exception("두뇌 오류")
            reply = f"오류가 발생했습니다: {e}"
        self.sig_reply.emit(reply, gen)

    def _cancel_busy(self) -> None:
        self._cancel.set()
        self._gen += 1
        self.busy = False
        for cid in list(self._confirms):
            self.answer_confirm(cid, False)
        self.bridge.set("replyText", "작업을 취소했습니다.")
        self.say("취소했습니다.", follow_up=False)

    @Slot(int, str)
    def _on_stream(self, gen: int, delta: str) -> None:
        """답이 만들어지는 대로 화면에 보이고, 문장이 완성될 때마다 바로 읽는다 (대화 모드 · Claude 명령)."""
        if gen != self._gen:
            return
        if self._stream_gen != gen:
            if not delta.strip():
                return                      # 내용 없는 줄바꿈만 온 경우 아직 시작하지 않음
            self._stream_gen, self._stream_buf, self._stream_text = gen, "", ""
            self._stream_cut = False
            self._follow_up = True
            self.tts.stream_begin()
        if self._stream_cut:
            return                          # 출처 목록이 시작된 뒤의 글은 읽지도 보여 주지도 않는다
        self._stream_buf += delta
        self._stream_text += delta
        m = _SOURCES.search(self._stream_text)
        if m:
            drop = len(self._stream_text) - m.start()
            self._stream_text = self._stream_text[:m.start()]
            self._stream_buf = self._stream_buf[:max(0, len(self._stream_buf) - drop)]
            self._stream_cut = True
        sentences, self._stream_buf = split_sentences(self._stream_buf)
        for sent in sentences:
            self.tts.stream_feed(sent)
        self.bridge.set("replyText", re.sub(r"\s*\n\s*", " ", self._stream_text).strip())

    @Slot(object, int)
    def _on_reply(self, reply, gen: int) -> None:
        if gen != self._gen:
            return
        self.busy = False
        streamed = self._stream_gen == gen
        self._stream_gen = -1
        if streamed:
            sentences, self._stream_buf = split_sentences(self._stream_buf, final=True)
            for sent in sentences:
                self.tts.stream_feed(sent)
            spoken = re.sub(r"\s*\n\s*", " ", self._stream_text).strip()
            if reply and reply.strip() and reply.strip()[:20] not in spoken:
                self.tts.stream_feed(reply)        # 스트리밍 뒤 다른 답(오류 안내 등)이 온 경우
                spoken = f"{spoken} {reply}".strip()
            self.tts.stream_end()
            self.bridge.set("replyText", spoken or (reply or ""))
            return
        if not reply:
            self._to_idle()
            return
        self.bridge.set("replyText", reply)
        self.say(reply)

    # ================================================================== 말하기
    def say(self, text: str, follow_up: bool = True) -> None:
        self._follow_up = follow_up
        sentences, rest = split_sentences(text, final=True)
        if len(sentences) <= 1:
            self.tts.say(text)
            return
        # 한 번에 길게 합성하면 느리고, 네트워크가 불안하면 뒷부분이 잘린 소리가 올 수 있다
        self.tts.stream_begin()
        for s in sentences:
            self.tts.stream_feed(s)
        self.tts.stream_end()

    @Slot()
    def _on_speak_start(self) -> None:
        self.listener.muted = True
        self._set_state("speaking")

    @Slot()
    def _on_speak_end(self) -> None:
        QTimer.singleShot(350, self._unmute)
        if self._enroll:
            self._enroll_prompt()
            return
        if self.busy:
            self._set_state("thinking")
        elif (getattr(self, "_follow_up", True) or self._pending_confirm) and self.mic_ok:
            if self.brain.chat_mode and not self._pending_confirm:
                self.active_until = time.monotonic() + float(self.cfg["chat_idle_seconds"] or 40)
                self.listener.force_capture = True
                self._set_state("listening", "대화 모드 · 편하게 말씀하세요")
                return
            self.active_until = time.monotonic() + float(self.cfg["follow_up_seconds"] or 7)
            self.listener.force_capture = True
            self._set_state("listening", "이어서 말씀하셔도 됩니다")
        else:
            self._to_idle()

    def _unmute(self) -> None:
        if not self.speaker.playing:
            self.listener.muted = False

    # ================================================================== 도구 이벤트
    @Slot(str, str, str, str)
    def _on_action(self, aid: str, label: str, status: str, detail: str) -> None:
        self.bridge.actionEvent.emit(aid, label, status, detail[:300])

    def _confirm_blocking(self, title: str, detail: str) -> bool:
        """두뇌 스레드에서 호출: HUD/음성으로 승인 받을 때까지 대기."""
        cid = uuid.uuid4().hex[:8]
        ev = threading.Event()
        self._confirms[cid] = [ev, False]
        self.sig_confirm.emit(cid, title, detail)
        answered = ev.wait(45)
        result = self._confirms.pop(cid, [None, False])[1] if answered else False
        self._confirms.pop(cid, None)
        self.sig_confirm_close.emit(cid)
        return bool(result)

    @Slot(str, str, str)
    def _on_confirm(self, cid: str, title: str, detail: str) -> None:
        self._pending_confirm = cid
        self.bridge.confirmRequest.emit(cid, title, detail)
        if not self.win.isVisible():
            if self.bridge._activeMode:      # 액티브 모드: 승인 카드를 누를 수 있게 잠깐만 띄운다
                self._hud_for_confirm = True
            self.toggle_visible(True, force=True)
        elif self.bridge._activeMode:
            self.win.raise_()
        self.say(f"{title}, 승인하시겠습니까?", follow_up=True)

    @Slot(str)
    def _on_confirm_close(self, cid: str) -> None:
        if self._pending_confirm == cid:
            self._pending_confirm = None
            self.active_until = 0
            if self.busy:
                self._set_state("thinking")
        self.bridge.confirmClosed.emit(cid)
        self._rehide_after_confirm()

    def _rehide_after_confirm(self) -> None:
        if self._hud_for_confirm and not self._pending_confirm:
            self._hud_for_confirm = False
            if self.bridge._activeMode:
                QTimer.singleShot(1200, self._hide_hud_for_active)

    def answer_confirm(self, cid: str, approved: bool) -> None:
        entry = self._confirms.get(cid)
        if entry:
            entry[1] = approved
            entry[0].set()
        if self._pending_confirm == cid:
            self._pending_confirm = None
            self._rehide_after_confirm()
            self.tts.cancel()
            self.active_until = 0
        self.bridge.confirmClosed.emit(cid)
        if self.busy:
            self._set_state("thinking")

    # ================================================================== 자유 대화 모드
    def toggle_chat(self) -> None:
        if self.busy:
            self.bridge.toast.emit("info", "처리 중입니다. 끝난 뒤 다시 눌러 주세요")
            return
        if not self.win.isVisible():
            self.toggle_visible(True)
        self.run_command("대화 모드 끝" if self.brain.chat_mode else "대화 모드 시작")

    @Slot(bool)
    def _on_mode(self, on: bool) -> None:
        self.bridge.set("chatMode", on)
        if hasattr(self, "act_chat") and self.act_chat.isChecked() != on:
            self.act_chat.setChecked(on)
        if not on and self.bridge._state == "listening" and not self.busy:
            self.active_until = min(self.active_until, time.monotonic() + float(self.cfg["follow_up_seconds"] or 7))

    @Slot(str)
    def _on_hud(self, action: str) -> None:
        if action == "small":
            self.set_compact(True)
        elif action == "big":
            if not self.win.isVisible():
                self.toggle_visible(True, force=True)
            self.set_compact(False)
        elif action == "hide":
            QTimer.singleShot(2500, lambda: self.toggle_visible(False))   # 대답을 들려준 뒤 숨김
        elif action in ("active_on", "active_off"):
            self.set_active(action == "active_on")

    # ================================================================== 액티브 모드 (전체 화면 HUD)
    def set_active(self, on: bool) -> None:
        """화면 전체에 헬멧 시야 HUD 를 펼치거나 접는다. 입력은 아래 창으로 통과하므로 켠 채로 PC 를 쓸 수 있다."""
        on = bool(on)
        if on and self.overlay is None:
            # 움직임 줄이기: 설정 hud_motion (auto 면 Windows '애니메이션 효과' 꺼짐일 때 회전 · 스캔 연출을 멈춤)
            motion = str(self.cfg.get("hud_motion", "auto")).lower()
            calm = motion == "off" or (motion not in ("on", "true", "1") and winutil.reduce_motion())
            self.engine.rootContext().setContextProperty("reduceMotion", calm)
            self.engine.load(QUrl.fromLocalFile(str(UI_DIR / "ActiveMode.qml")))
            roots = [o for o in self.engine.rootObjects() if o.objectName() == "activeMode"]
            if not roots:
                log.error("액티브 모드 화면(ActiveMode.qml) 로드 실패")
                self.bridge.toast.emit("error", "액티브 모드 화면을 불러오지 못했습니다")
                return
            self.overlay = roots[0]
            self._overlay_hwnd = int(self.overlay.winId())
            self.focus.own_hwnds.add(self._overlay_hwnd)
            for w in QGuiApplication.allWindows():      # 채팅 입력 바 (추적 박스가 이 창을 '지금 창'으로 잡지 않게)
                if w.objectName() == "activeChat":
                    self.focus.own_hwnds.add(int(w.winId()))
        if on:
            screen = self.win.screen() or QGuiApplication.primaryScreen()
            self.overlay.setGeometry(screen.geometry())
        self.brain.active_hud = on
        if hasattr(self, "act_active") and self.act_active.isChecked() != on:
            self.act_active.setChecked(on)
        if on == self.bridge._activeMode:
            return
        self.bridge.set("activeMode", on)   # 펼치기 / 접기 연출과 창 보이기 · 숨기기는 QML 이 맡는다
        log.info("액티브 모드 %s", "켜짐" if on else "꺼짐")
        if on:
            self.chime.play()
            # 작은 HUD 는 오른쪽 패널들을 가리므로 숨긴다 (상태 · 대답은 전체 화면 HUD 에 나온다)
            self._hud_before_active = self.win.isVisible()
            self._hud_for_confirm = False
            if self._pending_confirm:
                self._hud_for_confirm = True
                self.win.raise_()
            else:
                QTimer.singleShot(250, self._hide_hud_for_active)
            self._start_feed()
        else:
            self._stop_feed()
            if self._hud_before_active or self._pending_confirm:
                self.toggle_visible(True)
            self._hud_for_confirm = False

    def _hide_hud_for_active(self) -> None:
        if self.bridge._activeMode and not self._pending_confirm and not self._enroll:
            self.win.hide()

    # ---- 액티브 모드 실시간 정보 ----
    def _start_feed(self) -> None:
        if not hasattr(self, "_focus_timer"):
            self._focus_timer = QTimer(self)
            self._focus_timer.setInterval(350)
            self._focus_timer.timeout.connect(self._update_target)
        self._focus_timer.start()
        if self._feed_stop.is_set():
            self._feed_stop = threading.Event()
            threading.Thread(target=self._proc_loop, args=(self._feed_stop,), daemon=True, name="hud-procs").start()
        if time.monotonic() - self._weather_at > 900 or self.bridge._weatherJson in ("{}", ""):
            self._weather_at = time.monotonic()
            threading.Thread(target=self._fetch_weather, daemon=True, name="hud-weather").start()

    def _stop_feed(self) -> None:
        self._feed_stop.set()
        if hasattr(self, "_focus_timer"):
            self._focus_timer.stop()
        self._point_until = 0.0
        self._target_hwnd = 0
        self.bridge.set("targetJson", "{}")

    def _proc_loop(self, stop: threading.Event) -> None:
        """프로세스별 CPU · 메모리 측정 (2초마다, 추적 박스용). 첫 측정은 CPU 값이 없어 곧바로 한 번 더 잰다."""
        if self._proc_watch is None:
            self._proc_watch = hud_feed.ProcWatch()
        first = True
        while not stop.is_set():
            try:
                self._proc_watch.sample()   # 추적 박스에 보여 줄 창별 CPU · 메모리
            except Exception:
                log.exception("프로세스 목록 실패")
            if stop.wait(0.6 if first else 2.0):
                break
            first = False
            if time.monotonic() - self._weather_at > 900:   # 켜 둔 동안 15분마다 날씨 새로 고침
                self._weather_at = time.monotonic()
                threading.Thread(target=self._fetch_weather, daemon=True, name="hud-weather").start()

    def _fetch_weather(self) -> None:
        try:
            data = self.tools.weather_data()
        except Exception as e:
            log.warning("액티브 모드 날씨 실패: %s", e)
            self._weather_at = time.monotonic() - 780   # 2분 뒤 다시 시도
            data = {"error": "OFFLINE"}
        self.sig_feed.emit("weatherJson", json.dumps(data, ensure_ascii=False))

    @Slot(str, str)
    def _on_feed(self, name: str, value: str) -> None:
        self.bridge.set(name, value)

    def _overlay_dpr(self) -> float:
        scr = self.overlay.screen() if self.overlay is not None else None
        return scr.devicePixelRatio() if scr else 1.0

    def _to_overlay(self, x: float, y: float) -> tuple[float, float]:
        """실제 화면 픽셀 → 액티브 모드 창 안의 좌표."""
        k = self._overlay_dpr()
        g = self.overlay.geometry()
        return x / k - g.x(), y / k - g.y()

    def _update_target(self) -> None:
        """추적 박스: 짚은 위치를 잠시 보여 주고, 평소에는 지금 쓰고 있는 창을 따라다닌다."""
        if self.overlay is None or not self.bridge._activeMode or time.monotonic() < self._point_until:
            return
        info = hud_feed.foreground_window(set(self.focus.own_hwnds))
        if not info:
            if self._target_hwnd or self.bridge._targetJson != "{}":
                self._target_hwnd = 0
                self.bridge.set("targetJson", "{}")
            return
        x, y = self._to_overlay(info["x"], info["y"])
        k = self._overlay_dpr()
        st = self._proc_watch.stats_of(info["pid"]) if self._proc_watch else None
        self._target_hwnd = info["hwnd"]
        self.bridge.set("targetJson", json.dumps({
            "kind": "window", "id": str(info["hwnd"]), "x": round(x), "y": round(y),
            "w": round(info["w"] / k), "h": round(info["h"] / k),
            "title": info["title"][:80], "app": hud_feed.display_name(info["exe"]) if info["exe"] else "",
            "cpu": round(st[0], 1) if st else -1, "mem": round(st[1]) if st else -1,
        }, ensure_ascii=False))

    def _point_hook(self, x: int, y: int, w: int, h: int, label: str) -> bool:
        """point_at 도구 (두뇌 스레드) → 화면에 표시. 액티브 모드가 꺼져 있으면 False."""
        if not self.bridge._activeMode:
            return False
        self.sig_point.emit(int(x), int(y), int(w), int(h), str(label))
        return True

    @Slot(int, int, int, int, str)
    def _on_point(self, x: int, y: int, w: int, h: int, label: str) -> None:
        if self.overlay is None or not self.bridge._activeMode:
            return
        k = self._overlay_dpr()
        bw, bh = (w / k, h / k) if w > 0 and h > 0 else (0.0, 0.0)
        cx, cy = self._to_overlay(x, y)
        if bw and bh:   # 영역을 준 경우 (x, y) 는 왼쪽 위 → 가운데로
            cx, cy = cx + bw / 2, cy + bh / 2
        bw, bh = max(bw, 70.0), max(bh, 70.0)
        self._point_until = time.monotonic() + 9.0
        self._target_hwnd = 0
        self.bridge.set("targetJson", json.dumps({
            "kind": "point", "id": f"p{time.monotonic():.3f}", "x": round(cx - bw / 2), "y": round(cy - bh / 2),
            "w": round(bw), "h": round(bh), "title": label or "TARGET",
        }, ensure_ascii=False))

    @Slot(str)
    def _on_notify(self, msg: str) -> None:
        """작업 감시 등 백그라운드 알림. 말하는 중·처리 중이면 끝날 때까지 기다렸다가 알린다."""
        if self.busy or self.speaker.playing or self._pending_confirm or self._enroll:
            QTimer.singleShot(2500, lambda m=msg: self._on_notify(m))
            return
        self.chime.play()
        self.bridge.toast.emit("warn", msg)
        self.bridge.actionEvent.emit(uuid.uuid4().hex[:8], f"알림 · {msg[:40]}", "ok", "")
        if not self.win.isVisible():
            self.toggle_visible(True)
        title = self.cfg["user_title"] or "주인님"
        text = f"{title}, {msg}"
        self.bridge.set("replyText", text)
        self.say(text, follow_up=True)

    @Slot(int, str)
    def _on_timer_req(self, seconds: int, label: str) -> None:
        tid = uuid.uuid4().hex[:8]
        qt = QTimer(self)
        qt.setSingleShot(True)
        qt.timeout.connect(lambda t=tid: self._timer_fired(t))
        qt.start(seconds * 1000)
        self._timers[tid] = {"label": label, "end": int(time.time() * 1000) + seconds * 1000, "total": seconds, "qt": qt}
        self._publish_timers()

    def _publish_timers(self) -> None:
        rows = sorted(({"label": t["label"], "end": t["end"], "total": t["total"]} for t in self._timers.values()),
                      key=lambda r: r["end"])
        self.bridge.set("timersJson", json.dumps(rows, ensure_ascii=False))

    def _cancel_timers_hook(self) -> int:
        """cancel_timer 도구 (두뇌 스레드) → 메인 스레드에서 취소."""
        n = len(self._timers)
        if n:
            self.sig_timer_cancel.emit()
        return n

    @Slot()
    def _cancel_timers(self) -> None:
        for t in self._timers.values():
            t["qt"].stop()
            t["qt"].deleteLater()
        self._timers.clear()
        self._publish_timers()

    def _timer_fired(self, tid: str) -> None:
        t = self._timers.pop(tid, None)
        if t is None:
            return
        t["qt"].deleteLater()
        self._publish_timers()
        label = t["label"]
        self.chime.play()
        title = self.cfg["user_title"] or "주인님"
        self.bridge.toast.emit("warn", f"⏰ {label}")
        self.bridge.actionEvent.emit(uuid.uuid4().hex[:8], f"타이머 완료 · {label}", "ok", "")
        if not self.win.isVisible():
            self.toggle_visible(True)
        msg = f"{title}, {label} 시간입니다."
        self.bridge.set("replyText", msg)
        self.say(msg, follow_up=False)

    # ================================================================== 주기 작업
    def _on_tick(self) -> None:
        if self._enroll and not self._active() and not self.speaker.playing:
            self.cancel_enroll("목소리 등록 시간이 초과되어 취소했습니다.")
        if (self.bridge._state == "listening" and not self._active() and not self.busy
                and not self.speaker.playing and not self._pending_confirm):
            self.listener.force_capture = False
            if self.brain.chat_mode:
                self.brain.set_chat(False)
                self.bridge.toast.emit("info", "한동안 말씀이 없어 대화 모드를 끝냈습니다")
            self._to_idle()
        self._sync_listener()

    def _update_stats(self) -> None:
        now_net, now_t = psutil.net_io_counters(), time.monotonic()
        last_net, last_t = self._net_last
        dt = max(0.001, now_t - last_t)
        down = (now_net.bytes_recv - last_net.bytes_recv) / dt
        up = (now_net.bytes_sent - last_net.bytes_sent) / dt
        self._net_last = (now_net, now_t)
        if self._stat_n % 15 == 0:
            try:
                b = psutil.sensors_battery()
                self._bat = (b.percent, b.power_plugged) if b else None
            except Exception:
                self._bat = None
        if self._stat_n % 30 == 0:
            try:
                self._disk = psutil.disk_usage(os.environ.get("SystemDrive", "C:") + "\\").percent
            except Exception:
                pass
        self._stat_n += 1
        self.bridge.set("statsJson", json.dumps({
            "cpu": psutil.cpu_percent(None),
            "ram": psutil.virtual_memory().percent,
            "disk": self._disk,
            "down": down, "up": up,
            "bat": self._bat[0] if self._bat else -1,
            "plugged": bool(self._bat[1]) if self._bat else True,
        }))

    # ================================================================== 화자 인식 / 목소리 등록
    @Slot()
    def _on_voice_status(self) -> None:
        """모델/프로필 상태를 HUD 설정 화면에 반영 (모델 로더 스레드 → 시그널로 호출됨)."""
        vid, prof = self.voiceid, self.profile
        if prof.exists:
            who = f"등록됨 · 문장 {len(prof.samples)}개" + (f" · {prof.created[:10]}" if prof.created else "")
        else:
            who = "목소리 미등록"
        model = {
            "off": "화자 인식 꺼짐",
            "downloading": f"음성 모델 다운로드 중 {vid.progress}%",
            "loading": "음성 모델 준비 중…",
            "error": f"모델 오류: {vid.error}",
        }.get(vid.state, "")
        self.bridge.set("voiceStatus", f"{who} · {model}" if model else who)
        self.bridge.set("voiceEnrolled", prof.exists)
        if vid.state in ("downloading", "loading"):
            self._voice_err_shown = False
        elif vid.state == "error":
            self._enroll_when_ready = False
            if not getattr(self, "_voice_err_shown", False):
                self._voice_err_shown = True
                self.bridge.toast.emit("error", f"화자 인식을 쓸 수 없습니다 — {vid.error}")
        elif vid.ready and self._enroll_when_ready:
            self._enroll_when_ready = False
            self.start_enroll()

    def start_enroll(self) -> None:
        if self._enroll:
            return
        if not self.mic_ok:
            self.bridge.toast.emit("warn", "마이크를 사용할 수 없어 목소리를 등록할 수 없습니다")
            return
        if self.busy or self._pending_confirm:
            self.bridge.toast.emit("info", "지금 하는 작업이 끝난 뒤 다시 시도해 주세요")
            return
        if not self.voiceid.ready:
            self._enroll_when_ready = True
            self.voiceid.start_loading()
            self.bridge.toast.emit("info", "음성 모델을 준비하는 중입니다 (처음 한 번 약 28MB 다운로드). "
                                           "준비되면 바로 등록을 시작합니다")
            return
        self._enroll = Enrollment()
        self.gate.reset()
        # 안내 음성을 합성하는 동안(재생 전) 시간 초과로 취소되지 않도록 미리 대기 시간을 잡는다
        self.active_until = time.monotonic() + 30
        if self.bridge._compact:
            self.set_compact(False)
        self.toggle_visible(True, force=True)
        self.bridge.set("userText", "")
        msg = (f"목소리 등록을 시작합니다. 화면에 나오는 문장 {self._enroll.n}개를 "
               "평소 말투로 하나씩 읽어 주세요.")
        self.bridge.set("replyText", msg)
        self.say(msg, follow_up=False)          # 말이 끝나면 _on_speak_end → 첫 문장 표시

    def _enroll_prompt(self) -> None:
        e = self._enroll
        self.bridge.set("replyText", f"“{e.sentence}”")
        self.active_until = time.monotonic() + 30
        self.listener.force_capture = True
        self._set_state("listening", f"목소리 등록 {e.index + 1}/{e.n} · 위 문장을 읽어 주세요 (코어 클릭 시 취소)")

    def _enroll_feed(self, text, voice) -> None:
        e = self._enroll
        if self.speaker.playing:
            return
        if text and CANCEL_RE.search(text):
            self.cancel_enroll()
            return
        result, msg = e.feed(voice)
        if result == "ok":
            self._enroll_prompt()
        elif result == "retry":
            self.bridge.set("statusText", msg)
            self.say(msg, follow_up=False)      # 안내가 끝나면 같은 문장을 다시 표시
        elif result == "abort":
            self._enroll = None
            self.active_until = 0
            self.listener.force_capture = False
            self.bridge.set("replyText", msg)
            self.say(msg, follow_up=False)
        elif result == "done":
            self._enroll = None
            self.active_until = 0
            self.listener.force_capture = False
            try:
                self.profile.save(e.samples)
            except Exception as ex:
                log.exception("목소리 프로필 저장 실패")
                msg = f"목소리 프로필을 저장하지 못했습니다: {ex}"
            else:
                self.cfg.update({"owner_only": True})
                self.gate.reset()
                title = self.cfg["user_title"] or "주인님"
                msg = f"목소리 등록을 마쳤습니다. 이제 {title}의 목소리에만 반응합니다."
                log.info("목소리 등록 완료 (샘플 %d개)", len(e.samples))
            self._on_voice_status()
            self.bridge.set("replyText", msg)
            self.say(msg, follow_up=False)

    def cancel_enroll(self, msg: str = "목소리 등록을 취소했습니다.") -> None:
        if not self._enroll:
            return
        self._enroll = None
        self.active_until = 0
        self.listener.force_capture = False
        self.bridge.set("replyText", msg)
        self.say(msg, follow_up=False)

    def clear_voice(self) -> None:
        self.profile.clear()
        self.cfg.update({"owner_only": False})
        self.gate.reset()
        self._on_voice_status()
        self.bridge.toast.emit("info", "등록된 목소리를 삭제했습니다 — 이제 누구나 부를 수 있습니다")

    # ================================================================== 창/트레이
    def _place(self, initial: bool = False) -> None:
        w, h = COMPACT if self.bridge._compact else EXPANDED
        geo = QGuiApplication.primaryScreen().availableGeometry()
        if initial:
            x = geo.right() - w - MARGIN + 1
            y = (geo.top() + MARGIN) if self.cfg["position"] == "top-right" else (geo.bottom() - h - MARGIN + 1)
        else:  # 현재 위치 기준으로 오른쪽 모서리(위/아래) 고정
            g = self.win.geometry()
            x = g.x() + g.width() - w
            y = g.y() if self.cfg["position"] == "top-right" else g.y() + g.height() - h
            x = max(geo.left(), min(x, geo.right() - w))
            y = max(geo.top(), min(y, geo.bottom() - h))
        self.win.setGeometry(QRect(x, y, w, h))

    def set_compact(self, on: bool) -> None:
        self.bridge.set("compact", bool(on))
        self.cfg.update({"compact": bool(on)})
        self._place()

    def set_wake(self, on: bool) -> None:
        self.bridge.set("wakeEnabled", bool(on))
        self.cfg.update({"wake_word_enabled": bool(on)})
        if hasattr(self, "act_wake"):
            self.act_wake.setChecked(bool(on))
        if not self.busy and not self.speaker.playing and self.bridge._state in ("standby", "listening"):
            self._to_idle()
        self.bridge.toast.emit("info", "호출어 대기 켜짐 — “자비스”" if on else
                               f"호출어 대기 꺼짐 — {self._hotkeyText()} 로 호출")

    def toggle_visible(self, show: bool | None = None, force: bool = False) -> None:
        """작은 HUD 보이기/숨기기. 액티브 모드 중에는 전체 화면 HUD 를 가리지 않도록
        사용자가 직접 띄울 때(force)만 보인다 — 듣기 · 알림 · 타이머는 전체 화면 HUD 에 나온다."""
        show = (not self.win.isVisible()) if show is None else show
        if show and self.bridge._activeMode and not force:
            return
        if show:
            self.win.show()
            self.win.raise_()
        else:
            self.win.hide()

    def save_settings(self, values: dict) -> None:
        old_hotkey = self.cfg["hotkey"]
        if not values.get("anthropic_api_key"):
            values.pop("anthropic_api_key", None)   # 빈 칸이면 기존 키 유지
        if values.pop("clear_api_key", False):
            values["anthropic_api_key"] = ""
        for key, lo, hi in (("mic_sensitivity", 0.3, 3.0), ("speaker_threshold", 0.2, 0.7)):
            if key in values:
                try:
                    values[key] = max(lo, min(hi, float(values[key])))
                except (TypeError, ValueError):
                    values.pop(key)
        if values.get("owner_only") and not self.profile.exists:
            values["owner_only"] = False
            self.bridge.toast.emit("warn", "주인 전용 모드는 목소리를 먼저 등록해야 켜집니다")
        self.cfg.update(values)
        if self.cfg["speaker_lock"] or self.cfg["owner_only"]:
            self.voiceid.start_loading()
        self.gate.reset()
        self._on_voice_status()
        self.listener.sensitivity = float(self.cfg["mic_sensitivity"] or 1.0)
        self.listener.noise_robust = bool(self.cfg["noise_robust"])
        self.listener.beamforming = bool(self.cfg["beamforming"])
        self.listener.agc = bool(self.cfg["agc"])
        if self.listener.noise_robust:
            self.noise_models.start_loading()
        self._apply_stt_engine(start=self.mic_ok)
        self.brain.reset()
        self._refresh_link()
        if "wake_word_enabled" in values:
            self.set_wake(bool(values["wake_word_enabled"]))
        msg = "설정을 저장했습니다"
        if self.cfg["hotkey"] != old_hotkey:
            self.hotkey.stop()
            self.hotkey = GlobalHotkey(self.cfg["hotkey"], self.sig_hotkey.emit, fallback=False)
            self.hotkey.start()
            if not self.hotkey.ok:   # 사용자가 고른 조합이 안 되면 원래 조합으로 되돌림
                msg += f" (단축키 {self.cfg['hotkey']} 등록 실패 — 다른 앱이 사용 중, {old_hotkey.upper()} 유지)"
                self.cfg.update({"hotkey": old_hotkey})
                self.hotkey = GlobalHotkey(old_hotkey, self.sig_hotkey.emit)
                self.hotkey.start()
            self._show_hotkey()
        self.bridge.toast.emit("info", msg)
        if not self.busy and not self.speaker.playing:
            self._to_idle()

    def _icon(self) -> QIcon:
        pm = QPixmap(64, 64)
        pm.fill(QColor(0, 0, 0, 0))
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing)
        g = QRadialGradient(QPointF(32, 32), 30)
        g.setColorAt(0.0, QColor(255, 255, 255, 255))
        g.setColorAt(0.35, QColor(62, 230, 255, 230))
        g.setColorAt(1.0, QColor(62, 230, 255, 0))
        p.setBrush(g)
        p.setPen(QPen(QColor(62, 230, 255), 3))
        p.drawEllipse(QPointF(32, 32), 27, 27)
        p.setBrush(QColor(0, 0, 0, 0))
        p.setPen(QPen(QColor(200, 250, 255), 2))
        p.drawEllipse(QPointF(32, 32), 15, 15)
        p.end()
        ico = DATA_DIR / "jarvis.ico"
        if not ico.exists():
            pm.save(str(ico))
        return QIcon(pm)

    def _refresh_link(self) -> None:
        """두뇌 연결 상태를 HUD 에 반영."""
        if self.cfg["brain"] == "local":
            ok, text, model = False, "LOCAL ONLY · NO TOKENS", "LOCAL"
        elif (self.cfg["brain"] or "pro") == "pro":
            ok = bool(Brain.claude_exe())
            text = "AI LINK · PRO ACCOUNT" if ok else "CLAUDE CODE NOT FOUND"
            model = f"PRO · {self.cfg['pro_model'] or 'haiku'}"
        else:
            ok = bool(self.cfg.api_key())
            text = "AI LINK · API" if ok else "LOCAL MODE · NO API KEY"
            model = self.cfg["model"] or ""
        self.bridge.set("hasApiKey", ok)
        self.bridge.set("linkText", text)
        self.bridge.set("modelName", model)

    def _make_tray(self) -> None:
        icon = self._icon()
        self.app.setWindowIcon(icon)
        self.tray = QSystemTrayIcon(icon, self)
        self.tray.setToolTip("J.A.R.V.I.S")
        menu = QMenu()
        menu.addAction("HUD 보이기 / 숨기기", lambda: self.toggle_visible(force=True))
        menu.addAction("지금 듣기", self.activate)
        self.act_wake = QAction("“자비스” 호출어 대기", menu, checkable=True)
        self.act_wake.setChecked(bool(self.cfg["wake_word_enabled"]))
        self.act_wake.toggled.connect(lambda on: on != self.bridge._wakeEnabled and self.set_wake(on))
        menu.addAction(self.act_wake)
        self.act_chat = QAction("자유 대화 모드", menu, checkable=True)
        self.act_chat.toggled.connect(lambda on: on != self.brain.chat_mode and self.toggle_chat())
        menu.addAction(self.act_chat)
        self.act_active = QAction("액티브 모드 (전체 화면 HUD)", menu, checkable=True)
        self.act_active.toggled.connect(lambda on: on != self.bridge._activeMode and self.set_active(on))
        menu.addAction(self.act_active)
        menu.addAction("목소리 등록 (주인 인식)", self.start_enroll)
        self.act_startup = QAction("Windows 시작 시 자동 실행", menu, checkable=True)
        self.act_startup.setChecked(_startup_link().exists())
        self.act_startup.toggled.connect(self._toggle_startup)
        menu.addAction(self.act_startup)
        menu.addAction("데이터 폴더 열기", lambda: os.startfile(str(DATA_DIR)))
        menu.addSeparator()
        menu.addAction("종료", self.quit)
        self._menu = menu
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self._tray_activated)
        self.tray.show()

    def _tray_activated(self, reason) -> None:
        if reason in (QSystemTrayIcon.ActivationReason.Trigger, QSystemTrayIcon.ActivationReason.DoubleClick):
            self.toggle_visible(force=True)

    def _toggle_startup(self, on: bool) -> None:
        link = _startup_link()
        try:
            if on:
                import win32com.client
                exe = Path(sys.executable)
                pyw = exe.with_name("pythonw.exe")
                sc = win32com.client.Dispatch("WScript.Shell").CreateShortcut(str(link))
                sc.TargetPath = str(pyw if pyw.exists() else exe)
                sc.Arguments = f'"{ROOT / "main.py"}"'
                sc.WorkingDirectory = str(ROOT)
                sc.IconLocation = str(DATA_DIR / "jarvis.ico")
                sc.Description = "J.A.R.V.I.S"
                sc.Save()
                self.bridge.toast.emit("info", "Windows 시작 시 자동 실행됩니다")
            else:
                link.unlink(missing_ok=True)
                self.bridge.toast.emit("info", "자동 실행을 해제했습니다")
        except Exception as e:
            self.bridge.toast.emit("error", f"자동 실행 설정 실패: {e}")

    # ================================================================== 기타
    def _make_chime(self) -> QSoundEffect:
        path = Path(tempfile.gettempdir()) / "jarvis_chime.wav"
        if not path.exists():
            sr = 44100
            parts = []
            for f, d in ((880, 0.07), (1320, 0.11)):
                t = np.arange(int(sr * d)) / sr
                env = np.minimum(1, t / 0.005) * np.exp(-t * 18)
                tone = np.sin(2 * math.pi * f * t) + 0.3 * np.sin(2 * math.pi * f * 2 * t)
                parts.append(tone * env)
            audio = (np.concatenate(parts) * 0.35 * 32767).astype(np.int16)
            with wave.open(str(path), "wb") as w:
                w.setnchannels(1)
                w.setsampwidth(2)
                w.setframerate(sr)
                w.writeframes(audio.tobytes())
        fx = QSoundEffect(self)
        fx.setSource(QUrl.fromLocalFile(str(path)))
        fx.setVolume(0.45)
        return fx

    def show_external(self) -> None:
        self.toggle_visible(True, force=True)

    def quit(self) -> None:
        try:
            self.listener.stop()
            self.brain.shutdown()
            self.toolserver.stop()
            self.hotkey.stop()
            self.focus.stop()
            self._cancel.set()
            for cid in list(self._confirms):
                self.answer_confirm(cid, False)
            self.tray.hide()
        finally:
            self.app.quit()


def _startup_link() -> Path:
    return Path(os.environ.get("APPDATA", "")) / r"Microsoft\Windows\Start Menu\Programs\Startup\JARVIS.lnk"
