"""액티브 모드(전체 화면 HUD)에 띄우는 실시간 정보.

- ProcWatch: PC 를 느리게 하는 프로그램 상위 목록 (같은 이름의 프로세스는 묶어서)
- foreground_window: 지금 쓰고 있는 창의 위치 · 제목 · 프로그램
- parse_kill_index: "1번 꺼줘" 같은 말에서 번호 뽑기
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import os
import re
import struct
import threading
import time

import psutil

# 목록에서 빼고, 종료도 하지 않는 Windows 핵심 프로세스
PROTECTED = {
    "system idle process", "system", "registry", "memory compression", "memcompression", "secure system", "smss.exe",
    "csrss.exe", "wininit.exe", "services.exe", "lsass.exe", "lsaiso.exe", "winlogon.exe", "svchost.exe",
    "dwm.exe", "fontdrvhost.exe", "msmpeng.exe", "nissrv.exe", "securityhealthservice.exe", "sihost.exe",
    "ctfmon.exe", "explorer.exe", "taskhostw.exe", "audiodg.exe", "spoolsv.exe", "wudfhost.exe",
    "searchindexer.exe", "startmenuexperiencehost.exe", "shellexperiencehost.exe", "textinputhost.exe",
}

# 실행 파일 → 한국어로 부르는 이름 (HUD 표시용)
FRIENDLY = {
    "chrome.exe": "크롬", "msedge.exe": "엣지", "whale.exe": "웨일", "firefox.exe": "파이어폭스",
    "kakaotalk.exe": "카카오톡", "discord.exe": "디스코드", "spotify.exe": "스포티파이", "code.exe": "VS Code",
    "notepad.exe": "메모장", "winword.exe": "워드", "excel.exe": "엑셀", "powerpnt.exe": "파워포인트",
    "steam.exe": "스팀", "zoom.exe": "줌", "slack.exe": "슬랙", "notion.exe": "노션", "ms-teams.exe": "팀즈",
    "claude.exe": "클로드", "photoshop.exe": "포토샵", "blender.exe": "블렌더", "obs64.exe": "OBS",
    "hwp.exe": "한글", "inkscape.exe": "잉크스케이프", "melon.exe": "멜론", "taskmgr.exe": "작업 관리자",
    "python.exe": "파이썬", "pythonw.exe": "파이썬", "node.exe": "Node.js", "javaw.exe": "자바",
    "ollama.exe": "올라마", "ollama app.exe": "올라마",
}

_NUM = {"1": 1, "2": 2, "3": 3, "4": 4, "5": 5, "일": 1, "이": 2, "삼": 3, "사": 4, "오": 5,
        "하나": 1, "한": 1, "첫": 1, "둘": 2, "두": 2, "셋": 3, "세": 3, "넷": 4, "네": 4, "다섯": 5}
KILL_RE = re.compile(r"(1|2|3|4|5|일|이|삼|사|오|하나|한|첫|둘|두|셋|세|넷|네|다섯)\s*(?:번째|번)\s*"
                     r"(?:프로그램|프로세스|거|것|꺼|앱)?\s*(?:을|를)?\s*"
                     r"(?:꺼|끄기|종료|종료해|닫아|죽여|정리|정리해|강제\s*종료|강제\s*종료해)")


def parse_kill_index(c: str) -> int | None:
    """'1번 꺼', '첫 번째 거 종료', '이번 프로그램 닫아' → 1~5 (정규화된 문장 기준)."""
    m = KILL_RE.fullmatch(c.strip())
    return _NUM[m.group(1)] if m else None


def display_name(exe: str) -> str:
    e = exe.lower()
    return FRIENDLY.get(e) or re.sub(r"\.exe$", "", exe, flags=re.I)


def own_pids() -> set[int]:
    """자비스 자신과 자신을 띄운 부모들 (목록 · 종료에서 제외)."""
    out = {os.getpid()}
    try:
        p = psutil.Process()
        for a in p.parents():
            out.add(a.pid)
    except Exception:
        pass
    return out


_ntdll = ctypes.windll.ntdll


def _snapshot_nt() -> list[tuple[int, str, float, int]]:
    """모든 프로세스를 시스템 호출 한 번으로: (pid, 실행 파일 이름, 누적 CPU 초, 전용 작업 집합 바이트).

    psutil 로 프로세스마다 열어 보면 300개에 0.8초 걸리지만, 이 방법은 몇 ms 면 된다.
    메모리는 작업 관리자의 '메모리' 열과 같은 값(전용 작업 집합)."""
    size = 1 << 20
    while True:
        buf = ctypes.create_string_buffer(size)
        ret = wt.ULONG()
        st = _ntdll.NtQuerySystemInformation(5, buf, size, ctypes.byref(ret)) & 0xFFFFFFFF
        if st == 0xC0000004:   # 버퍼가 작음
            size = max(size * 2, ret.value + 65536)
            continue
        if st != 0:
            raise OSError(f"NtQuerySystemInformation 0x{st:08X}")
        break
    base = ctypes.addressof(buf)
    out, off = [], 0
    while True:
        nxt, = struct.unpack_from("<I", buf, off)
        private, = struct.unpack_from("<q", buf, off + 8)
        user, kernel = struct.unpack_from("<qq", buf, off + 40)
        nlen, = struct.unpack_from("<H", buf, off + 56)
        nptr, = struct.unpack_from("<Q", buf, off + 64)
        pid, = struct.unpack_from("<Q", buf, off + 80)
        name = ctypes.wstring_at(nptr, nlen // 2) if nptr and base <= nptr < base + size else ""
        out.append((int(pid), name or ("System Idle Process" if pid == 0 else ""), (user + kernel) / 1e7, int(private)))
        if not nxt:
            break
        off += nxt
    return out


def all_processes() -> list[tuple[int, str, float, int]]:
    if ctypes.sizeof(ctypes.c_void_p) == 8:
        try:
            return _snapshot_nt()
        except Exception:
            pass
    rows = []   # 예비: psutil (느림)
    for p in psutil.process_iter(["name", "cpu_times", "memory_info"]):
        ct, mi = p.info.get("cpu_times"), p.info.get("memory_info")
        if ct is not None and mi is not None:
            rows.append((p.pid, p.info.get("name") or "", ct.user + ct.system, mi.rss))
    return rows


class ProcWatch:
    """같은 이름의 프로세스를 묶어 CPU · 메모리 사용량 상위 목록을 만든다."""

    def __init__(self) -> None:
        self._last: dict[int, float] = {}   # pid → 지난번 누적 CPU 시간(초)
        self._last_t = 0.0
        self.exclude = own_pids()
        self.ncpu = psutil.cpu_count() or 1
        self.total_mem = psutil.virtual_memory().total
        self.pid_stats: dict[int, tuple[float, float]] = {}   # pid → (CPU %, 메모리 MB) 마지막 측정값
        self._lock = threading.Lock()

    def sample(self, top: int = 5) -> list[dict]:
        """CPU 는 지난번 측정 이후 쓴 CPU 시간으로 계산한다 (처음 본 프로세스는 이번엔 0)."""
        now = time.monotonic()
        dt = max(1e-3, now - self._last_t) if self._last_t else 0.0
        cur: dict[int, float] = {}
        groups: dict[str, dict] = {}
        stats: dict[int, tuple[float, float]] = {}
        for pid, name, used, mem in all_processes():
            if not name or pid in self.exclude or name.lower() in PROTECTED:
                continue
            cur[pid] = used
            prev = self._last.get(pid)
            cpu = max(0.0, (used - prev) / dt * 100 / self.ncpu) if (dt and prev is not None) else 0.0
            stats[pid] = (cpu, mem / 1048576)
            g = groups.setdefault(name.lower(), {"exe": name, "count": 0, "cpu": 0.0, "mem": 0})
            g["count"] += 1
            g["cpu"] += cpu
            g["mem"] += mem
        self._last, self._last_t = cur, now
        with self._lock:
            self.pid_stats = stats
        rows = []
        for g in groups.values():
            mem_pct = g["mem"] / self.total_mem * 100
            rows.append({"exe": g["exe"], "name": display_name(g["exe"]), "count": g["count"],
                         "cpu": round(g["cpu"], 1), "mem": round(g["mem"] / 1048576),
                         "score": g["cpu"] + mem_pct})
        rows.sort(key=lambda r: r["score"], reverse=True)
        for r in rows:
            del r["score"]
        return rows[:top]

    def stats_of(self, pid: int) -> tuple[float, float] | None:
        with self._lock:
            return self.pid_stats.get(pid)


# ---------------------------------------------------------------- 지금 쓰고 있는 창
_user32 = ctypes.windll.user32
_dwm = ctypes.windll.dwmapi
_SKIP_CLASSES = {"Progman", "WorkerW", "Shell_TrayWnd", "Shell_SecondaryTrayWnd", "NotifyIconOverflowWindow",
                 "Windows.UI.Core.CoreWindow", "XamlExplorerHostIslandWindow", "TopLevelWindowForOverflowXamlIsland"}


def _class_name(hwnd: int) -> str:
    buf = ctypes.create_unicode_buffer(256)
    _user32.GetClassNameW(hwnd, buf, 256)
    return buf.value


def foreground_window(own_hwnds: set[int] | None = None) -> dict | None:
    """지금 앞에 있는 창 → {hwnd, pid, exe, title, x, y, w, h} (실제 화면 픽셀). 바탕화면 · 작업 표시줄 · 자비스 창이면 None."""
    hwnd = _user32.GetForegroundWindow()
    if not hwnd or (own_hwnds and hwnd in own_hwnds) or _user32.IsIconic(hwnd):
        return None
    if _class_name(hwnd) in _SKIP_CLASSES:
        return None
    pid = wt.DWORD()
    _user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    if pid.value == os.getpid():
        return None
    r = wt.RECT()
    # 그림자를 뺀 실제 창 테두리 (DWMWA_EXTENDED_FRAME_BOUNDS)
    if _dwm.DwmGetWindowAttribute(hwnd, 9, ctypes.byref(r), ctypes.sizeof(r)) != 0:
        _user32.GetWindowRect(hwnd, ctypes.byref(r))
    w, h = r.right - r.left, r.bottom - r.top
    if w < 40 or h < 30:
        return None
    n = _user32.GetWindowTextLengthW(hwnd)
    buf = ctypes.create_unicode_buffer(n + 1)
    _user32.GetWindowTextW(hwnd, buf, n + 1)
    try:
        exe = psutil.Process(pid.value).name()
    except psutil.Error:
        exe = ""
    return {"hwnd": int(hwnd), "pid": pid.value, "exe": exe, "title": buf.value,
            "x": r.left, "y": r.top, "w": w, "h": h}
