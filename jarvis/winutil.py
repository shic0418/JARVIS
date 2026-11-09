"""Windows 저수준 유틸: 키 입력, 창 제어, 클립보드, 포커스, 알려진 폴더."""
from __future__ import annotations

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
    **{f"f{i}": 0x6F + i for i in range(1, 25)},
}
EXTENDED = {0x2E, 0x2D, 0x24, 0x23, 0x21, 0x22, 0x26, 0x28, 0x25, 0x27, 0x5B,
            0xAF, 0xAE, 0xAD, 0xB3, 0xB0, 0xB1, 0xB2}


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
    keys = [_vk(k) for k in combo.replace(" ", "").split("+") if k]
    for vk in keys:
        _key(vk, False)
        time.sleep(0.02)
    for vk in reversed(keys):
        _key(vk, True)
        time.sleep(0.02)


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


def set_capture_excluded(hwnd: int, excluded: bool) -> None:
    """스크린샷 시 HUD 자신을 캡처에서 제외 (Win10 2004+)."""
    try:
        user32.SetWindowDisplayAffinity(hwnd, 0x11 if excluded else 0x0)
    except Exception:
        pass
