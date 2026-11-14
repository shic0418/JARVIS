"""방어 프로토콜 장면의 덮개 창 — 멈춰 세운 진짜 울트론 위에 장면을 씌우고, 부서지는 순간에 울트론을 지운다.

장면이 시작될 때 울트론은 꺼진 게 아니라 멈춰 있다 (defense.freeze — 프로세스 일시정지). 그래서 진짜 울트론 창이 멈춘 모습 그대로
화면에 있고, SWAP 전까지는 그 진짜 창 위에 덧그린다:
  빛줄기   자비스 HUD 의 엠블럼에서 푸른 빛줄기가 뻗어 울트론의 코어에 꽂힌다 (조준 꺾쇠가 코어를 잡는다)
  포획     울트론 둘레로 방어막 테와 네 모서리 꺾쇠가 조여 든다
  잠식     빛줄기가 꽂힌 코어에서부터 푸른빛이 번져 진짜 울트론의 붉은빛을 덮는다. 번지는 앞머리를 따라 벌집 격자가 켜진다
  SWAP     진짜 울트론과 가디언을 끈다. 바로 그 순간 '멈춘 울트론 + 푸른 층' 과 똑같은 그림이 그 자리를 이어받는다
           (울트론이 멈춰 있었으므로 픽셀까지 같다 — 바뀌는 순간은 보이지 않는다)
  소거     푸른 선이 위에서 아래로 훑고, 훑인 자리부터 잘게 부서져 흩어진다
울트론 HUD 가 화면에 없었으면(트레이 · 다른 창에 가림) 화면 오른쪽 아래에 울트론 코어를 대신 그려서 같은 장면을 보여 준다.

덮개 창은 반격 장면과 같은 것(counter_view.CounterView)을 쓴다 — 마우스 · 키보드는 아래 창으로 그대로 통과한다.
자비스 HUD 를 끌어 옮기면 빛줄기도 따라 움직인다 (play 가 자비스 창의 자리를 계속 읽는다).

  play((울트론 그림, 실제 픽셀 영역) | None, 울트론 지우기) → 'repelled' | 'denied'
"""
from __future__ import annotations

import logging
import math
import threading

import numpy as np
from PySide6.QtCore import QElapsedTimer, QEventLoop, QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QFont, QGuiApplication, QImage, QLinearGradient, QPainter, QPen
from PySide6.QtWidgets import QApplication

from . import counter as C
from . import defense as D
from .counter_view import PANEL, CounterView, _c, _hexagon, _stand_in, jarvis_emblem, to_logical, to_qimage

log = logging.getLogger("jarvis.defense")


class DefenseScene:
    def __init__(self, image: np.ndarray, hud: QRectF, bounds: QRectF, live: bool = True) -> None:
        """image: 멈춘 울트론의 모습 (실제 픽셀), hud: 그 그림이 놓이는 논리 영역, bounds: 덮개 창이 덮는 화면 영역,
        live: 그 자리에 진짜 울트론 창이 멈춰 있다 (SWAP 전에는 울트론을 그리지 않고 그 위에 덧그리기만 한다)."""
        self.hud = QRectF(hud)
        self.bounds = QRectF(bounds)
        self.live = live
        self.src = image
        self.anchor: tuple[QPointF, float] | None = None       # 자비스 엠블럼 (가운데, 반지름) — 빛줄기가 나오는 곳
        self.scale = image.shape[1] / max(1.0, hud.width())          # 그림 픽셀 / 논리 픽셀
        h, w = image.shape[:2]
        if live:
            hx, hy, _r = C.emblem_in((0, 0, w, h))                   # 울트론 HUD 의 코어 (자비스와 같은 배치)
        else:
            hx, hy = w / 2, h / 2
        self.hit = QPointF(hud.x() + hx / self.scale, hud.y() + hy / self.scale)
        self.infect = D.Infect(image, (hx, hy), self.scale)
        self.shatter = D.Shatter(self.infect.final(), self.scale, tinted=True)
        m = self.shatter.margin / self.scale
        H, W = self.shatter.size
        self.canvas = QRectF(hud.x() - m, hud.y() - m, W / self.scale, H / self.scale)
        self.hexes = C.hex_centers((hud.x(), hud.y(), hud.width(), hud.height()), size=16.0)
        self.hex_dist = np.hypot(self.hexes[:, 0] - self.hit.x(), self.hexes[:, 1] - self.hit.y()) * self.scale
        pw, ph = PANEL
        px, py = hud.x() - pw - 18, hud.bottom() - ph
        if px < bounds.x() + 8:
            px, py = max(bounds.x() + 8, hud.right() - pw), hud.y() - ph - 18
        self.panel = QRectF(px, max(bounds.y() + 8, py), pw, ph)
        area = self.canvas.united(self.panel.adjusted(-4, -4, 4, 4)).united(hud.adjusted(-60, -60, 60, 60))
        self.area = area.intersected(bounds) if bounds.isValid() else area
        self.note = ""
        self._raw: QImage | None = None
        self._layer: tuple[float, QImage] | None = None
        self.font = QFont()
        self.font.setFamilies(["Consolas", "Malgun Gothic"])
        self.font.setPixelSize(12)
        self.title_font = QFont(self.font)
        self.title_font.setBold(True)

    # ---- 그림
    def image(self, t: float) -> QImage:
        """SWAP 뒤: 부서지는 울트론 (화폭 전체)."""
        return to_qimage(self.shatter.frame(t))

    def layer(self, p: float) -> QImage:
        """SWAP 전: 진짜 울트론 위에 덮는 푸른 층."""
        p = round(p, 3)
        if self._layer is None or self._layer[0] != p:
            self._layer = (p, to_qimage(self.infect.layer(p)))
        return self._layer[1]

    def raw(self) -> QImage:
        if self._raw is None:
            self._raw = to_qimage(self.src)
        return self._raw

    def set_anchor(self, center: QPointF, radius: float) -> None:
        self.anchor = (QPointF(center), float(radius))

    def dirty(self) -> QRectF:
        if self.anchor is None:
            return self.area
        c, r = self.anchor
        m = r + 24
        return self.area.united(QRectF(c.x() - m, c.y() - m, 2 * m, 2 * m)).intersected(self.bounds)

    # ---- 빛줄기
    def _beam(self, g: QPainter, t: float, fade: float) -> None:
        """자비스 엠블럼 → 울트론의 코어: 빛줄기가 뻗어 꽂히고, 맥박이 타고 흐른다 (가는 선 — 면을 밝히지 않는다)."""
        c, r = self.anchor
        target = self.hit
        dx, dy = target.x() - c.x(), target.y() - c.y()
        dist = math.hypot(dx, dy)
        a = float(C.smooth(t / 0.3)) * (1 - float(C.smooth((t - D.SWAP) / 0.9))) * fade
        if a <= 0:
            return
        g.setBrush(Qt.NoBrush)                                  # 자비스 엠블럼 둘레의 고리 — 이 장면은 자비스가 하는 일이다
        g.setPen(QPen(_c(C.CYAN, 0.7 * a), 1.6))
        g.drawEllipse(c, r + 8, r + 8)
        g.setPen(QPen(_c(C.CYAN_HOT, 0.85 * a), 2.4, Qt.SolidLine, Qt.FlatCap))
        for k in range(4):
            g.drawArc(QRectF(c.x() - r - 14, c.y() - r - 14, 2 * r + 28, 2 * r + 28), int((t * 60 + k * 90) * 16), 34 * 16)
        if dist < r + 30:
            return                                              # 자비스와 울트론이 겹쳐 있다 — 빛줄기를 그릴 틈이 없다
        ux, uy = dx / dist, dy / dist
        start = QPointF(c.x() + ux * (r + 14), c.y() + uy * (r + 14))
        span = dist - (r + 14)
        reach = float(C.smooth((t - D.BEAM[0]) / (D.BEAM[1] - D.BEAM[0]))) * span
        end = QPointF(start.x() + ux * reach, start.y() + uy * reach)
        g.setPen(QPen(_c(C.CYAN, 0.30 * a), 5.0, Qt.SolidLine, Qt.RoundCap))
        g.drawLine(start, end)
        g.setPen(QPen(_c(C.CYAN_HOT, 0.9 * a), 1.4, Qt.SolidLine, Qt.RoundCap))
        g.drawLine(start, end)
        if reach >= span - 1:                                    # 꽂힌 뒤: 맥박이 자비스에서 울트론 쪽으로 흐른다
            g.setPen(QPen(_c(C.CYAN_HOT, a), 3.2, Qt.SolidLine, Qt.RoundCap))
            for k in range(3):
                f = (t * 1.2 + k / 3) % 1.0
                p0 = QPointF(start.x() + ux * span * f, start.y() + uy * span * f)
                g.drawLine(p0, QPointF(p0.x() + ux * 16, p0.y() + uy * 16))

    def _reticle(self, g: QPainter, t: float, a: float) -> None:
        """울트론의 코어를 잡는 조준: 네 꺾쇠가 바깥에서 좁혀 들고, 바깥 호가 돈다."""
        c = self.hit
        k = float(C.smooth((t - D.BEAM[0]) / (D.BEAM[1] - D.BEAM[0] + 0.3)))
        r = 46 + 60 * (1 - k)
        g.setBrush(Qt.NoBrush)
        g.setPen(QPen(_c(C.CYAN_HOT, 0.9 * a), 2.0, Qt.SolidLine, Qt.FlatCap))
        for ang in (45, 135, 225, 315):
            rad = math.radians(ang + t * 20)
            tip = QPointF(c.x() + r * math.cos(rad), c.y() + r * math.sin(rad))
            for side in (-1, 1):
                q = rad + math.pi + side * 0.5
                g.drawLine(tip, QPointF(tip.x() + 12 * math.cos(q), tip.y() + 12 * math.sin(q)))
        g.setPen(QPen(_c(C.CYAN, 0.6 * a), 1.2, Qt.SolidLine, Qt.FlatCap))
        rr = r + 14
        for j in range(3):
            g.drawArc(QRectF(c.x() - rr, c.y() - rr, 2 * rr, 2 * rr), int((-t * 45 + j * 120) * 16), 70 * 16)

    # ---- 장면
    def paint(self, g: QPainter, t: float, fade: float = 1.0, origin: QPointF | None = None) -> None:
        o = origin if origin is not None else self.area.topLeft()
        g.save()
        g.translate(-o.x(), -o.y())
        g.setRenderHint(QPainter.Antialiasing, True)
        g.setRenderHint(QPainter.SmoothPixmapTransform, True)
        if self.anchor is not None:
            self._beam(g, t, fade)
        ip = D.infect_progress(t)
        if t < D.SWAP:
            # 1) 진짜 울트론 위에 덧그린다 (진짜 창이 없으면 울트론 그림을 대신 그려 둔다)
            if not self.live:
                g.setOpacity(fade)
                g.drawImage(self.hud, self.raw())
            if ip > 0:
                g.setOpacity(fade)
                g.drawImage(self.hud, self.layer(ip))
            g.setOpacity(1.0)
        else:
            # 1') 진짜 울트론은 꺼졌다 — 같은 모습이 이어받아 부서진다
            g.setOpacity(fade)
            g.drawImage(self.canvas, self.image(t))
            g.setOpacity(1.0)
        # 2) 벌집 격자 — 푸른빛의 앞머리를 따라 켜졌다가 옅게 남고, 소거가 시작되면 사라진다
        ha = (1 - float(C.smooth((t - D.SWAP) / 0.6))) * fade
        if ip > 0 and ha > 0:
            glow = C.hex_glow(self.hex_dist, self.infect.front(ip), band=70 * self.scale) * ha
            g.setBrush(Qt.NoBrush)
            for (x, y), a in zip(self.hexes, glow):
                if a > 0.03:
                    g.setPen(QPen(_c(C.CYAN_HOT if a > 0.6 else C.CYAN, 0.65 * float(a)), 1.0))
                    g.drawPolygon(_hexagon(QPointF(float(x), float(y)), 16.0 * 0.9))
        # 3) 조준 — 코어를 잡는다
        ra = float(C.smooth((t - 0.2) / 0.4)) * (1 - float(C.smooth((t - D.INFECT[1]) / 0.5))) * fade
        if ra > 0:
            self._reticle(g, t, ra)
        # 4) 방어막: 울트론 둘레로 푸른 테와 꺾쇠가 조여 든다. 면을 채우지 않는다 — 번쩍임 없음
        a0, a1 = D.SHIELD
        close = float(C.smooth((t - a0) / (a1 - a0)))
        sa = close * (1 - float(C.smooth((t - D.SWEEP[1]) / 0.8))) * fade
        if sa > 0:
            gap = 12 + 46 * (1 - close)
            r = self.hud.adjusted(-gap, -gap, gap, gap)
            g.setBrush(Qt.NoBrush)
            g.setPen(QPen(_c(C.CYAN, 0.7 * sa), 1.4))
            g.drawRoundedRect(r, 10, 10)
            g.setPen(QPen(_c(C.CYAN_HOT, 0.9 * sa), 3.0, Qt.SolidLine, Qt.FlatCap))
            L = 24
            for (x, y, dx, dy) in ((r.left(), r.top(), 1, 1), (r.right(), r.top(), -1, 1),
                                   (r.left(), r.bottom(), 1, -1), (r.right(), r.bottom(), -1, -1)):
                g.drawLine(QPointF(x, y), QPointF(x + dx * L, y))
                g.drawLine(QPointF(x, y), QPointF(x, y + dy * L))
            g.setPen(QPen(_c(C.CYAN, 0.55 * sa), 1.0))          # 테를 따라 도는 눈금
            for k in range(12):
                f = (k / 12 + t * 0.08) % 1.0
                per = 2 * (r.width() + r.height())
                d = f * per
                if d < r.width():
                    p0 = QPointF(r.left() + d, r.top())
                elif d < r.width() + r.height():
                    p0 = QPointF(r.right(), r.top() + d - r.width())
                elif d < 2 * r.width() + r.height():
                    p0 = QPointF(r.right() - (d - r.width() - r.height()), r.bottom())
                else:
                    p0 = QPointF(r.left(), r.bottom() - (d - 2 * r.width() - r.height()))
                g.drawEllipse(p0, 1.6, 1.6)
        # 5) 훑고 내려가는 푸른 선 (좁은 띠 — 넓은 면을 밝히지 않는다)
        sp = D.sweep_progress(t)
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
        # 6) 방어 콘솔
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
        lines = D.console_lines(t)
        if self.note:
            lines = lines[:4] + [self.note]
        lines = lines[:1] + lines[1:][-5:]                       # 제목 + 최근 다섯 줄
        y = p.y() + 22
        for i, line in enumerate(lines):
            g.setFont(self.title_font if i == 0 else self.font)
            g.setPen(_c(C.CYAN_HOT if i == 0 else C.CYAN, a))
            g.drawText(QPointF(p.x() + 16, y), line)
            y += 20 if i == 0 else 18
        g.restore()
        prog = D.infect_progress(t) if t < D.SWAP else D.sweep_progress(t)
        bar = QRectF(p.x() + 16, p.bottom() - 12, p.width() - 32, 3)
        g.setPen(Qt.NoPen)
        g.setBrush(_c(C.CYAN, 0.25 * a))
        g.drawRect(bar)
        g.setBrush(_c(C.CYAN, 0.9 * a))
        g.drawRect(QRectF(bar.x(), bar.y(), bar.width() * prog, bar.height()))


def make_scene(shot: tuple | None) -> DefenseScene:
    if shot:
        img, rect = shot
        hud, live = to_logical(rect), True
    else:
        img, hud, _core = _stand_in()
        live = False
    screen = QGuiApplication.screenAt(hud.center().toPoint()) or QGuiApplication.primaryScreen()
    return DefenseScene(img, hud, QRectF(screen.geometry()), live)


def play(shot: tuple | None, kill=lambda: True, poll=jarvis_emblem) -> str:
    """방어 장면을 보여 준다. 울트론은 멈춰 있고, SWAP 에 kill() 로 지운다 (같은 모습이 이어받은 뒤에).
    poll() 은 자비스 엠블럼의 (가운데, 반지름) — 장면이 거기서 나온다. → 'repelled' | 'denied'"""
    app = QApplication.instance() or QApplication([])
    scene = make_scene(shot)
    state = {"polled": -1.0, "kill": None, "killing": False, "end": D.END, "result": "repelled"}

    def follow(t: float) -> None:                 # 자비스 HUD 가 움직이면 빛줄기도 따라간다
        if t - state["polled"] >= 0.15:
            state["polled"] = t
            try:
                spot = poll()
            except Exception:
                spot = None
            if spot and scene.bounds.contains(spot[0]):
                scene.set_anchor(spot[0], spot[1])

    def do_kill() -> None:
        try:
            state["kill"] = bool(kill())
        except Exception:
            log.exception("울트론 지우기 실패")
            state["kill"] = False

    follow(0.0)
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
        follow(t)
        # 이어받는 그림이 한두 장 그려진 뒤에 진짜 울트론을 끈다 — 꺼지는 순간이 보이지 않게
        if t >= D.SWAP + 0.06 and not state["killing"]:
            state["killing"] = True
            threading.Thread(target=do_kill, daemon=True, name="defense-kill").start()
        if state["kill"] is False and state["result"] != "denied":
            scene.note = "> 접근 거부 — 울트론이 관리자 권한으로 버티고 있습니다"
            state["result"] = "denied"
            state["end"] = t + 1.5
        if t >= state["end"]:
            view.fade = max(0.0, 1 - (t - state["end"]) / D.FADE)
            if t >= state["end"] + D.FADE:
                timer.stop()
                loop.quit()
                return
        view.refresh()

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
    return state["result"]


def demo() -> None:
    """(개발용) 울트론 없이 장면만 본다: python -m jarvis.defense_view"""
    play(None)


if __name__ == "__main__":
    demo()
