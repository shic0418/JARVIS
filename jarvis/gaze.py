"""시선 추적 — 액티브 모드의 홀로그램 고리가 눈이 가는 곳을 따라가게 한다.

웹캠 한 대로 대략적인 시선을 추정한다 (전용 아이트래커 없이):
  1. YuNet(OpenCV 공식 얼굴 검출 모델, jarvis/models)으로 얼굴과 두 눈 · 코 위치를 찾는다.
  2. 고개 방향: 두 눈 가운데에 대한 코의 위치 (좌우 = yaw, 위아래 = pitch).
  3. 눈동자: 눈 주변에서 가장 어두운 부분의 무게중심이 눈 가운데에서 얼마나 벗어났는지.
  4. 위 값을 섞은 '날 시선'을 화면 좌표로 바꾼다. 사람마다 · 앉은 자세마다 기준이 달라서
     최근 값의 평균을 화면 가운데로, 흩어진 정도를 화면 폭으로 삼아 스스로 맞춘다(자동 보정).
  5. 떨림은 One Euro 필터로 누른다 (천천히 볼 때는 매끄럽게, 빨리 옮길 때는 바로 따라가게).

카메라 영상은 이 프로세스 메모리 안에서만 처리하고 저장 · 전송하지 않는다.
액티브 모드가 켜져 있는 동안에만 카메라를 열고, 끄면 바로 닫는다.
얼굴을 못 찾거나 카메라 · 모델이 없으면 latest() 가 None 을 돌려주고, 앱은 마우스 커서를 대신 따라간다.
"""
from __future__ import annotations

import logging
import math
import threading
import time
from pathlib import Path

log = logging.getLogger("jarvis.gaze")

MODEL = Path(__file__).resolve().parent / "models" / "face_detection_yunet_2023mar.onnx"
DET_SIZE = (320, 240)          # 얼굴 검출 입력 크기 (작을수록 빠름)


# ---------------------------------------------------------------- 순수 계산 (테스트 가능)
def pupil_offset(gray, cx: float, cy: float, eye_dist: float) -> tuple[float, float] | None:
    """눈 중심(cx, cy) 주변에서 눈동자(가장 어두운 부분)의 위치를 -1 ~ 1 로 돌려준다.

    gray: 2차원 numpy 배열 (흑백 영상). 영역이 너무 작거나 대비가 없으면 None.
    """
    import numpy as np
    hw, hh = 0.24 * eye_dist, 0.15 * eye_dist
    if hw < 4 or hh < 3:
        return None
    x0, x1 = int(round(cx - hw)), int(round(cx + hw))
    y0, y1 = int(round(cy - hh)), int(round(cy + hh))
    h, w = gray.shape[:2]
    if x0 < 0 or y0 < 0 or x1 > w or y1 > h:
        return None
    roi = gray[y0:y1, x0:x1].astype(np.float32)
    if roi.size < 20 or float(roi.max() - roi.min()) < 18:
        return None
    thr = float(np.percentile(roi, 14))
    wgt = np.clip(thr - roi, 0, None)
    total = float(wgt.sum())
    if total <= 0:
        return None
    ys, xs = np.mgrid[0:roi.shape[0], 0:roi.shape[1]]
    px = float((wgt * xs).sum() / total)
    py = float((wgt * ys).sum() / total)
    rx = (px - (roi.shape[1] - 1) / 2) / (roi.shape[1] / 2)
    ry = (py - (roi.shape[0] - 1) / 2) / (roi.shape[0] / 2)
    return max(-1.0, min(1.0, rx)), max(-1.0, min(1.0, ry))


def raw_gaze(face, img_w: int, img_h: int, pupils=None) -> tuple[float, float]:
    """YuNet 얼굴 한 줄(x, y, w, h, 오른눈xy, 왼눈xy, 코xy, ...) → 날 시선 (화면 기준: 오른쪽 · 아래가 +).

    카메라는 사용자를 마주 보므로 좌우가 거울처럼 뒤집혀 있다 → x 는 부호를 바꾼다.
    """
    rx, ry, lx, ly, nx, ny = (float(v) for v in face[4:10])
    mx, my = (rx + lx) / 2, (ry + ly) / 2
    d = max(1.0, math.hypot(lx - rx, ly - ry))
    yaw = (nx - mx) / d
    pitch = (ny - my) / d
    fx = mx / img_w - 0.5
    fy = my / img_h - 0.5
    px = py = 0.0
    if pupils:
        px = sum(p[0] for p in pupils) / len(pupils)
        py = sum(p[1] for p in pupils) / len(pupils)
    gx = -(yaw * 1.0 + px * 0.35 + fx * 0.35)
    gy = pitch * 1.0 + py * 0.25 + fy * 0.25
    return gx, gy


class AutoCal:
    """날 시선 → 0~1 화면 좌표. 최근 평균을 가운데로, 평균 편차를 화면 반 폭의 1/2.6 으로 삼는다."""

    def __init__(self, spread: float, tau_mean: float = 20.0, tau_spread: float = 40.0, gain: float = 2.6) -> None:
        self.mean: float | None = None
        self.spread = spread
        self.min_spread = spread * 0.35
        self.tau_mean, self.tau_spread, self.gain = tau_mean, tau_spread, gain

    def __call__(self, v: float, dt: float) -> float:
        if self.mean is None:
            self.mean = v
        a = 1 - math.exp(-dt / self.tau_mean)
        b = 1 - math.exp(-dt / self.tau_spread)
        self.mean += (v - self.mean) * a
        self.spread += (abs(v - self.mean) - self.spread) * b
        self.spread = max(self.min_spread, self.spread)
        return max(0.0, min(1.0, 0.5 + (v - self.mean) / (self.spread * self.gain) * 0.5))


class OneEuro:
    """One Euro 필터 — 느린 움직임은 강하게, 빠른 움직임은 약하게 걸러 떨림과 지연을 함께 줄인다."""

    def __init__(self, min_cutoff: float = 0.9, beta: float = 2.5, d_cutoff: float = 1.0) -> None:
        self.min_cutoff, self.beta, self.d_cutoff = min_cutoff, beta, d_cutoff
        self.x: float | None = None
        self.dx = 0.0

    @staticmethod
    def _alpha(cutoff: float, dt: float) -> float:
        tau = 1.0 / (2 * math.pi * cutoff)
        return 1.0 / (1.0 + tau / max(dt, 1e-3))

    def __call__(self, x: float, dt: float) -> float:
        if self.x is None:
            self.x = x
            return x
        dx = (x - self.x) / max(dt, 1e-3)
        self.dx += (dx - self.dx) * self._alpha(self.d_cutoff, dt)
        cutoff = self.min_cutoff + self.beta * abs(self.dx)
        self.x += (x - self.x) * self._alpha(cutoff, dt)
        return self.x


def pick_face(faces):
    """여러 얼굴이 잡히면 가장 크고 확실한 것 (사진 · 포스터보다 사용자가 보통 가장 크다)."""
    if faces is None or len(faces) == 0:
        return None
    return max(faces, key=lambda f: float(f[2]) * float(f[3]) * float(f[-1]))


# ---------------------------------------------------------------- 카메라 스레드
class GazeTracker:
    """start() 로 카메라를 열고 백그라운드에서 시선을 갱신한다. latest() → (x, y, 신뢰도) 0~1, 없으면 None."""

    def __init__(self, camera: int = 0, fps: float = 15.0) -> None:
        self.camera = camera
        self.period = 1.0 / max(5.0, fps)
        self.error = ""
        self._stop = threading.Event()
        self._stop.set()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._latest: tuple[float, float, float, float] | None = None   # x, y, conf, 시각

    @staticmethod
    def available() -> bool:
        if not MODEL.exists():
            return False
        try:
            import cv2
            return hasattr(cv2, "FaceDetectorYN")
        except Exception:
            return False

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> bool:
        if self.running or not self.available():
            return self.running
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, args=(self._stop,), daemon=True, name="gaze")
        self._thread.start()
        return True

    def stop(self) -> None:
        self._stop.set()
        with self._lock:
            self._latest = None

    def latest(self, max_age: float = 1.2) -> tuple[float, float, float] | None:
        with self._lock:
            v = self._latest
        if v is None or time.monotonic() - v[3] > max_age:
            return None
        return v[0], v[1], v[2]

    def _loop(self, stop: threading.Event) -> None:
        import cv2
        cap = None
        try:
            cv2.setNumThreads(1)          # 작은 영상이라 여러 스레드가 오히려 CPU 만 더 쓴다
            cap = cv2.VideoCapture(self.camera, cv2.CAP_DSHOW)
            if not cap.isOpened():
                self.error = "카메라를 열 수 없습니다"
                log.warning("시선 추적: %s", self.error)
                return
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
            det = cv2.FaceDetectorYN.create(str(MODEL), "", DET_SIZE, 0.6, 0.3, 50)
            cal_x, cal_y = AutoCal(0.10), AutoCal(0.07)
            fil_x, fil_y = OneEuro(), OneEuro()
            last = time.monotonic()
            self.error = ""
            log.info("시선 추적 시작 (카메라 %d)", self.camera)
            while not stop.is_set():
                t0 = time.monotonic()
                ok, frame = cap.read()
                if not ok or frame is None:
                    if stop.wait(0.2):
                        break
                    continue
                h, w = frame.shape[:2]
                small = cv2.resize(frame, DET_SIZE)
                _, faces = det.detect(small)
                face = pick_face(faces)
                if face is not None:
                    sx, sy = w / DET_SIZE[0], h / DET_SIZE[1]
                    f = [float(face[i]) * (sx if i % 2 == 0 else sy) for i in range(14)] + [float(face[-1])]
                    # 눈동자는 두 눈을 감싼 작은 영역만 흑백 · 흐림 처리한다 (화면 전체를 하면 CPU 를 몇 배 더 쓴다)
                    d = math.hypot(f[6] - f[4], f[7] - f[5])
                    bx0 = max(0, int(min(f[4], f[6]) - 0.4 * d)); bx1 = min(w, int(max(f[4], f[6]) + 0.4 * d))
                    by0 = max(0, int(min(f[5], f[7]) - 0.3 * d)); by1 = min(h, int(max(f[5], f[7]) + 0.3 * d))
                    pupils = []
                    if bx1 - bx0 > 8 and by1 - by0 > 6:
                        gray = cv2.GaussianBlur(cv2.cvtColor(frame[by0:by1, bx0:bx1], cv2.COLOR_BGR2GRAY), (5, 5), 0)
                        pupils = [p for p in (pupil_offset(gray, f[4] - bx0, f[5] - by0, d),
                                              pupil_offset(gray, f[6] - bx0, f[7] - by0, d)) if p]
                    gx, gy = raw_gaze(f, w, h, pupils)
                    now = time.monotonic()
                    dt = max(0.01, min(0.5, now - last))
                    last = now
                    x = fil_x(cal_x(gx, dt), dt)
                    y = fil_y(cal_y(gy, dt), dt)
                    conf = min(1.0, float(face[-1])) * (1.0 if pupils else 0.6)
                    with self._lock:
                        self._latest = (x, y, conf, now)
                spent = time.monotonic() - t0
                if stop.wait(max(0.0, self.period - spent)):
                    break
        except Exception as e:
            self.error = str(e)
            log.exception("시선 추적 실패")
        finally:
            if cap is not None:
                cap.release()
            with self._lock:
                self._latest = None
            log.info("시선 추적 종료")
