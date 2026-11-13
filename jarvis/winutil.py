"""Windows 저수준 유틸: 키 입력, 창 제어, 클립보드, 포커스, 알려진 폴더."""
from __future__ import annotations

import contextlib
import ctypes
import ctypes.wintypes as wt
import os
import threading
import time
from pathlib import Path

import psutil

try:
    import win32clipboard
    import win32con
    import win32gui
    import win32process
except ImportError:  # pywin32 미설치
    win32clipboard = win32con = win32gui = win32process = None

user32 = ctypes.windll.user32
KEYEVENTF_EXTENDEDKEY = 0x0001
KEYEVENTF_KEYUP = 0x0002

VK = {
    "ctrl": 0x11, "control": 0x11, "shift": 0x10, "alt": 0x12, "win": 0x5B, "windows": 0x5B,
    "enter": 0x0D, "return": 0x0D, "esc": 0x1B, "escape": 0x1B, "tab": 0x09, "space": 0x20,
    "backspace": 0x08, "delete": 0x2E, "del": 0x2E, "insert": 0x2D, "home": 0x24, "end": 0x23,
    "pageup": 0x21, "pagedown": 0x22, "up": 0x26, "down": 0x28, "left": 0x25, "right": 0x27,
    "capslock": 0x14, "printscreen": 0x2C, "prtsc": 0x2C,
    "volumeup": 0xAF, "volumedown": 0xAE, "volumemute": 0xAD,
    "playpause": 0xB3, "nexttrack": 0xB0, "prevtrack": 0xB1, "stop": 0xB2,
    "hangul": 0x15, "hanja": 0x19,
    "plus": 0xBB, "minus": 0xBD, "comma": 0xBC, "period": 0xBE, "menu": 0x5D, "apps": 0x5D, "pause": 0x13,
    "browserback": 0xA6, "browserforward": 0xA7, "browserrefresh": 0xA8,
    **{f"f{i}": 0x6F + i for i in range(1, 25)},
}
EXTENDED = {0x2E, 0x2D, 0x24, 0x23, 0x21, 0x22, 0x26, 0x28, 0x25, 0x27, 0x5B, 0x5D,
            0xAF, 0xAE, 0xAD, 0xB3, 0xB0, 0xB1, 0xB2, 0xA6, 0xA7, 0xA8}


def _vk(name: str) -> int:
    name = name.strip().lower()
    if name in VK:
        return VK[name]
    if len(name) == 1:
        return user32.VkKeyScanW(ord(name)) & 0xFF
    raise ValueError(f"알 수 없는 키: {name}")


def _key(vk: int, up: bool) -> None:
    flags = (KEYEVENTF_KEYUP if up else 0) | (KEYEVENTF_EXTENDEDKEY if vk in EXTENDED else 0)
    user32.keybd_event(vk, 0, flags, 0)


def tap(vk: int, times: int = 1) -> None:
    for _ in range(times):
        _key(vk, False)
        _key(vk, True)
        time.sleep(0.01)


def press_combo(combo: str) -> None:
    """'ctrl+shift+esc', 'alt+tab', 'win+d', 'enter' 형식의 단축키 입력."""
    combo = combo.replace(" ", "")
    if combo.endswith("++") or combo == "+":       # 'ctrl++' 의 마지막 + 는 키 이름이다 (나누는 기호가 아니라)
        combo = combo[:-1] + "plus"
    keys = [_vk(k) for k in combo.split("+") if k]
    if not keys:
        raise ValueError("누를 키가 없습니다")
    for vk in keys:
        _key(vk, False)
        time.sleep(0.02)
    for vk in reversed(keys):
        _key(vk, True)
        time.sleep(0.02)


@contextlib.contextmanager
def held(keys: str):
    """'ctrl' · 'shift' · 'ctrl+shift' 를 누른 채로 안의 동작을 한다 (여러 개 고르기 · 범위 고르기 클릭)."""
    vks = [_vk(k) for k in (keys or "").replace(" ", "").split("+") if k]
    for vk in vks:
        _key(vk, False)
    try:
        if vks:
            time.sleep(0.03)
        yield
    finally:
        for vk in reversed(vks):
            _key(vk, True)


# ---------------- 포커스 추적 ----------------
class FocusTracker:
    """HUD 를 클릭/입력해도 키 입력이 사용자의 '작업 창'으로 가도록 마지막 외부 창을 기억."""

    def __init__(self) -> None:
        self.own_hwnds: set[int] = set()
        self.last_external: int = 0
        self.last_title: str = ""
        self._stop = threading.Event()
        threading.Thread(target=self._loop, daemon=True, name="focus-tracker").start()

    def _loop(self) -> None:
        own_pid = os.getpid()
        while not self._stop.wait(0.4):
            try:
                hwnd = user32.GetForegroundWindow()
                if not hwnd:
                    continue
                pid = wt.DWORD()
                user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                if pid.value == own_pid:
                    continue
                title = window_title(hwnd)
                if title:
                    self.last_external = hwnd
                    self.last_title = title
            except Exception:
                pass

    def restore(self) -> None:
        """사용자의 작업 창에 포커스를 돌려준다(현재 포커스가 HUD 일 때만)."""
        fg = user32.GetForegroundWindow()
        pid = wt.DWORD()
        user32.GetWindowThreadProcessId(fg, ctypes.byref(pid))
        if pid.value == os.getpid() and self.last_external and user32.IsWindow(self.last_external):
            force_foreground(self.last_external)
            time.sleep(0.15)

    def stop(self) -> None:
        self._stop.set()


def window_title(hwnd: int) -> str:
    n = user32.GetWindowTextLengthW(hwnd)
    buf = ctypes.create_unicode_buffer(n + 1)
    user32.GetWindowTextW(hwnd, buf, n + 1)
    return buf.value


def force_foreground(hwnd: int) -> bool:
    """SetForegroundWindow 제약을 우회(ALT 키 트릭)."""
    try:
        if user32.IsIconic(hwnd):
            user32.ShowWindow(hwnd, 9)  # SW_RESTORE
        _key(0x12, False)
        _key(0x12, True)
        ok = bool(user32.SetForegroundWindow(hwnd))
        return ok
    except Exception:
        return False


def list_windows() -> list[dict]:
    """보이는 최상위 창 목록 [{hwnd, title, exe}]."""
    result: list[dict] = []
    if not win32gui:
        return result
    own = os.getpid()

    def cb(hwnd, _):
        if not win32gui.IsWindowVisible(hwnd):
            return True
        title = win32gui.GetWindowText(hwnd)
        if not title or title in ("Program Manager", "Windows 입력 환경", "Windows Input Experience"):
            return True
        # 도구창/소유 창 제외
        if win32gui.GetWindow(hwnd, win32con.GW_OWNER):
            return True
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        if pid == own:
            return True
        try:
            exe = psutil.Process(pid).name()
        except Exception:
            exe = ""
        result.append({"hwnd": hwnd, "title": title, "exe": exe, "pid": pid})
        return True

    win32gui.EnumWindows(cb, None)
    return result


def close_window(hwnd: int) -> None:
    user32.PostMessageW(hwnd, 0x0010, 0, 0)  # WM_CLOSE (정상 종료: 저장 여부를 앱이 물어봄)


# ---------------- 클립보드 ----------------
def get_clipboard_text() -> str:
    if not win32clipboard:
        return ""
    for _ in range(5):
        try:
            win32clipboard.OpenClipboard()
            try:
                if win32clipboard.IsClipboardFormatAvailable(win32con.CF_UNICODETEXT):
                    return win32clipboard.GetClipboardData(win32con.CF_UNICODETEXT) or ""
                return ""
            finally:
                win32clipboard.CloseClipboard()
        except Exception:
            time.sleep(0.05)
    return ""


def set_clipboard_text(text: str) -> None:
    if not win32clipboard:
        raise RuntimeError("pywin32 가 필요합니다")
    for _ in range(5):
        try:
            win32clipboard.OpenClipboard()
            try:
                win32clipboard.EmptyClipboard()
                win32clipboard.SetClipboardData(win32con.CF_UNICODETEXT, text)
                return
            finally:
                win32clipboard.CloseClipboard()
        except Exception:
            time.sleep(0.05)
    raise RuntimeError("클립보드를 열 수 없습니다")


# ---------------- 알려진 폴더 ----------------
def known_folder(name: str) -> Path | None:
    name = name.strip().lower().replace(" ", "")
    mapping = {
        "바탕화면": "Desktop", "desktop": "Desktop",
        "문서": "Personal", "내문서": "Personal", "documents": "Personal",
        "다운로드": "{374DE290-123F-4565-9164-39C4925E467B}", "downloads": "{374DE290-123F-4565-9164-39C4925E467B}",
        "사진": "My Pictures", "그림": "My Pictures", "pictures": "My Pictures",
        "음악": "My Music", "music": "My Music",
        "동영상": "My Video", "비디오": "My Video", "videos": "My Video",
    }
    key = mapping.get(name)
    if name in ("홈", "home", "사용자폴더"):
        return Path.home()
    if not key:
        return None
    # 레지스트리 User Shell Folders (OneDrive 리디렉션 반영)
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders") as k:
            val, _ = winreg.QueryValueEx(k, key)
            p = Path(os.path.expandvars(val))
            if p.exists():
                return p
    except Exception:
        pass
    fallback = {"Desktop": "Desktop", "Personal": "Documents", "My Pictures": "Pictures",
                "My Music": "Music", "My Video": "Videos"}.get(key, "Downloads")
    return Path.home() / fallback


def window_rect(hwnd: int) -> tuple[int, int, int, int] | None:
    """창이 화면에서 차지하는 영역 (왼, 위, 오, 아래). 최소화돼 있거나 알 수 없으면 None."""
    try:
        if not hwnd or not user32.IsWindow(hwnd) or user32.IsIconic(hwnd):
            return None
        r = wt.RECT()
        # DWMWA_EXTENDED_FRAME_BOUNDS(9): 눈에 보이는 테두리. GetWindowRect 는 보이지 않는 그림자(약 7px)까지 포함한다
        ok = False
        try:
            ok = ctypes.windll.dwmapi.DwmGetWindowAttribute(wt.HWND(hwnd), 9, ctypes.byref(r), ctypes.sizeof(r)) == 0
        except Exception:
            ok = False
        if not ok and not user32.GetWindowRect(wt.HWND(hwnd), ctypes.byref(r)):
            return None
        if r.right - r.left < 8 or r.bottom - r.top < 8:
            return None
        return (r.left, r.top, r.right, r.bottom)
    except Exception:
        return None


class _MONITORINFO(ctypes.Structure):
    _fields_ = [("cbSize", wt.DWORD), ("rcMonitor", wt.RECT), ("rcWork", wt.RECT), ("dwFlags", wt.DWORD)]


def monitor_rect(hwnd: int = 0) -> tuple[int, int, int, int] | None:
    """hwnd 창이 있는 모니터의 영역 (왼, 위, 오, 아래 — 가상 화면 좌표라 음수일 수 있다).
    hwnd 가 없으면 주 모니터. 알 수 없으면 None (→ 호출한 쪽은 주 모니터 전체를 찍는다)."""
    try:
        fn = user32.MonitorFromWindow
        fn.restype = ctypes.c_void_p            # 64비트 핸들이 잘리지 않게
        fn.argtypes = [wt.HWND, wt.DWORD]
        mon = fn(wt.HWND(hwnd or 0), 2 if hwnd else 1)   # 2 = 가장 가까운 모니터, 1 = 주 모니터
        if not mon:
            return None
        info = _MONITORINFO()
        info.cbSize = ctypes.sizeof(info)
        get = user32.GetMonitorInfoW
        get.argtypes = [ctypes.c_void_p, ctypes.POINTER(_MONITORINFO)]
        get.restype = wt.BOOL
        if not get(mon, ctypes.byref(info)):
            return None
        m = info.rcMonitor
        if m.right - m.left < 100 or m.bottom - m.top < 100:
            return None
        return (m.left, m.top, m.right, m.bottom)
    except Exception:
        return None


def blocks_clicks(hwnd: int, x: int, y: int) -> bool:
    """화면 좌표 (x, y) 를 누르면 클릭이 이 창으로 들어가는가 — 보이는 창이 그 자리를 덮고 있고, 입력을 통과시키는 창이 아닐 때."""
    try:
        if not hwnd or not user32.IsWindowVisible(wt.HWND(hwnd)):
            return False
        if int(user32.GetWindowLongW(wt.HWND(hwnd), -20)) & 0x20:      # GWL_EXSTYLE · WS_EX_TRANSPARENT (액티브 모드 화면)
            return False
        r = wt.RECT()
        if not user32.GetWindowRect(wt.HWND(hwnd), ctypes.byref(r)):
            return False
        return r.left <= int(x) < r.right and r.top <= int(y) < r.bottom
    except Exception:
        return False


def show_window(hwnd: int, show: bool) -> None:
    """창을 잠깐 숨기거나 다시 보인다 (포커스는 건드리지 않는다)."""
    try:
        user32.ShowWindow(wt.HWND(hwnd), 8 if show else 0)             # SW_SHOWNA / SW_HIDE
    except Exception:
        pass


def set_capture_excluded(hwnd: int, excluded: bool) -> None:
    """스크린샷 시 HUD 자신을 캡처에서 제외 (Win10 2004+)."""
    try:
        user32.SetWindowDisplayAffinity(hwnd, 0x11 if excluded else 0x0)
    except Exception:
        pass


def reduce_motion() -> bool:
    """Windows 설정 '애니메이션 효과' 가 꺼져 있으면 True (액티브 모드 HUD 가 회전 · 스캔 연출을 멈춤)."""
    try:
        on = wt.BOOL()
        if user32.SystemParametersInfoW(0x1042, 0, ctypes.byref(on), 0):   # SPI_GETCLIENTAREAANIMATION
            return not bool(on.value)
    except Exception:
        pass
    return False


def foreground() -> int:
    """지금 맨 앞에 있는 창."""
    try:
        return int(user32.GetForegroundWindow() or 0)
    except Exception:
        return 0


def broadcast_setting(name: str) -> None:
    """열려 있는 프로그램들에게 설정이 바뀌었다고 알린다 (WM_SETTINGCHANGE — 예: 'ImmersiveColorSet' = 색 · 다크 모드)."""
    try:
        user32.SendMessageTimeoutW(0xFFFF, 0x001A, 0, ctypes.c_wchar_p(name), 0x0002, 300, None)
    except Exception:
        pass


def clipboard_seq() -> int:
    """클립보드 내용이 바뀔 때마다 올라가는 번호 (복사가 실제로 일어났는지 볼 때 쓴다)."""
    try:
        return int(user32.GetClipboardSequenceNumber())
    except Exception:
        return 0


def work_rect(hwnd: int = 0) -> tuple[int, int, int, int] | None:
    """hwnd 창이 있는 모니터에서 작업 표시줄을 뺀 영역 (창을 놓을 수 있는 곳). 모르면 None."""
    try:
        fn = user32.MonitorFromWindow
        fn.restype = ctypes.c_void_p
        fn.argtypes = [wt.HWND, wt.DWORD]
        mon = fn(wt.HWND(hwnd or 0), 2 if hwnd else 1)
        if not mon:
            return None
        info = _MONITORINFO()
        info.cbSize = ctypes.sizeof(info)
        get = user32.GetMonitorInfoW
        get.argtypes = [ctypes.c_void_p, ctypes.POINTER(_MONITORINFO)]
        get.restype = wt.BOOL
        if not get(mon, ctypes.byref(info)):
            return None
        w = info.rcWork
        if w.right - w.left < 100 or w.bottom - w.top < 100:
            return None
        return (w.left, w.top, w.right, w.bottom)
    except Exception:
        return None


def tile(area: tuple[int, int, int, int], n: int, layout: str = "columns") -> list[tuple[int, int, int, int]]:
    """area 를 창 n개가 나눠 쓸 자리들로 (왼, 위, 오, 아래). columns = 옆으로 나란히, rows = 위아래, grid = 바둑판."""
    left, top, right, bottom = area
    w, h = right - left, bottom - top
    n = max(1, int(n))
    if layout == "rows":
        return [(left, top + h * i // n, right, top + h * (i + 1) // n) for i in range(n)]
    if layout == "grid" and n >= 3:
        cols = 2 if n <= 4 else 3
        rows = -(-n // cols)
        out = []
        for i in range(n):
            r, c = divmod(i, cols)
            last_row = r == rows - 1
            in_row = n - r * cols if last_row else cols        # 마지막 줄에 남는 칸은 그 줄 창들이 나눠 쓴다
            out.append((left + w * c // in_row, top + h * r // rows, left + w * (c + 1) // in_row, top + h * (r + 1) // rows))
        return out
    return [(left + w * i // n, top, left + w * (i + 1) // n, bottom) for i in range(n)]


def place_window(hwnd: int, rect: tuple[int, int, int, int]) -> bool:
    """창을 rect(눈에 보이는 테두리 기준) 자리에 놓는다. 최대화 · 최소화돼 있으면 먼저 푼다."""
    try:
        user32.ShowWindow(wt.HWND(hwnd), 9)                     # SW_RESTORE
        left, top, right, bottom = rect
        # 보이지 않는 그림자 테두리(약 7px)만큼 넓혀야 창끼리 틈 없이 붙는다
        outer, seen = wt.RECT(), window_rect(hwnd)
        if seen and user32.GetWindowRect(wt.HWND(hwnd), ctypes.byref(outer)):
            dl, dt_, dr, db = seen[0] - outer.left, seen[1] - outer.top, outer.right - seen[2], outer.bottom - seen[3]
            if all(0 <= d <= 20 for d in (dl, dt_, dr, db)):
                left, top, right, bottom = left - dl, top - dt_, right + dr, bottom + db
        return bool(user32.SetWindowPos(wt.HWND(hwnd), 0, int(left), int(top), int(right - left), int(bottom - top),
                                        0x0004 | 0x0040))     # SWP_NOZORDER | SWP_SHOWWINDOW
    except Exception:
        return False


def set_window_state(hwnd: int, state: str) -> bool:
    """maximize · minimize · restore — 단축키(win+↑)와 달리 창이 어디에 붙어 있든 뜻대로 된다."""
    code = {"maximize": 3, "minimize": 6, "restore": 9}.get(state)
    try:
        if not code or not hwnd or not user32.IsWindow(wt.HWND(hwnd)):
            return False
        user32.ShowWindow(wt.HWND(hwnd), code)
        return True
    except Exception:
        return False
