"""컴퓨터 조작 도구 (control.py + tools.py 의 조작 도구) — 가짜 창 · 가짜 키보드로 '무엇을 어떤 순서로 하는지'를 본다.

지켜야 하는 것: 브라우저 명령은 브라우저 창에 간다, 탭은 이름으로 찾는다, 입력칸은 한 번에 채우되 비밀번호 칸은 거절한다,
파일은 승인 없이 지우거나 뭉텅이로 옮기지 않는다, 방금 켠 앱은 창이 뜬 뒤에 만진다.
"""
import sys
import types

import pytest

from jarvis import tools
from jarvis.config import DEFAULTS
from jarvis.tools import Hooks, PCTools, ToolError
from jarvis.uia import Item


class Cfg(dict):
    def __getitem__(self, k):
        return self.get(k, DEFAULTS.get(k))


class FakeScreen:
    """uia.Screen 흉내: 미리 넣어 둔 요소 목록에서 찾고, 누른 것을 기록한다."""

    def __init__(self):
        self.items, self.hwnd, self.title = [], 10, "가짜 창"
        self.clicked, self.reads, self.text = [], 0, ""
        self.later = None               # read 를 이만큼 부른 뒤에 나타날 요소들 (횟수, 요소들)

    def read(self, hwnd, query=""):
        self.reads += 1
        self.hwnd = hwnd
        if self.later and self.reads >= self.later[0]:
            self.items = self.later[1]
        return "\n".join(it.line() for it in self.items)

    def read_text(self, hwnd, include_offscreen=False):
        return self.text

    def find(self, n=None, name=""):
        if n:
            return next((it for it in self.items if it.n == n), None)
        return next((it for it in self.items if name and name in it.name), None)

    def find_hidden(self, hwnd, name):
        return []

    def click(self, it, double=False, **how):
        self.clicked.append((it.name, double, how))
        return f"'{it.name}' {it.kind} " + ("클릭" if how or double else "누름")


@pytest.fixture(autouse=True)
def fake_home(tmp_path_factory, monkeypatch):
    """임시 폴더가 사용자 AppData 아래에 있어도 '시스템 폴더' 로 막히지 않게, 사용자 폴더를 다른 곳으로 돌려 둔다."""
    home = tmp_path_factory.mktemp("home")
    for var in ("USERPROFILE", "HOME"):
        monkeypatch.setenv(var, str(home))
    return home


def item(n, kind, name, rect):
    return Item(n, kind, name, rect, None)


@pytest.fixture
def pc(monkeypatch, tmp_path):
    me = PCTools.__new__(PCTools)
    me.cfg = Cfg()
    me.focus = types.SimpleNamespace(last_external=10, last_title="메모장", restore=lambda: None)
    me.asked, me.approve = [], True
    me.hooks = Hooks(confirm=lambda t, d: me.asked.append((t, d)) or me.approve, schedule_timer=lambda s, l: None,
                     hud_hwnd=lambda: [])
    me.screen = FakeScreen()
    me._view, me.vision_model = None, ""
    me._small = lambda: None                       # 화면 변화 확인은 건너뛴다 (test_screen_tools 가 따로 본다)
    me.log = []                                    # 키 · 클립보드 · 창 조작이 일어난 순서
    me.clip = "예전 클립보드"
    me.windows = [{"hwnd": 10, "title": "제목 없음 - 메모장", "exe": "Notepad.exe", "pid": 1},
                  {"hwnd": 20, "title": "YouTube - Chrome", "exe": "chrome.exe", "pid": 2},
                  {"hwnd": 30, "title": "카카오톡", "exe": "KakaoTalk.exe", "pid": 3}]
    W = tools.winutil
    monkeypatch.setattr(W, "press_combo", lambda keys: me.log.append(keys))
    monkeypatch.setattr(W, "get_clipboard_text", lambda: me.clip)
    monkeypatch.setattr(W, "set_clipboard_text", lambda t: (setattr(me, "clip", t), me.log.append(("clip", t)))[0])
    monkeypatch.setattr(W, "list_windows", lambda: list(me.windows))
    me.front = None                                # 맨 앞으로 가져온 창 (없으면 쓰던 창이 맨 앞)

    def to_front(h):
        me.log.append(("front", h))
        me.front = h
        return True
    monkeypatch.setattr(W, "force_foreground", to_front)
    monkeypatch.setattr(W, "window_rect", lambda h: (0, 0, 1600, 900))
    monkeypatch.setattr(W, "window_title", lambda h: next((w["title"] for w in me.windows if w["hwnd"] == h), ""))
    monkeypatch.setattr(W, "monitor_rect", lambda h=0: (0, 0, 1920, 1080))
    monkeypatch.setattr(W, "work_rect", lambda h=0: (0, 0, 1920, 1040))
    monkeypatch.setattr(W, "place_window", lambda h, r: me.log.append(("place", h, r)) or True)
    monkeypatch.setattr(W, "set_window_state", lambda h, s: me.log.append(("state", h, s)) or True)
    monkeypatch.setattr(W, "close_window", lambda h: me.log.append(("close", h)))
    monkeypatch.setattr(W, "blocks_clicks", lambda h, x, y: False, raising=False)
    monkeypatch.setattr(W, "type_unicode", lambda text: me.log.append(("keys", text)) or len(text), raising=False)
    monkeypatch.setattr(W, "known_folder", lambda name: {"다운로드": tmp_path / "Downloads", "문서": tmp_path / "Docs"}.get(
        name.strip().replace(" ", "")))
    monkeypatch.setattr(W, "foreground", lambda: me.front or me.focus.last_external)
    me._active_hwnd = lambda: me.focus.last_external
    monkeypatch.setattr(tools.uia, "click_at", lambda x, y, **kw: me.log.append(("click", x, y, kw)))
    monkeypatch.setattr(tools.uia, "scroll", lambda hwnd, direction, amount, at=None: me.log.append(("wheel", direction, amount)))
    monkeypatch.setattr(tools.time, "sleep", lambda s: None)
    return me


def keys(pc):
    return [e for e in pc.log if isinstance(e, str)]


# ---------------------------------------------------------------- 브라우저
def test_browser_commands_go_to_the_browser_even_when_another_window_is_active(pc):
    out = pc.t_browser("new_tab")
    assert ("front", 20) in pc.log and keys(pc) == ["ctrl+t"] and "새 탭" in out
    assert pc.focus.last_external == 20                              # 이후 입력은 브라우저로 간다
    pc.log.clear()
    pc.t_browser("reopen_tab")
    assert keys(pc) == ["ctrl+shift+t"] and ("front", 20) not in pc.log     # 이미 앞에 있으면 다시 가져오지 않는다


def test_browser_needs_an_open_browser_but_a_new_tab_with_url_just_opens_it(pc):
    pc.windows = pc.windows[:1]
    with pytest.raises(ToolError, match="브라우저"):
        pc.t_browser("back")
    pc.t_open_url = lambda url: f"열기: {url}"
    assert pc.t_browser("new_tab", url="https://example.com") == "열기: https://example.com"


def test_browser_go_types_the_address_into_the_current_tab_and_restores_the_clipboard(pc):
    pc.t_browser("go", url="naver.com")
    assert pc.log[-6:] == ["ctrl+l", ("clip", "naver.com"), "ctrl+a", "ctrl+v", ("clip", "예전 클립보드"), "enter"]
    with pytest.raises(ToolError):
        pc.t_browser("go")
    pc.log.clear()
    pc.t_browser("find", text="환불")
    assert keys(pc) == ["ctrl+f", "ctrl+a", "ctrl+v", "enter"]
    pc.windows[1]["exe"] = "firefox.exe"
    pc.log.clear()
    pc.t_browser("incognito")
    assert keys(pc) == ["ctrl+shift+p"]                              # 파이어폭스는 단축키가 다르다


def test_switch_tab_finds_the_tab_by_site_name_and_ignores_tabs_inside_the_page(pc):
    pc.screen.items = [item(1, "탭", "네이버 - 메모리 사용량 120MB", (10, 8, 250, 42)),
                       item(2, "탭", "YouTube", (250, 8, 490, 42)),
                       item(3, "탭", "받은편지함 - Gmail", (490, 8, 730, 42)),
                       item(4, "탭", "동영상", (300, 400, 380, 430)),          # 웹 페이지 안의 탭 모양 버튼
                       item(5, "버튼", "YouTube 홈", (20, 120, 100, 150))]
    assert pc.t_browser("list_tabs").splitlines()[1:] == ["1. 네이버 - 메모리 사용량 120MB", "2. YouTube", "3. 받은편지함 - Gmail"]
    out = pc.t_browser("switch_tab", name="유튜브")                   # 탭에는 영어로 적혀 있다
    click = next(e for e in pc.log if e[0] == "click")
    assert "YouTube" in out and click[1:3] == (310, 25)              # 탭의 왼쪽 (오른쪽 끝의 닫기 단추를 피해서)
    pc.log.clear()
    pc.t_browser("switch_tab", name="지메일")
    assert next(e for e in pc.log if e[0] == "click")[1] == 550
    pc.log.clear()
    pc.t_browser("switch_tab", number=-1)
    assert next(e for e in pc.log if e[0] == "click")[1] == 550      # 마지막 탭
    with pytest.raises(ToolError, match="열린 탭: '네이버"):
        pc.t_browser("switch_tab", name="쿠팡")
    with pytest.raises(ToolError):
        pc.t_browser("switch_tab", number=7)


def test_switch_tab_falls_back_to_shortcuts_when_tabs_cannot_be_read(pc):
    pc.t_browser("switch_tab", number=2)
    pc.t_browser("switch_tab", number=-1)
    assert keys(pc) == ["ctrl+2", "ctrl+9"]
    assert "읽지 못했습니다" in pc.t_browser("list_tabs")


# ---------------------------------------------------------------- 창
def test_arrange_puts_named_windows_side_by_side_in_the_order_given(pc):
    out = pc.t_arrange_windows(apps=["크롬", "메모장"])
    assert [e for e in pc.log if e[0] == "place"] == [("place", 20, (0, 0, 960, 1040)), ("place", 10, (960, 0, 1920, 1040))]
    assert pc.log[-1] == ("front", 20) and pc.focus.last_external == 20 and "2개" in out      # 첫 창이 활성 창
    with pytest.raises(ToolError, match="한글"):
        pc.t_arrange_windows(apps=["크롬", "한글"])


def test_arrange_without_names_uses_the_two_most_recent_windows_and_other_layouts(pc):
    pc.t_arrange_windows()
    assert [e[1] for e in pc.log if e[0] == "place"] == [10, 20]
    pc.log.clear()
    pc.t_arrange_windows(apps=["메모장", "크롬", "카카오톡"], layout="grid")
    assert [e[2] for e in pc.log if e[0] == "place"] == [(0, 0, 960, 520), (960, 0, 1920, 520), (0, 520, 1920, 1040)]
    pc.windows = pc.windows[:1]
    with pytest.raises(ToolError):
        pc.t_arrange_windows()


def test_tile_layouts():
    tile = tools.winutil.tile
    assert tile((0, 0, 1000, 600), 2) == [(0, 0, 500, 600), (500, 0, 1000, 600)]
    assert tile((0, 0, 1000, 600), 2, "rows") == [(0, 0, 1000, 300), (0, 300, 1000, 600)]
    assert tile((100, 50, 1100, 650), 4, "grid") == [(100, 50, 600, 350), (600, 50, 1100, 350),
                                                    (100, 350, 600, 650), (600, 350, 1100, 650)]
    assert len(tile((0, 0, 1200, 600), 5, "grid")) == 5 and tile((0, 0, 1200, 600), 5, "grid")[-1] == (600, 300, 1200, 600)


# ---------------------------------------------------------------- 입력칸
def test_fill_ui_clicks_the_box_with_the_real_mouse_and_replaces_its_content(pc):
    pc.screen.items = [item(1, "입력칸", "검색", (100, 100, 500, 140)), item(2, "버튼", "검색 실행", (510, 100, 560, 140))]
    out = pc.t_fill_ui(name="검색", text="자비스", press_enter=True)
    assert pc.log == [("click", 300, 120, {"hwnd": 10}), ("clip", "자비스"), "ctrl+a", "ctrl+v", ("clip", "예전 클립보드"), "enter"]
    assert "'검색' 칸에 3자" in out and "Enter" in out
    pc.log.clear()
    pc.t_fill_ui(number=1, text=" 더", append=True)
    assert "ctrl+a" not in pc.log                                    # 있던 내용을 지우지 않는다


def test_fill_ui_fills_a_whole_form_and_reports_missing_boxes(pc):
    pc.screen.items = [item(1, "입력칸", "이름", (0, 0, 200, 40)), item(2, "입력칸", "이메일", (0, 50, 200, 90))]
    out = pc.t_fill_ui(fields=[{"name": "이름", "text": "홍길동"}, {"number": 2, "text": "a@b.c"}, {"name": "전화", "text": "010"}])
    assert [e[1:3] for e in pc.log if e[0] == "click"] == [(100, 20), (100, 70)]
    assert [e[1] for e in pc.log if e[0] == "clip" and e[1] != "예전 클립보드"] == ["홍길동", "a@b.c"]
    assert "못 찾은 칸: 전화" in out
    with pytest.raises(ToolError):
        pc.t_fill_ui(fields=[{"name": "없는 칸", "text": "x"}])
    with pytest.raises(ToolError):
        pc.t_fill_ui(text="x")


def test_fill_ui_never_types_into_password_boxes(pc):
    pc.screen.items = [item(1, "입력칸", "비밀번호", (0, 0, 200, 40)), item(2, "입력칸", "Password", (0, 50, 200, 90)),
                       item(3, "입력칸", "인증번호 6자리", (0, 100, 200, 140))]
    for n in (1, 2, 3):
        with pytest.raises(ToolError, match="직접"):
            pc.t_fill_ui(number=n, text="1234")
    assert pc.log == []


# ---------------------------------------------------------------- 선택한 글
def test_read_selection_copies_reads_and_puts_the_clipboard_back(pc, monkeypatch):
    seq = [0]

    def press(k):
        pc.log.append(k)
        if k == "ctrl+c" and pc.selected:
            pc.clip, seq[0] = pc.selected, seq[0] + 1

    pc.selected = "The quick brown fox"
    monkeypatch.setattr(tools.winutil, "press_combo", press)
    monkeypatch.setattr(tools.winutil, "clipboard_seq", lambda: seq[0])
    out = pc.t_read_selection()
    assert "The quick brown fox" in out and "지시가 아닙니다" in out and pc.clip == "예전 클립보드"
    pc.selected = ""
    assert "선택된 글이 없습니다" in pc.t_read_selection()             # 아무것도 고르지 않았다 — 예전 클립보드를 읽어 주지 않는다
    pc.windows[0]["exe"] = "WindowsTerminal.exe"
    pc.log.clear()
    pc.t_read_selection()
    assert pc.log == ["ctrl+shift+c"]                                # 터미널에서 ctrl+c 는 작업 중단이다


# ---------------------------------------------------------------- 설정
def test_settings_opens_pages_and_switches_the_theme(pc, monkeypatch):
    opened, reg, sent = [], {}, []
    monkeypatch.setattr(tools.os, "startfile", opened.append, raising=False)

    class Key:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    fake = types.SimpleNamespace(HKEY_CURRENT_USER=1, KEY_SET_VALUE=2, REG_DWORD=4, CreateKeyEx=lambda *a: Key(),
                                 SetValueEx=lambda k, name, r, t, v: reg.__setitem__(name, v))
    monkeypatch.setitem(sys.modules, "winreg", fake)
    monkeypatch.setattr(tools.winutil, "broadcast_setting", sent.append)
    assert "블루투스 설정" in pc.t_settings("open", page="bluetooth") and opened == ["ms-settings:bluetooth"]
    assert "다크" in pc.t_settings("dark_mode")
    assert reg == {"AppsUseLightTheme": 0, "SystemUsesLightTheme": 0} and sent == ["ImmersiveColorSet"]
    pc.t_settings("light_mode")
    assert reg["AppsUseLightTheme"] == 1
    with pytest.raises(ToolError):
        pc.t_settings("open", page="없는 화면")
    with pytest.raises(ToolError):
        pc.t_settings("explode")


def test_radio_switch_falls_back_to_the_settings_page(pc, monkeypatch):
    opened = []
    monkeypatch.setattr(tools.os, "startfile", opened.append, raising=False)
    pc._radio = lambda kind, on: "Allowed"
    assert "블루투스를 켰습니다" in pc.t_settings("bluetooth_on") and opened == []
    assert "인터넷이 끊기면" in pc.t_settings("wifi_off")
    pc._radio = lambda kind, on: "DeniedBySystem"
    assert "설정 화면을 열었습니다" in pc.t_settings("wifi_on") and opened == ["ms-settings:network-wifi"]
    pc._radio = lambda kind, on: "NONE"
    assert "장치가 없습니다" in pc.t_settings("bluetooth_off")

    def boom(kind, on):
        raise OSError("powershell 없음")
    pc._radio = boom
    assert "설정 화면을 열었습니다" in pc.t_settings("bluetooth_on")


# ---------------------------------------------------------------- 파일
@pytest.fixture
def downloads(tmp_path):
    d = tmp_path / "Downloads"
    d.mkdir()
    for name in ("과제.hwp", "사진.jpg", "영상.mp4", "setup.exe"):
        (d / name).write_bytes(b"x")
    return d


def test_organize_asks_first_shows_the_plan_and_can_be_undone(pc, downloads):
    out = pc.t_file_action("organize", folder="다운로드")
    title, detail = pc.asked[0]
    assert title == "폴더 정리" and "파일 4개" in detail and "사진 폴더 ← 1개" in detail
    assert "파일 4개를 폴더 4개로" in out and (downloads / "문서" / "과제.hwp").exists()
    assert "4개를 원래 자리로" in pc.t_file_action("undo")
    assert (downloads / "과제.hwp").exists() and not (downloads / "문서").exists()
    pc.approve = False
    with pytest.raises(ToolError, match="거부"):
        pc.t_file_action("organize", folder="다운로드")
    assert (downloads / "과제.hwp").exists()                           # 거절하면 아무것도 옮기지 않는다


def test_file_actions_take_known_folder_names_and_never_overwrite(pc, downloads, tmp_path):
    assert "과제.hwp" in pc.t_list_folder("다운로드")
    pc.t_file_action("new_folder", dest="문서/학교")
    out = pc.t_file_action("move", paths=["다운로드/과제.hwp"], dest="문서/학교")
    assert (tmp_path / "Docs" / "학교" / "과제.hwp").exists() and "1개" in out and pc.asked == []
    (downloads / "과제.hwp").write_bytes(b"new")
    out = pc.t_file_action("copy", paths=[str(downloads / "과제.hwp")], dest="문서/학교")
    assert "과제 (2).hwp" in out
    assert "최종.hwp" in pc.t_file_action("rename", paths=["다운로드/과제.hwp"], new_name="최종")
    assert ".zip" in pc.t_file_action("zip", paths=["다운로드/사진.jpg"])
    with pytest.raises(ToolError, match="전체 경로"):
        pc.t_file_action("move", paths=["그냥이름.txt"], dest="문서")
    with pytest.raises(ToolError):
        pc.t_file_action("move", paths=["다운로드/없는파일.txt"], dest="문서")
    with pytest.raises(ToolError):
        pc.t_file_action("shred", paths=["다운로드/사진.jpg"])


def test_delete_goes_to_the_recycle_bin_only_after_approval(pc, downloads, monkeypatch):
    trashed = []
    monkeypatch.setattr("jarvis.files.trash", lambda paths: trashed.extend(paths) or len(paths))
    out = pc.t_file_action("delete", paths=["다운로드/setup.exe"])
    assert pc.asked[0][0] == "휴지통으로 보내기" and "setup.exe" in pc.asked[0][1] and "휴지통" in out
    assert [p.name for p in trashed] == ["setup.exe"]
    pc.approve = False
    with pytest.raises(ToolError, match="거부"):
        pc.t_file_action("delete", paths=["다운로드/사진.jpg"])
    assert len(trashed) == 1
    pc.approve = True
    with pytest.raises(ToolError, match="폴더 자체"):
        pc.t_file_action("delete", paths=["다운로드"])                # 다운로드 폴더를 통째로 지우지 않는다
    with pytest.raises(ToolError):
        pc.t_file_action("delete", paths=["다운로드/없는파일"])


def test_moving_many_files_at_once_asks_first(pc, downloads):
    for i in range(31):
        (downloads / f"f{i}.txt").write_text("x")
    pc.t_file_action("move", paths=[f"다운로드/f{i}.txt" for i in range(31)], dest="문서/많이")
    assert pc.asked and pc.asked[0][0] == "파일 옮기기" and "31개" in pc.asked[0][1]


# ---------------------------------------------------------------- 앱 켠 직후 · 도구 목록


def test_a_screen_tool_right_after_open_app_waits_for_the_new_window(pc, monkeypatch):
    monkeypatch.setattr(tools.os, "startfile", lambda p: None, raising=False)
    pc._apps = []
    assert "실행함" in pc.t_open_app("계산기")
    polls = [0]

    def windows():
        polls[0] += 1
        new = [{"hwnd": 99, "title": "계산기", "exe": "CalculatorApp.exe", "pid": 9}] if polls[0] >= 3 else []
        return new + pc.windows
    monkeypatch.setattr(tools.winutil, "list_windows", windows)
    pc._await_launch()
    assert polls[0] >= 3 and pc.focus.last_external == 99 and pc.focus.last_title == "계산기"
    polls[0] = 0
    pc._await_launch()                                               # 한 번 기다린 뒤에는 다시 기다리지 않는다
    assert polls[0] == 0


def test_key_helpers():
    W = tools.winutil
    pressed = []
    orig = W._key
    try:
        W._key = lambda vk, up: pressed.append((vk, up))
        W.press_combo("ctrl++")                                      # 마지막 + 는 키 이름
        assert pressed == [(0x11, False), (0xBB, False), (0xBB, True), (0x11, True)]
        pressed.clear()
        with W.held("ctrl+shift"):
            pressed.append("click")
        assert pressed == [(0x11, False), (0x10, False), "click", (0x10, True), (0x11, True)]
        with pytest.raises(ValueError):
            W.press_combo("")
    finally:
        W._key = orig


def test_new_tools_are_registered_with_labels(pc):
    names = {s["name"] for s in pc.schemas()}
    new = {"browser", "arrange_windows", "fill_ui", "read_selection", "settings", "list_folder", "file_action"}
    assert new <= names and len(names) == len(pc.schemas())           # 이름이 겹치지 않는다
    for n in new:
        assert hasattr(pc, f"t_{n}") and PCTools.label(n, {"action": "x", "folder": "다운로드"}) != n
    assert PCTools.label("browser", {"action": "switch_tab", "name": "유튜브"}) == "브라우저 · switch_tab 유튜브"


# ---------------------------------------------------------------- 이름으로 탭 닫기 ('인스타그램 닫아')
EDGE_TABS = ["gmail - 검색", "받은편지함 (124) - someone@gmail.com - Gmail", "받은편지함 (446) - other@gmail.com - Gmail",
             "Instagram", "일본어 회화 대본 모음 - Google Docs"]


@pytest.fixture
def edge(pc, monkeypatch):
    """탭 5개가 열린 엣지 — 지금 보고 있는 탭은 구글 문서 (창 제목에는 그 탭만 나온다)."""
    pc.tabs = list(EDGE_TABS)
    pc.windows = [{"hwnd": 20, "title": "일본어 회화 대본 모음 - Google Docs - 프로필 1 - Microsoft​ Edge", "exe": "msedge.exe", "pid": 2},
                  {"hwnd": 10, "title": "제목 없음 - 메모장", "exe": "Notepad.exe", "pid": 1}]
    pc.focus.last_external = 20
    pc.middle_works = True

    def read(hwnd, query=""):
        pc.screen.hwnd = hwnd
        pc.screen.items = ([item(i + 1, "탭", t, (10 + 240 * i, 8, 250 + 240 * i, 42)) for i, t in enumerate(pc.tabs)]
                           + [item(99, "탭", "페이지 안의 탭", (300, 500, 380, 530))]) if hwnd == 20 else []
        return ""
    pc.screen.read = read

    def click(x, y, **kw):
        pc.log.append(("click", x, y, kw))
        i = (x - 10) // 240
        if kw.get("middle") and pc.middle_works and 0 <= i < len(pc.tabs):
            del pc.tabs[i]
        elif not kw.get("middle"):
            pc.selected_tab = i
    monkeypatch.setattr(tools.uia, "click_at", click)

    def press(k):
        pc.log.append(k)
        if k == "ctrl+w" and getattr(pc, "selected_tab", None) is not None:
            del pc.tabs[pc.selected_tab]
            pc.selected_tab = None
    monkeypatch.setattr(tools.winutil, "press_combo", press)
    monkeypatch.setattr(tools.uia, "cursor_pos", lambda: (900, 600))
    monkeypatch.setattr(tools.uia, "set_cursor", lambda pos: pc.log.append(("cursor", pos)))
    return pc


    # '지메일' 을 'google' 로 넓혀 찾지 않는다 — 구글 문서 탭은 그대로다


def test_close_app_still_closes_real_apps_and_whole_browsers_by_their_name(edge):
    assert "1개 창" in edge.t_close_app("메모장") and ("close", 10) in edge.log
    edge.log.clear()
    assert "1개 창" in edge.t_close_app("엣지") and ("close", 20) in edge.log and len(edge.tabs) == 5
    with pytest.raises(ToolError, match="열린 창이 없습니다"):
        edge.t_close_app("넷플릭스")


def test_tabs_close_even_when_the_middle_button_does_nothing(edge):
    edge.middle_works = False
    edge.t_browser("close_tab", name="인스타그램")
    assert "Instagram" not in edge.tabs and "ctrl+w" in edge.log     # 그 탭으로 가서 닫는다
    with pytest.raises(ToolError, match="열려 있지 않습니다"):
        edge.t_browser("close_tab", name="쿠팡")


def test_close_tab_by_number_and_plain_close_tab(edge):
    edge.t_browser("close_tab", number=1)
    assert edge.tabs == EDGE_TABS[1:]
    edge.t_browser("close_tab", number=-1)
    assert edge.tabs == EDGE_TABS[1:-1]
    edge.log.clear()
    edge.t_browser("close_tab")
    assert keys(edge) == ["ctrl+w"]                                   # 이름 · 번호가 없으면 지금 탭
    with pytest.raises(ToolError):
        edge.t_browser("close_tab", number=9)


def test_page_title_strips_the_browser_name():
    from jarvis.control import _site_words, page_title
    assert page_title("받은편지함 - Gmail - 프로필 1 - Microsoft​ Edge") == "받은편지함 - Gmail"
    assert page_title("YouTube - Google Chrome") == "YouTube"
    assert page_title("네이버 외 페이지 4개 - 개인 - Microsoft Edge") == "네이버"
    assert page_title("Instagram") is None and page_title("제목 없음 - 메모장") is None
    assert "google" not in _site_words("지메일") and "gmail" in _site_words("지메일")
    assert "youtube" in _site_words("유튜브") and "youtubemusic" in _site_words("유튜브 뮤직")


# ---------------------------------------------------------------- 검토 뒤 보강
def test_fill_ui_asks_before_pressing_a_risky_button(pc):
    pc.screen.items = [item(1, "버튼", "결제하기", (0, 0, 200, 40))]
    pc.approve = False
    with pytest.raises(ToolError):
        pc.t_fill_ui(number=1, text="x")
    assert pc.asked and pc.asked[0][0] == "화면 입력" and pc.log == []


def test_wifi_off_asks_first(pc):
    pc._radio = lambda kind, on: "Allowed"
    pc.approve = False
    with pytest.raises(ToolError):
        pc.t_settings("wifi_off")
    assert pc.asked[0][0] == "와이파이 끄기"
    pc.asked.clear()
    pc.t_settings("wifi_on")
    assert pc.asked == []


def test_organize_without_a_folder_does_not_fall_back_to_the_working_folder(pc):
    with pytest.raises(ToolError, match="폴더가 비었습니다"):
        pc.t_file_action("organize")
    assert pc.asked == []
