"""화면 조작: Windows UI 자동화(UIA)로 창 안의 버튼·링크·탭을 읽고 누른다.

크롬·엣지는 웹 페이지 내용도 UIA 로 내보내므로, 로그인된 사용자 브라우저 그대로
'구글 클래스룸 → 경제 탭' 같은 사이트 안 이동을 할 수 있다. 일반 앱(메모장, 카톡, 설정 등)도 같은 방식.

  read(hwnd)      → 눌러 볼 만한 요소 목록 (번호, 종류, 이름)
  click(번호)      → 그 요소를 실행 (Invoke/선택/토글 패턴, 안 되면 가운데를 마우스로 클릭)

UIA COM 은 스레드마다 초기화해야 하므로 호출할 때마다 CoInitialize 한다.
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import logging
import re
import threading
import time
from dataclasses import dataclass

log = logging.getLogger("jarvis.uia")
user32 = ctypes.windll.user32

# UIA 상수
UIA_ControlTypePropertyId = 30003
UIA_NamePropertyId = 30005
UIA_BoundingRectanglePropertyId = 30001
UIA_IsOffscreenPropertyId = 30022
UIA_IsEnabledPropertyId = 30010
UIA_HelpTextPropertyId = 30013
UIA_ValueValuePropertyId = 30045
UIA_ValueIsReadOnlyPropertyId = 30046
UIA_InvokePatternId = 10000
UIA_SelectionItemPatternId = 10010
UIA_TogglePatternId = 10015
UIA_ExpandCollapsePatternId = 10005
UIA_LegacyIAccessiblePatternId = 10018
TreeScope_Descendants = 4

CONTROL_TYPES = {
    50000: "버튼", 50002: "체크박스", 50003: "콤보박스", 50004: "입력칸", 50005: "링크",
    50007: "목록항목", 50011: "메뉴항목", 50013: "라디오", 50019: "탭",
    50024: "트리항목", 50031: "분할버튼",
}
# 이름이 이렇게 생긴 요소는 누르기 전에 사용자 승인을 받는다
RISKY = re.compile(r"결제|구매|주문|송금|이체|삭제|탈퇴|해지|전송|보내기|제출|게시|업로드|포맷|초기화|"
                   r"\b(pay|buy|purchase|order|checkout|delete|remove|send|submit|post|publish|upload|format|reset)\b",
                   re.I)
MAX_ITEMS = 150


@dataclass
class Item:
    n: int
    kind: str
    name: str
    rect: tuple[int, int, int, int]   # left, top, right, bottom (물리 픽셀)
    el: object                        # IUIAutomationElement
    value: str = ""

    def line(self) -> str:
        v = f" = '{self.value[:40]}'" if self.value else ""
        return f"[{self.n}] {self.kind} '{self.name[:60]}'{v}"


_tls = threading.local()


def _uia():
    """스레드별 IUIAutomation 객체."""
    a = getattr(_tls, "uia", None)
    if a is not None:
        return a
    import comtypes
    import comtypes.client
    try:
        comtypes.CoInitializeEx(comtypes.COINIT_MULTITHREADED)
    except OSError:
        pass
    comtypes.client.GetModule("UIAutomationCore.dll")
    from comtypes.gen import UIAutomationClient as U
    a = comtypes.client.CreateObject(U.CUIAutomation, interface=U.IUIAutomation)
    _tls.uia, _tls.U = a, U
    return a


def _U():
    _uia()
    return _tls.U


class Screen:
    """마지막으로 읽은 요소 목록을 기억해 두고 번호로 누른다."""

    def __init__(self) -> None:
        self.items: list[Item] = []
        self.hwnd = 0
        self.title = ""
        self._woken: set[int] = set()     # 접근성을 깨운 Chromium 창
        self._lock = threading.Lock()

    # ------------------------------------------------------------------ 읽기
    def read(self, hwnd: int, query: str = "") -> str:
        with self._lock:
            return self._read(hwnd, query)

    def _read(self, hwnd: int, query: str) -> str:
        a, U = _uia(), _U()
        root = a.ElementFromHandle(hwnd)
        self.hwnd, self.title = hwnd, _title(hwnd)
        if _is_browser(hwnd) and hwnd not in self._woken:
            # 크롬·엣지·Electron 은 접근성 클라이언트가 붙었다는 신호를 받아야 웹 내용 트리를 만든다.
            # 신호 후 트리가 다 만들어질 때까지(요소 수가 더 늘지 않을 때까지) 잠깐 기다린다.
            if _wake_chromium(hwnd):
                self._woken.add(hwnd)
                prev = -1
                for _ in range(6):
                    time.sleep(0.35)
                    items = self._collect(a, U, root)
                    if len(items) == prev:
                        break
                    prev = len(items)
            else:
                items = self._collect(a, U, root)
        else:
            items = self._collect(a, U, root)
        if query:
            q = _norm(query)
            hits = [it for it in items if q in _norm(it.name)]
            items = hits or items
        self.items = items[:MAX_ITEMS]
        for i, it in enumerate(self.items, 1):
            it.n = i
        if not self.items:
            return f"'{self.title}' 창에서 누를 수 있는 요소를 찾지 못했습니다. look_at_screen 으로 화면을 보고 click_screen 을 쓰세요."
        more = f"\n(요소가 많아 {MAX_ITEMS}개만 표시. query 로 좁히세요)" if len(items) > MAX_ITEMS else ""
        return (f"창: {self.title}\n누를 수 있는 요소 (click_ui 에 번호를 넘기세요):\n"
                + "\n".join(it.line() for it in self.items) + more)

    def _collect(self, a, U, root) -> list[Item]:
        cache = a.CreateCacheRequest()
        for pid in (UIA_ControlTypePropertyId, UIA_NamePropertyId, UIA_BoundingRectanglePropertyId,
                    UIA_IsOffscreenPropertyId, UIA_IsEnabledPropertyId, UIA_HelpTextPropertyId,
                    UIA_ValueValuePropertyId, UIA_ValueIsReadOnlyPropertyId):
            cache.AddProperty(pid)
        conds = [a.CreatePropertyCondition(UIA_ControlTypePropertyId, ct) for ct in CONTROL_TYPES]
        cond = a.CreateOrConditionFromArray(conds)
        found = root.FindAllBuildCache(TreeScope_Descendants, cond, cache)
        out: list[Item] = []
        seen: set[tuple] = set()
        for i in range(found.Length if found else 0):
            el = found.GetElement(i)
            try:
                if el.CachedIsOffscreen or not el.CachedIsEnabled:
                    continue
                r = el.CachedBoundingRectangle
                rect = (r.left, r.top, r.right, r.bottom)
                if rect[2] - rect[0] < 2 or rect[3] - rect[1] < 2:
                    continue
                ct = el.CachedControlType
                name = (el.CachedName or el.CachedHelpText or "").strip()
                value = ""
                if ct in (50004, 50003):
                    if ct == 50004 and el.GetCachedPropertyValue(UIA_ValueIsReadOnlyPropertyId) is True:
                        continue          # 읽기 전용 칸(탐색기 목록의 열 값 등)은 누를 일이 없음
                    v = el.GetCachedPropertyValue(UIA_ValueValuePropertyId)
                    value = v.strip() if isinstance(v, str) else ""
                if not name and ct not in (50004,):
                    continue
                key = (ct, name, rect)
                if key in seen:
                    continue
                seen.add(key)
                out.append(Item(0, CONTROL_TYPES.get(ct, "요소"), re.sub(r"\s+", " ", name), rect, el, value))
            except Exception:
                continue
        # 위→아래, 왼→오 순서 (사람이 읽는 순서)
        out.sort(key=lambda it: (it.rect[1] // 12, it.rect[0]))
        return out

    # ------------------------------------------------------------------ 찾기
    def find(self, n: int | None = None, name: str = "") -> Item | None:
        if n:
            return next((it for it in self.items if it.n == n), None)
        if not name:
            return None
        q = _norm(name)
        exact = [it for it in self.items if _norm(it.name) == q]
        if exact:
            return exact[0]
        part = [it for it in self.items if q in _norm(it.name)]
        return min(part, key=lambda it: len(it.name)) if part else None

    # ------------------------------------------------------------------ 누르기
    def click(self, it: Item, double: bool = False) -> str:
        with self._lock:
            U = _U()
            if not double:
                for pid, iface, call in ((UIA_InvokePatternId, U.IUIAutomationInvokePattern, "Invoke"),
                                         (UIA_SelectionItemPatternId, U.IUIAutomationSelectionItemPattern, "Select"),
                                         (UIA_TogglePatternId, U.IUIAutomationTogglePattern, "Toggle"),
                                         (UIA_ExpandCollapsePatternId, U.IUIAutomationExpandCollapsePattern, "Expand")):
                    try:
                        p = it.el.GetCurrentPattern(pid)
                        if p:
                            getattr(p.QueryInterface(iface), call)()
                            return f"'{it.name[:40]}' {it.kind} 누름"
                    except Exception as e:
                        log.debug("패턴 %s 실패: %s", pid, e)
            l, t, r, b = it.rect
            click_at((l + r) // 2, (t + b) // 2, double=double, hwnd=self.hwnd)
            return f"'{it.name[:40]}' {it.kind} {'더블' if double else ''}클릭"


# ---------------------------------------------------------------------- 마우스
MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP = 0x0002, 0x0004
MOUSEEVENTF_RIGHTDOWN, MOUSEEVENTF_RIGHTUP = 0x0008, 0x0010
MOUSEEVENTF_WHEEL = 0x0800


def click_at(x: int, y: int, double: bool = False, right: bool = False, hwnd: int = 0) -> None:
    """물리 픽셀 좌표 클릭. 대상 창을 먼저 앞으로 가져온다."""
    if hwnd:
        from .winutil import force_foreground
        force_foreground(hwnd)
        time.sleep(0.08)
    user32.SetCursorPos(int(x), int(y))
    time.sleep(0.03)
    down, up = (MOUSEEVENTF_RIGHTDOWN, MOUSEEVENTF_RIGHTUP) if right else (MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP)
    for _ in range(2 if double else 1):
        user32.mouse_event(down, 0, 0, 0, 0)
        user32.mouse_event(up, 0, 0, 0, 0)
        time.sleep(0.06)


def scroll(hwnd: int, direction: str, amount: int = 5) -> None:
    rect = wt.RECT()
    if hwnd and user32.GetWindowRect(hwnd, ctypes.byref(rect)):
        from .winutil import force_foreground
        force_foreground(hwnd)
        user32.SetCursorPos((rect.left + rect.right) // 2, (rect.top + rect.bottom) // 2)
        time.sleep(0.05)
    delta = 120 * max(1, min(int(amount), 30)) * (1 if direction == "up" else -1)
    user32.mouse_event(MOUSEEVENTF_WHEEL, 0, 0, ctypes.c_uint32(delta & 0xFFFFFFFF).value, 0)


# ---------------------------------------------------------------------- 보조
def _norm(s: str) -> str:
    return re.sub(r"[\s\-_.()·:]+", "", (s or "").lower())


def _title(hwnd: int) -> str:
    n = user32.GetWindowTextLengthW(hwnd)
    buf = ctypes.create_unicode_buffer(n + 1)
    user32.GetWindowTextW(hwnd, buf, n + 1)
    return buf.value


def _is_browser(hwnd: int) -> bool:
    buf = ctypes.create_unicode_buffer(64)
    user32.GetClassNameW(hwnd, buf, 64)
    return buf.value.startswith("Chrome_WidgetWin")


_IID_IAccessible = None


def _wake_chromium(hwnd: int) -> bool:
    """Chromium 렌더 창에 IAccessible 을 요청해 웹 페이지 접근성 트리를 켠다."""
    global _IID_IAccessible
    from comtypes import GUID
    if _IID_IAccessible is None:
        _IID_IAccessible = GUID("{618736E0-3C3D-11CF-810C-00AA00389B71}")
    kids: list[int] = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, wt.HWND, wt.LPARAM)
    def cb(h, _):
        buf = ctypes.create_unicode_buffer(64)
        user32.GetClassNameW(h, buf, 64)
        if buf.value == "Chrome_RenderWidgetHostHWND":
            kids.append(h)
        return True

    user32.EnumChildWindows(hwnd, cb, 0)
    for h in kids:
        try:
            ptr = ctypes.c_void_p()
            ctypes.oledll.oleacc.AccessibleObjectFromWindow(h, 0xFFFFFFFC, ctypes.byref(_IID_IAccessible),
                                                            ctypes.byref(ptr))
        except OSError:
            pass
    return bool(kids)


def is_risky(name: str) -> bool:
    return bool(RISKY.search(name or ""))
