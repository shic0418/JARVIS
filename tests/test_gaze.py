"""시선 추적 계산부 (카메라 없이)."""
from __future__ import annotations

import numpy as np

from jarvis.gaze import AutoCal, OneEuro, pick_face, pupil_offset, raw_gaze


def _eye(px: int, py: int, w: int = 120, h: int = 80) -> np.ndarray:
    img = np.full((h, w), 200, np.uint8)
    yy, xx = np.mgrid[0:h, 0:w]
    img[(xx - px) ** 2 + (yy - py) ** 2 <= 16] = 20      # 눈동자
    return img


def test_pupil_left_right():
    left = pupil_offset(_eye(52, 40), 60, 40, 60)
    right = pupil_offset(_eye(68, 40), 60, 40, 60)
    centre = pupil_offset(_eye(60, 40), 60, 40, 60)
    assert left[0] < -0.2 and right[0] > 0.2 and abs(centre[0]) < 0.1


def test_pupil_rejects_flat_or_out_of_bounds():
    flat = np.full((80, 120), 128, np.uint8)
    assert pupil_offset(flat, 60, 40, 60) is None
    assert pupil_offset(_eye(5, 5), 3, 3, 60) is None


def _face(nose_dx: float, nose_dy: float = 20.0):
    # x, y, w, h, 오른눈, 왼눈, 코, 입 오른쪽, 입 왼쪽, 점수
    return [100, 100, 120, 140, 130, 150, 190, 150, 160 + nose_dx, 150 + nose_dy, 135, 200, 185, 200, 0.95]


def test_raw_gaze_is_mirrored():
    # 사용자가 화면 오른쪽을 보면 카메라 영상에서는 코가 왼쪽으로 간다
    gx_right, _ = raw_gaze(_face(-12), 640, 480)
    gx_left, _ = raw_gaze(_face(12), 640, 480)
    assert gx_right > gx_left
    _, gy_down = raw_gaze(_face(0, 32), 640, 480)
    _, gy_up = raw_gaze(_face(0, 10), 640, 480)
    assert gy_down > gy_up


def test_autocal_centres_and_clamps():
    cal = AutoCal(0.1)
    for _ in range(200):
        v = cal(0.3, 0.05)
    assert abs(v - 0.5) < 0.05
    assert cal(5.0, 0.05) == 1.0 and cal(-5.0, 0.05) == 0.0


def test_one_euro_smooths_jitter_but_follows_moves():
    f = OneEuro()
    out = [f(0.5 + (0.01 if i % 2 else -0.01), 0.05) for i in range(40)]
    assert max(out[10:]) - min(out[10:]) < 0.012
    for _ in range(20):
        y = f(0.9, 0.05)
    assert y > 0.85


def test_pick_largest_confident_face():
    small = [0, 0, 20, 20] + [0] * 10 + [0.99]
    big = [0, 0, 120, 140] + [0] * 10 + [0.9]
    assert pick_face([small, big]) is big
    assert pick_face(None) is None and pick_face([]) is None
