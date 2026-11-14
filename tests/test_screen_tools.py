"""화면을 보고 조작하는 도구 (tools.py 의 look_at_screen · zoom_screen · click_screen …) — 가짜 화면으로 흐름을 확인한다.

지켜야 하는 것: AI 가 본 이미지의 좌표가 실제 화면의 같은 자리로 바뀐다 (모델 등급 · 모니터 위치 · 확대와 상관없이),
화면을 보지 않고는 좌표로 누를 수 없다, 좌표로 눌러도 위험한 버튼은 승인을 받는다, 누른 뒤 화면이 바뀌었는지 알려 준다.
"""
import base64
import io
import types

import pytest
from PIL import Image

from jarvis import tools, vision
from jarvis.config import DEFAULTS
from jarvis.tools import Hooks, PCTools, ToolError


REAL_SETTLE = vision.settle


class Cfg(dict):
    def __getitem__(self, k):
        return self.get(k, DEFAULTS.get(k))


class Clock:
    def __init__(self):
        self.t = 0.0

    def sleep(self, s):
        self.t += s

    def now(self):
        return self.t


class Rig:
    """가짜 화면 한 벌: 모니터 · 활성 창 · 캡처 · 클릭 기록."""

    def __init__(self, monkeypatch, monitor=(0, 0, 1920, 1080), window=None, **cfg):
        self.monitor, self.window = monitor, window
        self.grabs: list = []           # 캡처한 영역들
        self.clicks: list = []          # (x, y, double, right)
        self.asked: list = []           # 승인 카드 제목 · 내용
        self.approve = True
        self.element = ("", "")         # 누르려는 자리에 있는 요소 (이름, 종류)
        self.shade = 30                 # 화면 밝기 — 바꾸면 '화면이 바뀐' 것이 된다
        self.on_click = lambda: None
        self.keys: list = []

        me = PCTools.__new__(PCTools)
        me.cfg = Cfg(cfg)
        me.focus = types.SimpleNamespace(last_external=77, last_title="테스트 창", restore=lambda: None)
        me.hooks = Hooks(confirm=lambda t, d: self.events.append("ask") or self.asked.append((t, d)) or self.approve,
                         schedule_timer=lambda s, l: None, hud_hwnd=lambda: [1, 2])
        me.screen = types.SimpleNamespace(items=[], hwnd=77, title="테스트 창")
        me._view = None
        me.vision_model = ""
        me._grab_raw = self._grab
        me._active_hwnd = lambda: 77    # 가짜 창 번호 (Windows 에서는 진짜 IsWindow 가 0 을 돌려준다)
        self.me = me

        monkeypatch.setattr(tools.winutil, "monitor_rect", lambda hwnd=0: self.monitor)
        monkeypatch.setattr(tools.winutil, "window_rect", lambda hwnd: self.window)
        monkeypatch.setattr(tools.winutil, "set_capture_excluded", lambda h, on: None)
        monkeypatch.setattr(tools.winutil, "window_title", lambda hwnd: "테스트 창")
        self.hud = None                 # 작은 HUD 창(번호 1)이 덮고 있는 화면 영역 (왼, 위, 오, 아래)
        self.events: list = []          # HUD 숨김/보임 · 클릭 · 승인 카드가 일어난 순서
        monkeypatch.setattr(tools.winutil, "blocks_clicks", lambda h, x, y: bool(
            h == 1 and self.hud and self.hud[0] <= x < self.hud[2] and self.hud[1] <= y < self.hud[3]))
        monkeypatch.setattr(tools.winutil, "show_window", lambda h, show: self.events.append("show" if show else "hide"))
        monkeypatch.setattr(tools.uia, "scroll", lambda hwnd, direction, amount, at=None: self.events.append(("scroll", at) if at else "scroll"))
        monkeypatch.setattr(tools.uia, "move_to", lambda x, y: self.events.append(("move", x, y)))
        monkeypatch.setattr(tools.uia, "drag", lambda x1, y1, x2, y2: self.events.append(("drag", x1, y1, x2, y2)) or self.on_click())
        monkeypatch.setattr(tools.winutil, "press_combo", lambda keys: self.keys.append(keys))
        monkeypatch.setattr(tools.winutil, "get_clipboard_text", lambda: "예전 클립보드")
        monkeypatch.setattr(tools.winutil, "set_clipboard_text", lambda t: self.keys.append(("clip", t)))
        monkeypatch.setattr(tools.uia, "element_at", lambda x, y: self.element)
        monkeypatch.setattr(tools.uia, "click_at", self._click)
        monkeypatch.setattr(tools.time, "sleep", lambda s: None)
        real = REAL_SETTLE

        def fast_settle(grab, before, **kw):       # 실제로 기다리지 않고 가짜 시계로
            c = Clock()
            return real(grab, before, sleep=c.sleep, clock=c.now, **kw)

        monkeypatch.setattr(tools.vision, "settle", fast_settle)

    def _grab(self, bbox=None):
        bbox = bbox or self.monitor
        self.grabs.append(bbox)
        return Image.new("RGB", (bbox[2] - bbox[0], bbox[3] - bbox[1]), (self.shade,) * 3)

    def _click(self, x, y, double=False, right=False, hwnd=0):
        self.events.append("click")
        self.clicks.append((x, y, double, right))
        self.on_click()

    @staticmethod
    def image(blocks) -> Image.Image:
        assert blocks[0]["type"] == "image" and blocks[0]["source"]["media_type"] == "image/jpeg"
        return Image.open(io.BytesIO(base64.b64decode(blocks[0]["source"]["data"])))


@pytest.fixture
def rig(monkeypatch):
    return Rig(monkeypatch)


# ---------------------------------------------------------------- 보기
def test_look_sends_a_size_the_model_will_not_shrink_and_remembers_the_mapping(rig):
    blocks = rig.me.t_look_at_screen()
    assert rig.image(blocks).size == (1456, 819)                 # 모델을 모를 때는 표준 등급 크기
    assert "1456x819" in blocks[1]["text"] and "테스트 창" in blocks[1]["text"]
    assert rig.grabs == [(0, 0, 1920, 1080)]
    assert rig.me._view.to_screen(728, 409.5) == (960, 540)


def test_newer_models_get_the_full_1080p_screen(rig):
    rig.me.set_vision_model("claude-opus-5-5")
    assert rig.image(rig.me.t_look_at_screen()).size == (1920, 1080)
    assert rig.me._view.to_screen(1000, 500) == (1000, 500)      # 줄이지 않았으니 좌표가 그대로
    rig.me.set_vision_model("claude-haiku-4-5-20251001")
    assert rig.image(rig.me.t_look_at_screen()).size == (1456, 819)


def test_screen_detail_setting_can_only_make_the_capture_smaller(monkeypatch):
    low = Rig(monkeypatch, screen_detail="standard")
    low.me.set_vision_model("claude-opus-5-5")
    assert low.image(low.me.t_look_at_screen()).size == (1456, 819)
    # 모델이 받을 수 있는 크기보다 크게 보내는 설정은 없다 — 그렇게 보내면 서버가 다시 줄여 좌표가 어긋난다
    odd = Rig(monkeypatch, screen_detail="high")
    odd.me.set_vision_model("claude-haiku-4-5")
    assert odd.image(odd.me.t_look_at_screen()).size == (1456, 819)


def test_look_captures_the_monitor_where_the_user_is_working(monkeypatch):
    rig = Rig(monkeypatch, monitor=(1920, 0, 4480, 1440))        # 오른쪽 2560×1440 모니터에 활성 창이 있다
    img = rig.image(rig.me.t_look_at_screen())
    assert rig.grabs == [(1920, 0, 4480, 1440)]
    assert img.size == (1456, 819)
    rig.me.t_click_screen(728, 409)
    assert rig.clicks[0][:2] == (3200, 719)                      # 그 모니터의 한가운데


def test_look_at_window_captures_only_the_visible_part_of_the_window(monkeypatch):
    rig = Rig(monkeypatch, window=(-8, 100, 1000, 900))          # 왼쪽으로 조금 삐져나간 창
    img = rig.image(rig.me.t_look_at_screen(target="window"))
    assert rig.grabs == [(0, 100, 1000, 900)] and img.size == (1000, 800)
    assert "활성 창 캡처" in rig.me.t_look_at_screen(target="window")[1]["text"]
    assert rig.me._view.kind == "window" and rig.me._view.to_screen(10, 10) == (10, 110)
    rig.window = None                                            # 최소화됐거나 알 수 없는 창 → 화면 전체
    rig.me.t_look_at_screen(target="window")
    assert rig.grabs[-1] == (0, 0, 1920, 1080) and rig.me._view.kind == "screen"


def test_marks_draw_numbered_boxes_tied_to_click_ui_numbers(rig):
    plain = rig.image(rig.me.t_look_at_screen())
    items = [types.SimpleNamespace(n=1, rect=(100, 100, 400, 160), line=lambda: "[1] 버튼 '확인'"),
             types.SimpleNamespace(n=2, rect=(5000, 100, 5100, 160), line=lambda: "[2] 버튼 '숨은 버튼'")]
    rig.me.screen.items = items
    rig.me.screen.read = lambda hwnd: "목록"
    blocks = rig.me.t_look_at_screen(marks=True)
    assert rig.image(blocks).tobytes() != plain.tobytes()        # 상자가 그려졌다
    text = blocks[1]["text"]
    assert "[1] 버튼 '확인'" in text and "숨은 버튼" not in text and "표시하지 않은 요소 1개" in text and "click_ui" in text


def test_marks_fall_back_to_a_plain_screenshot_when_elements_cannot_be_read(rig):
    def boom(hwnd):
        raise OSError("접근성 정보를 읽을 수 없음")

    rig.me.screen.read = boom
    blocks = rig.me.t_look_at_screen(marks=True)
    assert rig.image(blocks).size == (1456, 819) and "요소 번호를 표시하지 못했습니다" in blocks[1]["text"]


# ---------------------------------------------------------------- 좌표로 누르기
def test_click_needs_a_screenshot_first_and_coordinates_inside_it(rig):
    with pytest.raises(ToolError, match="먼저 look_at_screen"):
        rig.me.t_click_screen(100, 100)
    rig.me.t_look_at_screen()
    with pytest.raises(ToolError, match="밖입니다"):
        rig.me.t_click_screen(1700, 400)                         # 실제 화면 좌표를 그대로 준 경우 (이미지는 1456 까지)
    assert rig.clicks == []


def test_click_reports_whether_the_screen_changed(rig):
    rig.me.t_look_at_screen()
    out = rig.me.t_click_screen(100, 100)
    assert rig.clicks == [(132, 132, False, False)]
    assert "변화 없음" in out                                    # 눌렀는데 그대로 → 빗나갔을 수 있다고 알려 준다
    rig.on_click = lambda: setattr(rig, "shade", 200)
    out = rig.me.t_click_screen(200, 300, double=True)
    # 화면이 바뀌었으면 바뀐 화면을 결과에 같이 돌려준다 → AI 가 다시 보러 오는 왕복이 줄어든다
    assert rig.clicks[-1] == (264, 396, True, False)
    assert rig.image(out).size == (1456, 819) and rig.image(out).getpixel((10, 10))[0] > 150
    assert "크게 바뀜" in out[1]["text"] and "누른 뒤의 화면" in out[1]["text"]


def test_follow_up_can_be_turned_off_and_keeps_the_window_scope(monkeypatch):
    rig = Rig(monkeypatch, screen_follow=False)
    rig.me.t_look_at_screen()
    rig.on_click = lambda: setattr(rig, "shade", 200)
    assert isinstance(rig.me.t_click_screen(100, 100), str)
    rig = Rig(monkeypatch, window=(100, 100, 1100, 900))
    rig.me.t_look_at_screen(target="window")
    rig.on_click = lambda: setattr(rig, "shade", 200)
    out = rig.me.t_click_screen(50, 50)
    assert rig.clicks[-1][:2] == (150, 150) and rig.image(out).size == (1000, 800)      # 창만 보고 있었으면 창만 다시 보여 준다
    assert rig.me._view.kind == "window" and rig.me._view.to_screen(0, 0) == (100, 100)


def test_click_ui_lists_the_new_screen_when_it_changed(rig):
    items = [types.SimpleNamespace(n=1, name="다음", kind="버튼", rect=(100, 100, 200, 140))]
    rig.me.screen.find = lambda number, name: items[0]
    rig.me.screen.click = lambda it, double=False: rig.events.append("click") or "'다음' 버튼 누름"
    reads = []
    rig.me.screen.read = lambda hwnd, query="": reads.append(hwnd) or "창: 둘째 화면\n누를 수 있는 요소:\n[1] 버튼 '완료'"
    out = rig.me.t_click_ui(number=1)
    assert "변화 없음" in out and reads == [] and "누른 뒤의 화면" not in out             # 안 바뀌었으면 붙이지 않는다
    rig.me.screen.click = lambda it, double=False: setattr(rig, "shade", 220) or "'다음' 버튼 누름"
    out = rig.me.t_click_ui(number=1)
    assert reads == [77] and "누른 뒤의 화면" in out and "[1] 버튼 '완료'" in out


def test_click_names_the_element_and_asks_before_risky_buttons(rig):
    rig.me.t_look_at_screen()
    rig.element = ("다음", "버튼")
    assert rig.me.t_click_screen(10, 10).startswith("'다음' 버튼 클릭함")
    assert rig.asked == []
    rig.element = ("결제하기", "버튼")
    rig.approve = False
    with pytest.raises(ToolError, match="거부"):
        rig.me.t_click_screen(10, 10)
    assert len(rig.clicks) == 1 and rig.asked[0][0] == "화면 클릭" and "결제하기" in rig.asked[0][1]
    rig.approve = True
    rig.me.t_click_screen(10, 10)
    assert len(rig.clicks) == 2


def test_hud_steps_aside_only_while_clicking_under_it(rig):
    rig.hud = (1500, 316, 1920, 1040)                            # 오른쪽 아래의 비전 HUD — 캡처에는 안 보이지만 클릭은 막는다
    rig.me.t_look_at_screen()
    rig.me.t_click_screen(300, 300)                              # HUD 밖 → 그대로 누른다
    assert rig.events == ["click"]
    rig.events.clear()
    rig.element = ("보내기", "버튼")
    rig.me.t_click_screen(1300, 600)                             # 화면의 (1714, 791) = HUD 밑
    # 밑에 뭐가 있는지 볼 때와 누를 때만 숨기고, 승인 카드는 HUD 가 보이는 동안 띄운다
    assert rig.events == ["hide", "show", "ask", "hide", "click", "show"]


def test_hud_steps_aside_for_element_clicks_and_scrolling_too(monkeypatch):
    rig = Rig(monkeypatch, window=(960, 0, 1920, 1080))
    rig.hud = (1500, 316, 1920, 1040)
    item = types.SimpleNamespace(n=3, name="다음", kind="버튼", rect=(1600, 500, 1700, 540))
    rig.me.screen.find = lambda number, name: item
    rig.me.screen.click = lambda it, double=False: rig.events.append("click") or "'다음' 버튼 누름"
    assert rig.me.t_click_ui(number=3).startswith("'다음' 버튼 누름")
    assert rig.events == ["hide", "click", "show"]
    rig.events.clear()
    rig.me._target_window = lambda app: 77
    rig.window = (960, 0, 1920, 1080)                            # 창 한가운데 (1440, 540) 는 HUD 밖
    rig.me.t_scroll("down")
    assert rig.events == ["scroll"]
    rig.events.clear()
    rig.window = (1200, 200, 1920, 1080)                         # 창 한가운데 (1560, 640) 가 HUD 밑
    rig.me.t_scroll("down")
    assert rig.events == ["hide", "scroll", "show"]


# ---------------------------------------------------------------- 확대
def test_zoom_enlarges_a_region_and_later_coordinates_refer_to_the_zoomed_image(rig):
    rig.me.t_look_at_screen()                                    # 1920×1080 → 1456×819
    blocks = rig.me.t_zoom_screen(728, 409, 364, 205)            # 화면의 (960,539)~(1440,810)
    left, top, right, bottom = rig.grabs[-1]
    assert (left, top) == (960, 539) and abs(right - 1440) <= 1 and abs(bottom - 810) <= 1
    img = rig.image(blocks)
    assert img.width == 1280 and "확대한 영역" in blocks[1]["text"]      # 480픽셀 영역을 1280 으로 키워 보여 준다
    rig.me.t_click_screen(img.width // 2, img.height // 2)       # 확대 이미지의 한가운데 = 그 영역의 한가운데
    x, y = rig.clicks[-1][:2]
    assert abs(x - 1200) <= 2 and abs(y - 675) <= 2
    rig.me.t_zoom_screen(0, 0, 640, 360)                         # 확대한 것을 한 번 더 확대
    assert rig.grabs[-1][:2] == (960, 539) and rig.grabs[-1][2] - rig.grabs[-1][0] in (239, 240, 241)


def test_zoom_needs_a_screenshot_and_a_reasonable_region(rig):
    with pytest.raises(ToolError, match="먼저 look_at_screen"):
        rig.me.t_zoom_screen(0, 0, 100, 100)
    rig.me.t_look_at_screen()
    with pytest.raises(ToolError, match="너무 작습니다"):
        rig.me.t_zoom_screen(10, 10, 2, 2)


def test_point_at_uses_the_same_mapping(rig):
    seen = []
    rig.me.hooks.point_at = lambda x, y, w, h, label: seen.append((x, y, w, h, label)) or True
    with pytest.raises(ToolError):
        rig.me.t_point_at(10, 10)
    rig.me.t_look_at_screen()
    rig.me.t_point_at(728, 409, 0, 0, "여기")
    rig.me.t_point_at(100, 100, 200, 100, "상자")
    assert seen[0] == (960, 539, 0, 0, "여기")
    assert seen[1] == (132, 132, 264, 132, "상자")


# ---------------------------------------------------------------- 기다리기 · 입력
def test_wait_screen_returns_when_the_screen_is_still(rig):
    assert "화면이 멈췄습니다" in rig.me.t_wait_screen()
    n = [0]

    def moving(bbox=None):
        n[0] += 1
        rig.shade = 40 + (n[0] * 37) % 200
        return Rig._grab(rig, bbox)

    rig.me._grab_raw = moving
    assert "계속 바뀌고 있습니다" in rig.me.t_wait_screen(max_seconds=2)


def test_type_text_can_replace_the_field_and_reports_the_change_after_enter(rig):
    rig.me.t_type_text("안녕")
    assert rig.keys == [("clip", "안녕"), "ctrl+v", ("clip", "예전 클립보드")]
    rig.keys.clear()
    out = rig.me.t_type_text("고양이", press_enter=True, replace=True)
    assert rig.keys == [("clip", "고양이"), "ctrl+a", "ctrl+v", "enter", ("clip", "예전 클립보드")]
    assert out.startswith("3자 입력함") and "변화 없음" in out


def test_read_screen_text_passes_the_scope_through(rig):
    calls = []
    rig.me.screen.read_text = lambda hwnd, include_offscreen=False: calls.append((hwnd, include_offscreen)) or "본문"
    rig.me._target_window = lambda app: 77
    assert rig.me.t_read_screen_text() == "본문" and rig.me.t_read_screen_text(all=True) == "본문"
    assert calls == [(77, False), (77, True)]


def test_layout_text_orders_pieces_like_a_reader():
    from jarvis.uia import layout_text
    pieces = [
        ((400, 100, 500, 120), "오른쪽"), ((100, 102, 200, 122), "왼쪽"),       # 같은 줄 → 왼쪽부터
        ((100, 300, 300, 320), "셋째 줄"), ((100, 200, 300, 220), "둘째 줄"),
        ((100, 200, 300, 220), "둘째 줄"),                                      # 같은 글이 두 번 (겹친 요소) → 한 번만
        ((100, 400, 300, 500), "문단 첫 줄\n문단 둘째 줄"), ((100, 600, 200, 620), "   "),
    ]
    assert layout_text(pieces) == "왼쪽 오른쪽\n둘째 줄\n셋째 줄\n문단 첫 줄\n문단 둘째 줄"
    long = layout_text([((0, i * 30, 100, i * 30 + 20), f"줄 {i} " + "가" * 50) for i in range(200)], limit=500)
    assert len(long) < 600 and "이하 생략" in long


# ---------------------------------------------------------------- 끌기 · 올려놓기 · 영역 스크롤 · 화면 밖 요소
def test_drag_hover_and_area_scroll_use_image_coordinates(rig):
    with pytest.raises(ToolError, match="먼저 look_at_screen"):
        rig.me.t_drag_screen(10, 10, 20, 20)
    rig.me.t_look_at_screen()                                    # 1920×1080 → 1456×819
    rig.me._target_window = lambda app: 77
    out = rig.me.t_drag_screen(100, 100, 400, 100)
    assert rig.events[-1] == ("drag", 132, 132, 527, 132) and "끌어다 놓음" in out and "변화 없음" in out
    rig.on_click = lambda: setattr(rig, "shade", 210)
    out = rig.me.t_drag_screen(100, 100, 400, 100)
    assert "바뀐 화면" in out[1]["text"] and rig.image(out).size == (1456, 819)   # 바뀌었으면 바뀐 화면을 같이 돌려준다
    rig.me.t_hover_screen(728, 409)
    assert rig.events[-1] == ("move", 960, 539)
    rig.me.t_scroll("down", x=1000, y=400)
    assert rig.events[-1] == ("scroll", (1319, 527))             # 그 자리에서 휠을 굴린다
    with pytest.raises(ToolError, match="밖입니다"):
        rig.me.t_scroll("down", x=5000, y=10)


def test_click_by_name_scrolls_to_an_element_that_is_out_of_view(rig):
    hidden = types.SimpleNamespace(n=0, name="문의하기", kind="링크", rect=(100, 3000, 200, 3020))
    shown = types.SimpleNamespace(n=4, name="문의하기", kind="링크", rect=(100, 500, 200, 520))
    state = {"revealed": False}
    rig.me.screen.find = lambda number, name: shown if state["revealed"] and name == "문의하기" else None
    rig.me.screen.read = lambda hwnd, query="": "목록"
    rig.me.screen.find_hidden = lambda hwnd, name: [hidden] if name == "문의하기" else []
    rig.me.screen.reveal = lambda it: state.__setitem__("revealed", True) or True
    rig.me.screen.click = lambda it, double=False: rig.events.append(("click", it.rect)) or "'문의하기' 링크 누름"
    assert rig.me.t_click_ui(name="문의하기").startswith("'문의하기' 링크 누름")
    assert rig.events[-1] == ("click", (100, 500, 200, 520))     # 스크롤한 뒤의 자리를 누른다
    with pytest.raises(ToolError, match="찾지 못했습니다"):
        rig.me.t_click_ui(name="없는 것")


def test_read_ui_mentions_matches_that_are_scrolled_out_of_view(rig):
    rig.me._target_window = lambda app: 77
    rig.me.screen.read = lambda hwnd, query="": "창: 시험\n누를 수 있는 요소:\n[1] 버튼 '홈'"
    rig.me.screen.find_hidden = lambda hwnd, name: [types.SimpleNamespace(name="문의하기")]
    out = rig.me.t_read_ui(query="문의")
    assert "화면 밖" in out and "'문의하기'" in out and "click_ui" in out
    rig.me.screen.find_hidden = lambda hwnd, name: []
    assert "화면 밖" not in rig.me.t_read_ui(query="문의") and "화면 밖" not in rig.me.t_read_ui()
