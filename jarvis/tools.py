"""자비스의 '손': PC 제어 도구 모음과 Claude 용 도구 스키마."""
from __future__ import annotations

import base64
import datetime as dt
import difflib
import io
import json
import logging
import os
import re
import subprocess
import threading
import time
import urllib.parse
import urllib.request
import webbrowser
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import psutil

from . import winutil
from .config import Config, load_memory, save_memory

log = logging.getLogger("jarvis.tools")
NO_WINDOW = 0x08000000


class ToolError(Exception):
    pass


@dataclass
class Hooks:
    confirm: Callable[[str, str], bool]          # (제목, 상세) -> 승인 여부 (블로킹)
    schedule_timer: Callable[[int, str], None]   # (초, 라벨)
    hud_hwnd: Callable[[], int]


# 한국어 별칭 → Start 메뉴 검색어 / 실행 파일
APP_ALIASES: dict[str, list[str]] = {
    "크롬": ["chrome", "google chrome"], "구글크롬": ["chrome"], "엣지": ["microsoft edge", "edge"],
    "웨일": ["naver whale", "whale"], "파이어폭스": ["firefox"],
    "메모장": ["메모장", "notepad"], "계산기": ["계산기", "calculator"], "그림판": ["그림판", "paint"],
    "탐색기": ["파일 탐색기", "file explorer"], "파일탐색기": ["파일 탐색기", "file explorer"],
    "설정": ["설정", "settings"], "작업관리자": ["작업 관리자", "task manager"],
    "워드": ["word"], "엑셀": ["excel"], "파워포인트": ["powerpoint"], "피피티": ["powerpoint"],
    "아웃룩": ["outlook"], "원노트": ["onenote"], "팀즈": ["teams"],
    "브이에스코드": ["visual studio code"], "vscode": ["visual studio code"], "비주얼스튜디오코드": ["visual studio code"],
    "카톡": ["카카오톡", "kakaotalk"], "카카오톡": ["카카오톡", "kakaotalk"],
    "디스코드": ["discord"], "디코": ["discord"], "스포티파이": ["spotify"], "멜론": ["melon"],
    "스팀": ["steam"], "줌": ["zoom"], "슬랙": ["slack"], "노션": ["notion"],
    "캡처도구": ["캡처 도구", "snipping tool"], "터미널": ["terminal", "터미널"],
    "명령프롬프트": ["명령 프롬프트", "command prompt"], "파워셸": ["windows powershell"], "파워쉘": ["windows powershell"],
    "제어판": ["제어판", "control panel"], "카메라": ["카메라", "camera"], "사진": ["사진", "photos"],
    "시계": ["시계", "clock"], "알람": ["시계", "clock"], "캘린더": ["calendar", "일정"],
}
EXE_ALIASES: dict[str, list[str]] = {
    "크롬": ["chrome.exe"], "엣지": ["msedge.exe"], "웨일": ["whale.exe"], "파이어폭스": ["firefox.exe"],
    "메모장": ["notepad.exe"], "계산기": ["calculatorapp.exe", "calc.exe"], "그림판": ["mspaint.exe"],
    "탐색기": ["explorer.exe"], "파일탐색기": ["explorer.exe"], "워드": ["winword.exe"], "엑셀": ["excel.exe"],
    "파워포인트": ["powerpnt.exe"], "피피티": ["powerpnt.exe"], "카톡": ["kakaotalk.exe"], "카카오톡": ["kakaotalk.exe"],
    "디스코드": ["discord.exe"], "디코": ["discord.exe"], "스포티파이": ["spotify.exe"], "vscode": ["code.exe"],
    "브이에스코드": ["code.exe"], "작업관리자": ["taskmgr.exe"], "설정": ["systemsettings.exe"], "멜론": ["melon.exe"],
    "스팀": ["steam.exe"], "줌": ["zoom.exe"], "슬랙": ["slack.exe"], "노션": ["notion.exe"], "팀즈": ["ms-teams.exe"],
}
SYSTEM_EXE = {"작업관리자": "taskmgr.exe", "명령프롬프트": "cmd.exe", "파워셸": "powershell.exe",
              "파워쉘": "powershell.exe", "제어판": "control.exe", "레지스트리": "regedit.exe",
              "설정": "ms-settings:", "메모장": "notepad.exe", "계산기": "calc.exe", "그림판": "mspaint.exe",
              "탐색기": "explorer.exe", "파일탐색기": "explorer.exe"}
RISKY_EXT = {".exe", ".bat", ".cmd", ".ps1", ".vbs", ".js", ".msi", ".reg", ".scr", ".com", ".lnk"}


def _norm(s: str) -> str:
    return re.sub(r"[\s\-_.()]+", "", s.lower())


class PCTools:
    def __init__(self, cfg: Config, focus: winutil.FocusTracker, hooks: Hooks) -> None:
        self.cfg = cfg
        self.focus = focus
        self.hooks = hooks
        self._apps: list[tuple[str, str]] = []
        threading.Thread(target=self._index_apps, daemon=True, name="app-index").start()

    # ------------------------------------------------------------------ 앱 인덱스
    def _index_apps(self) -> None:
        cmd = ("[Console]::OutputEncoding=[Text.Encoding]::UTF8; "
               "Get-StartApps | Select-Object Name,AppID | ConvertTo-Json -Compress")
        try:
            out = subprocess.run(["powershell", "-NoProfile", "-Command", cmd], capture_output=True,
                                 timeout=30, creationflags=NO_WINDOW).stdout.decode("utf-8", "replace")
            items = json.loads(out) if out.strip() else []
            if isinstance(items, dict):
                items = [items]
            self._apps = [(i["Name"], i["AppID"]) for i in items if i.get("Name") and i.get("AppID")]
            log.info("시작 메뉴 앱 %d개 인덱싱", len(self._apps))
        except Exception as e:
            log.warning("앱 인덱싱 실패: %s", e)

    def _find_app(self, query: str) -> tuple[str, str] | None:
        terms = [query] + APP_ALIASES.get(_norm(query), [])
        best, best_score = None, 0.0
        for name, appid in self._apps:
            nn = _norm(name)
            for t in terms:
                tn = _norm(t)
                if not tn:
                    continue
                if nn == tn:
                    s = 100.0
                elif nn.startswith(tn):
                    s = 85.0 - min(20, len(nn) - len(tn))
                elif tn in nn:
                    s = 70.0 - min(20, len(nn) - len(tn))
                elif nn in tn and len(nn) >= 3:
                    s = 55.0
                else:
                    s = difflib.SequenceMatcher(None, tn, nn).ratio() * 50
                if s > best_score:
                    best, best_score = (name, appid), s
        return best if best_score >= 38 else None

    # ------------------------------------------------------------------ 스키마
    def schemas(self) -> list[dict]:
        def tool(name, desc, props=None, required=None):
            return {"name": name, "description": desc,
                    "input_schema": {"type": "object", "properties": props or {},
                                     "required": required or []}}
        s = {"type": "string"}
        return [
            tool("open_app", "Launch an installed application by name (Korean or English, e.g. '메모장', '크롬', '카카오톡', 'Visual Studio Code'). Searches the Start menu.",
                 {"name": s}, ["name"]),
            tool("close_app", "Gracefully close windows of an application (sends WM_CLOSE so unsaved work prompts). Match by app name or window title.",
                 {"name": s}, ["name"]),
            tool("focus_app", "Bring an already-open window to the front by app name or window title.", {"name": s}, ["name"]),
            tool("list_windows", "List currently open windows (title and process). Use to see what is running."),
            tool("window_action", "Control the active window or desktop.",
                 {"action": {"type": "string", "enum": ["show_desktop", "maximize", "minimize", "snap_left", "snap_right",
                                                         "switch_next", "close_active", "task_view", "new_virtual_desktop"]}},
                 ["action"]),
            tool("open_url", "Open a URL in the default browser.", {"url": s}, ["url"]),
            tool("browser_search", "Open a search results page in the browser for the user to look at.",
                 {"query": s, "site": {"type": "string", "enum": ["google", "naver", "youtube", "maps"]}}, ["query"]),
            tool("play_youtube", "Find a video on YouTube and start playing the top result in the browser (music, videos).",
                 {"query": s}, ["query"]),
            tool("media_control", "Control the currently playing media (any player) using media keys.",
                 {"action": {"type": "string", "enum": ["play_pause", "next", "previous", "stop"]}}, ["action"]),
            tool("volume", "Get or change the system speaker volume.",
                 {"action": {"type": "string", "enum": ["get", "set", "up", "down", "mute", "unmute"]},
                  "level": {"type": "integer", "description": "0-100 for set; step size for up/down (default 10)"}},
                 ["action"]),
            tool("type_text", "Type text into the user's active window (works for Korean). Optionally press Enter after.",
                 {"text": s, "press_enter": {"type": "boolean"}}, ["text"]),
            tool("press_keys", "Press a keyboard shortcut in the user's active window, e.g. 'ctrl+s', 'alt+tab', 'win+shift+s', 'f5', 'enter'.",
                 {"keys": s, "times": {"type": "integer"}}, ["keys"]),
            tool("look_at_screen", "Capture the user's primary screen and look at it. Use when the user asks about what is on screen or you need to see it to help."),
            tool("save_screenshot", "Save a screenshot of the screen to the Pictures\\Jarvis folder."),
            tool("system_status", "Get CPU, memory, disk, battery, network and top processes."),
            tool("open_folder", "Open a folder in File Explorer. Accepts known names (바탕화면, 문서, 다운로드, 사진, 음악, 동영상, 홈) or an absolute path.",
                 {"target": s}, ["target"]),
            tool("find_files", "Search the user's Desktop/Documents/Downloads/Pictures/Music/Videos for files whose name contains the query.",
                 {"query": s, "folder": {"type": "string", "description": "optional known folder name or path to limit search"}}, ["query"]),
            tool("open_path", "Open a file or folder with its default program.", {"path": s}, ["path"]),
            tool("run_powershell", "Run a PowerShell command on the user's PC and return its output. Use for tasks no other tool covers. The user is asked to approve it first.",
                 {"command": s, "reason": {"type": "string", "description": "short Korean explanation shown to the user"}},
                 ["command", "reason"]),
            tool("power", "Lock, sleep, restart or shut down the PC (sleep/restart/shutdown ask the user first). cancel_shutdown aborts a pending shutdown.",
                 {"action": {"type": "string", "enum": ["lock", "sleep", "restart", "shutdown", "cancel_shutdown"]}}, ["action"]),
            tool("set_timer", "Set a timer/reminder. Jarvis will speak the label when it fires.",
                 {"seconds": {"type": "integer"}, "label": s}, ["seconds", "label"]),
            tool("get_weather", "Get current weather and today's forecast.", {"location": {"type": "string", "description": "city name; default is the user's home city"}}),
            tool("read_clipboard", "Read the text currently in the clipboard."),
            tool("write_clipboard", "Put text into the clipboard.", {"text": s}, ["text"]),
            tool("remember", "Save a fact about the user to long-term memory (e.g. preferences, names). Use when the user asks you to remember something.",
                 {"fact": s}, ["fact"]),
        ]

    # ------------------------------------------------------------------ 표시용 라벨
    @staticmethod
    def label(name: str, a: dict) -> str:
        m = {
            "open_app": lambda: f"앱 실행 · {a.get('name')}",
            "close_app": lambda: f"앱 종료 · {a.get('name')}",
            "focus_app": lambda: f"창 전환 · {a.get('name')}",
            "list_windows": lambda: "열린 창 확인",
            "window_action": lambda: f"창 제어 · {a.get('action')}",
            "open_url": lambda: f"링크 열기 · {a.get('url', '')[:40]}",
            "browser_search": lambda: f"{a.get('site', 'google')} 검색 · {a.get('query')}",
            "play_youtube": lambda: f"YouTube 재생 · {a.get('query')}",
            "media_control": lambda: f"미디어 · {a.get('action')}",
            "volume": lambda: f"볼륨 · {a.get('action')} {a.get('level', '')}".strip(),
            "type_text": lambda: f"입력 · {a.get('text', '')[:30]}",
            "press_keys": lambda: f"단축키 · {a.get('keys')}",
            "look_at_screen": lambda: "화면 분석",
            "save_screenshot": lambda: "스크린샷 저장",
            "system_status": lambda: "시스템 진단",
            "open_folder": lambda: f"폴더 열기 · {a.get('target')}",
            "find_files": lambda: f"파일 검색 · {a.get('query')}",
            "open_path": lambda: f"파일 열기 · {Path(str(a.get('path', ''))).name}",
            "run_powershell": lambda: f"PowerShell · {a.get('command', '')[:40]}",
            "power": lambda: f"전원 · {a.get('action')}",
            "set_timer": lambda: f"타이머 · {a.get('label')} ({a.get('seconds')}초)",
            "get_weather": lambda: f"날씨 · {a.get('location') or '현재 위치'}",
            "read_clipboard": lambda: "클립보드 읽기",
            "write_clipboard": lambda: "클립보드 쓰기",
            "remember": lambda: f"기억 저장 · {a.get('fact', '')[:30]}",
            "web_search": lambda: f"웹 검색 · {a.get('query', '')}",
        }
        try:
            return m[name]()
        except Exception:
            return name

    # ------------------------------------------------------------------ 실행
    def run(self, name: str, args: dict):
        fn = getattr(self, f"t_{name}", None)
        if not fn:
            raise ToolError(f"알 수 없는 도구: {name}")
        return fn(**(args or {}))

    def _confirm(self, title: str, detail: str) -> None:
        if self.cfg["auto_approve"]:
            return
        if not self.hooks.confirm(title, detail):
            raise ToolError("사용자가 실행을 거부했습니다.")

    # --- 앱/창 ---
    def t_open_app(self, name: str) -> str:
        key = _norm(name)
        hit = self._find_app(name)
        if hit:
            subprocess.Popen(["explorer.exe", f"shell:AppsFolder\\{hit[1]}"], creationflags=NO_WINDOW)
            return f"'{hit[0]}' 실행함"
        exe = SYSTEM_EXE.get(key)
        target = exe or name
        try:
            os.startfile(target)
            return f"'{target}' 실행함"
        except OSError:
            if not self._apps:
                raise ToolError("앱 목록을 아직 불러오는 중입니다. 잠시 후 다시 시도하세요.")
            raise ToolError(f"'{name}' 앱을 찾지 못했습니다.")

    def _match_windows(self, name: str) -> list[dict]:
        q = _norm(name)
        exes = [e.lower() for e in EXE_ALIASES.get(q, [])]
        wins = winutil.list_windows()
        hits = []
        for w in wins:
            exe = w["exe"].lower()
            if (exes and exe in exes) or (q and (q in _norm(w["title"]) or q == _norm(exe.removesuffix(".exe")))):
                hits.append(w)
        return hits

    def t_close_app(self, name: str) -> str:
        hits = self._match_windows(name)
        if not hits:
            raise ToolError(f"'{name}'에 해당하는 열린 창이 없습니다.")
        for w in hits[:8]:
            winutil.close_window(w["hwnd"])
        return f"{len(hits[:8])}개 창에 닫기 요청: " + ", ".join(w["title"][:30] for w in hits[:8])

    def t_focus_app(self, name: str) -> str:
        hits = self._match_windows(name)
        if not hits:
            raise ToolError(f"'{name}' 창이 열려 있지 않습니다.")
        winutil.force_foreground(hits[0]["hwnd"])
        self.focus.last_external = hits[0]["hwnd"]
        return f"'{hits[0]['title']}' 창으로 전환"

    def t_list_windows(self) -> str:
        wins = winutil.list_windows()
        if not wins:
            return "열린 창이 없습니다."
        return "\n".join(f"- {w['title'][:60]} ({w['exe']})" for w in wins[:30])

    def t_window_action(self, action: str) -> str:
        combos = {"show_desktop": "win+d", "maximize": "win+up", "minimize": "win+down",
                  "snap_left": "win+left", "snap_right": "win+right", "switch_next": "alt+tab",
                  "close_active": "alt+f4", "task_view": "win+tab", "new_virtual_desktop": "win+ctrl+d"}
        if action not in combos:
            raise ToolError("지원하지 않는 동작")
        if action != "show_desktop":
            self.focus.restore()
        winutil.press_combo(combos[action])
        return f"{action} 완료"

    # --- 웹 ---
    def t_open_url(self, url: str) -> str:
        if not re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*:", url):
            url = "https://" + url
        if not url.lower().startswith(("http://", "https://")):
            raise ToolError("http/https 주소만 열 수 있습니다.")
        webbrowser.open(url)
        return f"열기: {url}"

    def t_browser_search(self, query: str, site: str = "google") -> str:
        q = urllib.parse.quote(query)
        url = {"google": f"https://www.google.com/search?q={q}",
               "naver": f"https://search.naver.com/search.naver?query={q}",
               "youtube": f"https://www.youtube.com/results?search_query={q}",
               "maps": f"https://map.naver.com/p/search/{q}"}.get(site, f"https://www.google.com/search?q={q}")
        webbrowser.open(url)
        return f"{site}에서 '{query}' 검색 결과를 열었습니다."

    def t_play_youtube(self, query: str) -> str:
        url = "https://www.youtube.com/results?search_query=" + urllib.parse.quote(query)
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0", "Accept-Language": "ko-KR,ko"})
            html = urllib.request.urlopen(req, timeout=8).read().decode("utf-8", "replace")
            m = re.search(r'"videoRenderer":\{"videoId":"([\w-]{11})".*?"title":\{"runs":\[\{"text":"(.*?)"', html)
            if m:
                vid, title = m.group(1), m.group(2)
                webbrowser.open(f"https://www.youtube.com/watch?v={vid}")
                return f"재생: {title}"
            m = re.search(r'"videoId":"([\w-]{11})"', html)
            if m:
                webbrowser.open(f"https://www.youtube.com/watch?v={m.group(1)}")
                return "검색 결과 첫 영상 재생"
        except Exception as e:
            log.warning("YouTube 검색 실패: %s", e)
        webbrowser.open(url)
        return "검색 결과 페이지를 열었습니다."

    # --- 미디어/볼륨 ---
    def t_media_control(self, action: str) -> str:
        vk = {"play_pause": 0xB3, "next": 0xB0, "previous": 0xB1, "stop": 0xB2}.get(action)
        if not vk:
            raise ToolError("지원하지 않는 동작")
        winutil.tap(vk)
        return f"{action} 완료"

    def _endpoint(self):
        import comtypes
        comtypes.CoInitialize()
        from pycaw.pycaw import AudioUtilities
        dev = AudioUtilities.GetSpeakers()
        vol = getattr(dev, "EndpointVolume", None)
        if vol is None:  # 구버전 pycaw
            from ctypes import POINTER, cast
            from comtypes import CLSCTX_ALL
            from pycaw.pycaw import IAudioEndpointVolume
            iface = dev.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
            vol = cast(iface, POINTER(IAudioEndpointVolume))
        return vol

    def t_volume(self, action: str, level: int | None = None) -> str:
        try:
            vol = self._endpoint()
            cur = round(vol.GetMasterVolumeLevelScalar() * 100)
            if action == "get":
                muted = bool(vol.GetMute())
                return f"현재 볼륨 {cur}%" + (" (음소거)" if muted else "")
            if action == "mute":
                vol.SetMute(1, None); return "음소거"
            if action == "unmute":
                vol.SetMute(0, None); return "음소거 해제"
            step = int(level or 10)
            new = {"set": int(level if level is not None else cur), "up": cur + step, "down": cur - step}[action]
            new = max(0, min(100, new))
            vol.SetMute(0, None)
            vol.SetMasterVolumeLevelScalar(new / 100.0, None)
            return f"볼륨 {cur}% → {new}%"
        except ToolError:
            raise
        except Exception as e:  # pycaw 실패 시 볼륨 키로 대체
            log.warning("pycaw 실패, 키 입력으로 대체: %s", e)
            if action == "mute" or action == "unmute":
                winutil.tap(0xAD); return "음소거 전환"
            if action == "set" and level is not None:
                winutil.tap(0xAE, 50); winutil.tap(0xAF, int(level) // 2); return f"볼륨 약 {level}%"
            n = max(1, int(level or 10) // 2)
            winutil.tap(0xAF if action == "up" else 0xAE, n)
            return f"볼륨 {'증가' if action == 'up' else '감소'}"

    # --- 키보드 ---
    def t_type_text(self, text: str, press_enter: bool = False) -> str:
        self.focus.restore()
        old = winutil.get_clipboard_text()
        winutil.set_clipboard_text(text)
        time.sleep(0.05)
        winutil.press_combo("ctrl+v")
        if press_enter:
            time.sleep(0.1)
            winutil.press_combo("enter")
        time.sleep(0.3)
        try:
            winutil.set_clipboard_text(old)
        except Exception:
            pass
        return f"{len(text)}자 입력함 (대상 창: {self.focus.last_title[:40]})"

    def t_press_keys(self, keys: str, times: int = 1) -> str:
        self.focus.restore()
        times = max(1, min(int(times or 1), 50))
        try:
            for _ in range(times):
                winutil.press_combo(keys)
                time.sleep(0.05)
        except ValueError as e:
            raise ToolError(str(e))
        return f"'{keys}' x{times} 입력함"

    # --- 화면 ---
    def _grab(self):
        from PIL import ImageGrab
        hwnd = self.hooks.hud_hwnd()
        winutil.set_capture_excluded(hwnd, True)
        try:
            time.sleep(0.05)
            return ImageGrab.grab()
        finally:
            winutil.set_capture_excluded(hwnd, False)

    def t_look_at_screen(self):
        img = self._grab().convert("RGB")
        img.thumbnail((1568, 1568))
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=72)
        data = base64.standard_b64encode(buf.getvalue()).decode()
        return [
            {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": data}},
            {"type": "text", "text": f"사용자 화면 캡처 ({img.width}x{img.height}). 활성 창: {self.focus.last_title}"},
        ]

    def t_save_screenshot(self) -> str:
        pics = winutil.known_folder("사진") or Path.home() / "Pictures"
        folder = pics / "Jarvis"
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"screenshot_{dt.datetime.now():%Y%m%d_%H%M%S}.png"
        self._grab().save(path)
        return f"저장됨: {path}"

    # --- 시스템 ---
    def t_system_status(self) -> str:
        cpu = psutil.cpu_percent(interval=0.4)
        vm = psutil.virtual_memory()
        disk = psutil.disk_usage(os.environ.get("SystemDrive", "C:") + "\\")
        lines = [f"CPU {cpu:.0f}% ({psutil.cpu_count()}코어)",
                 f"메모리 {vm.percent:.0f}% ({vm.used / 2**30:.1f}/{vm.total / 2**30:.1f} GB)",
                 f"디스크 {disk.percent:.0f}% (여유 {disk.free / 2**30:.0f} GB)"]
        bat = psutil.sensors_battery()
        if bat:
            lines.append(f"배터리 {bat.percent:.0f}% {'충전 중' if bat.power_plugged else '배터리 사용'}")
        up = dt.timedelta(seconds=int(time.time() - psutil.boot_time()))
        lines.append(f"가동 시간 {up}")
        procs = []
        for p in psutil.process_iter(["name", "memory_info"]):
            try:
                procs.append((p.info["memory_info"].rss, p.info["name"]))
            except Exception:
                pass
        procs.sort(reverse=True)
        lines.append("메모리 상위: " + ", ".join(f"{n} {m / 2**20:.0f}MB" for m, n in procs[:5]))
        return "\n".join(lines)

    # --- 파일 ---
    def _resolve_folder(self, target: str) -> Path:
        kf = winutil.known_folder(target)
        if kf:
            return kf
        p = Path(os.path.expandvars(os.path.expanduser(target)))
        if p.exists():
            return p
        raise ToolError(f"폴더를 찾을 수 없습니다: {target}")

    def t_open_folder(self, target: str) -> str:
        p = self._resolve_folder(target)
        os.startfile(str(p))
        return f"열기: {p}"

    def t_find_files(self, query: str, folder: str | None = None) -> str:
        roots = [self._resolve_folder(folder)] if folder else [
            winutil.known_folder(n) for n in ("바탕화면", "문서", "다운로드", "사진", "음악", "동영상")]
        q = query.lower().strip("* ")
        skip = {"node_modules", ".git", "appdata", "$recycle.bin", "__pycache__", ".venv", "venv"}
        results: list[str] = []
        deadline = time.monotonic() + 5
        for root in filter(None, roots):
            stack = [Path(root)]
            while stack and len(results) < 25 and time.monotonic() < deadline:
                d = stack.pop()
                try:
                    with os.scandir(d) as it:
                        for e in it:
                            if e.name.lower() in skip or e.name.startswith("."):
                                continue
                            if q in e.name.lower():
                                results.append(e.path)
                            if e.is_dir(follow_symlinks=False):
                                stack.append(Path(e.path))
                except OSError:
                    continue
        if not results:
            return f"'{query}' 이름의 파일을 찾지 못했습니다."
        return "\n".join(results[:25])

    def t_open_path(self, path: str) -> str:
        p = Path(os.path.expandvars(os.path.expanduser(path)))
        if not p.exists():
            raise ToolError(f"경로가 없습니다: {p}")
        if p.suffix.lower() in RISKY_EXT:
            self._confirm("프로그램 실행", str(p))
        os.startfile(str(p))
        return f"열기: {p}"

    # --- 명령/전원 ---
    def t_run_powershell(self, command: str, reason: str = "") -> str:
        self._confirm("PowerShell 실행", f"{reason}\n\n{command}" if reason else command)
        full = "[Console]::OutputEncoding=[Text.Encoding]::UTF8; $ProgressPreference='SilentlyContinue'; " + command
        try:
            r = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", full],
                               capture_output=True, timeout=90, creationflags=NO_WINDOW)
        except subprocess.TimeoutExpired:
            raise ToolError("90초 시간 초과")
        out = r.stdout.decode("utf-8", "replace").strip()
        err = r.stderr.decode("utf-8", "replace").strip()
        text = (out or "(출력 없음)")[:6000]
        if r.returncode != 0 or err:
            text += f"\n[종료 코드 {r.returncode}] {err[:2000]}"
        return text

    def t_power(self, action: str) -> str:
        if action == "lock":
            winutil.user32.LockWorkStation()
            return "PC를 잠갔습니다."
        if action == "cancel_shutdown":
            subprocess.run(["shutdown", "/a"], creationflags=NO_WINDOW)
            return "예약된 종료를 취소했습니다."
        names = {"sleep": "절전 모드", "restart": "다시 시작", "shutdown": "시스템 종료"}
        if action not in names:
            raise ToolError("지원하지 않는 동작")
        self._confirm(names[action], f"PC를 {names[action]}합니다. 저장하지 않은 작업이 있는지 확인하세요.")
        if action == "sleep":
            subprocess.Popen(["rundll32.exe", "powrprof.dll,SetSuspendState", "0,1,0"], creationflags=NO_WINDOW)
            return "절전 모드로 전환합니다."
        flag = "/r" if action == "restart" else "/s"
        subprocess.run(["shutdown", flag, "/t", "15"], creationflags=NO_WINDOW)
        return f"15초 후 {names[action]}합니다. 취소하려면 '종료 취소'라고 말하세요."

    # --- 기타 ---
    def t_set_timer(self, seconds: int, label: str) -> str:
        seconds = int(seconds)
        if seconds <= 0 or seconds > 86400:
            raise ToolError("1초 ~ 24시간 사이로 설정하세요.")
        self.hooks.schedule_timer(seconds, label)
        at = dt.datetime.now() + dt.timedelta(seconds=seconds)
        return f"타이머 설정: {label} — {at:%H:%M:%S}에 알림"

    def t_get_weather(self, location: str | None = None) -> str:
        loc = location or self.cfg["home_city"] or "Seoul"
        url = f"https://wttr.in/{urllib.parse.quote(loc)}?format=j1&lang=ko"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "curl/8"})
            data = json.loads(urllib.request.urlopen(req, timeout=10).read().decode("utf-8"))
        except Exception as e:
            raise ToolError(f"날씨 정보를 가져오지 못했습니다: {e}")
        cur = data["current_condition"][0]
        desc = (cur.get("lang_ko") or cur.get("weatherDesc") or [{"value": ""}])[0]["value"]
        today = data["weather"][0]
        rain = max(int(h.get("chanceofrain", 0)) for h in today.get("hourly", [{"chanceofrain": 0}]))
        return (f"{loc}: {desc}, 기온 {cur['temp_C']}°C (체감 {cur['FeelsLikeC']}°C), 습도 {cur['humidity']}%, "
                f"바람 {cur['windspeedKmph']}km/h. 오늘 최고 {today['maxtempC']}°C / 최저 {today['mintempC']}°C, 강수확률 최대 {rain}%")

    def t_read_clipboard(self) -> str:
        t = winutil.get_clipboard_text()
        return t[:8000] if t else "(클립보드에 텍스트가 없습니다)"

    def t_write_clipboard(self, text: str) -> str:
        winutil.set_clipboard_text(text)
        return "클립보드에 복사함"

    def t_remember(self, fact: str) -> str:
        mem = load_memory()
        mem.append(f"{fact} (기록: {dt.date.today():%Y-%m-%d})")
        save_memory(mem)
        return "기억했습니다."
