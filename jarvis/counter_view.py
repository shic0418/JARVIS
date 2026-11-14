"""보안 프로토콜 반격 장면의 덮개 창 — counter.py 가 계산한 장면을 울트론 HUD 위에 그린다.

울트론의 흡수 연출 덮개와 같은 성질의 창이다: 마우스 · 키보드는 아래 창으로 그대로 통과하고, 포커스를 빼앗지 않는다.
창은 울트론 HUD 가 있는 모니터 전체를 덮지만, 실제로 다시 그리는 곳은 장면이 있는 영역뿐이다 (나머지는 투명한 채 그대로).

  play(찾은 울트론들, 울트론 끄기, 자비스 켜기) → 'countered' | 'denied'

울트론 HUD 가 화면에 보이면 그 모습을 찍어서 그 자리에 덮고(그래서 울트론이 꺼지는 순간이 보이지 않는다),
트레이로 숨어 있거나 가려 있으면 울트론 코어를 화면 오른쪽 아래에 대신 그려서 그것을 바꾼다.

장면은 자비스와 이어진다: 재구성된 자비스 고리는 진짜 자비스 HUD 가 나타나면 그 엠블럼 자리로 날아가 겹치며 사라지고,
그 사이 자비스 HUD 가 움직이면 고리도 따라간다 (play 가 자비스 창의 자리를 계속 읽는다).
"""
from __future__ import annotations

import logging
import math
import threading

import numpy as np
from PySide6.QtCore import QElapsedTimer, QEventLoop, QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import (QColor, QFont, QGuiApplication, QImage, QPainter, QPainterPath, QPen, QPolygonF,
                           QRadialGradient)
from PySide6.QtWidgets import QApplication, QWidget

from . import counter as C

log = logging.getLogger("jarvis.counter")

CORE_SIZE = 220          # 울트론 HUD 가 보이지 않을 때 대신 그리는 코어의 크기 (논리 픽셀)
PANEL = (380, 152)       # 보안 콘솔 크기
PAD = 96                 # HUD 둘레로 회로 · 조준 고리 · 파문이 퍼지는 여유


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


def jarvis_emblem() -> tuple[QPointF, float] | None:
    """지금 화면에 보이는 자비스 HUD 의 엠블럼 (가운데, 반지름 — 논리 좌표). 자비스가 아직 없으면 None."""
    rect = C.jarvis_hud_rect()
    if not rect:
        return None
    r = to_logical(rect)
    x, y, rad = C.emblem_in((r.x(), r.y(), r.width(), r.height()))
    return QPointF(x, y), rad


def _hexagon(c: QPointF, r: float) -> QPolygonF:
    return QPolygonF([QPointF(c.x() + r * math.cos(math.pi / 6 + k * math.pi / 3),
                              c.y() + r * math.sin(math.pi / 6 + k * math.pi / 3)) for k in range(6)])


def draw_emblem(g: QPainter, c: QPointF, r: float, t: float, a: float) -> None:
    """자비스 고리 — 세 조각 바깥 고리 · 눈금 고리 · 반대로 도는 안쪽 고리 · 가운데 빛."""
    if a <= 0 or r <= 1:
        return
    g.setBrush(Qt.NoBrush)
    spin = t * 38.0                                  # 도 / 초 — 천천히
    g.setPen(QPen(_c(C.CYAN, 0.9 * a), max(2.0, r * 0.06), Qt.SolidLine, Qt.FlatCap))
    for k in range(3):                               # 바깥 고리: 세 조각 호
        g.drawArc(QRectF(c.x() - r, c.y() - r, 2 * r, 2 * r), int((spin + k * 120) * 16), int(96 * 16))
    g.setPen(QPen(_c(C.CYAN, 0.5 * a), 1.0))
    r1 = r * 0.88
    for k in range(48):                              # 눈금 고리
        ang = math.radians(k * 7.5 - spin * 0.5)
        ln = r * (0.07 if k % 4 == 0 else 0.035)
        g.drawLine(QPointF(c.x() + (r1 - ln) * math.cos(ang), c.y() + (r1 - ln) * math.sin(ang)),
                   QPointF(c.x() + r1 * math.cos(ang), c.y() + r1 * math.sin(ang)))
    g.setPen(QPen(_c(C.CYAN, 0.55 * a), 1.2))
    r2 = r * 0.74
    g.drawEllipse(c, r2, r2)
    g.setPen(QPen(_c(C.CYAN_HOT, 0.8 * a), max(1.5, r * 0.035), Qt.SolidLine, Qt.FlatCap))
    r3 = r * 0.52
    for k in range(6):                               # 안쪽 고리: 반대로 도는 짧은 호
        g.drawArc(QRectF(c.x() - r3, c.y() - r3, 2 * r3, 2 * r3), int((-spin * 1.4 + k * 60) * 16), int(30 * 16))
    g.setPen(QPen(_c(C.CYAN, 0.45 * a), 1.0))
    g.drawPolygon(_hexagon(c, r * 0.36))
    grad = QRadialGradient(c, r * 0.34)
    grad.setColorAt(0, _c(C.CYAN_HOT, 0.85 * a))
    grad.setColorAt(0.5, _c(C.CYAN, 0.35 * a))
    grad.setColorAt(1, _c(C.CYAN, 0))
    g.setPen(Qt.NoPen)
    g.setBrush(grad)
    g.drawEllipse(c, r * 0.34, r * 0.34)


# ---------------------------------------------------------------- 장면 (창 없이도 그릴 수 있다 — 시험용)
class Scene:
    def __init__(self, image: np.ndarray, hud: QRectF, core: tuple[float, float], bounds: QRectF) -> None:
        """image: 울트론 그림 (실제 픽셀), hud: 그 그림이 놓이는 논리 영역, core: 그림 안 코어의 자리 (그림 픽셀),
        bounds: 덮개 창이 차지할 수 있는 화면 영역 (논리)."""
        self.hud = QRectF(hud)
        self.bounds = QRectF(bounds)
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
        box = (hud.x() - 24, hud.y() - 24, hud.width() + 48, hud.height() + 48)
        self.traces = C.traces((self.core.x(), self.core.y()), box)
        self.emblem_r = max(34.0, min(107.0, min(hud.width(), hud.height()) * 0.30))
        self.reach = max(math.hypot(x - self.core.x(), y - self.core.y())
                         for x in (hud.left(), hud.right()) for y in (hud.top(), hud.bottom()))
        self.hexes = C.hex_centers((hud.x(), hud.y(), hud.width(), hud.height()))
        self.hex_dist = np.hypot(self.hexes[:, 0] - self.core.x(), self.hexes[:, 1] - self.core.y())
        self.motes = C.Motes((hud.x(), hud.y(), hud.width(), hud.height()))
        self.dock: tuple[QPointF, float] | None = None    # 진짜 자비스 엠블럼 (가운데, 반지름) — 나타나면 정해진다
        self.dock_at: float | None = None
        self._img_p = -1.0
        self._img: QImage | None = None
        self.note = ""                     # 콘솔 마지막 줄을 바꿔 쓸 때 (울트론을 끌 수 없었을 때)
        self.font = QFont()
        self.font.setFamilies(["Consolas", "Malgun Gothic"])   # 영문은 고정폭, 한글은 맑은 고딕으로
        self.font.setPixelSize(12)
        self.title_font = QFont(self.font)
        self.title_font.setBold(True)
        self.name_font = QFont("Bahnschrift")
        self.name_font.setPixelSize(13)
        self.name_font.setLetterSpacing(QFont.AbsoluteSpacing, 6)
        self.name_font.setWeight(QFont.DemiBold)

    # ---- 자비스와 잇기
    def dock_to(self, center: QPointF, radius: float, t: float) -> None:
        """진짜 자비스 엠블럼의 자리 (자비스 HUD 가 움직이면 다시 부른다). 처음 부른 때부터 고리가 그리로 날아간다."""
        self.dock = (QPointF(center), float(radius))
        if self.dock_at is None:
            self.dock_at = t

    def emblem_at(self, t: float) -> tuple[QPointF, float]:
        """t 초에 자비스 고리의 (가운데, 반지름) — 합류가 시작되면 진짜 자비스 엠블럼 쪽으로 옮겨 간다."""
        d = C.dock_progress(t, self.dock_at)
        if self.dock is None or d <= 0:
            return self.core, self.emblem_r
        c, r = self.dock
        return (QPointF(self.core.x() + (c.x() - self.core.x()) * d, self.core.y() + (c.y() - self.core.y()) * d),
                self.emblem_r + (r - self.emblem_r) * d)

    def dirty(self) -> QRectF:
        """다시 그려야 하는 영역 (화면 좌표): 장면 영역 + 고리가 자비스에게 날아가는 길."""
        if self.dock is None:
            return self.area
        c, r = self.dock
        m = max(r, self.emblem_r) + 30
        return self.area.united(QRectF(c.x() - m, c.y() - m, 2 * m, 2 * m).united(
            QRectF(self.core.x() - m, self.core.y() - m, 2 * m, 2 * m))).intersected(self.bounds)

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
        dk = C.dock_progress(t, self.dock_at)
        stay = fade * (1 - dk)                           # 울트론 자리에 남는 것들 — 합류하는 동안 사라진다
        rp = C.rewrite_progress(t)
        # 1) 울트론 그림 — 처음부터 실제 창을 덮는다 (얼어붙은 울트론). 재구성 동안 옅어진다
        g.setOpacity(stay * (1 - rb * (1 - C.GHOST)))
        g.drawImage(self.hud, self.image(t))
        g.setOpacity(1.0)
        # 2) 벌집 격자 — 재작성의 앞머리가 지나가는 칸이 켜졌다가 옅게 남는다
        ha = (1 - rb) * stay
        if ha > 0 and 0 < rp:
            glow = C.hex_glow(self.hex_dist, rp * (self.reach + 90)) * ha
            g.setBrush(Qt.NoBrush)
            for (x, y), a in zip(self.hexes, glow):
                if a > 0.02:
                    g.setPen(QPen(_c(C.CYAN_HOT if a > 0.6 else C.CYAN, 0.7 * float(a)), 1.0))
                    g.drawPolygon(_hexagon(QPointF(float(x), float(y)), C.HEX * 0.92))
        # 3) 각성 신호 — 코어에서 얇은 파문이 퍼진다
        for k, a in C.ping_rings(t):
            g.setBrush(Qt.NoBrush)
            g.setPen(QPen(_c(C.CYAN, 0.55 * a * stay), 1.4))
            rr = 8 + k * (self.reach * 0.75)
            g.drawEllipse(self.core, rr, rr)
        # 4) 코어 한가운데의 푸른 점 (흡수된 자비스가 깨어난다)
        spark = float(C.smooth((t - C.SPARK) / 0.5)) * (1 - rb) * stay
        if spark > 0:
            r = 3 + 9 * spark
            grad = QRadialGradient(self.core, r * 3)
            grad.setColorAt(0, _c(C.CYAN_HOT, 0.9 * spark))
            grad.setColorAt(0.35, _c(C.CYAN, 0.45 * spark))
            grad.setColorAt(1, _c(C.CYAN, 0))
            g.setPen(Qt.NoPen)
            g.setBrush(grad)
            g.drawEllipse(self.core, r * 3, r * 3)
        # 5) 회로 — 직각으로 꺾이는 반듯한 선과 꺾이는 자리의 작은 패드
        ta = (1 - rb) * stay
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
        # 6) 조준 고리 — 바깥에서 돌며 조여 들고, 재작성 진행률만큼 채워진다
        la = C.lock_alpha(t) * stay
        if la > 0:
            self._lock(g, t, la, rp)
        # 7) 빛 알갱이 — 울트론에서 풀려나 자비스 고리 자리로 소용돌이치며 모인다
        if C.CONVERGE[0] < t < C.CONVERGE[1] + 0.1 and stay > 0:
            pos, alpha = self.motes.state(t, (self.core.x(), self.core.y()), self.emblem_r)
            g.setPen(Qt.NoPen)
            for (x, y), a in zip(pos, alpha):
                if a > 0.03:
                    g.setBrush(_c(C.CYAN_HOT, 0.85 * float(a) * stay))
                    g.drawRect(QRectF(float(x) - 1.3, float(y) - 1.3, 2.6, 2.6))
        # 8) 자비스 고리 — 재구성 동안 그려지고, 자비스 HUD 가 나타나면 그 엠블럼 자리로 날아가 겹친다
        if rb > 0:
            c, r = self.emblem_at(t)
            ea = rb * fade * (1 - float(C.smooth((dk - 0.7) / 0.3)))    # 다 겹치면 진짜 엠블럼에게 자리를 내준다
            draw_emblem(g, c, r, t, ea)
            na = float(C.smooth((t - C.SHOCK[0]) / 0.5)) * stay
            if na > 0:                                   # 이름표
                g.setFont(self.name_font)
                g.setPen(_c(C.CYAN_HOT, 0.9 * na))
                g.drawText(QRectF(c.x() - 150, c.y() + r + 10, 300, 22), Qt.AlignHCenter | Qt.AlignTop, "J.A.R.V.I.S")
        # 9) 완성 파문 — 선 하나
        sk, sa = C.shock(t)
        if sa > 0:
            g.setBrush(Qt.NoBrush)
            g.setPen(QPen(_c(C.CYAN_HOT, 0.7 * sa * stay), 1.6))
            rr = self.emblem_r * (1.0 + 1.5 * sk)
            g.drawEllipse(self.core, rr, rr)
        # 10) 보안 콘솔
        pa = float(C.smooth(t / 0.4)) * stay
        if pa > 0:
            self._console(g, t, pa)
        g.restore()

    def _lock(self, g: QPainter, t: float, a: float, progress: float) -> None:
        c = self.core
        k = C.lock_scale(t)
        g.setBrush(Qt.NoBrush)
        for i, (mul, speed, n, span) in enumerate(((1.00, 26.0, 4, 52), (1.16, -40.0, 3, 74), (1.34, 18.0, 8, 16))):
            r = self.emblem_r * mul * k
            rect = QRectF(c.x() - r, c.y() - r, 2 * r, 2 * r)
            g.setPen(QPen(_c(C.CYAN, (0.75 - 0.18 * i) * a), 2.0 if i == 0 else 1.2, Qt.SolidLine, Qt.FlatCap))
            for j in range(n):
                g.drawArc(rect, int((t * speed + j * 360 / n) * 16), int(span * 16))
        # 진행률 호 (12시에서 시계 방향)
        r = self.emblem_r * 1.52 * k
        rect = QRectF(c.x() - r, c.y() - r, 2 * r, 2 * r)
        g.setPen(QPen(_c(C.CYAN, 0.22 * a), 3.0, Qt.SolidLine, Qt.FlatCap))
        g.drawArc(rect, 0, 360 * 16)
        g.setPen(QPen(_c(C.CYAN_HOT, 0.9 * a), 3.0, Qt.SolidLine, Qt.FlatCap))
        g.drawArc(rect, 90 * 16, -int(360 * 16 * progress))
        # 네 방향 꺾쇠가 안쪽을 겨눈다
        g.setPen(QPen(_c(C.CYAN_HOT, 0.85 * a), 2.0, Qt.SolidLine, Qt.FlatCap))
        d = r + 12
        for ang in (45, 135, 225, 315):
            rad = math.radians(ang)
            tip = QPointF(c.x() + d * math.cos(rad), c.y() + d * math.sin(rad))
            for side in (-1, 1):
                q = rad + side * 2.5
                g.drawLine(tip, QPointF(tip.x() + 12 * math.cos(q), tip.y() + 12 * math.sin(q)))

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
    """장면 하나를 그리는 덮개 창. 장면에 bounds(모니터 전체)가 있으면 그만큼 덮고, 다시 그리는 곳은 dirty() 뿐이다."""

    def __init__(self, scene) -> None:
        super().__init__(None, Qt.FramelessWindowHint | Qt.Tool | Qt.WindowStaysOnTopHint
                         | Qt.WindowTransparentForInput | Qt.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setWindowTitle("JARVIS PROTOCOL")       # 'J.A.R.V.I.S' 로 시작하지 않는다 — 다시 켠 자비스 HUD 와 헷갈리지 않게
        self.scene = scene
        bounds = getattr(scene, "bounds", None)
        self.setGeometry((bounds if bounds is not None and bounds.isValid() else scene.area).toAlignedRect())
        self.t = 0.0
        self.fade = 1.0
        self._last = None

    def refresh(self) -> None:
        """장면이 있는 곳만 다시 그린다 (지난번에 그린 곳도 함께 — 지나간 자국이 남지 않게)."""
        dirty = getattr(self.scene, "dirty", None)
        rect = (dirty() if dirty else self.scene.area).translated(-self.x(), -self.y()).toAlignedRect().adjusted(-2, -2, 2, 2)
        self.update(rect if self._last is None else rect.united(self._last))
        self._last = rect

    def paintEvent(self, _ev) -> None:
        g = QPainter(self)
        try:
            self.scene.paint(g, self.t, self.fade, QPointF(self.geometry().topLeft()))
        finally:
            g.end()


def _snapshot(found: list[C.Found]) -> tuple[np.ndarray, QRectF, tuple[float, float]] | None:
    """화면에 보이는 울트론 HUD 를 찍는다 → (그림, 논리 영역, 그림 안 코어 자리). 보이지 않으면 None."""
    shot = C.grab_hud(found)
    if not shot:
        return None
    img, rect = shot
    h, w = img.shape[:2]
    cx, cy, _r = C.emblem_in((0, 0, w, h))                # 울트론 HUD 의 엠블럼 자리 (자비스와 같은 배치)
    return img, to_logical(rect), (cx, cy)


def _stand_in() -> tuple[np.ndarray, QRectF, tuple[float, float]]:
    """울트론 HUD 가 안 보일 때: 화면 오른쪽 아래 (울트론 HUD 의 기본 자리)에 울트론 코어를 대신 그린다."""
    screen = QGuiApplication.primaryScreen()
    geo = screen.availableGeometry()
    dpr = screen.devicePixelRatio()
    px = int(round(CORE_SIZE * dpr))
    img = C.ultron_core_image(px)
    rect = QRectF(geo.right() - CORE_SIZE - 28, geo.bottom() - CORE_SIZE - 28, CORE_SIZE, CORE_SIZE)
    return img, rect, (px / 2, px / 2)


def play(found: list[C.Found], kill, relaunch, poll=jarvis_emblem, max_wait: float = C.MAX_WAIT) -> str:
    """반격 장면을 보여 준다. 장면 도중 kill() 로 울트론을 끄고, relaunch() 로 자비스를 켠다 → 'countered' | 'denied'.
    poll() 은 진짜 자비스 엠블럼의 (가운데, 반지름) 을 돌려준다 (아직 없으면 None) — 나타나면 고리가 그리로 날아가 겹친다."""
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
        if state["result"] == "countered" and t >= C.SHOCK[1] and t - state["polled"] >= 0.2:
            state["polled"] = t
            spot = poll() if state["launched"] else None
            if spot:                                      # 자비스가 나타났다 (움직이면 따라간다)
                scene.dock_to(spot[0], spot[1], t)
                if state["fade_at"] is None:
                    state["fade_at"] = t + C.DOCK
            elif t >= max_wait and state["fade_at"] is None:
                state["fade_at"] = t
        if state["fade_at"] is not None:
            view.fade = max(0.0, 1 - (t - state["fade_at"]) / C.FADE) if t >= state["fade_at"] else 1.0
            if t >= state["fade_at"] + C.FADE:
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
    """(개발용) 울트론 없이 장면만 본다: python -m jarvis.counter_view  (자비스가 켜져 있으면 고리가 그 엠블럼으로 날아간다)"""
    play([], lambda: True, lambda: None, max_wait=C.SHOCK[1] + 2.0)


if __name__ == "__main__":
    demo()
