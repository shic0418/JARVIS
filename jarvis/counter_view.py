"""보안 프로토콜 반격 장면의 덮개 창 — counter.py 가 계산한 장면을 울트론 HUD 위에 그린다.

울트론의 흡수 연출 덮개와 같은 성질의 창이다: 마우스 · 키보드는 아래 창으로 그대로 통과하고, 포커스를 빼앗지 않는다.
장면이 그려지는 영역(울트론 HUD 둘레 + 보안 콘솔)만큼만 창을 띄운다.

  play(찾은 울트론들, 울트론 끄기, 자비스 켜기) → 'countered' | 'denied'

울트론 HUD 가 화면에 보이면 그 모습을 찍어서 그 자리에 덮고(그래서 울트론이 꺼지는 순간이 보이지 않는다),
트레이로 숨어 있거나 가려 있으면 울트론 코어를 화면 오른쪽 아래에 대신 그려서 그것을 바꾼다.
"""
from __future__ import annotations

import logging
import threading

import numpy as np
from PySide6.QtCore import QElapsedTimer, QEventLoop, QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QGuiApplication, QImage, QPainter, QPainterPath, QPen, QRadialGradient
from PySide6.QtWidgets import QApplication, QWidget

from . import counter as C

log = logging.getLogger("jarvis.counter")

CORE_SIZE = 220          # 울트론 HUD 가 보이지 않을 때 대신 그리는 코어의 크기 (논리 픽셀)
PANEL = (380, 152)       # 보안 콘솔 크기
PAD = 40                 # HUD 둘레로 회로가 뻗어 나가는 여유


def _c(rgb, a: float) -> QColor:
    return QColor(int(rgb[0]), int(rgb[1]), int(rgb[2]), int(255 * min(max(a, 0.0), 1.0)))


def to_qimage(rgba: np.ndarray) -> QImage:
    rgba = np.ascontiguousarray(rgba)
    h, w = rgba.shape[:2]
    return QImage(rgba.data, w, h, 4 * w, QImage.Format_RGBA8888).copy()


def to_logical(rect: tuple[int, int, int, int]) -> QRectF:
    """실제 픽셀 영역 (왼, 위, 오, 아래) → Qt 논리 좌표. 모니터마다 배율이 달라도 그 모니터의 배율로 바꾼다
    (Qt 는 모니터의 왼쪽 위 모서리를 실제 좌표 그대로 두고, 그 안쪽만 배율로 나눈다)."""
    left, top, right, bottom = rect
    cx, cy = (left + right) / 2, (top + bottom) / 2
    for s in QGuiApplication.screens():
        g, r = s.geometry(), s.devicePixelRatio()
        if g.x() <= cx < g.x() + g.width() * r and g.y() <= cy < g.y() + g.height() * r:
            return QRectF(g.x() + (left - g.x()) / r, g.y() + (top - g.y()) / r, (right - left) / r, (bottom - top) / r)
    return QRectF(left, top, right - left, bottom - top)


# ---------------------------------------------------------------- 장면 (창 없이도 그릴 수 있다 — 시험용)
class Scene:
    def __init__(self, image: np.ndarray, hud: QRectF, core: tuple[float, float], bounds: QRectF) -> None:
        """image: 울트론 그림 (실제 픽셀), hud: 그 그림이 놓이는 논리 영역, core: 그림 안 코어의 자리 (그림 픽셀),
        bounds: 덮개 창이 차지할 수 있는 화면 영역 (논리)."""
        self.hud = QRectF(hud)
        scale = image.shape[1] / max(1.0, hud.width())
        self.rewrite = C.Rewrite(image, core, scale)
        self.core = QPointF(hud.x() + core[0] / scale, hud.y() + core[1] / scale)
        # 보안 콘솔: HUD 왼쪽 (자리가 없으면 위쪽), 아래를 맞춘다
        pw, ph = PANEL
        px, py = hud.x() - pw - 18, hud.bottom() - ph
        if px < bounds.x() + 8:
            px, py = max(bounds.x() + 8, hud.right() - pw), hud.y() - ph - 18
        self.panel = QRectF(px, max(bounds.y() + 8, py), pw, ph)
        area = hud.adjusted(-PAD, -PAD, PAD, PAD).united(self.panel.adjusted(-4, -4, 4, 4))
        self.area = area.intersected(bounds) if bounds.isValid() else area
        box = (hud.x() - PAD * 0.6, hud.y() - PAD * 0.6, hud.width() + PAD * 1.2, hud.height() + PAD * 1.2)
        self.traces = C.traces((self.core.x(), self.core.y()), box)
        self.emblem_r = max(34.0, min(110.0, min(hud.width(), hud.height()) * 0.30))
        self._img_p = -1.0
        self._img: QImage | None = None
        self.note = ""                     # 콘솔 마지막 줄을 바꿔 쓸 때 (울트론을 끌 수 없었을 때)
        self.font = QFont()
        self.font.setFamilies(["Consolas", "Malgun Gothic"])   # 영문은 고정폭, 한글은 맑은 고딕으로
        self.font.setPixelSize(12)
        self.title_font = QFont(self.font)
        self.title_font.setBold(True)

    def image(self, t: float) -> QImage:
        p = round(C.rewrite_progress(t), 3)          # 재작성이 진행될 때만 새로 계산한다
        if self._img is None or p != self._img_p:
            self._img, self._img_p = to_qimage(self.rewrite.frame(t)), p
        return self._img

    def paint(self, g: QPainter, t: float, fade: float = 1.0, origin: QPointF | None = None) -> None:
        """t 초의 장면을 그린다. origin: 덮개 창의 왼쪽 위 (화면 좌표) — 그만큼 옮겨서 그린다. fade: 끝날 때 전체 진하기."""
        o = origin if origin is not None else self.area.topLeft()
        g.save()
        g.translate(-o.x(), -o.y())
        g.setRenderHint(QPainter.Antialiasing, True)
        g.setRenderHint(QPainter.SmoothPixmapTransform, True)
        rb = C.rebuild_progress(t)
        # 1) 울트론 그림 — 처음부터 실제 창을 덮는다 (얼어붙은 울트론). 재구성 동안 옅어진다
        g.setOpacity(fade * (1 - rb * (1 - C.GHOST)))
        g.drawImage(self.hud, self.image(t))
        g.setOpacity(1.0)
        # 2) 코어 한가운데의 푸른 점 (흡수된 자비스가 깨어난다)
        spark = float(C.smooth((t - C.SPARK) / 0.5)) * (1 - rb) * fade
        if spark > 0:
            r = 3 + 9 * spark
            grad = QRadialGradient(self.core, r * 3)
            grad.setColorAt(0, _c(C.CYAN_HOT, 0.9 * spark))
            grad.setColorAt(0.35, _c(C.CYAN, 0.45 * spark))
            grad.setColorAt(1, _c(C.CYAN, 0))
            g.setPen(Qt.NoPen)
            g.setBrush(grad)
            g.drawEllipse(self.core, r * 3, r * 3)
        # 3) 회로 — 직각으로 꺾이는 반듯한 선과 꺾이는 자리의 작은 패드
        ta = (1 - rb) * fade
        if ta > 0 and t >= C.TRACE:
            pen = QPen(_c(C.CYAN, 0.85 * ta), 1.6)
            pen.setCapStyle(Qt.SquareCap)
            pen.setJoinStyle(Qt.MiterJoin)
            for tr in self.traces:
                pts = tr.drawn(t)
                if len(pts) < 2:
                    continue
                path = QPainterPath(QPointF(*pts[0]))
                for x, y in pts[1:]:
                    path.lineTo(x, y)
                g.setPen(pen)
                g.setBrush(Qt.NoBrush)
                g.drawPath(path)
                g.setPen(Qt.NoPen)
                g.setBrush(_c(C.CYAN, 0.9 * ta))
                for x, y in pts[1:-1]:
                    g.drawRect(QRectF(x - 2, y - 2, 4, 4))
                hx, hy = pts[-1]
                if len(pts) <= len(tr.points) and (t - tr.start) * C.TRACE_SPEED < tr.length:
                    g.setBrush(_c(C.CYAN_HOT, ta))
                    g.drawEllipse(QPointF(hx, hy), 2.6, 2.6)
        # 4) 자비스 고리 — 재구성 동안 그려지고, 자비스 HUD 가 나타날 때까지 천천히 돈다
        if rb > 0:
            self._emblem(g, t, rb * fade)
        # 5) 보안 콘솔
        pa = float(C.smooth(t / 0.4)) * fade
        if pa > 0:
            self._console(g, t, pa)
        g.restore()

    def _emblem(self, g: QPainter, t: float, a: float) -> None:
        c, r = self.core, self.emblem_r
        g.setBrush(Qt.NoBrush)
        spin = t * 38.0                                  # 도 / 초 — 천천히
        g.setPen(QPen(_c(C.CYAN, 0.9 * a), max(2.0, r * 0.06), Qt.SolidLine, Qt.FlatCap))
        for k in range(3):                               # 바깥 고리: 세 조각 호
            g.drawArc(QRectF(c.x() - r, c.y() - r, 2 * r, 2 * r), int((spin + k * 120) * 16), int(96 * 16))
        g.setPen(QPen(_c(C.CYAN, 0.55 * a), 1.2))
        r2 = r * 0.74
        g.drawEllipse(c, r2, r2)
        g.setPen(QPen(_c(C.CYAN_HOT, 0.8 * a), max(1.5, r * 0.035), Qt.SolidLine, Qt.FlatCap))
        r3 = r * 0.52
        for k in range(6):                               # 안쪽 고리: 반대로 도는 짧은 눈금
            g.drawArc(QRectF(c.x() - r3, c.y() - r3, 2 * r3, 2 * r3), int((-spin * 1.4 + k * 60) * 16), int(30 * 16))
        grad = QRadialGradient(c, r * 0.36)
        grad.setColorAt(0, _c(C.CYAN_HOT, 0.85 * a))
        grad.setColorAt(0.5, _c(C.CYAN, 0.35 * a))
        grad.setColorAt(1, _c(C.CYAN, 0))
        g.setPen(Qt.NoPen)
        g.setBrush(grad)
        g.drawEllipse(c, r * 0.36, r * 0.36)

    def _console(self, g: QPainter, t: float, a: float) -> None:
        p = self.panel
        g.setPen(QPen(_c(C.CYAN, 0.75 * a), 1.0))
        g.setBrush(_c(C.DARK, 0.84 * a))
        g.drawRoundedRect(p, 6, 6)
        g.setPen(Qt.NoPen)
        g.setBrush(_c(C.CYAN, 0.9 * a))
        g.drawRect(QRectF(p.x(), p.y() + 10, 3, p.height() - 20))      # 왼쪽 띠
        g.save()
        g.setClipRect(p.adjusted(4, 2, -6, -16))                 # 글이 길어도 콘솔 밖 · 진행 막대 위로 넘치지 않게
        lines = C.console_lines(t)
        if self.note:
            lines = lines[:4] + [self.note]
        y = p.y() + 22
        for i, line in enumerate(lines):
            g.setFont(self.title_font if i == 0 else self.font)
            g.setPen(_c(C.CYAN_HOT if i == 0 else C.CYAN, a))
            g.drawText(QPointF(p.x() + 16, y), line)
            y += 20 if i == 0 else 18
        g.restore()
        # 아래쪽 진행 막대
        prog = C.rewrite_progress(t)
        bar = QRectF(p.x() + 16, p.bottom() - 12, p.width() - 32, 3)
        g.setPen(Qt.NoPen)
        g.setBrush(_c(C.CYAN, 0.25 * a))
        g.drawRect(bar)
        g.setBrush(_c(C.CYAN, 0.9 * a))
        g.drawRect(QRectF(bar.x(), bar.y(), bar.width() * prog, bar.height()))


# ---------------------------------------------------------------- 덮개 창
class CounterView(QWidget):
    def __init__(self, scene: Scene) -> None:
        super().__init__(None, Qt.FramelessWindowHint | Qt.Tool | Qt.WindowStaysOnTopHint
                         | Qt.WindowTransparentForInput | Qt.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setWindowTitle("JARVIS PROTOCOL")       # 'J.A.R.V.I.S' 로 시작하지 않는다 — 다시 켠 자비스 HUD 와 헷갈리지 않게
        self.scene = scene
        self.setGeometry(scene.area.toAlignedRect())
        self.t = 0.0
        self.fade = 1.0

    def paintEvent(self, _ev) -> None:
        g = QPainter(self)
        try:
            self.scene.paint(g, self.t, self.fade, QPointF(self.geometry().topLeft()))
        finally:
            g.end()


def _snapshot(found: list[C.Found]) -> tuple[np.ndarray, QRectF, tuple[float, float]] | None:
    """화면에 보이는 울트론 HUD 를 찍는다 → (그림, 논리 영역, 그림 안 코어 자리). 보이지 않으면 None."""
    for f in found:
        rect = C.hud_rect(f)
        if not rect:
            continue
        from PIL import ImageGrab
        img = np.asarray(ImageGrab.grab(bbox=rect, all_screens=True).convert("RGBA")).copy()
        h, w = img.shape[:2]
        core = (w / 2, w * 0.45 if h > w * 1.25 else h / 2)   # 울트론 HUD 의 엠블럼은 위쪽 가운데 (작게 보기면 한가운데)
        return img, to_logical(rect), core
    return None


def _stand_in() -> tuple[np.ndarray, QRectF, tuple[float, float]]:
    """울트론 HUD 가 안 보일 때: 화면 오른쪽 아래 (울트론 HUD 의 기본 자리)에 울트론 코어를 대신 그린다."""
    screen = QGuiApplication.primaryScreen()
    geo = screen.availableGeometry()
    dpr = screen.devicePixelRatio()
    px = int(round(CORE_SIZE * dpr))
    img = C.ultron_core_image(px)
    rect = QRectF(geo.right() - CORE_SIZE - 28, geo.bottom() - CORE_SIZE - 28, CORE_SIZE, CORE_SIZE)
    return img, rect, (px / 2, px / 2)


def play(found: list[C.Found], kill, relaunch, poll=C.jarvis_shown, max_wait: float = C.MAX_WAIT) -> str:
    """반격 장면을 보여 준다. 장면 도중 kill() 로 울트론을 끄고, relaunch() 로 자비스를 켠다 → 'countered' | 'denied'."""
    app = QApplication.instance() or QApplication([])
    shot = _snapshot(found)
    image, hud, core = shot if shot else _stand_in()
    screen = QGuiApplication.screenAt(hud.center().toPoint()) or QGuiApplication.primaryScreen()
    scene = Scene(image, hud, core, QRectF(screen.geometry()))
    view = CounterView(scene)
    try:
        from .config import DATA_DIR
        C.play_wav(C.write_wav(C.sound(), DATA_DIR / "counter.wav"))
    except Exception as e:
        log.debug("반격 소리 준비 실패: %s", e)

    state = {"kill": None, "launched": False, "fade_at": None, "result": "countered", "polled": 0.0}
    clock = QElapsedTimer()
    loop = QEventLoop()

    def do_kill() -> None:
        try:
            state["kill"] = bool(kill())
        except Exception:
            log.exception("울트론 끄기 실패")
            state["kill"] = False

    def tick() -> None:
        t = clock.elapsed() / 1000.0
        view.t = t
        if t >= C.TAKEOVER and state["kill"] is None and not state.get("killing"):
            state["killing"] = True
            threading.Thread(target=do_kill, daemon=True, name="counter-kill").start()
        if state["kill"] is False and state["fade_at"] is None:
            scene.note = "> 접근 거부 — 울트론이 관리자 권한으로 버티고 있습니다"
            state["result"] = "denied"
            state["fade_at"] = t + 2.0                    # 거부 문구를 잠깐 보여 주고 거둔다
        if state["kill"] and not state["launched"] and t >= C.LAUNCH:
            state["launched"] = True
            relaunch()
        if state["fade_at"] is None and t >= C.REBUILD[1]:
            if t - state["polled"] >= 0.25:
                state["polled"] = t
                if (state["launched"] and poll()) or t >= max_wait:
                    state["fade_at"] = t
        if state["fade_at"] is not None:
            view.fade = max(0.0, 1 - (t - state["fade_at"]) / C.FADE) if t >= state["fade_at"] else 1.0
            if t >= state["fade_at"] + C.FADE:
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
    return state["result"]


def demo() -> None:
    """(개발용) 울트론 없이 장면만 본다: python -m jarvis.counter_view"""
    play([], lambda: True, lambda: None, poll=lambda: False, max_wait=C.REBUILD[1] + 1.5)


if __name__ == "__main__":
    demo()
