"""(개발용) HUD 상태 데모 / 스크린샷 저장."""
from __future__ import annotations

import math
import os
import time

from PySide6.QtCore import QTimer
from PySide6.QtGui import QColor, QImage, QLinearGradient, QPainter


def run_demo(core, args) -> None:
    b = core.bridge
    state = os.environ.get("JARVIS_DEMO_STATE", "speaking")
    t0 = time.monotonic()

    def fill():
        b.set("userText", "유튜브에서 아이유 노래 틀어주고 볼륨 40으로 맞춰줘")
        b.set("replyText", "아이유의 ‘밤편지’를 재생하고 볼륨을 40%로 맞췄습니다, 주인님.")
        for i, (label, st) in enumerate([("앱 실행 · 크롬", "ok"), ("YouTube 재생 · 아이유 노래", "ok"),
                                          ("볼륨 · set 40", "ok"), ("웹 검색 · 오늘 서울 날씨", "run")]):
            b.actionEvent.emit(f"demo{i}", label, st, "")
        if os.environ.get("JARVIS_DEMO_REPLY"):  # 긴 답 표시 확인용
            b.set("replyText", os.environ["JARVIS_DEMO_REPLY"])
        if os.environ.get("JARVIS_DEMO_CHAT"):   # 1 = 자유 대화 모드 표시
            b.set("chatMode", True)
        compact = os.environ.get("JARVIS_DEMO_COMPACT")
        if compact is not None:             # 1 = 축소 모드, 0 = 전체 모드 (설정 파일은 건드리지 않음)
            b.set("compact", compact not in ("", "0"))
            core._place()
        if state == "settings":
            from PySide6.QtCore import QMetaObject, QObject
            obj = core.win.findChild(QObject, "settings")
            QMetaObject.invokeMethod(obj, "show")
            core._set_state("standby", "“자비스”라고 불러주세요")
        elif state == "confirm":
            b.confirmRequest.emit("democ", "PowerShell 실행", "임시 파일 정리\n\nRemove-Item $env:TEMP\\*.log -Force")
            core._set_state("speaking")
        else:
            core._set_state(state, {"standby": "“자비스”라고 불러주세요"}.get(state))

    def wobble():
        t = time.monotonic() - t0
        lvl = 0.45 + 0.35 * abs(math.sin(t * 5.1)) * abs(math.sin(t * 1.7))
        if state in ("speaking", "confirm"):
            b.set("voiceLevel", lvl)
        elif state == "listening":
            b.set("micLevel", lvl)

    QTimer.singleShot(2600, fill)
    timer = QTimer(core)
    timer.timeout.connect(wobble)
    timer.start(33)
    core._demo_timer = timer

    if args.shot:
        def shot():
            img: QImage = core.win.grabWindow()
            img.setDevicePixelRatio(1.0)
            w, h = img.width(), img.height()
            out = QImage(w * 2 + 30, h + 20, QImage.Format.Format_ARGB32)
            p = QPainter(out)
            g = QLinearGradient(0, 0, w * 2, h)
            g.setColorAt(0, QColor("#1b2735"))
            g.setColorAt(1, QColor("#090a0f"))
            p.fillRect(0, 0, w + 15, h + 20, g)
            g2 = QLinearGradient(0, 0, 0, h)
            g2.setColorAt(0, QColor("#7aa7c7"))
            g2.setColorAt(0.5, QColor("#d9c6a5"))
            g2.setColorAt(1, QColor("#3d5a40"))
            p.fillRect(w + 15, 0, w + 15, h + 20, g2)
            p.drawImage(10, 10, img)
            p.drawImage(w + 20, 10, img)
            p.end()
            out.save(args.shot)
            print("saved", args.shot, w, h)
            core.quit()
        QTimer.singleShot(int(args.shot_delay * 1000), shot)
