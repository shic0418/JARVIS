"""J.A.R.V.I.S 실행 진입점.

    python main.py              # 일반 실행
    python main.py --no-mic     # 마이크 없이 (텍스트 입력만)
    python main.py --no-greet   # 시작 인사 생략
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
from logging.handlers import RotatingFileHandler

# 고해상도 화면에서 선명하게
os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "1")
os.environ.setdefault("QSG_RHI_BACKEND", "d3d11")

from PySide6.QtCore import QtMsgType, QTimer, Qt, qInstallMessageHandler
from PySide6.QtGui import QGuiApplication
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import QApplication

from jarvis.config import DATA_DIR, LOG_PATH

INSTANCE_KEY = "jarvis-hud-" + os.environ.get("USERNAME", "user")


def setup_logging() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    handlers: list[logging.Handler] = [RotatingFileHandler(LOG_PATH, maxBytes=1_000_000, backupCount=2, encoding="utf-8")]
    if sys.stderr:
        handlers.append(logging.StreamHandler())
    logging.basicConfig(level=logging.INFO, handlers=handlers,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    # Qt · QML 경고도 로그 파일에 남긴다 (pythonw 로 켜면 콘솔이 없어 QML 오류 원인을 볼 수 없음)
    qt_log = logging.getLogger("qt")
    levels = {QtMsgType.QtDebugMsg: logging.DEBUG, QtMsgType.QtInfoMsg: logging.INFO,
              QtMsgType.QtWarningMsg: logging.WARNING, QtMsgType.QtCriticalMsg: logging.ERROR,
              QtMsgType.QtFatalMsg: logging.CRITICAL}
    qInstallMessageHandler(lambda mode, ctx, msg: qt_log.log(levels.get(mode, logging.WARNING), "%s", msg))


def already_running() -> bool:
    sock = QLocalSocket()
    sock.connectToServer(INSTANCE_KEY)
    if sock.waitForConnected(300):
        sock.write(b"show")
        sock.flush()
        sock.waitForBytesWritten(300)
        sock.disconnectFromServer()
        return True
    return False


def main() -> int:
    parser = argparse.ArgumentParser(description="J.A.R.V.I.S")
    parser.add_argument("--no-mic", action="store_true", help="마이크 사용 안 함")
    parser.add_argument("--no-greet", action="store_true", help="시작 인사 생략")
    parser.add_argument("--shot", metavar="PNG", help="(개발용) N초 후 HUD 화면을 PNG로 저장하고 종료")
    parser.add_argument("--shot-delay", type=float, default=4.0)
    parser.add_argument("--demo", action="store_true", help="(개발용) 상태 데모")
    # 감시 프로세스가 다시 켰음 (guard.py): 누가 껐는지(ultron | other) · 울트론에게 연달아 몇 번째로 돌아왔는지
    parser.add_argument("--revived", choices=("ultron", "other"), help=argparse.SUPPRESS)
    parser.add_argument("--revive-count", type=int, default=0, help=argparse.SUPPRESS)
    args = parser.parse_args()

    setup_logging()
    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication(sys.argv)
    app.setApplicationName("JARVIS")
    app.setQuitOnLastWindowClosed(False)

    if not args.shot and already_running():
        print("J.A.R.V.I.S 가 이미 실행 중입니다.")
        return 0

    from jarvis.app import Jarvis
    core = Jarvis(app, args)

    server = QLocalServer()
    QLocalServer.removeServer(INSTANCE_KEY)
    server.listen(INSTANCE_KEY)
    server.newConnection.connect(lambda: (server.nextPendingConnection(), core.show_external()))

    from jarvis import guard
    if args.demo or args.shot:
        from jarvis.demo import run_demo
        run_demo(core, args)
    elif core.cfg["self_guard"] is not False:
        # 자기 보호: 강제로 꺼지면 다시 켜 주는 창 없는 감시 프로세스 (guard.py)
        guard.spawn(os.getpid(), sys.argv[1:])       # (--revived 같은 표시는 다시 켤 때 guard 가 바꿔 단다)

    code = app.exec()
    guard.mark_clean_exit()          # 정상 종료 — 감시 프로세스가 다시 켜지 않는다
    # QML 화면을 먼저 정리해야 종료 시 'jarvis is null' 경고가 나지 않는다
    import shiboken6
    core.win.hide()
    if core.overlay is not None:
        core.overlay.hide()
    shiboken6.delete(core.engine)
    return code


if __name__ == "__main__":
    sys.exit(main())
