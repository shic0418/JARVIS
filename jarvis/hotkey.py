"""전역 단축키 (Win32 RegisterHotKey). 다른 창에 포커스가 있어도 동작한다."""
from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import logging
import threading
from typing import Callable

from .winutil import _vk

log = logging.getLogger("jarvis.hotkey")
user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32
MODS = {"alt": 0x1, "ctrl": 0x2, "control": 0x2, "shift": 0x4, "win": 0x8}
MOD_NOREPEAT = 0x4000
WM_HOTKEY = 0x0312
WM_QUIT = 0x0012


class GlobalHotkey:
    def __init__(self, combo: str, callback: Callable[[], None]) -> None:
        self.combo = combo
        self.callback = callback
        self._tid = 0
        self.ok = False

    def start(self) -> None:
        ready = threading.Event()
        threading.Thread(target=self._run, args=(ready,), daemon=True, name="hotkey").start()
        ready.wait(2)

    def _run(self, ready: threading.Event) -> None:
        self._tid = kernel32.GetCurrentThreadId()
        mods, vk = MOD_NOREPEAT, 0
        try:
            for part in self.combo.lower().replace(" ", "").split("+"):
                if part in MODS:
                    mods |= MODS[part]
                else:
                    vk = _vk(part)
        except ValueError as e:
            log.error("단축키 형식 오류: %s", e)
        self.ok = bool(vk) and bool(user32.RegisterHotKey(None, 1, mods, vk))
        if not self.ok:
            log.warning("단축키 등록 실패(다른 프로그램이 사용 중일 수 있음): %s", self.combo)
        ready.set()
        if not self.ok:
            return
        msg = wt.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            if msg.message == WM_HOTKEY:
                try:
                    self.callback()
                except Exception:
                    log.exception("단축키 콜백 오류")
        user32.UnregisterHotKey(None, 1)

    def stop(self) -> None:
        if self._tid:
            user32.PostThreadMessageW(self._tid, WM_QUIT, 0, 0)
