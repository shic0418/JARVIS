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
UIA_TextPatternId = 10014
UIA_ScrollItemPatternId = 10017
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
# 글자 읽기(read_text)에서 보는 종류: 글(50020) · 입력칸(50004) · 문서(50030)
TEXT_TYPES = (50020, 50004, 50030)
MAX_TEXT = 6000            # 한 번에 돌려주는 글자 수 상한


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
        self.url = ""                     # read_text 가 마지막으로 읽은 웹 문서의 주소 (브라우저가 아니면 빈 값)
        self._lock = threading.Lock()
        self._hidden = False              # True 인 동안 _collect 가 화면 밖(스크롤해야 보이는) 요소만 모은다

    # ------------------------------------------------------------------ 화면 밖 요소
    def find_hidden(self, hwnd: int, name: str) -> list[Item]:
        """스크롤해야 보이는 요소 중 이름이 맞는 것들 (가장 비슷한 것부터). 못 읽으면 빈 목록."""
        q = _norm(name)
        if not q:
            return []
        with self._lock:
            self._hidden = True
            try:
                items = self._collect(_uia(), _U(), _uia().ElementFromHandle(hwnd))
            except Exception as e:
                log.debug("화면 밖 요소 읽기 실패: %s", e)
                return []
            finally:
                self._hidden = False
        hits = [it for it in items if q in _norm(it.name)]
        return sorted(hits, key=lambda it: (_norm(it.name) != q, len(it.name)))

    def reveal(self, it: Item) -> bool:
        """화면 밖 요소가 보이도록 스크롤한다 (요소가 스스로 스크롤하는 기능을 지원할 때)."""
        try:
            p = it.el.GetCurrentPattern(UIA_ScrollItemPatternId)
            if not p:
                return False
            p.QueryInterface(_U().IUIAutomationScrollItemPattern).ScrollIntoView()
            return True
        except Exception as e:
            log.debug("요소로 스크롤 실패: %s", e)
            return False

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
                if bool(el.CachedIsOffscreen) != self._hidden or not el.CachedIsEnabled:
                    continue
                r = el.CachedBoundingRectangle
                rect = (r.left, r.top, r.right, r.bottom)
                if not self._hidden and (rect[2] - rect[0] < 2 or rect[3] - rect[1] < 2):
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

    # ------------------------------------------------------------------ 글자 읽기
    def read_text(self, hwnd: int, include_offscreen: bool = False, limit: int = MAX_TEXT) -> str:
        """창에 보이는 글을 읽는 순서대로 돌려준다 (웹 페이지 본문 · 문서 · 라벨).
        include_offscreen=True 면 웹 페이지에서 스크롤해야 보이는 부분까지 읽는다."""
        with self._lock:
            a, U = _uia(), _U()
            root = a.ElementFromHandle(hwnd)
            title = _title(hwnd)
            self.url = ""
            if _is_browser(hwnd) and hwnd not in self._woken and _wake_chromium(hwnd):
                self._woken.add(hwnd)
                prev = -1
                for _ in range(6):          # 접근성 트리가 다 만들어질 때까지 (글 조각 수가 더 늘지 않을 때까지)
                    time.sleep(0.35)
                    pieces = self._collect_text(a, U, root, include_offscreen)
                    if len(pieces) == prev:
                        break
                    prev = len(pieces)
            else:
                pieces = self._collect_text(a, U, root, include_offscreen)
            body = layout_text(pieces, limit)
            if not body:
                return (f"'{title}' 창에서 읽을 수 있는 글을 찾지 못했습니다. "
                        "look_at_screen 으로 화면을 보세요 (그림 · 게임 · 일부 앱은 글자를 내보내지 않습니다).")
            scope = "스크롤해야 보이는 부분 포함" if include_offscreen else "지금 보이는 부분"
            where = f"\n주소: {self.url}" if self.url else ""
            return f"창: {title} ({scope}){where}\n{body}"

    def _collect_text(self, a, U, root, include_offscreen: bool) -> list[tuple[tuple[int, int, int, int], str]]:
        """[(화면 좌표 사각형, 글)] — 글 조각 · 입력칸 값 · 문서 본문."""
        cache = a.CreateCacheRequest()
        for pid in (UIA_ControlTypePropertyId, UIA_NamePropertyId, UIA_BoundingRectanglePropertyId,
                    UIA_IsOffscreenPropertyId, UIA_ValueValuePropertyId):
            cache.AddProperty(pid)
        cond = a.CreateOrConditionFromArray([a.CreatePropertyCondition(UIA_ControlTypePropertyId, ct) for ct in TEXT_TYPES])
        found = root.FindAllBuildCache(TreeScope_Descendants, cond, cache)
        out: list[tuple[tuple[int, int, int, int], str]] = []
        for i in range(found.Length if found else 0):
            el = found.GetElement(i)
            try:
                if el.CachedIsOffscreen and not include_offscreen:
                    continue
                r = el.CachedBoundingRectangle
                rect = (r.left, r.top, r.right, r.bottom)
                ct = el.CachedControlType
                text = ""
                if ct in (50004, 50030):
                    v = el.GetCachedPropertyValue(UIA_ValueValuePropertyId)
                    text = v if isinstance(v, str) else ""
                    if ct == 50030 and re.match(r"^[a-z][a-z0-9+.-]*:", text.strip(), re.I):
                        self.url = text.strip()[:300]         # 크롬 · 엣지: 웹 문서의 값은 지금 탭의 주소
                        continue
                    if not text.strip() and (rect[2] - rect[0]) * (rect[3] - rect[1]) > 4000:
                        text = _pattern_text(el, U)          # 메모장 · 워드 같은 문서 영역
                    if not text.strip() and ct == 50030:
                        continue                              # 웹 문서 뿌리: 이름은 창 제목과 같다 (본문은 글 조각으로 읽는다)
                    if not text.strip():
                        text = el.CachedName or ""
                else:
                    text = el.CachedName or ""
                text = text.strip()
                if text:
                    out.append((rect, text))
            except Exception:
                continue
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


def move_to(x: int, y: int) -> None:
    """마우스를 그 자리로 옮긴다 (누르지 않음). 조금씩 움직여서 '올려놓으면 펼쳐지는' 메뉴가 반응하게 한다."""
    user32.SetCursorPos(int(x) - 3, int(y) - 3)
    time.sleep(0.03)
    user32.SetCursorPos(int(x), int(y))
    time.sleep(0.05)


def drag(x1: int, y1: int, x2: int, y2: int, steps: int = 14) -> None:
    """(x1, y1) 에서 누른 채 (x2, y2) 까지 끌고 가서 놓는다 (슬라이더 · 파일 옮기기 · 범위 선택)."""
    user32.SetCursorPos(int(x1), int(y1))
    time.sleep(0.05)
    user32.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
    time.sleep(0.08)
    for i in range(1, steps + 1):                 # 한 번에 건너뛰면 끌기를 알아채지 못하는 앱이 많다
        user32.SetCursorPos(round(x1 + (x2 - x1) * i / steps), round(y1 + (y2 - y1) * i / steps))
        time.sleep(0.015)
    time.sleep(0.08)
    user32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)


def scroll(hwnd: int, direction: str, amount: int = 5, at: tuple[int, int] | None = None) -> None:
    """창 한가운데(또는 at 자리)에서 마우스 휠을 굴린다."""
    rect = wt.RECT()
    if at is not None:
        user32.SetCursorPos(int(at[0]), int(at[1]))
        time.sleep(0.05)
    elif hwnd and user32.GetWindowRect(hwnd, ctypes.byref(rect)):
        from .winutil import force_foreground
        force_foreground(hwnd)
        user32.SetCursorPos((rect.left + rect.right) // 2, (rect.top + rect.bottom) // 2)
        time.sleep(0.05)
    delta = 120 * max(1, min(int(amount), 30)) * (1 if direction == "up" else -1)
    user32.mouse_event(MOUSEEVENTF_WHEEL, 0, 0, ctypes.c_uint32(delta & 0xFFFFFFFF).value, 0)


# ---------------------------------------------------------------------- 글자 · 위치
def _pattern_text(el, U) -> str:
    """문서/입력 영역의 본문 (TextPattern). 지원하지 않으면 빈 문자열."""
    try:
        p = el.GetCurrentPattern(UIA_TextPatternId)
        if not p:
            return ""
        return p.QueryInterface(U.IUIAutomationTextPattern).DocumentRange.GetText(MAX_TEXT) or ""
    except Exception as e:
        log.debug("TextPattern 읽기 실패: %s", e)
        return ""


def layout_text(pieces: list[tuple[tuple[int, int, int, int], str]], limit: int = MAX_TEXT) -> str:
    """[(사각형, 글)] → 사람이 읽는 순서의 글. 같은 높이의 조각은 왼쪽부터 한 줄로 잇고, 바로 앞과 같은 글은 한 번만 쓴다."""
    rows: list[tuple[int, int, str]] = []
    for (left, top, _right, bottom), text in pieces:
        text = re.sub(r"[ \t\r\f\v]+", " ", text).strip()
        if text:
            rows.append(((top + bottom) // 2, left, text))
    rows.sort(key=lambda r: r[0])
    lines: list[str] = []
    group: list[tuple[int, int, str]] = []

    def flush() -> None:
        if not group:
            return
        parts: list[str] = []
        for _y, _x, text in sorted(group, key=lambda r: r[1]):
            if not parts or parts[-1] != text:
                parts.append(text)
        joined = " ".join(parts)
        if not lines or lines[-1] != joined:
            lines.append(joined)
        group.clear()

    for row in rows:
        # 여러 줄짜리 글(문서 본문)은 혼자 한 덩어리로 둔다
        if group and (row[0] - group[0][0] > 6 or "\n" in row[2] or "\n" in group[0][2]):
            flush()
        group.append(row)
    flush()
    out = "\n".join(lines).strip()
    if len(out) > limit:
        out = out[:limit].rstrip() + f"\n…(이하 생략 — 전체 {len(out)}자 중 {limit}자)"
    return out


def element_at(x: int, y: int) -> tuple[str, str]:
    """화면 좌표에 있는 요소의 (이름, 종류). 누를 수 있는 요소(버튼 · 링크 등)가 아니거나 알 수 없으면 ("", "").
    버튼 안의 글자 · 아이콘을 짚은 경우를 위해 위로 세 단계까지 올라가며 찾는다."""
    try:
        a, U = _uia(), _U()
        el = a.ElementFromPoint(U.tagPOINT(int(x), int(y)))
        walker = a.ControlViewWalker
        inner = ""
        for _ in range(4):
            if not el:
                break
            name = re.sub(r"\s+", " ", (el.CurrentName or "")).strip()
            ct = el.CurrentControlType
            if ct in CONTROL_TYPES:
                return (name or inner)[:80], CONTROL_TYPES[ct]
            inner = inner or name
            el = walker.GetParentElement(el)
    except Exception as e:
        log.debug("좌표의 요소 확인 실패: %s", e)
    return "", ""


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


_STOP = re.compile(r"^(중지|정지|응답\s*중지|생성\s*중지|답변\s*중지|stop|stop\s*(generating|response|streaming|answering)"
                   r"|interrupt|응답 생성 중지)$", re.I)


def is_stop_button(name: str) -> bool:
    """AI 앱이 답을 만드는 동안만 보이는 '중지' 버튼인가 (작업 감시용)."""
    return bool(_STOP.match((name or "").strip()))
