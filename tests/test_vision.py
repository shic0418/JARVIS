"""화면을 AI 에게 보여 줄 때의 계산 (vision.py) — 보낼 크기 · 좌표 대응 · 번호 상자 · 화면 변화 감지."""
import base64
import io

import numpy as np
import pytest
from PIL import Image

from jarvis import vision
from jarvis.vision import View


# ---------------------------------------------------------------- 보낼 크기
def test_resized_size_matches_the_documented_examples():
    assert vision.count_image_tokens(1568, 1568) == 3136
    assert vision.resized_size(1000, 1000) == (1000, 1000)                 # 한도 안이면 그대로
    assert vision.resized_size(1075, 1520) == (924, 1307)                  # 세로로 긴 이미지 (표준 등급)
    # 1920×1080 화면: 표준 등급에서는 조각 수 한도 때문에 1568 이 아니라 1456 까지 줄어든다 — 예전 코드가 놓친 부분
    assert vision.resized_size(1920, 1080) == (1456, 819)
    assert vision.resized_size(1920, 1080, *vision.HIGH) == (1920, 1080)   # 고해상도 등급은 그대로 본다


@pytest.mark.parametrize("w, h", [(1920, 1080), (2560, 1440), (3840, 2160), (1366, 768), (1280, 1024), (3440, 1440),
                                  (1080, 1920), (800, 600), (5120, 1440), (300, 4000), (1568, 1568), (1569, 28)])
@pytest.mark.parametrize("tier", ["standard", "high"])
def test_send_size_is_the_largest_size_the_server_will_not_shrink_again(w, h, tier):
    edge, tokens = vision.limits(tier)
    sw, sh = vision.send_size(w, h, tier)
    assert sw <= w and sh <= h                                             # 키우지 않는다
    assert vision.resized_size(sw, sh, edge, tokens) == (sw, sh)           # 서버가 다시 줄이지 않는다 → 좌표가 어긋나지 않는다
    assert abs(sw / sh - w / h) < 0.02 * (w / h) + 0.02                    # 비율 유지
    if (sw, sh) != (w, h):                                                 # 줄였다면 한 픽셀만 더 커도 한도를 넘는다
        long_edge = max(sw, sh) + 1
        other = max(round(long_edge * min(w, h) / max(w, h)), 1)
        bigger = (long_edge, other) if w >= h else (other, long_edge)
        assert vision.resized_size(*bigger, edge, tokens) != bigger


def test_high_tier_keeps_a_1080p_screen_and_caps_larger_ones_near_1920():
    assert vision.send_size(1920, 1080, "high") == (1920, 1080)
    w, h = vision.send_size(2560, 1440, "high")
    assert 1900 <= w <= vision.SCREEN_EDGE_CAP and abs(w / h - 16 / 9) < 0.01
    assert vision.send_size(1920, 1080, "standard") == (1456, 819)


@pytest.mark.parametrize("model, tier", [
    ("claude-haiku-4-5", "standard"), ("claude-haiku-4-5-20251001", "standard"), ("claude-sonnet-4-6", "standard"),
    ("claude-opus-4-20250514", "standard"), ("claude-sonnet-4-5-20250929", "standard"),
    ("claude-opus-4-7", "high"), ("claude-opus-4-8", "high"), ("claude-sonnet-5", "high"), ("claude-opus-5-5", "high"),
    ("claude-haiku-5-5", "high"), ("claude-fable-5-2", "high"), ("claude-opus-5-5[1m]", "high"), ("CLAUDE-OPUS-5-5", "high"),
    # 버전을 알 수 없으면 안전한 쪽(표준) — 표준 크기 이미지는 어느 모델에서도 다시 줄어들지 않는다
    ("haiku", "standard"), ("sonnet", "standard"), ("opus", "standard"), ("", "standard"), (None, "standard"),
    ("claude-3-5-sonnet-20241022", "standard"), ("gpt-4o", "standard"),
])
def test_tier_for_model(model, tier):
    assert vision.tier_for_model(model) == tier


def test_zoom_size_enlarges_small_regions_and_fits_large_ones():
    assert vision.zoom_size(400, 200, "standard") == (1200, 600)           # 최대 3배
    w, h = vision.zoom_size(800, 450, "standard")
    assert (w, h) == (1280, 720)                                           # 긴 변을 1280 까지
    w, h = vision.zoom_size(1900, 1000, "standard")                        # 큰 영역은 한도에 맞춰 줄인다
    assert vision.resized_size(w, h) == (w, h) and w < 1900
    assert vision.zoom_size(0, 0, "high") == (3, 3)                        # 0 이 들어와도 죽지 않는다


# ---------------------------------------------------------------- 좌표
def test_view_maps_image_pixels_to_screen_pixels():
    # 1920×1080 화면을 1456×819 로 보낸 경우 — Claude 가 이미지 한가운데를 짚으면 화면 한가운데를 눌러야 한다
    v = vision.make_view((0, 0, 1920, 1080), (1456, 819))
    assert v.to_screen(728, 409.5) == (960, 540)
    assert v.to_screen(0, 0) == (0, 0)
    x, y = v.to_screen(1455, 818)
    assert 1917 <= x <= 1919 and 1077 <= y <= 1079
    # 예전 방식(1568×882 로 보냈다고 믿고 변환)이었다면 같은 점이 화면에서 100픽셀 넘게 빗나간다
    old_x = round(1000 * 1920 / 1568)
    assert abs(v.to_screen(1000, 400)[0] - old_x) > 90


def test_view_on_second_monitor_and_round_trip():
    v = vision.make_view((1920, -200, 4480, 1240), (1456, 819), "screen")   # 오른쪽 위에 붙은 2560×1440 모니터
    assert v.to_screen(0, 0) == (1920, -200)
    assert v.to_screen(728, 409.5) == (3200, 520)
    ix, iy = v.from_screen(*v.to_screen(300, 500))
    assert abs(ix - 300) < 1 and abs(iy - 500) < 1


def test_view_bounds_and_region():
    v = View(100.0, 50.0, 2.0, 2.0, 500, 300)
    assert v.contains(0, 0) and v.contains(499, 299) and not v.contains(500, 10) and not v.contains(10, -1)
    assert v.to_screen(9999, -5) == (100 + 499 * 2, 50)                    # 조금 벗어난 값은 가장자리로
    assert v.rect_to_screen(10, 20, 100, 50) == (120, 90, 320, 190)
    assert v.rect_to_screen(450, 280, 500, 500) == (1000, 610, 1100, 650)  # 이미지 밖으로 나간 영역은 잘라 낸다


# ---------------------------------------------------------------- 인코딩
def test_encode_returns_a_jpeg_of_the_same_size_and_shrinks_heavy_images():
    img = Image.new("RGB", (640, 360), (20, 30, 40))
    data, media = vision.encode(img)
    assert media == "image/jpeg"
    back = Image.open(io.BytesIO(base64.b64decode(data)))
    assert back.size == (640, 360) and back.format == "JPEG"
    noisy = Image.fromarray(np.random.default_rng(1).integers(0, 255, (1080, 1920, 3), dtype=np.uint8), "RGB")
    heavy = base64.b64decode(vision.encode(noisy)[0])
    best = io.BytesIO()
    noisy.save(best, "JPEG", quality=vision.JPEG_QUALITY)
    assert len(heavy) < best.tell()                                        # 너무 큰 이미지는 화질을 낮춰 보낸다


# ---------------------------------------------------------------- 번호 상자
def test_pick_marks_keeps_visible_distinct_boxes_in_image_coordinates():
    v = vision.make_view((0, 0, 1920, 1080), (960, 540))                   # 화면 2픽셀 = 이미지 1픽셀
    items = [
        (1, (100, 100, 300, 160)),          # 보임
        (2, (102, 101, 301, 161)),          # 1번과 거의 같은 자리 → 하나만
        (3, (2000, 100, 2100, 160)),        # 화면 밖
        (4, (500, 500, 506, 504)),          # 너무 작음
        (5, (1800, 1000, 2000, 1200)),      # 일부만 보임 → 이미지 안으로 잘라서
        (6, (-50, -50, 0, 0)),              # 화면 밖 (왼쪽 위)
    ]
    assert vision.pick_marks(items, v) == [(1, (50, 50, 150, 80)), (5, (900, 500, 959, 539))]
    many = [(n, (n * 20, 10, n * 20 + 16, 40)) for n in range(1, 60)]
    assert [n for n, _ in vision.pick_marks(many, v, max_marks=10)] == list(range(1, 11))


def test_annotate_draws_boxes_and_labels_without_touching_the_original():
    img = Image.new("RGB", (400, 300), (0, 0, 0))
    out = vision.annotate(img, [(7, (50, 80, 200, 140)), (12, (0, 0, 60, 30))])
    assert out.size == img.size and img.getpixel((50, 80)) == (0, 0, 0)
    assert out.getpixel((50, 100)) != (0, 0, 0)                            # 왼쪽 테두리
    assert out.getpixel((125, 140)) != (0, 0, 0)                           # 아래 테두리
    assert out.getpixel((125, 110)) == (0, 0, 0)                           # 상자 안은 가리지 않는다
    label = np.asarray(out.crop((50, 60, 80, 80)))                         # 번호표는 상자 바로 위
    assert (label.sum(axis=2) > 0).mean() > 0.3


# ---------------------------------------------------------------- 화면 변화
def frame(value: int = 0, box: tuple[int, int, int, int] | None = None) -> np.ndarray:
    a = np.full((54, 96), value, dtype=np.int16)
    if box:
        a[box[1]:box[3], box[0]:box[2]] = 200
    return a


class Clock:
    def __init__(self):
        self.t = 0.0

    def sleep(self, s: float) -> None:
        self.t += s

    def now(self) -> float:
        return self.t


def run_settle(frames, **kw):
    """frames: 차례로 돌려줄 화면들 (다 쓰면 마지막 것을 계속 돌려준다)."""
    it = iter(frames)
    last = [frames[-1]]

    def grab():
        try:
            last[0] = next(it)
        except StopIteration:
            pass
        return last[0]

    c = Clock()
    return vision.settle(grab, frames[0] if kw.pop("same_before", True) else frame(), sleep=c.sleep, clock=c.now, **kw)


def test_changed_fraction_and_small_gray():
    assert vision.changed_fraction(frame(), frame()) == 0.0
    assert vision.changed_fraction(frame(), frame(5)) == 0.0               # 미세한 밝기 차이는 무시
    assert abs(vision.changed_fraction(frame(), frame(box=(0, 0, 48, 54))) - 0.5) < 0.01
    assert vision.changed_fraction(None, frame()) == 1.0
    g = vision.small_gray(Image.new("RGB", (1920, 1080), (255, 255, 255)))
    assert g.shape == (270, 480) and int(g.max()) == 255


def screen(*boxes):
    """1920×1080 흰 화면에 검은 상자들을 그린 것 (실제 화면 픽셀 기준)."""
    img = Image.new("RGB", (1920, 1080), (255, 255, 255))
    for box in boxes:
        img.paste((0, 0, 0), box)
    return vision.small_gray(img)


def change_text(before, after):
    return run_settle([before, after, after, after, after]).text()


def test_small_changes_are_noticed_and_located():
    # 실제 Claude 로 돌려 본 시험에서: 탭을 눌러 제목 글자만 바뀌었는데 '변화 없음'으로 알려 줘서 같은 탭을 세 번 눌렀다
    assert change_text(screen(), screen((60, 150, 120, 174))) == "화면의 작은 부분이 바뀜 — 왼쪽 위"      # 제목 한 낱말
    assert change_text(screen(), screen((1700, 950, 1716, 966))).startswith("화면의 작은 부분이 바뀜 — 오른쪽 아래")   # 체크 상자
    assert "아주 조금만" in change_text(screen(), screen((900, 500, 902, 518)))                       # 글자 커서 하나
    assert "변화 없음" in change_text(screen(), screen((900, 500, 901, 502)))                         # 잡티
    assert change_text(screen(), screen((760, 390, 1160, 690))) == "화면 일부가 바뀜 (약 6% — 가운데)"
    assert change_text(screen(), screen((0, 0, 1920, 600))) == "화면이 크게 바뀜 (약 56%)"
    assert vision.changed_where(screen(), screen((10, 10, 60, 40), (1800, 1000, 1900, 1060))) == ""   # 여러 곳에 흩어진 변화


def test_settle_returns_as_soon_as_a_changed_screen_stops_moving():
    before = frame()
    loading, done = frame(box=(0, 0, 30, 30)), frame(box=(0, 0, 60, 54))
    ch = run_settle([before, loading, done, done, done, done], same_before=True)
    assert ch.settled and ch.fraction > 0.5 and ch.seconds < 1.0
    assert "크게 바뀜" in ch.text()


def test_settle_waits_a_little_before_declaring_nothing_happened():
    ch = run_settle([frame()] * 3, nochange_wait=1.0)
    assert ch.settled and ch.fraction == 0.0 and 1.0 <= ch.seconds < 1.4   # 늦게 반응하는 화면을 위해 1초는 지켜본다
    assert "변화 없음" in ch.text()
    late = run_settle([frame()] * 5 + [frame(box=(0, 0, 20, 20))] * 5, nochange_wait=1.0)
    assert late.settled and late.fraction > 0 and "일부가 바뀜" in late.text()


def test_settle_gives_up_on_a_screen_that_never_stops():
    frames = [frame(box=(i % 60, 0, i % 60 + 30, 54)) for i in range(0, 600, 7)]
    ch = run_settle(frames, timeout=2.0)
    assert not ch.settled and 2.0 <= ch.seconds < 2.4
    assert "계속 바뀌는 중" in ch.text()
