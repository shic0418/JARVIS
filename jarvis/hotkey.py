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


# 원하는 조합을 다른 프로그램이 이미 쓰고 있을 때 차례로 시도할 대체 조합
FALLBACKS = ("ctrl+alt+shift+j", "ctrl+shift+space", "win+alt+j")


def parse_combo(combo: str) -> tuple[int, int]:
    """'ctrl+alt+j' → (수식키 비트, 가상 키 코드). 형식이 틀리면 ValueError."""
    mods, vk = MOD_NOREPEAT, 0
    for part in combo.lower().replace(" ", "").split("+"):
        if part in MODS:
            mods |= MODS[part]
        elif vk:
            raise ValueError(f"키가 두 개 이상입니다: {combo}")
        else:
            vk = _vk(part)
    if not vk:
        raise ValueError(f"수식키만 있고 키가 없습니다: {combo}")
    return mods, vk


class GlobalHotkey:
    """combo 등록에 실패하면 FALLBACKS 를 차례로 시도한다. 실제로 등록된 조합은 .active."""

    def __init__(self, combo: str, callback: Callable[[], None], fallback: bool = True) -> None:
        self.combo = combo
        self.callback = callback
        self.fallback = fallback
        self._tid = 0
        self.ok = False
        self.active = ""

    def start(self) -> None:
        ready = threading.Event()
        threading.Thread(target=self._run, args=(ready,), daemon=True, name="hotkey").start()
        ready.wait(2)

    def _run(self, ready: threading.Event) -> None:
        self._tid = kernel32.GetCurrentThreadId()
        tries = [self.combo] + ([c for c in FALLBACKS if c != self.combo.lower()] if self.fallback else [])
        for combo in tries:
            try:
                mods, vk = parse_combo(combo)
            except ValueError as e:
                log.error("단축키 형식 오류: %s", e)
                continue
            if user32.RegisterHotKey(None, 1, mods, vk):
                self.ok, self.active = True, combo
                break
            log.warning("단축키 등록 실패(다른 프로그램이 사용 중일 수 있음): %s", combo)
        if self.ok and self.active != self.combo:
            log.info("대체 단축키 사용: %s", self.active)
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
