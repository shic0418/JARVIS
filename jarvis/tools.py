"""자비스의 '손': PC 제어 도구 모음과 Claude 용 도구 스키마."""
from __future__ import annotations

import contextlib
import datetime as dt
import difflib
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

from . import sentinel, todos, uia, vision, winutil
from .config import DATA_DIR, Config, load_memory, save_memory
from .control import ControlTools, ToolError

log = logging.getLogger("jarvis.tools")
NO_WINDOW = 0x08000000


@dataclass
class Hooks:
    confirm: Callable[[str, str], bool]          # (제목, 상세) -> 승인 여부 (블로킹)
    schedule_timer: Callable[[int, str], None]   # (초, 라벨)
    hud_hwnd: Callable[[], "int | list[int]"]   # 스크린샷에서 뺄 자비스 창 (하나 또는 여러 개)
    notify: Callable[[str], None] = lambda msg: None   # 백그라운드 작업이 사용자에게 말로 알림
    cancel_timers: Callable[[], int] = lambda: 0       # 돌고 있는 타이머 모두 취소 → 취소한 개수
    point_at: Callable[[int, int, int, int, str], bool] = lambda x, y, w, h, label: False  # 액티브 모드 화면에 위치 표시
    feed: Callable[[str, str], None] = lambda name, value: None   # 액티브 모드 화면 정보 (속성 이름, JSON)


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


class PCTools(ControlTools):
    def __init__(self, cfg: Config, focus: winutil.FocusTracker, hooks: Hooks) -> None:
        self.cfg = cfg
        self.focus = focus
        self.hooks = hooks
        self._apps: list[tuple[str, str]] = []
        self.screen = uia.Screen()          # 화면 조작: 마지막으로 읽은 요소 목록
        self._view: vision.View | None = None    # Claude 가 마지막으로 본 이미지 ↔ 실제 화면의 대응 (좌표 변환용)
        self._view_target = "screen"             # 마지막으로 본 범위 (screen | window) — 누른 뒤 같은 범위를 다시 보여 준다
        self._moved = False                      # 방금 동작으로 화면이 바뀌었는가
        self.vision_model = ""              # 지금 화면을 보고 있는 모델 이름 → 보낼 이미지 크기 한도를 정한다
        self.sentinel = sentinel.Sentinel(cfg)   # Sentinel 웹 보안 분석기 연결
        self._sentinel_last = ""            # 이번 실행에서 마지막으로 요청한 검사 번호 (보고서 열기용)
        self.writer = None                  # 작가 여러 명에게 나눠 맡기는 함수 (app 이 brain.write_team 을 넣는다)
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
            tool("type_text", "Type text into the user's active window (works for Korean). Optionally press Enter after. "
                 "Set replace=true to overwrite what is already in the focused input box (select all, then type).",
                 {"text": s, "press_enter": {"type": "boolean"}, "replace": {"type": "boolean"}}, ["text"]),
            tool("press_keys", "Press a keyboard shortcut in the user's active window, e.g. 'ctrl+s', 'alt+tab', 'win+shift+s', 'f5', 'enter'.",
                 {"keys": s, "times": {"type": "integer"}}, ["keys"]),
            tool("look_at_screen", "Capture the user's screen (the monitor their active window is on) and look at it. Use when the user "
                 "asks about what is on screen or you need to see it to help. target='window' captures only the active window, "
                 "which shows it larger. marks=true draws a numbered box on every clickable element; then click one with "
                 "click_ui(number) instead of guessing coordinates. Text too small to read? Use zoom_screen on that area.",
                 {"target": {"type": "string", "enum": ["screen", "window"]}, "marks": {"type": "boolean"}}),
            tool("zoom_screen", "Look closer at one area of the LAST screenshot: give the area in that image's pixel coordinates and get "
                 "it enlarged at full detail (small text, icons, dense tables). After zooming, click_screen / point_at / zoom_screen "
                 "coordinates refer to the zoomed image. Call look_at_screen again to go back to the whole screen.",
                 {"x": {"type": "integer"}, "y": {"type": "integer"}, "width": {"type": "integer"}, "height": {"type": "integer"}},
                 ["x", "y", "width", "height"]),
            tool("read_screen_text", "Read the text shown in a window (web page text, document, labels) as plain text, in reading order. "
                 "Exact and cheap: prefer it over a screenshot for questions about what a page says, summaries, error messages, "
                 "or to find where something is mentioned. all=true also includes the part of a web page that is scrolled out of view. "
                 "Defaults to the user's active window.",
                 {"app": {"type": "string", "description": "optional app name or window title; default = active window"},
                  "all": {"type": "boolean"}}),
            tool("wait_screen", "Wait until the screen stops changing (page finished loading, app finished opening), up to max_seconds "
                 "(default 5). Returns as soon as it is still, so prefer it over a fixed wait.",
                 {"max_seconds": {"type": "integer"}}),
            tool("read_ui", "List clickable elements (buttons, links, tabs, menu items, input boxes) inside a window, numbered. "
                 "Works inside web pages in Chrome/Edge (e.g. Google Classroom tabs) and in normal apps. "
                 "Use this before click_ui to navigate inside a site or app. Defaults to the user's active window.",
                 {"app": {"type": "string", "description": "optional app name or window title; default = active window"},
                  "query": {"type": "string", "description": "optional text to filter elements by name"}}),
            tool("click_ui", "Click an element from the last read_ui list, by number or by (partial) name. "
                 "By name it also finds elements scrolled out of view and scrolls to them first. "
                 "The result says whether the screen changed; if it did, it also lists the elements of the new screen "
                 "(renumbered), so you can pick the next element without calling read_ui again. "
                 "To type into an input box: click it, then use type_text.",
                 {"number": {"type": "integer"}, "name": s, "double": {"type": "boolean"}}),
            tool("click_screen", "Click a point using pixel coordinates of the LAST image you were shown (look_at_screen or zoom_screen). "
                 "Fallback when read_ui / marks cannot find the element (games, canvas, images). Aim at the centre of the target. "
                 "The result says whether the screen changed and, if it did, includes a new screenshot — no need to call "
                 "look_at_screen again; later coordinates refer to that new image.",
                 {"x": {"type": "integer"}, "y": {"type": "integer"}, "double": {"type": "boolean"},
                  "right": {"type": "boolean"}}, ["x", "y"]),
            tool("scroll", "Scroll the active window (or the app given) up or down. The result says whether the screen moved; "
                 "no change means the end was reached. To scroll one area inside the window (a list, a chat pane), give x,y "
                 "of a point inside that area in the LAST image's pixel coordinates. To reach a named element that is "
                 "scrolled out of view, prefer click_ui(name=...): it scrolls there by itself.",
                 {"direction": {"type": "string", "enum": ["up", "down"]},
                  "amount": {"type": "integer", "description": "wheel notches, default 5"}, "app": s,
                  "x": {"type": "integer"}, "y": {"type": "integer"}}, ["direction"]),
            tool("hover_screen", "Move the mouse over a point (no click), in the LAST image's pixel coordinates. Use for menus "
                 "or tooltips that only appear on hover. Returns the new screenshot if something appeared.",
                 {"x": {"type": "integer"}, "y": {"type": "integer"}}, ["x", "y"]),
            tool("drag_screen", "Press at (x, y), drag to (to_x, to_y) and release, in the LAST image's pixel coordinates. "
                 "Use for sliders, moving or resizing things, drawing, selecting a range.",
                 {"x": {"type": "integer"}, "y": {"type": "integer"}, "to_x": {"type": "integer"}, "to_y": {"type": "integer"}},
                 ["x", "y", "to_x", "to_y"]),
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
            tool("sentinel_scan", "Run a PASSIVE (non-intrusive) web security scan of one site with the user's local "
                 "Sentinel Web Security Analyzer and return a summary of the findings. Only for a site the user owns or is "
                 "authorised to test: the app shows the user an authorisation card every time, and their confirmation is "
                 "recorded in Sentinel's audit log. Pass only the address the user asked about (or, for 'this site', the "
                 "address of the browser tab they are looking at); never pick or guess a target yourself. "
                 "Active or intrusive checks are not available here.",
                 {"url": s,
                  "basis": {"type": "string", "enum": ["owner", "written_permission", "bug_bounty_scope", "internal_lab"],
                            "description": "why the user may test it, only if they said so; default is the user's setting"},
                  "purpose": {"type": "string", "description": "short Korean note for the audit log, e.g. '배포 전 점검'"}},
                 ["url"]),
            tool("sentinel_report", "Open the full HTML report of the most recent Sentinel scan from this session in the browser."),
            tool("sentinel_status", "Check whether the local Sentinel Web Security Analyzer server is running and the API key works."),
            tool("todo_add", "Add a to-do item with an optional deadline (할 일 · 과제 · 마감). Use when the user says they "
                 "have to do something by some day, or asks to add / note a to-do. The app reminds them the day before and "
                 "on the day.", {"text": {"type": "string", "description": "the task in short Korean, without the date"},
                                 "due": {"type": "string", "description": "deadline as YYYY-MM-DD (resolve 금요일 · 내일 · "
                                                                         "다음 주 월요일 from today's date); omit if none"}},
                 ["text"]),
            tool("todo_list", "List the user's open to-do items with deadlines.",
                 {"scope": {"type": "string", "enum": ["all", "today", "tomorrow", "week", "next_week"]}}),
            tool("todo_done", "Mark a to-do item as done (or delete it with remove=true). Match by its name.",
                 {"query": s, "remove": {"type": "boolean"}}, ["query"]),
            tool("remember", "Save a fact about the user to long-term memory (e.g. preferences, names). Use when the user asks you to remember something.",
                 {"fact": s}, ["fact"]),
            tool("make_presentation",
                 "Create a PowerPoint (.pptx) presentation and open it. Use for PPT / 발표 자료 / 슬라이드 requests. Give "
                 "the slides in order; how much of each slide you write yourself (just layout + title, or the full text) "
                 "is set by the 작업 rules in your instructions — slides without text are written by a team of writer "
                 "agents in parallel. A cover, a 목차 slide and a 참고 자료 slide (from sources) are added automatically. "
                 "Saved to the user's Documents\\JARVIS folder unless folder is given.",
                 {"title": {"type": "string", "description": "presentation title (cover)"},
                  "subtitle": {"type": "string", "description": "cover subtitle, e.g. '3학년 2반 홍길동' or a one-line summary"},
                  "audience": {"type": "string", "description": "who listens, e.g. '중학교 2학년', '회사 임원' — sets the wording"},
                  "style": {"type": "string", "enum": ["clean", "bold", "side", "tech", "editorial", "pastel", "corporate"],
                            "description": "visual design — only when the user asked for a look; otherwise omit and a "
                                           "fitting design is picked, different each time. clean 깔끔 · bold 큰 글자와 강한 색 · "
                                           "side 왼쪽 제목 칸 (모던) · tech 어두운 바탕과 빛 · editorial 명조와 얇은 선 (매거진) · "
                                           "pastel 둥글고 밝은 색 (귀엽게) · corporate 진한 띠 (회사 · 공식 보고)"},
                  "theme": {"type": "string", "enum": ["light", "dark", "navy", "warm", "green", "purple", "teal", "rose",
                                                       "mono", "midnight", "forest"],
                            "description": "colors — only when the user asked for a color; otherwise omit (the style picks)"},
                  "facts": {"type": "array", "items": {"type": "string"},
                            "description": "facts for the writers (numbers, years, names) — only what you researched yourself"},
                  "slides": {"type": "array", "description": "content slides in order (cover, 목차 and 참고 자료 are added for you)",
                             "items": {"type": "object", "properties": {
                                 "layout": {"type": "string",
                                            "enum": ["bullets", "section", "two_column", "stats", "chart", "timeline", "process",
                                                     "cards", "table", "highlight", "quote", "closing"],
                                            "description": "section (chapter divider) · bullets · two_column (compare two "
                                                           "sides) · stats (2-4 key numbers) · chart · timeline (dated events) "
                                                           "· process (steps in order) · cards (3-4 parallel items) · table "
                                                           "(comparison grid) · highlight (one big sentence) · quote (a real "
                                                           "quote) · closing (last slide)"},
                                 "title": {"type": "string"},
                                 "points": {"type": "array", "items": {"type": "string"},
                                            "description": "outline only: 1-3 keywords the writers must cover on this slide"},
                                 "bullets": {"type": "array", "items": {"type": "string"},
                                             "description": "final text lines; '핵심어: 설명' is shown with the keyword in bold, a "
                                                            "line starting with '- ' is a sub-point"},
                                 "left": {"type": "object", "description": "two_column: {heading, bullets}"},
                                 "right": {"type": "object", "description": "two_column: {heading, bullets}"},
                                 "icon": {"type": "string", "description": "section / closing: Material Icons name for the "
                                                                           "big icon (default: picked from the text)"},
                                 "stats": {"type": "array", "description": "stats: 2-4 of {value: '73%', label, icon?} — a unit "
                                                                           "after the number is drawn smaller",
                                           "items": {"type": "object"}},
                                 "chart": {"type": "object", "description": "chart: the data for a real, editable chart",
                                           "properties": {
                                               "type": {"type": "string", "enum": ["column", "bar", "line", "pie"]},
                                               "categories": {"type": "array", "items": {"type": "string"}},
                                               "series": {"type": "array", "items": {"type": "object", "properties": {
                                                   "name": {"type": "string"},
                                                   "values": {"type": "array", "items": {"type": "number"}}}}},
                                               "unit": {"type": "string", "description": "e.g. '%', '℃', '명'"}}},
                                 "events": {"type": "array", "description": "timeline: 3-5 of {when, title, text, icon?}",
                                            "items": {"type": "object"}},
                                 "steps": {"type": "array", "description": "process: 3-5 of {title, text, icon?}", "items": {"type": "object"}},
                                 "cards": {"type": "array", "description": "cards: 3-4 of {title, text, icon?} — icon is a Material "
                                                                           "Icons name; omitted icons are picked from the text", "items": {"type": "object"}},
                                 "table": {"type": "object", "description": "table: {columns: [...], rows: [[...]]}, at most 5 x 6"},
                                 "statement": {"type": "string", "description": "highlight: the one big sentence"},
                                 "detail": {"type": "string", "description": "highlight: one supporting line"},
                                 "quote": {"type": "string"},
                                 "by": {"type": "string", "description": "who said the quote"},
                                 "notes": {"type": "string", "description": "speaker notes: what to say on this slide (1-2 sentences)"}},
                                 "required": ["title"]}},
                  "sources": {"type": "array", "items": {"type": "string"}, "description": "references you used yourself: 'title — URL'"},
                  "agenda": {"type": "boolean", "description": "add a 목차 slide (default: when there are 4+ content slides)"},
                  "icon": {"type": "string", "description": "cover icon (Material Icons name); default: picked from the title"},
                  "filename": {"type": "string", "description": "file name without extension (default: the title)"},
                  "folder": {"type": "string", "description": "'바탕화면', '문서', '다운로드' or a full path (default Documents\\JARVIS)"},
                  "overwrite": {"type": "boolean", "description": "replace the file of the same name (use when revising a file you just made)"},
                  "open": {"type": "boolean", "description": "open the file after saving (default true)"}},
                 ["title", "slides"]),
            tool("make_document",
                 "Create a report or document and open it — Word (.docx) by default, or 한글 (.hwpx) when the user asks for "
                 "한글 / 한컴 / hwp / 아래아한글. Use for 보고서 / 레포트 / 조사 정리 / 문서로 정리 / 가정통신문 requests. "
                 "Give the sections in order; how much you write yourself (just headings, or the full text) is set by the "
                 "작업 rules in your instructions — sections without text are written by writer agents in parallel. A 참고 자료 "
                 "list is added from sources and pages are numbered. Layout: a cover (subtitle split by ' · ' into "
                 "subject / name; today's date is added if no year), a 목차 when there are 3+ top-level headings, then the body.",
                 {"title": s,
                  "subtitle": {"type": "string", "description": "e.g. '과목 · 학번 이름 · 날짜'"},
                  "summary": {"anyOf": [{"type": "string"}, {"type": "array", "items": {"type": "string"}},
                                       {"type": "object", "properties": {"title": {"type": "string"}, "text": {"type": "string"},
                                                                         "bullets": {"type": "array", "items": {"type": "string"}}}}],
                             "description": "optional 핵심 요약 box near the start: a string, a list of strings, or "
                                             "{title, text | bullets}"},
                  "audience": {"type": "string", "description": "who reads it, e.g. '고등학교 과제', '팀장 보고'"},
                  "facts": {"type": "array", "items": {"type": "string"},
                            "description": "facts for the writers — only what you researched yourself"},
                  "sections": {"type": "array", "items": {"type": "object", "properties": {
                      "heading": {"type": "string"},
                      "level": {"type": "integer", "enum": [1, 2], "description": "2 for a sub-heading"},
                      "points": {"type": "array", "items": {"type": "string"},
                                 "description": "outline only: what this section must cover"},
                      "paragraphs": {"type": "array", "items": {"type": "string"}},
                      "bullets": {"type": "array", "items": {"type": "string"}},
                      "callout": {"anyOf": [{"type": "string"}, {"type": "array", "items": {"type": "string"}},
                                            {"type": "object", "properties": {"title": {"type": "string"}, "text": {"type": "string"},
                                                                         "bullets": {"type": "array", "items": {"type": "string"}}}}],
                             "description": "optional highlighted key-point box for this section: a string, a list "
                                                 "of strings, or {title, text | bullets}"},
                      "table": {"type": "object", "properties": {
                          "columns": {"type": "array", "items": {"type": "string"}},
                          "rows": {"type": "array", "items": {"type": "array", "items": {"type": "string"}}},
                          "caption": {"type": "string"}}}}}},
                  "sources": {"type": "array", "items": {"type": "string"}},
                  "format": {"type": "string", "enum": ["docx", "hwpx"],
                             "description": "docx = Word (default), hwpx = 한글 (when the user says 한글 · 한컴 · hwp)"},
                  "icon": {"type": "string", "description": "cover icon for Word reports (Material Icons name; "
                                                           "not used for hwpx)"},
                  "filename": s, "folder": s,
                  "overwrite": {"type": "boolean"}, "open": {"type": "boolean"}},
                 ["title", "sections"]),
            tool("make_spreadsheet",
                 "Create an Excel (.xlsx) file with one or more sheets and open it. Use for 표 / 엑셀 / 시간표 / 정리표 requests. "
                 "Give numbers as numbers. A cell that starts with '=' is written as a formula (e.g. '=SUM(B2:B8)').",
                 {"sheets": {"type": "array", "items": {"type": "object", "properties": {
                      "name": {"type": "string", "description": "sheet tab name"},
                      "title": {"type": "string", "description": "optional title row above the table"},
                      "columns": {"type": "array", "items": {"type": "string"}},
                      "rows": {"type": "array", "items": {"type": "array", "items": {}}},
                      "chart": {"type": "object", "description": "optional chart beside the table",
                                "properties": {"type": {"type": "string", "enum": ["column", "bar", "line", "pie"]},
                                               "title": {"type": "string"},
                                               "category_column": {"type": "integer", "description": "0-based label column (default 0)"},
                                               "value_columns": {"type": "array", "items": {"type": "integer"},
                                                                 "description": "0-based value columns (default: all numeric columns)"}}}},
                      "required": ["columns"]}},
                  "filename": s, "folder": s,
                  "overwrite": {"type": "boolean"}, "open": {"type": "boolean"}},
                 ["sheets"]),
            tool("make_cardnews",
                 "Create card news (카드뉴스): square 1080x1080 images — a cover, one card per item and a closing card — saved "
                 "as PNG files plus one PDF in a new folder, then open the folder. Use for 카드뉴스 / 인스타 카드 / SNS 홍보 "
                 "requests instead of operating a design website (much faster and more reliable). Keep each card short: a "
                 "title and 2-4 short lines — one message per card. Vary the card layout: a number → stat, before/after or "
                 "wrong/right → compare, an order → steps, a saying → quote, a checklist → list, one key idea → point "
                 "(omitted layouts are chosen from the content). Each card gets an icon picked from its text unless you give one.",
                 {"title": {"type": "string", "description": "cover title (big text)"},
                  "subtitle": {"type": "string", "description": "small tag on the cover, e.g. '환경 캠페인'"},
                  "cards": {"type": "array", "description": "content cards, 3-8 recommended (max 12)",
                            "items": {"type": "object", "properties": {
                                "title": {"type": "string"},
                                "bullets": {"type": "array", "items": {"type": "string"}},
                                "highlight": {"type": "string", "description": "optional one-line key message in a box"},
                                "layout": {"type": "string", "enum": ["point", "list", "stat", "steps", "compare", "quote"],
                                           "description": "point = big icon + message, list = numbered boxes, stat = one big "
                                                          "number, steps = ordered steps, compare = two columns, quote = quotation"},
                                "icon": {"type": "string", "description": "Material Icons name, e.g. bedtime, local_cafe"},
                                "number": {"type": "string", "description": "stat: the big number, e.g. '72' or '72%'"},
                                "unit": {"type": "string", "description": "stat: unit, e.g. '%', '시간'"},
                                "caption": {"type": "string", "description": "stat: one explaining line"},
                                "left": {"type": "object", "description": "compare: left column (e.g. wrong habit / before)",
                                         "properties": {"title": {"type": "string"},
                                                        "items": {"type": "array", "items": {"type": "string"}}}},
                                "right": {"type": "object", "description": "compare: right column (e.g. right habit / after)",
                                          "properties": {"title": {"type": "string"},
                                                         "items": {"type": "array", "items": {"type": "string"}}}},
                                "quote": {"type": "string"},
                                "by": {"type": "string", "description": "quote: who said it / source"}},
                                "required": ["title"]}},
                  "closing": {"type": "string", "description": "closing card: first line is the big message, later lines small text"},
                  "sources": {"type": "array", "items": {"type": "string"}},
                  "theme": {"type": "string", "enum": ["light", "dark", "navy", "warm", "green", "purple", "teal", "rose",
                                                       "mono", "midnight", "forest"]},
                  "style": {"type": "string", "enum": ["clean", "bold", "gradient", "pastel"],
                            "description": "look, combined with theme: clean (default), bold (strong color band, big "
                                           "numbers), gradient (gradient background), pastel (soft colors)"},
                  "icon": {"type": "string", "description": "cover icon (Material Icons name); default: picked from the title"},
                  "filename": s, "folder": s, "overwrite": {"type": "boolean"}, "open": {"type": "boolean"}},
                 ["title", "cards"]),
            tool("make_poster",
                 "Create a poster (포스터 · 홍보물 · 안내문 · 캠페인) as a portrait A4 (or A3) image plus a print-ready PDF and "
                 "open it. Use instead of operating a design website. A colored header with the title, an optional slogan "
                 "box, 2-4 sections of short bullet points and a footer. Put the key facts (일시 · 장소 · 대상 · 문의) in "
                 "info — they become an icon strip under the header.",
                 {"title": s,
                  "subtitle": {"type": "string"},
                  "highlight": {"type": "string", "description": "slogan or key message shown in a box"},
                  "sections": {"type": "array", "description": "2-4 recommended (max 6)",
                               "items": {"type": "object", "properties": {
                                   "heading": {"type": "string"},
                                   "bullets": {"type": "array", "items": {"type": "string"}},
                                   "icon": {"type": "string", "description": "Material Icons name"}}}},
                  "info": {"type": "array", "description": "key facts strip, max 4 (default: taken from short "
                                                          "'일시 / 장소 …' sections)",
                           "items": {"type": "object", "properties": {
                               "label": {"type": "string", "description": "e.g. '일시'"},
                               "text": {"type": "string"},
                               "icon": {"type": "string"}},
                               "required": ["text"]}},
                  "footer": {"type": "string", "description": "e.g. organizer · date · place"},
                  "sources": {"type": "array", "items": {"type": "string"}},
                  "theme": {"type": "string", "enum": ["light", "dark", "navy", "warm", "green", "purple", "teal", "rose",
                                                       "mono", "midnight", "forest"]},
                  "size": {"type": "string", "enum": ["a4", "a3"]},
                  "style": {"type": "string", "enum": ["clean", "bold", "gradient", "pastel"],
                            "description": "look, combined with theme: clean (default), bold (strong color band, big "
                                           "numbers), gradient (gradient background), pastel (soft colors)"},
                  "icon": {"type": "string", "description": "header icon (Material Icons name); default: picked from the title"},
                  "filename": s, "folder": s, "overwrite": {"type": "boolean"}, "open": {"type": "boolean"}},
                 ["title", "sections"]),
        ] + self.control_schemas(tool)

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
            "look_at_screen": lambda: "화면 분석" + (" · 번호 표시" if a.get("marks") else "") + (" · 활성 창" if a.get("target") == "window" else ""),
            "zoom_screen": lambda: "화면 확대",
            "read_screen_text": lambda: f"화면 글자 읽기 · {a.get('app') or '활성 창'}",
            "wait_screen": lambda: "화면이 멈출 때까지 대기",
            "read_ui": lambda: f"화면 읽기 · {a.get('app') or '활성 창'}" + (f" ({a['query']})" if a.get("query") else ""),
            "click_ui": lambda: f"클릭 · {a.get('name') or '#' + str(a.get('number'))}",
            "click_screen": lambda: f"화면 클릭 · ({a.get('x')}, {a.get('y')})",
            "scroll": lambda: f"스크롤 · {a.get('direction')}",
            "hover_screen": lambda: f"마우스 올리기 · ({a.get('x')}, {a.get('y')})",
            "drag_screen": lambda: f"끌어다 놓기 · ({a.get('x')}, {a.get('y')}) → ({a.get('to_x')}, {a.get('to_y')})",
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
            "todo_add": lambda: f"할 일 추가 · {str(a.get('text', ''))[:30]}",
            "todo_list": lambda: "할 일 목록",
            "todo_done": lambda: f"할 일 {'삭제' if a.get('remove') else '완료'} · {str(a.get('query', ''))[:30]}",
            "watch_app": lambda: f"작업 감시 · {a.get('name')}",
            "web_fetch": lambda: f"웹 페이지 읽기 · {str(a.get('url', ''))[:40]}",
            "sentinel_scan": lambda: f"Sentinel 검사 · {str(a.get('url', ''))[:40]}",
            "sentinel_report": lambda: "Sentinel 보고서 열기",
            "sentinel_status": lambda: "Sentinel 연결 확인",
            "make_presentation": lambda: f"PPT 만들기 · {str(a.get('title', ''))[:30]}",
            "make_document": lambda: f"문서 만들기 · {str(a.get('title', ''))[:30]}",
            "make_spreadsheet": lambda: f"엑셀 만들기 · {str(a.get('filename') or '표')[:30]}",
            "make_cardnews": lambda: f"카드뉴스 만들기 · {str(a.get('title', ''))[:30]}",
            "make_poster": lambda: f"포스터 만들기 · {str(a.get('title', ''))[:30]}",
            "web_search": lambda: f"웹 검색 · {a.get('query', '')}",
            **ControlTools.control_labels(a),
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

    def _confirm(self, title: str, detail: str, always: bool = False) -> None:
        """승인 카드. always=True 는 '위험 명령 자동 승인' 설정으로도 건너뛸 수 없는 확인 (사용자 본인만 답할 수 있는 것)."""
        if self.cfg["auto_approve"] and not always:
            return
        if not self.hooks.confirm(title, detail):
            raise ToolError("사용자가 실행을 거부했습니다.")

    # --- 앱/창 ---
    def t_open_app(self, name: str, min_score: float = 38) -> str:
        key = _norm(name)
        hit = self._find_app(name, min_score)
        before = {w["hwnd"] for w in winutil.list_windows()}
        if hit:
            subprocess.Popen(["explorer.exe", f"shell:AppsFolder\\{hit[1]}"], creationflags=NO_WINDOW)
            self._launch = (time.monotonic(), before, name)
            return f"'{hit[0]}' 실행함"
        exe = SYSTEM_EXE.get(key)
        if not exe and min_score > 38:
            raise ToolError(f"'{name}' 앱을 찾지 못했습니다.")   # 엄격 모드: 이름만으로 실행해 보지 않음
        target = exe or name
        try:
            os.startfile(target)
            self._launch = (time.monotonic(), before, name)
            return f"'{target}' 실행함"
        except OSError:
            if not self._apps:
                raise ToolError("앱 목록을 아직 불러오는 중입니다. 잠시 후 다시 시도하세요.")
            raise ToolError(f"'{name}' 앱을 찾지 못했습니다.")

    def _await_launch(self, timeout: float = 6.0) -> None:
        """방금 open_app 으로 켠 앱의 창이 뜰 때까지 기다렸다가 그 창을 '작업 창'으로 삼는다.
        앱을 켜자마자 입력 · 클릭하면 아직 창이 없어 예전 창에 들어가 버린다 — 화면을 만지는 도구들이 시작할 때 부른다.
        (open_app 자체는 기다리지 않는다: "메모장 열어" 는 바로 대답해야 하니까.)"""
        launch, self._launch = getattr(self, "_launch", None), None
        if not launch:
            return
        t0, before, name = launch
        if time.monotonic() - t0 > 8:
            return                                   # 한참 전에 켠 것 — 그새 사용자가 다른 창으로 갔을 수 있다
        had = bool(self._match_windows(name))        # 이미 열려 있던 앱이면 새 창이 안 뜰 수도 있다 (카톡처럼 창 하나짜리)
        limit = 2.5 if had else timeout
        while True:
            new = [w for w in winutil.list_windows() if w["hwnd"] not in before]
            if new:
                self.focus.last_external, self.focus.last_title = new[0]["hwnd"], new[0]["title"]
                if time.monotonic() - t0 < 1.5:
                    time.sleep(0.4)                  # 창이 막 떴다 — 안이 그려질 시간
                return
            if time.monotonic() - t0 >= limit:
                break
            time.sleep(0.2)
        hits = self._match_windows(name)
        if hits:
            winutil.force_foreground(hits[0]["hwnd"])
            self.focus.last_external, self.focus.last_title = hits[0]["hwnd"], hits[0]["title"]

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
        self._await_launch()                  # 방금 open_app 으로 켠 앱이면 그 창이 뜰 때까지
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
    def t_type_text(self, text: str, press_enter: bool = False, replace: bool = False) -> str:
        self._await_launch()                  # 방금 open_app 으로 켠 앱이면 그 창이 뜰 때까지
        self.focus.restore()
        old = winutil.get_clipboard_text()
        winutil.set_clipboard_text(text)
        time.sleep(0.05)
        if replace:                       # 칸에 있던 내용을 지우고 쓴다
            winutil.press_combo("ctrl+a")
            time.sleep(0.05)
        winutil.press_combo("ctrl+v")
        change = ""
        if press_enter:
            time.sleep(0.1)
            before = self._small()
            winutil.press_combo("enter")
            change = self._after(before)   # 엔터 뒤 화면이 바뀌었는지 (검색 · 전송 · 페이지 이동)
        else:
            time.sleep(0.3)
        try:
            winutil.set_clipboard_text(old)
        except Exception:
            pass
        return f"{len(text)}자 입력함 (대상 창: {self.focus.last_title[:40]})" + change

    def t_press_keys(self, keys: str, times: int = 1) -> str:
        self._await_launch()                  # 방금 open_app 으로 켠 앱이면 그 창이 뜰 때까지
        self.focus.restore()
        times = max(1, min(int(times or 1), 50))
        before = self._small()
        try:
            for _ in range(times):
                winutil.press_combo(keys)
                time.sleep(0.05)
        except ValueError as e:
            raise ToolError(str(e))
        return f"'{keys}' x{times} 입력함" + self._after(before, timeout=1.5, nochange_wait=0.6)

    # --- 화면 ---
    @contextlib.contextmanager
    def _hud_hidden(self):
        """캡처하는 동안 자비스 HUD 창들(작은 HUD + 액티브 모드 화면)을 캡처에서 뺀다."""
        hwnds = self.hooks.hud_hwnd()
        hwnds = hwnds if isinstance(hwnds, (list, tuple)) else [hwnds]
        for h in hwnds:
            winutil.set_capture_excluded(h, True)
        try:
            time.sleep(0.05)
            yield
        finally:
            for h in hwnds:
                winutil.set_capture_excluded(h, False)

    @contextlib.contextmanager
    def _hud_aside(self, x: int, y: int):
        """누를 자리가 자비스 HUD 창 밑이면, 그동안만 HUD 를 숨긴다.
        HUD 는 캡처에서 빠지므로 AI 는 HUD 밑의 화면을 보고 자리를 고른다 — 그대로 누르면 클릭이 HUD 로 들어가 버린다."""
        hwnds = self.hooks.hud_hwnd()
        hwnds = hwnds if isinstance(hwnds, (list, tuple)) else [hwnds]
        hidden = [h for h in hwnds if h and winutil.blocks_clicks(h, x, y)]
        for h in hidden:
            winutil.show_window(h, False)
        try:
            if hidden:
                time.sleep(0.12)
            yield
        finally:
            if hidden:
                time.sleep(0.15)          # 클릭이 밑의 창에 전달된 뒤에 다시 보인다
            for h in hidden:
                winutil.show_window(h, True)

    @staticmethod
    def _grab_raw(bbox: tuple[int, int, int, int] | None = None):
        """bbox(화면 좌표: 왼, 위, 오, 아래)를 캡처. None 이면 주 모니터 전체. 다른 모니터에 있는 영역도 찍힌다."""
        from PIL import ImageGrab
        return ImageGrab.grab(bbox=bbox, all_screens=True) if bbox else ImageGrab.grab()

    def _grab(self, bbox: tuple[int, int, int, int] | None = None):
        with self._hud_hidden():
            return self._grab_raw(bbox)

    # --- 화면 보기: 보낼 크기 · 좌표 대응 (vision.py) ---
    def set_vision_model(self, model: str | None) -> None:
        """지금 대화하는 모델 이름을 알려 준다 (두뇌가 호출). 모델 등급에 따라 화면을 얼마나 크게 보낼지 달라진다."""
        self.vision_model = str(model or "")

    def _tier(self) -> str:
        """화면을 보낼 크기 등급. 설정으로 '작게'를 고를 수는 있지만 모델이 받을 수 있는 크기보다 크게는 보내지 않는다
        (더 크게 보내면 서버가 다시 줄여 좌표가 어긋난다)."""
        if (self.cfg["screen_detail"] or "auto") == "standard":
            return "standard"
        return vision.tier_for_model(self.vision_model)

    def _active_hwnd(self) -> int:
        hwnd = self.focus.last_external
        return hwnd if hwnd and winutil.user32.IsWindow(hwnd) else 0

    def _shoot(self, bbox: tuple[int, int, int, int] | None, kind: str, zoom: bool = False):
        """bbox 를 찍어 모델이 다시 줄이지 않을 크기로 맞춘다 → (이미지, 좌표 대응)."""
        from PIL import Image
        img = self._grab(bbox).convert("RGB")
        if bbox is None:
            bbox = (0, 0, img.width, img.height)
        size = (vision.zoom_size if zoom else vision.send_size)(img.width, img.height, self._tier())
        if size != img.size:
            img = img.resize(size, Image.LANCZOS)
        return img, vision.make_view(bbox, img.size, kind)

    @staticmethod
    def _image_blocks(img, text: str) -> list[dict]:
        data, media = vision.encode(img)
        return [{"type": "image", "source": {"type": "base64", "media_type": media, "data": data}},
                {"type": "text", "text": text}]

    def _small(self):
        """화면 변화 비교용 축소 화면 (실패하면 None — 변화 확인을 건너뛴다)."""
        try:
            return vision.small_gray(self._grab(winutil.monitor_rect(self._active_hwnd())))
        except Exception as e:
            log.debug("화면 변화 확인용 캡처 실패: %s", e)
            return None

    def _after(self, before, timeout: float = 2.5, nochange_wait: float = 1.0) -> str:
        """동작 뒤 화면이 멈출 때까지 기다리고, 바뀌었는지를 결과 글 뒤에 붙일 말로 돌려준다."""
        self._moved = False
        if before is None:
            time.sleep(0.5)
            return ""
        try:
            bbox = winutil.monitor_rect(self._active_hwnd())
            with self._hud_hidden():
                ch = vision.settle(lambda: vision.small_gray(self._grab_raw(bbox)), before, timeout=timeout,
                                   nochange_wait=nochange_wait)
            self._moved = not ch.settled or ch.fraction * ch.cells >= vision.TINY_CELLS
            return " · " + ch.text()
        except Exception as e:
            log.debug("화면 변화 확인 실패: %s", e)
            time.sleep(0.5)
            return ""

    def _follow(self) -> bool:
        """방금 동작으로 화면이 바뀌었고, 바뀐 화면을 결과에 같이 보내도록 설정돼 있는가."""
        return bool(getattr(self, "_moved", False)) and self.cfg["screen_follow"] is not False

    def _follow_ui(self) -> str:
        """누른 뒤 바뀐 창의 요소 목록 — AI 가 read_ui 를 다시 부르지 않아도 다음 단계를 고를 수 있다."""
        if not self._follow() or not self.screen.hwnd:
            return ""
        try:
            lines = self.screen.read(self.screen.hwnd).splitlines()
        except Exception as e:
            log.debug("누른 뒤 요소 다시 읽기 실패: %s", e)
            return ""
        if len(lines) > 42:
            lines = lines[:42] + ["…(이하 생략 — read_ui 에 query 를 주면 좁혀 볼 수 있음)"]
        return "\n\n누른 뒤의 화면입니다 (번호가 새로 매겨졌으니 이 목록의 번호를 쓰세요):\n" + "\n".join(lines)

    def _target_bbox(self, target: str) -> tuple[tuple[int, int, int, int] | None, str]:
        hwnd = self._active_hwnd()
        if target == "window":
            wr, mon = winutil.window_rect(hwnd), winutil.monitor_rect(hwnd)
            if wr and mon:   # 창이 화면 밖으로 걸쳐 있으면 보이는 부분만
                wr = (max(wr[0], mon[0]), max(wr[1], mon[1]), min(wr[2], mon[2]), min(wr[3], mon[3]))
            if wr and wr[2] - wr[0] >= 40 and wr[3] - wr[1] >= 40:
                return wr, "window"
        return winutil.monitor_rect(hwnd), "screen"      # 사용자의 작업 창이 있는 모니터 (모르면 주 모니터)

    def t_look_at_screen(self, target: str = "screen", marks: bool = False):
        self._await_launch()                  # 방금 open_app 으로 켠 앱이면 그 창이 뜰 때까지
        hwnd = self._active_hwnd()
        bbox, kind = self._target_bbox(target)
        self._view_target = kind
        img, view = self._shoot(bbox, kind)
        self._view = view
        note = ""
        if marks:
            try:
                if not hwnd:
                    raise ToolError("활성 창을 알 수 없습니다")
                self.screen.read(hwnd)
                picked = vision.pick_marks([(it.n, it.rect) for it in self.screen.items], view)
                if picked:
                    img = vision.annotate(img, picked)
                    shown = {n for n, _ in picked}
                    rest = len(self.screen.items) - len(shown)
                    note = ("\n번호 상자 = 누를 수 있는 요소. click_ui 에 그 번호를 넘기세요 (좌표보다 정확함):\n"
                            + "\n".join(it.line() for it in self.screen.items if it.n in shown)
                            + (f"\n(화면 밖이거나 겹쳐서 표시하지 않은 요소 {rest}개 — read_ui 로 볼 수 있음)" if rest > 0 else ""))
                else:
                    note = "\n(이 창에서는 누를 수 있는 요소를 읽지 못했습니다. 좌표로 click_screen 을 쓰세요)"
            except Exception as e:
                note = f"\n(요소 번호를 표시하지 못했습니다: {e}. 좌표로 click_screen 을 쓰세요)"
        what = "활성 창" if kind == "window" else "화면"
        return self._image_blocks(img, (
            f"사용자 {what} 캡처 — 이미지 크기 {img.width}x{img.height} 픽셀. click_screen · zoom_screen · point_at 의 좌표는 "
            f"이 이미지의 픽셀 좌표입니다. 활성 창: {self.focus.last_title}{note}"))

    def t_zoom_screen(self, x: int, y: int, width: int, height: int):
        if self._view is None:
            raise ToolError("먼저 look_at_screen 으로 화면을 보세요.")
        left, top, right, bottom = self._view.rect_to_screen(x, y, width, height)
        if right - left < 8 or bottom - top < 8:
            raise ToolError("확대할 영역이 너무 작습니다. 조금 더 넓게 잡으세요.")
        img, view = self._shoot((left, top, right, bottom), "zoom", zoom=True)
        self._view = view
        return self._image_blocks(img, (
            f"확대한 영역 — 이미지 크기 {img.width}x{img.height} 픽셀. 이제 click_screen · point_at · zoom_screen 의 좌표는 "
            "이 확대 이미지의 픽셀 좌표입니다. 전체 화면으로 돌아가려면 look_at_screen 을 다시 부르세요."))

    def t_read_screen_text(self, app: str | None = None, all: bool = False) -> str:   # noqa: A002
        self._await_launch()                  # 방금 open_app 으로 켠 앱이면 그 창이 뜰 때까지
        hwnd = self._target_window(app)
        try:
            return self.screen.read_text(hwnd, include_offscreen=bool(all))
        except OSError as e:
            raise ToolError(f"창의 글자를 읽지 못했습니다: {e}")

    def t_wait_screen(self, max_seconds: int = 5) -> str:
        self._await_launch()                  # 방금 open_app 으로 켠 앱이면 그 창이 뜰 때까지
        before = self._small()
        if before is None:
            time.sleep(1.0)
            return "1초 기다렸습니다."
        limit = max(1.0, min(float(max_seconds or 5), 15.0))
        bbox = winutil.monitor_rect(self._active_hwnd())
        with self._hud_hidden():
            ch = vision.settle(lambda: vision.small_gray(self._grab_raw(bbox)), before, timeout=limit, interval=0.25,
                               quiet=3, nochange_wait=1.2)
        if ch.settled:
            return f"화면이 멈췄습니다 ({ch.seconds:.1f}초 기다림)."
        return f"{ch.seconds:.0f}초를 기다렸지만 화면이 계속 바뀌고 있습니다 (동영상이거나 아직 불러오는 중)."

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
        self._await_launch()                  # 방금 open_app 으로 켠 앱이면 그 창이 뜰 때까지
        hwnd = self._target_window(app)
        try:
            out = self.screen.read(hwnd, query or "")
        except OSError as e:
            raise ToolError(f"창 내용을 읽지 못했습니다: {e}")
        q = uia._norm(query or "")
        # 찾는 것이 보이는 곳에 없을 때만 화면 밖을 한 번 더 뒤진다 (창 전체를 다시 읽는 일이라 크롬에서는 1초쯤 걸린다)
        if q and not any(q in uia._norm(it.name) for it in self.screen.items):
            names = list(dict.fromkeys(it.name for it in self.screen.find_hidden(hwnd, query)))[:5]
            if names:
                out += ("\n화면 밖(스크롤해야 보이는 곳)에 있는 요소: " + ", ".join(f"'{n[:40]}'" for n in names)
                        + " — click_ui 에 name 으로 넘기면 그곳으로 스크롤해서 누릅니다.")
        return out

    def _reveal(self, name: str):
        """이름이 맞는 요소가 화면 밖에 있으면 그곳으로 스크롤한 뒤, 보이게 된 요소를 돌려준다 (없으면 None)."""
        hwnd = self.screen.hwnd or self._active_hwnd()
        if not hwnd:
            return None
        for hidden in self.screen.find_hidden(hwnd, name)[:1]:
            if not self.screen.reveal(hidden):
                return None
            time.sleep(0.4)
            self.screen.read(hwnd)
            return self.screen.find(None, name)
        return None

    def t_click_ui(self, number: int | None = None, name: str | None = None, double: bool = False) -> str:
        if not number and not name:
            raise ToolError("number 나 name 중 하나가 필요합니다.")
        it = self.screen.find(number, name or "")
        if it is None and name and self.screen.hwnd:
            # 목록이 오래됐을 수 있으니 같은 창을 다시 읽고 이름으로 한 번 더 찾는다
            self.screen.read(self.screen.hwnd)
            it = self.screen.find(None, name)
        if it is None and name:
            it = self._reveal(name)      # 스크롤해야 보이는 곳에 있으면 그곳으로 가서 누른다
        if it is None:
            raise ToolError("그 요소를 찾지 못했습니다. read_ui 로 목록을 다시 확인하세요.")
        if uia.is_risky(it.name):
            self._confirm("화면 클릭", f"'{it.name}' {it.kind} 을(를) 누릅니다.\n창: {self.screen.title}")
        before = self._small()
        left, top, right, bottom = it.rect
        try:
            with self._hud_aside((left + right) // 2, (top + bottom) // 2):
                out = self.screen.click(it, double=bool(double))
        except Exception as e:   # 페이지가 바뀌어 요소가 사라진 경우 등
            raise ToolError(f"누르지 못했습니다 ({e}). read_ui 로 다시 확인하세요.")
        change = self._after(before)     # 화면이 멈출 때까지 기다리고, 바뀌었는지 알려 준다
        return out + f" · 창: {winutil.window_title(self.screen.hwnd) or self.screen.title}" + change + self._follow_ui()

    def t_click_screen(self, x: int, y: int, double: bool = False, right: bool = False) -> str:
        view = self._view
        if view is None:
            raise ToolError("먼저 look_at_screen 으로 화면을 보세요 (좌표는 마지막으로 본 이미지 기준입니다).")
        if not view.contains(x, y):
            raise ToolError(f"좌표 ({x}, {y}) 가 마지막으로 본 이미지({view.w}x{view.h}) 밖입니다. 그 이미지 안의 좌표를 주세요.")
        sx, sy = view.to_screen(x, y)
        with self._hud_aside(sx, sy):
            name, kind = uia.element_at(sx, sy)  # 그 자리에 무엇이 있는지 (모르면 빈 값)
        if name and uia.is_risky(name):          # 좌표로 눌러도 결제 · 삭제 · 전송 같은 버튼은 승인을 받는다 (카드는 HUD 에 뜬다)
            self._confirm("화면 클릭", f"'{name}' {kind or '요소'} 을(를) 누릅니다.\n위치: ({sx}, {sy})")
        before = self._small()
        with self._hud_aside(sx, sy):
            uia.click_at(sx, sy, double=bool(double), right=bool(right))
        what = f"'{name[:40]}' {kind}".strip() if name else f"({sx}, {sy})"
        text = f"{what} 클릭함" + self._after(before)
        if self._follow():
            # 바뀐 화면을 바로 보여 준다 — 어차피 다시 보러 올 것을 한 번의 왕복으로 줄인다
            try:
                bbox, kind = self._target_bbox(getattr(self, "_view_target", "screen"))
                img, self._view = self._shoot(bbox, kind)
                return self._image_blocks(img, (
                    f"{text}\n누른 뒤의 화면입니다 — 이미지 크기 {img.width}x{img.height} 픽셀. "
                    "이제 click_screen · zoom_screen · point_at 의 좌표는 이 이미지 기준입니다."))
            except Exception as e:
                log.debug("누른 뒤 화면 캡처 실패: %s", e)
        return text

    def _on_view(self, x: int, y: int) -> tuple[int, int]:
        """마지막으로 본 이미지의 좌표 → 화면 좌표 (화면을 본 적이 없거나 이미지 밖이면 오류)."""
        view = self._view
        if view is None:
            raise ToolError("먼저 look_at_screen 으로 화면을 보세요 (좌표는 마지막으로 본 이미지 기준입니다).")
        if not view.contains(x, y):
            raise ToolError(f"좌표 ({x}, {y}) 가 마지막으로 본 이미지({view.w}x{view.h}) 밖입니다. 그 이미지 안의 좌표를 주세요.")
        return view.to_screen(x, y)

    def _shown(self, text: str):
        """동작 결과 글 + (화면이 바뀌었으면) 바뀐 화면 캡처."""
        if self._follow():
            try:
                bbox, kind = self._target_bbox(getattr(self, "_view_target", "screen"))
                img, self._view = self._shoot(bbox, kind)
                return self._image_blocks(img, (
                    f"{text}\n바뀐 화면입니다 — 이미지 크기 {img.width}x{img.height} 픽셀. "
                    "이제 좌표는 이 이미지 기준입니다."))
            except Exception as e:
                log.debug("바뀐 화면 캡처 실패: %s", e)
        return text

    def t_hover_screen(self, x: int, y: int):
        sx, sy = self._on_view(x, y)
        before = self._small()
        with self._hud_aside(sx, sy):
            uia.move_to(sx, sy)
            text = f"({sx}, {sy}) 에 마우스를 올려놓음" + self._after(before, timeout=1.5, nochange_wait=0.7)
            return self._shown(text)

    def t_drag_screen(self, x: int, y: int, to_x: int, to_y: int):
        sx, sy = self._on_view(x, y)
        ex, ey = self._on_view(to_x, to_y)
        before = self._small()
        with self._hud_aside(sx, sy), self._hud_aside(ex, ey):
            uia.drag(sx, sy, ex, ey)
        return self._shown(f"({sx}, {sy}) 에서 ({ex}, {ey}) 까지 끌어다 놓음" + self._after(before))

    def t_scroll(self, direction: str, amount: int = 5, app: str | None = None,
                 x: int | None = None, y: int | None = None) -> str:
        if direction not in ("up", "down"):
            raise ToolError("direction 은 up 또는 down")
        hwnd = self._target_window(app)
        before = self._small()
        if x is not None and y is not None:      # 화면 안의 특정 영역(목록 · 채팅창)만 굴릴 때: 그 자리에서 휠
            at = self._on_view(x, y)
        else:
            wr = winutil.window_rect(hwnd)       # 휠은 창 한가운데에서 굴린다 — 그 자리를 HUD 가 덮고 있으면 비켜 준다
            at = ((wr[0] + wr[2]) // 2, (wr[1] + wr[3]) // 2) if wr else (-1, -1)
        with self._hud_aside(*at):
            uia.scroll(hwnd, direction, amount or 5, at=at if x is not None and y is not None else None)
        change = self._after(before, timeout=1.5, nochange_wait=0.6)   # 변화가 없으면 끝까지 간 것일 수 있다
        return f"{'위' if direction == 'up' else '아래'}로 스크롤함" + change

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

    # ------------------------------------------------------------------ 작업 결과물 (발표 자료 · 보고서 · 표 — office.py)
    def _work_folder(self, folder: str = "") -> Path:
        """결과물을 저장할 폴더. 기본은 문서\\JARVIS. '바탕화면' · '문서' · '다운로드' 같은 이름이나 전체 경로를 받는다."""
        f = (folder or "").strip()
        if not f:
            return (winutil.known_folder("문서") or Path.home() / "Documents") / "JARVIS"
        known = winutil.known_folder(f)
        if known:
            return known
        p = Path(os.path.expandvars(os.path.expanduser(f)))
        if p.is_absolute():
            return p
        raise ToolError(f"저장할 폴더 '{folder}'를 알 수 없습니다. '바탕화면' · '문서' · '다운로드' 또는 전체 경로를 주세요.")

    def _where(self, path: Path) -> str:
        """말로 읽기 좋은 저장 위치 — '문서의 JARVIS 폴더', '바탕화면' (전체 경로를 소리 내어 읽지 않게)."""
        for name, label in (("바탕화면", "바탕화면"), ("다운로드", "다운로드 폴더"), ("문서", "문서")):
            base = winutil.known_folder(name)
            if not base:
                continue
            try:
                rel = Path(path).parent.relative_to(base)
            except ValueError:
                continue
            return label if not rel.parts else f"{label}의 {' › '.join(rel.parts)} 폴더"
        return f"'{Path(path).parent.name}' 폴더"

    def _make_file(self, build, name: str, ext: str, folder: str, overwrite: bool, open_after: bool):
        """build(경로) 로 파일을 만들고 연다 → (경로, 정보, 덧붙일 말).
        같은 이름의 파일이 열려 있어 덮어쓰지 못하면 새 이름으로 저장한다."""
        from . import office
        place = self._work_folder(folder)
        note = ""
        try:
            path = office.target(place, name, ext, bool(overwrite))
            try:
                info = build(path)
            except PermissionError:
                if not overwrite:
                    raise
                path = office.target(place, name, ext, False)
                info = build(path)
                note = " 원래 파일이 열려 있어 새 이름으로 저장했습니다."
        except ImportError as e:
            lib = {"pptx": "python-pptx", "docx": "python-docx", "xlsxwriter": "XlsxWriter", "PIL": "Pillow"}.get(e.name or "", e.name)
            raise ToolError(f"파일을 만드는 라이브러리({lib})가 설치되어 있지 않습니다. setup.bat 를 다시 실행해 설치하세요.")
        except PermissionError as e:
            raise ToolError(f"'{place}' 에 저장하지 못했습니다 (권한이 없거나 파일이 열려 있음): {e}")
        except ValueError as e:
            raise ToolError(str(e))
        if open_after is not False:
            try:
                os.startfile(str(path))
                note += " 파일을 열었습니다."
            except (OSError, AttributeError):
                note += " 파일을 열 프로그램을 찾지 못해 열지는 못했습니다."
        log.info("작업 결과물 저장: %s %s", path, info)
        return path, info, note

    def _team(self, kind: str, brief: dict, items: list) -> tuple[list, list, str]:
        """본문이 없는 장을 작가 여러 명에게 나눠 맡긴다 (자비스가 Claude 에 연결돼 있을 때) → (장들, 작가가 쓴 출처, 덧붙일 말).
        작가를 쓸 수 없거나 실패하면 받은 그대로 만든다."""
        writer = getattr(self, "writer", None)
        if writer is None or not isinstance(items, list):
            return items, [], ""
        try:
            out, info = writer(kind, brief, items)
        except Exception as e:
            log.warning("작가에게 맡기지 못함: %s", e)
            return items, [], ""
        if not info.get("written"):
            if info.get("asked") and info.get("writers"):       # 한 장도 못 썼다 (연결 문제 등) — 빈 파일을 만들지 않는다
                raise ToolError("작가들이 응답하지 않았습니다. 이번에는 장마다 본문(bullets · steps · events · cards · table …)과 "
                                "notes 를 직접 채워서 같은 도구를 다시 부르세요.")
            return out, [], ""
        found = f" 조사 담당이 찾은 자료 {info['researched']}건을 바탕으로," if info.get("researched") else ""
        note = f"{found} 작가 {info['writers']}명이 나눠 썼습니다 ({info['seconds']:.0f}초)."
        missing = set(info.get("missing") or [])
        if missing:                                             # 끝내 못 쓴 장: 개요(points)라도 있으면 그대로 넣고, 제목뿐이면 뺀다
            kept = [it for i, it in enumerate(out, 1) if i not in missing or (isinstance(it, dict) and it.get("points"))]
            note += f" {len(missing)}장은 쓰지 못해 " + ("개요만 넣었습니다." if len(kept) == len(out) else "뺐습니다.")
            out = kept
        return out, info.get("sources") or [], note

    def t_make_presentation(self, title: str, slides: list, subtitle: str = "", sources: list | None = None,
                            theme: str = "", agenda: bool | None = None, filename: str = "", folder: str = "",
                            overwrite: bool = False, open: bool = True, style: str = "", audience: str = "",
                            facts: list | None = None, icon: str = "", **_extra) -> str:
        from . import office, writers                 # (_extra: 모델이 덧붙인 모르는 칸은 무시한다 — 그 때문에 다시 부르게 하지 않는다)
        slides, found, team = self._team("slides", {"title": title, "subtitle": subtitle, "audience": audience,
                                                    "facts": facts}, slides)
        refs = writers.merge_sources(sources, found)
        look = office.pick_style(style, str(title), str(audience or subtitle or ""), getattr(self, "_last_style", ""))
        self._last_style = look                       # 다음 발표 자료는 다른 디자인으로
        color = office.pick_theme(theme, look, str(title))
        path, info, note = self._make_file(
            lambda p: office.build_presentation(p, title, slides, subtitle, refs, color, agenda, look, icon=icon or None),
            filename or title, ".pptx", folder, overwrite, open)
        talk = f", 발표 대본 {info['notes']}장" if info["notes"] else ""
        split = f", 글이 넘친 {info['split']}곳은 다음 장으로 나눔" if info["split"] else ""
        cited = f", 출처 {len(refs)}건" if refs else ""
        return (f"발표 자료를 만들었습니다 — 표지 포함 {info['slides']}장{talk}{cited}{split}, 디자인은 '{office.STYLE_NAMES[look]}' "
                f"스타일.{team} 저장한 곳: {self._where(path)} (파일 이름 {path.name}).{note} [전체 경로: {path}]")

    def t_make_document(self, title: str, sections: list, subtitle: str = "", sources: list | None = None,
                        filename: str = "", folder: str = "", overwrite: bool = False, open: bool = True,
                        audience: str = "", facts: list | None = None, format: str = "docx", summary=None,
                        icon: str = "", **_extra) -> str:
        from . import hwpx, office, writers
        hangul = str(format or "").strip().lower() in ("hwpx", "hwp", "한글", "한컴")
        sections, found, team = self._team("document", {"title": title, "subtitle": subtitle, "audience": audience,
                                                        "facts": facts}, sections)
        refs = writers.merge_sources(sources, found)
        path, info, note = self._make_file(
            lambda p: (hwpx.build_hwpx(p, title, sections, subtitle, refs, summary=summary) if hangul
                       else office.build_document(p, title, sections, subtitle, refs, summary=summary, icon=icon or None)),
            filename or title, ".hwpx" if hangul else ".docx", folder, overwrite, open)
        if hangul and "열 프로그램을 찾지 못해" in note:
            note += " 한컴오피스 한글이나 무료 '한컴오피스 뷰어'가 있으면 열 수 있습니다."
        tables = f", 표 {info['tables']}개" if info["tables"] else ""
        kind = "한글 문서" if hangul else "문서"
        return (f"{kind}를 만들었습니다 — 장 {info['sections']}개{tables}.{team} 저장한 곳: {self._where(path)} "
                f"(파일 이름 {path.name}).{note} [전체 경로: {path}]")

    def t_make_spreadsheet(self, sheets: list, filename: str = "", folder: str = "", overwrite: bool = False,
                           open: bool = True, **_extra) -> str:
        from . import office
        first = sheets[0] if isinstance(sheets, list) and sheets and isinstance(sheets[0], dict) else {}
        name = filename or first.get("title") or first.get("name") or "표"
        path, info, note = self._make_file(lambda p: office.build_spreadsheet(p, sheets), name, ".xlsx", folder,
                                           overwrite, open)
        return (f"엑셀 파일을 만들었습니다 — 시트 {info['sheets']}개, {info['rows']}행. 저장한 곳: {self._where(path)} "
                f"(파일 이름 {path.name}).{note} [전체 경로: {path}]")

    def t_make_cardnews(self, title: str, cards: list, subtitle: str = "", closing: str = "", sources: list | None = None,
                        theme: str = "light", filename: str = "", folder: str = "", overwrite: bool = False,
                        open: bool = True, style: str = "clean", icon: str = "", **_extra) -> str:
        from . import design
        path, info, note = self._make_file(
            lambda p: design.build_cardnews(p, title, cards, subtitle, closing, sources, theme, style=style, icon=icon),
            filename or f"{title} 카드뉴스", "", folder, overwrite, open)
        return (f"카드뉴스를 만들었습니다 — {info['cards']}장 (표지 · 마무리 포함, 그림 파일과 한 묶음 PDF). "
                f"저장한 곳: {self._where(path)} 안의 '{path.name}' 폴더.{note} [전체 경로: {path}]")

    def t_make_poster(self, title: str, sections: list | None = None, subtitle: str = "", highlight: str = "",
                      footer: str = "", sources: list | None = None, theme: str = "light", size: str = "a4",
                      filename: str = "", folder: str = "", overwrite: bool = False, open: bool = True,
                      style: str = "clean", icon: str = "", info: list | None = None, **_extra) -> str:
        from . import design
        path, made, note = self._make_file(
            lambda p: design.build_poster(p, title, sections or [], subtitle, highlight, footer, sources, theme, size,
                                          style=style, icon=icon, info=info),
            filename or title, ".png", folder, overwrite, open)
        return (f"포스터를 만들었습니다 — {str(size or 'a4').upper()} 세로, 구역 {made['sections']}개 (그림 파일과 인쇄용 PDF). "
                f"저장한 곳: {self._where(path)} (파일 이름 {path.name}).{note} [전체 경로: {path}]")

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
        view = self._view
        if view is None:
            raise ToolError("먼저 look_at_screen 으로 화면을 보세요.")
        if width and height:
            left, top, right, bottom = view.rect_to_screen(x, y, width, height)
            px, py, pw, ph = left, top, right - left, bottom - top
        else:
            (px, py), pw, ph = view.to_screen(x, y), 0, 0
        ok = self.hooks.point_at(int(px), int(py), int(pw), int(ph), str(label or "")[:30])
        if not ok:
            raise ToolError("액티브 모드가 꺼져 있어 화면에 표시하지 못했습니다. 위치를 말로 설명하세요.")
        return "화면에 표시함"

    def t_read_clipboard(self) -> str:
        t = winutil.get_clipboard_text()
        return t[:8000] if t else "(클립보드에 텍스트가 없습니다)"

    def t_write_clipboard(self, text: str) -> str:
        winutil.set_clipboard_text(text)
        return "클립보드에 복사함"


    # --- Sentinel 웹 보안 분석기 ---
    def _ask_user(self, title: str, detail: str) -> bool:
        """사용자에게 직접 묻는다 — 자동 승인 설정과 상관없이 항상 카드를 띄운다."""
        return bool(self.hooks.confirm(title, detail))

    def t_sentinel_scan(self, url: str, basis: str = "", purpose: str = "") -> str:
        try:
            text, scan_id = sentinel.run_scan(
                self.sentinel, str(url), str(basis or self.cfg["sentinel_basis"] or "owner"), str(purpose or ""),
                confirm=self._ask_user,
                feed=lambda state: self.hooks.feed("sentinelJson", json.dumps(state, ensure_ascii=False)),
                notify=self.hooks.notify)
        except sentinel.SentinelError as e:
            raise ToolError(str(e))
        self._sentinel_last = scan_id
        return text

    def t_sentinel_report(self) -> str:
        if not self._sentinel_last:
            raise ToolError("이번에 요청한 Sentinel 검사가 없습니다. 먼저 검사를 요청해 주세요.")
        try:
            html = self.sentinel.report_html(self._sentinel_last)
        except sentinel.SentinelError as e:
            raise ToolError(str(e))
        folder = DATA_DIR / "sentinel"
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"sentinel-{self._sentinel_last}.html"
        path.write_bytes(sentinel.harden_html(html))   # 보고서 안의 스크립트 · 외부 요청은 막아 두고 연다
        os.startfile(str(path))
        return "Sentinel 보고서를 열었습니다."

    def t_sentinel_status(self) -> str:
        try:
            self.sentinel.ping()
            return f"Sentinel 연결 정상입니다. 서버는 {self.sentinel.base()}."
        except sentinel.SentinelError as e:
            raise ToolError(str(e))

    # --- 할 일 (todos.py) ---
    def t_todo_add(self, text: str, due: str = "") -> str:
        d = None
        if due:
            try:
                d = dt.date.fromisoformat(str(due)[:10])
            except ValueError:
                try:
                    d, _ = todos.parse_due(str(due))
                except todos.BadDate as e:
                    raise ToolError(str(e))
                if d is None:
                    raise ToolError(f"마감 날짜 '{due}'를 알 수 없습니다. YYYY-MM-DD 로 주세요.")
        try:
            t = todos.store().add(text, d)
        except ValueError as e:
            raise ToolError(str(e))
        return f"할 일 저장: {t.text} · 마감 {todos.due_words(t.due_date)}" + (f" ({t.due})" if t.due else "")

    def t_todo_list(self, scope: str = "all") -> str:
        ok = ("all", "today", "tomorrow", "week", "next_week")
        return todos.speak_list(todos.store(), scope if scope in ok else "all")

    def t_todo_done(self, query: str, remove: bool = False) -> str:
        st = todos.store()
        t = st.remove(query) if remove else st.complete(query)
        if t is None:
            names = ", ".join(x.text for x in st.open_items()[:10]) or "없음"
            raise ToolError(f"'{query}'에 맞는 할 일이 하나로 정해지지 않습니다. 남은 할 일: {names}")
        return f"'{t.text}' " + ("삭제함" if remove else "완료 표시함")

    def t_remember(self, fact: str) -> str:
        mem = load_memory()
        mem.append(f"{fact} (기록: {dt.date.today():%Y-%m-%d})")
        save_memory(mem)
        return "기억했습니다."
