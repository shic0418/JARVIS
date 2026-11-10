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

from . import uia, winutil
from .config import Config, load_memory, save_memory

log = logging.getLogger("jarvis.tools")
NO_WINDOW = 0x08000000


class ToolError(Exception):
    pass


@dataclass
class Hooks:
    confirm: Callable[[str, str], bool]          # (제목, 상세) -> 승인 여부 (블로킹)
    schedule_timer: Callable[[int, str], None]   # (초, 라벨)
    hud_hwnd: Callable[[], "int | list[int]"]   # 스크린샷에서 뺄 자비스 창 (하나 또는 여러 개)
    notify: Callable[[str], None] = lambda msg: None   # 백그라운드 작업이 사용자에게 말로 알림
    cancel_timers: Callable[[], int] = lambda: 0       # 돌고 있는 타이머 모두 취소 → 취소한 개수
    point_at: Callable[[int, int, int, int, str], bool] = lambda x, y, w, h, label: False  # 액티브 모드 화면에 위치 표시


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
    # 한국어로 부르는 영어 이름 앱 (기록: '클로드 열어', '잉크스페이스' 가 앱을 못 찾아 Claude 로 넘어감)
    "클로드": ["claude"], "챗지피티": ["chatgpt"], "지피티": ["chatgpt"],
    "잉크스케이프": ["inkscape"], "잉크스페이스": ["inkscape"], "inkspace": ["inkscape"],
    "알디웍스": ["rdworks"],
    "포토샵": ["photoshop"], "일러스트레이터": ["illustrator"], "일러스트": ["illustrator"],
    "프리미어": ["premiere pro"], "프리미어프로": ["premiere pro"], "애프터이펙트": ["after effects"],
    "블렌더": ["blender"], "오비에스": ["obs studio"], "obs": ["obs studio"],
    "한글": ["한글", "hwp"], "한컴": ["한글", "hwp"], "유니티": ["unity hub", "unity"],
    "마인크래프트": ["minecraft"], "로블록스": ["roblox"],
    "리그오브레전드": ["league of legends"], "배틀넷": ["battle.net"],
    "에픽게임즈": ["epic games launcher"], "오페라": ["opera"], "곰플레이어": ["gom player"],
    "팟플레이어": ["potplayer"], "반디집": ["bandizip"], "캡컷": ["capcut"], "피그마": ["figma"],
    "파이참": ["pycharm"], "비주얼스튜디오": ["visual studio"], "아크로뱃": ["acrobat"],
}
EXE_ALIASES: dict[str, list[str]] = {
    "크롬": ["chrome.exe"], "엣지": ["msedge.exe"], "웨일": ["whale.exe"], "파이어폭스": ["firefox.exe"],
    "메모장": ["notepad.exe"], "계산기": ["calculatorapp.exe", "calc.exe"], "그림판": ["mspaint.exe"],
    "탐색기": ["explorer.exe"], "파일탐색기": ["explorer.exe"], "워드": ["winword.exe"], "엑셀": ["excel.exe"],
    "파워포인트": ["powerpnt.exe"], "피피티": ["powerpnt.exe"], "카톡": ["kakaotalk.exe"], "카카오톡": ["kakaotalk.exe"],
    "디스코드": ["discord.exe"], "디코": ["discord.exe"], "스포티파이": ["spotify.exe"], "vscode": ["code.exe"],
    "브이에스코드": ["code.exe"], "작업관리자": ["taskmgr.exe"], "설정": ["systemsettings.exe"], "멜론": ["melon.exe"],
    "스팀": ["steam.exe"], "줌": ["zoom.exe"], "슬랙": ["slack.exe"], "노션": ["notion.exe"], "팀즈": ["ms-teams.exe"],
    "클로드": ["claude.exe"], "잉크스케이프": ["inkscape.exe"], "잉크스페이스": ["inkscape.exe"],
    "포토샵": ["photoshop.exe"], "블렌더": ["blender.exe"], "챗지피티": ["chatgpt.exe"],
}
SYSTEM_EXE = {"작업관리자": "taskmgr.exe", "명령프롬프트": "cmd.exe", "파워셸": "powershell.exe",
              "파워쉘": "powershell.exe", "제어판": "control.exe", "레지스트리": "regedit.exe",
              "설정": "ms-settings:", "메모장": "notepad.exe", "계산기": "calc.exe", "그림판": "mspaint.exe",
              "탐색기": "explorer.exe", "파일탐색기": "explorer.exe"}
RISKY_EXT = {".exe", ".bat", ".cmd", ".ps1", ".vbs", ".js", ".msi", ".reg", ".scr", ".com", ".lnk"}


# wttr.in 이 한국어 설명을 안 줄 때가 있다 (기록: 'Clear ') → 흔한 날씨만 우리말로
_WEATHER_KO = [("thunder", "뇌우"), ("heavy snow", "많은 눈"), ("blizzard", "눈보라"), ("sleet", "진눈깨비"),
               ("light snow", "약한 눈"), ("snow", "눈"), ("heavy rain", "강한 비"), ("torrential", "폭우"),
               ("drizzle", "이슬비"), ("light rain", "약한 비"), ("patchy rain", "가끔 비"), ("shower", "소나기"),
               ("rain", "비"), ("fog", "안개"), ("mist", "옅은 안개"), ("haze", "연무"), ("overcast", "흐림"),
               ("partly", "구름 조금"), ("cloudy", "흐림"), ("sunny", "맑음"), ("clear", "맑음")]


def _weather_ko(desc: str) -> str:
    d = (desc or "").strip()
    if re.search(r"[가-힣]", d):
        return d
    low = d.lower()
    for en, ko in _WEATHER_KO:
        if en in low:
            return ko
    return d


def _norm(s: str) -> str:
    return re.sub(r"[\s\-_.()]+", "", s.lower())


class PCTools:
    def __init__(self, cfg: Config, focus: winutil.FocusTracker, hooks: Hooks) -> None:
        self.cfg = cfg
        self.focus = focus
        self.hooks = hooks
        self._apps: list[tuple[str, str]] = []
        self.screen = uia.Screen()          # 화면 조작: 마지막으로 읽은 요소 목록
        self._shot_scale = 1.0              # look_at_screen 이미지 → 실제 화면 좌표 배율
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

    def _find_app(self, query: str, min_score: float = 38) -> tuple[str, str] | None:
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
        return best if best_score >= min_score else None

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
            tool("read_ui", "List clickable elements (buttons, links, tabs, menu items, input boxes) inside a window, numbered. "
                 "Works inside web pages in Chrome/Edge (e.g. Google Classroom tabs) and in normal apps. "
                 "Use this before click_ui to navigate inside a site or app. Defaults to the user's active window.",
                 {"app": {"type": "string", "description": "optional app name or window title; default = active window"},
                  "query": {"type": "string", "description": "optional text to filter elements by name"}}),
            tool("click_ui", "Click an element from the last read_ui list, by number or by (partial) name. "
                 "After clicking, call read_ui again (or look_at_screen) to confirm the page changed before the next step. "
                 "To type into an input box: click it, then use type_text.",
                 {"number": {"type": "integer"}, "name": s, "double": {"type": "boolean"}}),
            tool("click_screen", "Click a point on the screen using pixel coordinates of the LAST look_at_screen image. "
                 "Fallback when read_ui cannot find the element (games, canvas, images).",
                 {"x": {"type": "integer"}, "y": {"type": "integer"}, "double": {"type": "boolean"},
                  "right": {"type": "boolean"}}, ["x", "y"]),
            tool("scroll", "Scroll the active window (or the app given) up or down.",
                 {"direction": {"type": "string", "enum": ["up", "down"]},
                  "amount": {"type": "integer", "description": "wheel notches, default 5"}, "app": s}, ["direction"]),
            tool("brightness", "Get or change the display brightness (laptop screens; external monitors may not support it).",
                 {"action": {"type": "string", "enum": ["get", "set", "up", "down"]},
                  "level": {"type": "integer", "description": "0-100 for set; step for up/down (default 20)"}}, ["action"]),
            tool("save_screenshot", "Save a screenshot of the screen to the Pictures\\Jarvis folder."),
            tool("system_status", "Get CPU, memory, disk, battery, network and top processes."),
            tool("open_folder", "Open a folder in File Explorer. Accepts known names (바탕화면, 문서, 다운로드, 사진, 음악, 동영상, 홈) or an absolute path.",
                 {"target": s}, ["target"]),
            tool("find_files", "Search the user's Desktop/Documents/Downloads/Pictures/Music/Videos for files whose name contains the query.",
                 {"query": s, "folder": {"type": "string", "description": "optional known folder name or path to limit search"}}, ["query"]),
            tool("open_path", "Open a file or folder. With 'app', opens the file in that program (e.g. app='RDWorks' for a .rld file) "
                 "instead of the default program. Never type file paths into an app's Open dialog; use this.",
                 {"path": s, "app": {"type": "string", "description": "optional program name to open the file with"}}, ["path"]),
            tool("run_powershell", "Run a PowerShell command on the user's PC and return its output. Use for tasks no other tool covers. The user is asked to approve it first.",
                 {"command": s, "reason": {"type": "string", "description": "short Korean explanation shown to the user"}},
                 ["command", "reason"]),
            tool("power", "Lock, sleep, restart or shut down the PC (sleep/restart/shutdown ask the user first). cancel_shutdown aborts a pending shutdown.",
                 {"action": {"type": "string", "enum": ["lock", "sleep", "restart", "shutdown", "cancel_shutdown"]}}, ["action"]),
            tool("set_timer", "Set a timer/reminder. Jarvis will speak the label when it fires.",
                 {"seconds": {"type": "integer"}, "label": s}, ["seconds", "label"]),
            tool("cancel_timer", "Cancel all running timers/reminders."),
            tool("end_process", "Force-quit a program that is slowing the PC (all its processes), by app name or exe name "
                 "(e.g. '크롬', 'chrome.exe'). Unsaved work is lost; the user is asked to approve first. Prefer close_app for a normal close.",
                 {"name": s}, ["name"]),
            tool("point_at", "When Active Mode (full-screen HUD) is on, mark a spot on the user's screen with a target box, "
                 "e.g. to show where an error message or a button is. Use coordinates of the LAST look_at_screen image; "
                 "optionally give the width/height of the area to frame it.",
                 {"x": {"type": "integer"}, "y": {"type": "integer"}, "width": {"type": "integer"}, "height": {"type": "integer"},
                  "label": {"type": "string", "description": "very short Korean label, e.g. '에러 메시지'"}}, ["x", "y"]),
            tool("get_weather", "Get current weather and today's forecast.", {"location": {"type": "string", "description": "city name; default is the user's home city"}}),
            tool("read_clipboard", "Read the text currently in the clipboard."),
            tool("write_clipboard", "Put text into the clipboard.", {"text": s}, ["text"]),
            tool("watch_app", "Watch an app window in the background and tell the user by voice when it finishes working, "
                 "e.g. 'tell me when Claude finishes', 'let me know when the render/download is done'. Returns immediately.",
                 {"name": {"type": "string", "description": "app name or window title to watch"},
                  "label": {"type": "string", "description": "short Korean description of what is being waited for"},
                  "max_minutes": {"type": "integer", "description": "give up after this many minutes (default 60)"}},
                 ["name"]),
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
            "read_ui": lambda: f"화면 읽기 · {a.get('app') or '활성 창'}" + (f" ({a['query']})" if a.get("query") else ""),
            "click_ui": lambda: f"클릭 · {a.get('name') or '#' + str(a.get('number'))}",
            "click_screen": lambda: f"화면 클릭 · ({a.get('x')}, {a.get('y')})",
            "scroll": lambda: f"스크롤 · {a.get('direction')}",
            "brightness": lambda: f"밝기 · {a.get('action')} {a.get('level', '')}".strip(),
            "save_screenshot": lambda: "스크린샷 저장",
            "system_status": lambda: "시스템 진단",
            "open_folder": lambda: f"폴더 열기 · {a.get('target')}",
            "find_files": lambda: f"파일 검색 · {a.get('query')}",
            "open_path": lambda: f"파일 열기 · {Path(str(a.get('path', ''))).name}" + (f" ({a['app']})" if a.get("app") else ""),
            "run_powershell": lambda: f"PowerShell · {a.get('command', '')[:40]}",
            "power": lambda: f"전원 · {a.get('action')}",
            "set_timer": lambda: f"타이머 · {a.get('label')} ({a.get('seconds')}초)",
            "get_weather": lambda: f"날씨 · {a.get('location') or '현재 위치'}",
            "cancel_timer": lambda: "타이머 취소",
            "end_process": lambda: f"프로그램 강제 종료 · {a.get('name')}",
            "point_at": lambda: f"화면 표시 · {a.get('label') or '위치'}",
            "read_clipboard": lambda: "클립보드 읽기",
            "write_clipboard": lambda: "클립보드 쓰기",
            "remember": lambda: f"기억 저장 · {a.get('fact', '')[:30]}",
            "watch_app": lambda: f"작업 감시 · {a.get('name')}",
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
    def t_open_app(self, name: str, min_score: float = 38) -> str:
        key = _norm(name)
        hit = self._find_app(name, min_score)
        if hit:
            subprocess.Popen(["explorer.exe", f"shell:AppsFolder\\{hit[1]}"], creationflags=NO_WINDOW)
            return f"'{hit[0]}' 실행함"
        exe = SYSTEM_EXE.get(key)
        if not exe and min_score > 38:
            raise ToolError(f"'{name}' 앱을 찾지 못했습니다.")   # 엄격 모드: 이름만으로 실행해 보지 않음
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
        hwnds = self.hooks.hud_hwnd()   # 자비스 HUD 창들 (작은 HUD + 액티브 모드 화면)
        hwnds = hwnds if isinstance(hwnds, (list, tuple)) else [hwnds]
        for h in hwnds:
            winutil.set_capture_excluded(h, True)
        try:
            time.sleep(0.05)
            return ImageGrab.grab()
        finally:
            for h in hwnds:
                winutil.set_capture_excluded(h, False)

    def t_look_at_screen(self):
        img = self._grab().convert("RGB")
        full_w = img.width
        img.thumbnail((1568, 1568))
        self._shot_scale = full_w / img.width
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=72)
        data = base64.standard_b64encode(buf.getvalue()).decode()
        return [
            {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": data}},
            {"type": "text", "text": f"사용자 화면 캡처 ({img.width}x{img.height}). 활성 창: {self.focus.last_title}"},
        ]

    # --- 화면 조작 ---
    def _target_window(self, app: str | None) -> int:
        if app:
            hits = self._match_windows(app)
            if not hits:
                raise ToolError(f"'{app}' 창이 열려 있지 않습니다.")
            return hits[0]["hwnd"]
        hwnd = self.focus.last_external
        if not hwnd or not winutil.user32.IsWindow(hwnd):
            raise ToolError("조작할 창이 없습니다. 먼저 앱이나 사이트를 여세요.")
        return hwnd

    def t_read_ui(self, app: str | None = None, query: str | None = None) -> str:
        hwnd = self._target_window(app)
        try:
            return self.screen.read(hwnd, query or "")
        except OSError as e:
            raise ToolError(f"창 내용을 읽지 못했습니다: {e}")

    def t_click_ui(self, number: int | None = None, name: str | None = None, double: bool = False) -> str:
        if not number and not name:
            raise ToolError("number 나 name 중 하나가 필요합니다.")
        it = self.screen.find(number, name or "")
        if it is None and name and self.screen.hwnd:
            # 목록이 오래됐을 수 있으니 같은 창을 다시 읽고 이름으로 한 번 더 찾는다
            self.screen.read(self.screen.hwnd)
            it = self.screen.find(None, name)
        if it is None:
            raise ToolError("그 요소를 찾지 못했습니다. read_ui 로 목록을 다시 확인하세요.")
        if uia.is_risky(it.name):
            self._confirm("화면 클릭", f"'{it.name}' {it.kind} 을(를) 누릅니다.\n창: {self.screen.title}")
        try:
            out = self.screen.click(it, double=bool(double))
        except Exception as e:   # 페이지가 바뀌어 요소가 사라진 경우 등
            raise ToolError(f"누르지 못했습니다 ({e}). read_ui 로 다시 확인하세요.")
        time.sleep(0.6)          # 페이지·창이 반응할 시간
        return out + f" · 창: {winutil.window_title(self.screen.hwnd) or self.screen.title}"

    def t_click_screen(self, x: int, y: int, double: bool = False, right: bool = False) -> str:
        sx, sy = int(x * self._shot_scale), int(y * self._shot_scale)
        uia.click_at(sx, sy, double=bool(double), right=bool(right))
        time.sleep(0.5)
        return f"({sx}, {sy}) 클릭함"

    def t_scroll(self, direction: str, amount: int = 5, app: str | None = None) -> str:
        if direction not in ("up", "down"):
            raise ToolError("direction 은 up 또는 down")
        hwnd = self._target_window(app)
        uia.scroll(hwnd, direction, amount or 5)
        time.sleep(0.3)
        return f"{'위' if direction == 'up' else '아래'}로 스크롤함"

    _NO_BRIGHT = "이 화면은 밝기 조절을 지원하지 않습니다. 외장 모니터는 모니터 버튼으로 조절해 주세요."

    def _ps(self, cmd: str) -> str:
        r = subprocess.run(["powershell", "-NoProfile", "-Command", cmd], capture_output=True,
                           timeout=10, creationflags=NO_WINDOW)
        if r.returncode != 0:
            raise ToolError(self._NO_BRIGHT)
        return r.stdout.decode("utf-8", "replace").strip()

    def t_brightness(self, action: str, level: int | None = None) -> str:
        cur_s = self._ps("(Get-CimInstance -Namespace root/WMI -ClassName WmiMonitorBrightness -ErrorAction Stop "
                         "| Select-Object -First 1).CurrentBrightness")
        try:
            cur = int(cur_s)
        except ValueError:
            raise ToolError(self._NO_BRIGHT)
        if action == "get":
            return f"현재 밝기 {cur}%"
        step = int(level or 20)
        new = {"set": int(level if level is not None else cur), "up": cur + step, "down": cur - step}.get(action)
        if new is None:
            raise ToolError("지원하지 않는 동작")
        new = max(0, min(100, new))
        self._ps("Get-CimInstance -Namespace root/WMI -ClassName WmiMonitorBrightnessMethods -ErrorAction Stop | "
                 f"Invoke-CimMethod -MethodName WmiSetBrightness -Arguments @{{Timeout=1; Brightness={new}}} | Out-Null")
        return f"밝기 {cur}% → {new}%"

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

    def t_open_path(self, path: str, app: str | None = None) -> str:
        p = Path(os.path.expandvars(os.path.expanduser(path)))
        if not p.exists():
            raise ToolError(f"경로가 없습니다: {p}")
        if p.suffix.lower() in RISKY_EXT:
            self._confirm("프로그램 실행", str(p))
        if app:
            exe = self._app_exe(app)
            if not exe:
                raise ToolError(f"'{app}' 프로그램 위치를 찾지 못했습니다. app 없이 기본 프로그램으로 열 수 있습니다.")
            subprocess.Popen([exe, str(p)], cwd=str(Path(exe).parent))
            return f"{Path(exe).stem}(으)로 열기: {p}"
        os.startfile(str(p))
        return f"열기: {p}"

    def _app_exe(self, name: str) -> str | None:
        """앱 이름 → 실행 파일 경로. 실행 중인 창 → 시작 메뉴·바탕화면 바로가기 순으로 찾는다."""
        for w in self._match_windows(name):
            try:
                exe = psutil.Process(w["pid"]).exe()
            except Exception:
                continue
            if exe.lower().endswith(".exe") and not exe.lower().endswith("explorer.exe"):
                return exe
        terms = [t for t in (_norm(x) for x in [name] + APP_ALIASES.get(_norm(name), [])) if t]
        dirs = [Path(os.environ.get("ProgramData", r"C:\ProgramData")) / "Microsoft/Windows/Start Menu/Programs",
                Path(os.environ.get("APPDATA", "")) / "Microsoft/Windows/Start Menu/Programs",
                Path(winutil.known_folder("바탕화면") or Path.home() / "Desktop"),
                Path(os.environ.get("PUBLIC", r"C:\Users\Public")) / "Desktop"]
        best, score = None, 0
        for d in dirs:
            if not d.is_dir():
                continue
            for lnk in d.rglob("*.lnk"):
                stem = _norm(lnk.stem)
                for t in terms:
                    sc = 3 if stem == t else 2 if stem.startswith(t) else 1 if t in stem else 0
                    if sc > score:
                        best, score = lnk, sc
        if not best:
            return None
        try:
            import win32com.client
            target = win32com.client.Dispatch("WScript.Shell").CreateShortcut(str(best)).TargetPath
        except Exception as e:
            log.warning("바로가기 해석 실패 %s: %s", best, e)
            return None
        return target if target and target.lower().endswith(".exe") and Path(target).exists() else None

    # --- 백그라운드 감시 ---
    def t_watch_app(self, name: str, label: str = "", max_minutes: int = 60) -> str:
        hits = self._match_windows(name)
        if not hits:
            raise ToolError(f"'{name}' 창이 열려 있지 않습니다.")
        hwnd, title = hits[0]["hwnd"], hits[0]["title"]
        minutes = max(1, min(int(max_minutes or 60), 240))
        what = (label or f"{name} 작업").strip()
        threading.Thread(target=self._watch_loop, args=(hwnd, what, minutes), daemon=True, name="watch").start()
        return f"'{title[:40]}' 창을 지켜보다가 끝나면 알려 드립니다 (최대 {minutes}분)."

    @staticmethod
    def _app_procs(hwnd: int) -> list:
        """창을 가진 앱의 프로세스 묶음 (Electron·크롬은 메인 + 렌더러·GPU 등 자식 프로세스)."""
        try:
            pid = next((w["pid"] for w in winutil.list_windows() if w["hwnd"] == hwnd), None)
            root = psutil.Process(pid) if pid else None
            while root is not None:
                parent = root.parent()
                if parent is None or parent.name().lower() != root.name().lower():
                    break
                root = parent
            return [root] + root.children(recursive=True) if root else []
        except Exception:
            return []

    def _watch_loop(self, hwnd: int, what: str, minutes: int) -> None:
        """작업 중 신호: '중지' 버튼이 보이거나, 앱 프로세스들이 CPU 를 쓰거나, 창 내용이 바뀜.
        한 번이라도 작업 중이었다가 신호가 25초 이상 없으면 끝난 것으로 본다.
        (Claude 데스크톱 앱은 화면 요소를 거의 노출하지 않아 CPU 사용량이 주된 신호)"""
        scr = uia.Screen()
        procs = self._app_procs(hwnd)
        for p in procs:
            try:
                p.cpu_percent(None)
            except Exception:
                pass
        t0 = time.monotonic()
        last_sig, last_busy, saw_busy = None, t0, False
        smooth = peak = 0.0       # 앱마다 평소 CPU 가 달라서, 작업 중 최고치의 40% 아래로 내려가야 '조용함'
        while time.monotonic() - t0 < minutes * 60:
            time.sleep(4)
            if not winutil.user32.IsWindow(hwnd):
                self.hooks.notify(f"지켜보던 창이 닫혔습니다. ({what})")
                return
            cpu = 0.0
            for p in procs:
                try:
                    cpu += p.cpu_percent(None)
                except Exception:
                    pass
            names: list[str] = []
            try:
                scr.read(hwnd)
                names = [it.name for it in scr.items]
            except Exception as e:
                log.debug("감시 읽기 실패: %s", e)
            sig = hash(tuple(names))
            changed = last_sig is not None and sig != last_sig and len(names) > 5
            last_sig = sig
            smooth = cpu if smooth == 0.0 else 0.5 * smooth + 0.5 * cpu
            peak = max(peak, smooth)
            busy = any(uia.is_stop_button(n) for n in names) or changed or cpu >= max(6.0, 0.4 * peak)
            now = time.monotonic()
            log.debug("감시 %s: cpu %.1f%% 요소 %d 바뀜 %s → %s", what, cpu, len(names), changed, busy)
            if busy:
                saw_busy, last_busy = True, now
            elif saw_busy and now - last_busy >= 25:
                self.hooks.notify(f"{what}, 끝난 것 같습니다.")
                return
            elif not saw_busy and now - t0 >= 90:
                self.hooks.notify(f"{what}, 지켜보는 동안 작업하는 움직임이 없었습니다. 이미 끝났을 수 있어요.")
                return
        self.hooks.notify(f"{what}, {minutes}분 동안 지켜봤지만 끝나지 않아 감시를 멈췄습니다.")

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

    def weather_data(self, location: str | None = None) -> dict:
        """현재 날씨 + 오늘 예보 (액티브 모드 화면과 get_weather 가 함께 씀)."""
        loc = location or self.cfg["home_city"] or "Seoul"
        url = f"https://wttr.in/{urllib.parse.quote(loc)}?format=j1&lang=ko"
        data, err = None, None
        for attempt in range(2):     # 연결이 한 번 끊겨도 바로 포기하지 않는다 (기록: SSL 연결 시간 초과)
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "curl/8"})
                data = json.loads(urllib.request.urlopen(req, timeout=7).read().decode("utf-8"))
                break
            except Exception as e:
                err = e
                if attempt == 0:
                    time.sleep(1.0)
        if data is None:
            raise ToolError(f"날씨 정보를 가져오지 못했습니다: {err}")
        cur = data["current_condition"][0]
        desc = _weather_ko((cur.get("lang_ko") or cur.get("weatherDesc") or [{"value": ""}])[0]["value"])
        today = data["weather"][0]
        hourly = [{"h": int(h.get("time", "0")) // 100, "t": int(h.get("tempC", 0)), "rain": int(h.get("chanceofrain", 0))}
                  for h in today.get("hourly", [])]
        return {"loc": loc, "desc": desc, "temp": int(cur["temp_C"]), "feels": int(cur["FeelsLikeC"]),
                "humidity": int(cur["humidity"]), "wind": int(cur["windspeedKmph"]),
                "max": int(today["maxtempC"]), "min": int(today["mintempC"]),
                "rain": max([h["rain"] for h in hourly] or [0]), "hourly": hourly}

    def t_get_weather(self, location: str | None = None) -> str:
        w = self.weather_data(location)
        return (f"{w['loc']}: {w['desc']}, 기온 {w['temp']}°C (체감 {w['feels']}°C), 습도 {w['humidity']}%, "
                f"바람 {w['wind']}km/h. 오늘 최고 {w['max']}°C / 최저 {w['min']}°C, 강수확률 최대 {w['rain']}%")

    def t_cancel_timer(self) -> str:
        n = self.hooks.cancel_timers()
        return f"타이머 {n}개를 취소했습니다." if n else "돌고 있는 타이머가 없습니다."

    def t_end_process(self, name: str) -> str:
        """프로그램의 프로세스를 모두 강제 종료 (Windows 핵심 프로세스 · 자비스 자신은 제외)."""
        import psutil
        from . import hud_feed
        q = _norm(name)
        exes = {e.lower() for e in EXE_ALIASES.get(q, [])}
        mine = hud_feed.own_pids()
        targets = []
        for p in psutil.process_iter(["name"]):
            pn = (p.info.get("name") or "").lower()
            if not pn or p.pid in mine or pn in hud_feed.PROTECTED:
                continue
            if pn in exes or _norm(pn.removesuffix(".exe")) == q or _norm(pn) == q or _norm(hud_feed.display_name(pn)) == q:
                targets.append(p)
        if not targets:
            raise ToolError(f"'{name}' 프로그램이 실행 중이 아니거나 종료할 수 없는 프로그램입니다.")
        exe = targets[0].info["name"]
        mem = 0
        for p in targets:
            try:
                mem += p.memory_info().rss
            except psutil.Error:
                pass
        self._confirm("프로그램 강제 종료",
                      f"{hud_feed.display_name(exe)} ({exe}, 프로세스 {len(targets)}개, 메모리 {mem / 1048576:,.0f} MB)\n"
                      "저장하지 않은 작업은 사라질 수 있습니다.")
        for p in targets:
            try:
                p.terminate()
            except psutil.Error:
                pass
        gone, alive = psutil.wait_procs(targets, timeout=3)
        for p in alive:
            try:
                p.kill()
            except psutil.Error:
                pass
        return f"{hud_feed.display_name(exe)} 종료함 (프로세스 {len(targets)}개, 메모리 약 {mem / 1048576:,.0f} MB 확보)"

    def t_point_at(self, x: int, y: int, width: int = 0, height: int = 0, label: str = "") -> str:
        k = self._shot_scale
        ok = self.hooks.point_at(int(x * k), int(y * k), int((width or 0) * k), int((height or 0) * k), str(label or "")[:30])
        if not ok:
            raise ToolError("액티브 모드가 꺼져 있어 화면에 표시하지 못했습니다. 위치를 말로 설명하세요.")
        return "화면에 표시함"

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
