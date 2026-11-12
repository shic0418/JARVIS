"""방어 프로토콜 장면의 덮개 창 — 막아 낸 울트론이 조각나 사라지는 모습을 울트론 HUD 가 있던 자리에 그린다.

울트론은 이 장면이 시작되기 전에 이미 꺼져 있다 (촉수가 닿기 전에 막아야 하므로). 그래서 끄기 직전에 찍어 둔
울트론 HUD 그림을 그 자리에 다시 놓고, 그것을 부순다. 울트론 HUD 가 보이지 않았으면 화면 오른쪽 아래에 울트론 코어를 대신 그린다.
덮개 창은 반격 장면과 같은 것(counter_view.CounterView)을 쓴다 — 마우스 · 키보드는 아래 창으로 그대로 통과한다.

  play((울트론 그림, 실제 픽셀 영역) | None) → 'repelled'
"""
from __future__ import annotations

import logging

import numpy as np
from PySide6.QtCore import QElapsedTimer, QEventLoop, QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QFont, QGuiApplication, QImage, QLinearGradient, QPainter, QPen
from PySide6.QtWidgets import QApplication

from . import counter as C
from . import defense as D
from .counter_view import PANEL, CounterView, _c, _stand_in, to_logical, to_qimage

log = logging.getLogger("jarvis.defense")


class DefenseScene:
    def __init__(self, image: np.ndarray, hud: QRectF, bounds: QRectF) -> None:
        self.hud = QRectF(hud)
        self.scale = image.shape[1] / max(1.0, hud.width())          # 그림 픽셀 / 논리 픽셀
        self.shatter = D.Shatter(image, self.scale)
        m = self.shatter.margin / self.scale
        H, W = self.shatter.size
        self.canvas = QRectF(hud.x() - m, hud.y() - m, W / self.scale, H / self.scale)
        pw, ph = PANEL
        px, py = hud.x() - pw - 18, hud.bottom() - ph
        if px < bounds.x() + 8:
            px, py = max(bounds.x() + 8, hud.right() - pw), hud.y() - ph - 18
        self.panel = QRectF(px, max(bounds.y() + 8, py), pw, ph)
        area = self.canvas.united(self.panel.adjusted(-4, -4, 4, 4)).united(hud.adjusted(-14, -14, 14, 14))
        self.area = area.intersected(bounds) if bounds.isValid() else area
        self.font = QFont()
        self.font.setFamilies(["Consolas", "Malgun Gothic"])
        self.font.setPixelSize(12)
        self.title_font = QFont(self.font)
        self.title_font.setBold(True)

    def image(self, t: float) -> QImage:
        return to_qimage(self.shatter.frame(t))

    def paint(self, g: QPainter, t: float, fade: float = 1.0, origin: QPointF | None = None) -> None:
        o = origin if origin is not None else self.area.topLeft()
        g.save()
        g.translate(-o.x(), -o.y())
        g.setRenderHint(QPainter.Antialiasing, True)
        g.setRenderHint(QPainter.SmoothPixmapTransform, True)
        # 1) 부서지는 울트론
        g.setOpacity(fade)
        g.drawImage(self.canvas, self.image(t))
        g.setOpacity(1.0)
        # 2) 방어막: 울트론 둘레로 푸른 테가 닫힌다 (촉수가 끊긴다). 면을 채우지 않는다 — 번쩍임 없음
        a0, a1 = D.SHIELD
        close = float(C.smooth((t - a0) / (a1 - a0)))
        sp = D.sweep_progress(t)
        sa = close * (1 - float(C.smooth((t - D.SWEEP[1]) / 0.8))) * fade
        if sa > 0:
            gap = 14 + 40 * (1 - close)
            r = self.hud.adjusted(-gap, -gap, gap, gap)
            g.setBrush(Qt.NoBrush)
            g.setPen(QPen(_c(C.CYAN, 0.75 * sa), 1.6))
            g.drawRoundedRect(r, 10, 10)
            g.setPen(QPen(_c(C.CYAN_HOT, 0.85 * sa), 3.0, Qt.SolidLine, Qt.FlatCap))
            L = 22
            for (x, y, dx, dy) in ((r.left(), r.top(), 1, 1), (r.right(), r.top(), -1, 1),
                                   (r.left(), r.bottom(), 1, -1), (r.right(), r.bottom(), -1, -1)):
                g.drawLine(QPointF(x, y), QPointF(x + dx * L, y))
                g.drawLine(QPointF(x, y), QPointF(x, y + dy * L))
        # 3) 훑고 내려가는 푸른 선 (좁은 띠 — 넓은 면을 밝히지 않는다)
        la = float(C.smooth(sp * 8)) * (1 - float(C.smooth((sp - 0.92) / 0.08))) * fade
        if 0 < sp < 1 and la > 0:
            y = self.hud.y() + self.shatter.line_y(t) / self.scale
            grad = QLinearGradient(QPointF(0, y - 10), QPointF(0, y + 10))
            grad.setColorAt(0, _c(C.CYAN, 0))
            grad.setColorAt(0.5, _c(C.CYAN_HOT, 0.55 * la))
            grad.setColorAt(1, _c(C.CYAN, 0))
            g.setPen(Qt.NoPen)
            g.setBrush(grad)
            g.drawRect(QRectF(self.hud.x() - 10, y - 10, self.hud.width() + 20, 20))
            g.setPen(QPen(_c(C.CYAN_HOT, 0.9 * la), 1.2))
            g.drawLine(QPointF(self.hud.x() - 10, y), QPointF(self.hud.right() + 10, y))
        # 4) 방어 콘솔
        pa = float(C.smooth(t / 0.4)) * fade
        if pa > 0:
            self._console(g, t, pa)
        g.restore()

    def _console(self, g: QPainter, t: float, a: float) -> None:
        p = self.panel
        g.setPen(QPen(_c(C.CYAN, 0.75 * a), 1.0))
        g.setBrush(_c(C.DARK, 0.84 * a))
        g.drawRoundedRect(p, 6, 6)
        g.setPen(Qt.NoPen)
        g.setBrush(_c(C.CYAN, 0.9 * a))
        g.drawRect(QRectF(p.x(), p.y() + 10, 3, p.height() - 20))
        g.save()
        g.setClipRect(p.adjusted(4, 2, -6, -16))
        y = p.y() + 22
        for i, line in enumerate(D.console_lines(t)):
            g.setFont(self.title_font if i == 0 else self.font)
            g.setPen(_c(C.CYAN_HOT if i == 0 else C.CYAN, a))
            g.drawText(QPointF(p.x() + 16, y), line)
            y += 20 if i == 0 else 18
        g.restore()
        bar = QRectF(p.x() + 16, p.bottom() - 12, p.width() - 32, 3)
        g.setPen(Qt.NoPen)
        g.setBrush(_c(C.CYAN, 0.25 * a))
        g.drawRect(bar)
        g.setBrush(_c(C.CYAN, 0.9 * a))
        g.drawRect(QRectF(bar.x(), bar.y(), bar.width() * D.sweep_progress(t), bar.height()))


def make_scene(shot: tuple | None) -> DefenseScene:
    if shot:
        img, rect = shot
        hud = to_logical(rect)
    else:
        img, hud, _core = _stand_in()
    screen = QGuiApplication.screenAt(hud.center().toPoint()) or QGuiApplication.primaryScreen()
    return DefenseScene(img, hud, QRectF(screen.geometry()))


def play(shot: tuple | None) -> str:
    """방어 장면을 보여 준다 (울트론은 이미 꺼져 있다)."""
    app = QApplication.instance() or QApplication([])
    scene = make_scene(shot)
    view = CounterView(scene)
    try:
        from .config import DATA_DIR
        C.play_wav(C.write_wav(D.sound(), DATA_DIR / "defense.wav"))
    except Exception as e:
        log.debug("방어 소리 준비 실패: %s", e)
    clock = QElapsedTimer()
    loop = QEventLoop()

    def tick() -> None:
        t = clock.elapsed() / 1000.0
        view.t = t
        if t >= D.END:
            view.fade = max(0.0, 1 - (t - D.END) / D.FADE)
            if t >= D.END + D.FADE:
                timer.stop()
                loop.quit()
                return
        view.update()

    timer = QTimer()
    timer.setTimerType(Qt.PreciseTimer)
    timer.setInterval(16)
    timer.timeout.connect(tick)
    view.show()
    clock.start()
    timer.start()
    loop.exec()
    view.hide()
    view.deleteLater()
    app.processEvents()
    return "repelled"


def demo() -> None:
    """(개발용) 울트론 없이 장면만 본다: python -m jarvis.defense_view"""
    play(None)


if __name__ == "__main__":
    demo()
