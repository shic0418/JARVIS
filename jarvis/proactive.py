"""먼저 말 거는 자비스 — 부르지 않아도 알려 줄 일이 생기면 먼저 말한다.

· 배터리: 충전기 없이 20% 아래로 떨어지면 한 번, 10% 아래면 한 번 더 (충전기를 꽂거나 30% 위로 오르면 다시 준비)
· 할 일 마감: 오늘 마감은 오전 9시 뒤에, 내일 마감은 저녁 7시 뒤에 하루 한 번씩 (todos.py)
· 일정: 캘린더가 연결돼 있으면 일정 시작 10분 전에 한 번 (agenda.py — 받아 둔 캘린더만 보고, 새로 받기는 뒤에서)
· 아침 브리핑: 그날 처음 자비스를 쓸 때(오전) 날짜 · 날씨 · 오늘 일정 · 안 읽은 메일 · 오늘 할 일을 한 번에
· 조용한 시간(기본 23시~7시)에는 말하지 않고, 자리를 비운 동안(입력 없음 10분)에는 할 일 알림을 미뤘다가 돌아오면 알린다

판단은 순수 함수에 가깝게 두고(시각 · 배터리 · 입력 없는 시간을 받아 할 말을 돌려줌) 말하기는 app.py 가 한다.
무엇을 이미 알렸는지는 data/proactive.json 에 남겨 자비스를 다시 켜도 같은 알림을 되풀이하지 않는다.
"""
from __future__ import annotations

import datetime as dt
import json
import logging
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from . import persona, todos
from .agenda import time_words
from .config import DATA_DIR

log = logging.getLogger("jarvis.proactive")

STATE_PATH = DATA_DIR / "proactive.json"
TODAY_REMIND_HOUR = 9        # 오늘 마감 알림은 이 시각 뒤에
TOMORROW_REMIND_HOUR = 19    # 내일 마감 알림은 이 시각 뒤에
BRIEFING_HOURS = (5, 12)     # 아침 브리핑을 하는 시간대 [시작, 끝)
AWAY_SECONDS = 600           # 이만큼 입력이 없으면 자리를 비운 것으로 보고 할 일 알림을 미룬다
BRIEF_ACTIVE_SECONDS = 120   # 아침 브리핑은 방금 PC 를 쓴 흔적이 있을 때만 (켜 둔 채 자는 동안 말하지 않게)
BATTERY_CRITICAL = 10
BATTERY_REARM = 10           # 경고 기준보다 이만큼 더 차오르면 다시 경고할 수 있다
KEEP_DAYS = 7


@dataclass
class Event:
    kind: str                # battery | todo_today | todo_tomorrow | event
    text: str
    speak: bool = True       # False 면 화면 알림만 (조용한 시간)


def parse_quiet(spec) -> tuple[int, int] | None:
    """'23-7' → (23, 7). 비었거나 잘못되면 None (조용한 시간 없음)."""
    try:
        a, b = (int(x) for x in str(spec).replace("~", "-").split("-"))
    except (TypeError, ValueError):
        return None
    if not (0 <= a <= 23 and 0 <= b <= 23) or a == b:
        return None
    return a, b


def in_quiet(hour: int, spec) -> bool:
    q = parse_quiet(spec)
    if q is None:
        return False
    a, b = q
    return a <= hour < b if a < b else (hour >= a or hour < b)


class Proactive:
    def __init__(self, cfg, store_fn: Callable[[], todos.TodoStore] = todos.store, path: Path = STATE_PATH,
                 agenda=None) -> None:
        self.cfg = cfg
        self.agenda = agenda         # agenda.Agenda (없으면 일정 알림을 하지 않는다)
        self.store_fn = store_fn
        self.path = path
        self._lock = threading.Lock()
        self._bat_warned = False
        self._bat_critical = False
        self.state: dict = {"briefing": "", "reminded": {}}
        try:
            d = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(d, dict):
                self.state["briefing"] = str(d.get("briefing", ""))
                self.state["reminded"] = {str(k): str(v) for k, v in dict(d.get("reminded", {})).items()}
        except FileNotFoundError:
            pass
        except Exception as e:
            log.warning("먼저 말 걸기 기록을 읽을 수 없습니다: %s", e)

    # ------------------------------------------------------------------ 설정
    def _on(self, key: str) -> bool:
        return self.cfg[key] is not False

    def _warn_level(self) -> int:
        try:
            return max(5, min(50, int(self.cfg["battery_warn"])))
        except (TypeError, ValueError):
            return 20

    def _save(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            todos.write_atomic(self.path, json.dumps(self.state, ensure_ascii=False))
        except OSError as e:
            log.warning("먼저 말 걸기 기록 저장 실패: %s", e)

    def _mark(self, key: str, day: dt.date) -> None:
        cutoff = (day - dt.timedelta(days=KEEP_DAYS)).isoformat()
        rem = {k: v for k, v in self.state["reminded"].items() if v >= cutoff}
        rem[key] = day.isoformat()
        self.state["reminded"] = rem
        self._save()

    # ------------------------------------------------------------------ 주기 확인
    def check(self, now: dt.datetime, battery: tuple[float, bool] | None = None,
              idle_seconds: float | None = None) -> list[Event]:
        """지금 먼저 말할 것들. 1분마다 부른다. 돌려준 알림은 이미 알린 것으로 기록된다."""
        if not self._on("proactive"):
            return []
        with self._lock:
            quiet = in_quiet(now.hour, self.cfg["quiet_hours"])
            out: list[Event] = []
            ev = self._battery(battery, quiet)
            if ev:
                out.append(ev)
            out.extend(self._event_events(now, quiet))
            if not quiet and (idle_seconds is None or idle_seconds < AWAY_SECONDS):
                out.extend(self._todo_events(now))
            return out

    def _lead_minutes(self) -> int:
        try:
            return max(1, min(120, int(self.cfg["event_remind_minutes"])))
        except (TypeError, ValueError):
            return 10

    def _event_events(self, now: dt.datetime, quiet: bool) -> list[Event]:
        """곧 시작하는 일정. 시각이 정해진 알림이라 자리를 비웠어도 미루지 않는다 (조용한 시간에는 화면 알림만)."""
        ag = self.agenda
        if ag is None or not self._on("event_reminders"):
            return []
        try:
            if not ag.calendar_on():
                return []
            ag.refresh_async()                       # 네트워크는 뒤에서 — 여기서는 받아 둔 것만 본다
            evs = ag.cached_events(now.date(), 2) or []
        except Exception as e:
            log.warning("일정을 확인할 수 없습니다: %s", type(e).__name__)
            return []
        title = self.cfg["user_title"] or "주인님"
        out = []
        for ev in evs:
            left = (ev.start - now).total_seconds() / 60
            if ev.all_day or not 0 <= left <= self._lead_minutes():
                continue
            key = f"event:{ev.uid or ev.title}:{ev.start.isoformat()}"
            if key in self.state["reminded"]:
                continue
            self._mark(key, now.date())
            when = "지금" if left < 1 else f"{round(left)}분 뒤"
            place = f" 장소는 {ev.location}입니다." if ev.location else ""
            out.append(Event("event", f"{title}, {when} {time_words(ev.start)}에 {ev.title} 일정이 있습니다.{place}",
                             speak=not quiet))
        return out

    def _battery(self, battery, quiet: bool) -> Event | None:
        if not battery:
            return None
        pct, plugged = battery
        warn = self._warn_level()
        if plugged or pct >= warn + BATTERY_REARM:
            self._bat_warned = self._bat_critical = False
            return None
        title = self.cfg["user_title"] or "주인님"
        if pct <= BATTERY_CRITICAL and not self._bat_critical:
            self._bat_critical = self._bat_warned = True
            return Event("battery", f"{title}, 배터리가 {pct:.0f}% 남았습니다. 곧 꺼질 수 있으니 지금 충전기를 연결해 주십시오.",
                         speak=True)               # 꺼지기 직전은 조용한 시간에도 말한다
        if pct <= warn and not self._bat_warned:
            self._bat_warned = True
            return Event("battery", f"{title}, 배터리가 {pct:.0f}% 남았습니다. 충전기를 연결하시는 게 좋겠습니다.",
                         speak=not quiet)
        return None

    def _todo_events(self, now: dt.datetime) -> list[Event]:
        if not self._on("todo_reminders"):
            return []
        try:
            st = self.store_fn()
        except Exception as e:
            log.warning("할 일 저장소를 열 수 없습니다: %s", e)
            return []
        today = now.date()
        title = self.cfg["user_title"] or "주인님"
        out = []
        key = f"today:{today.isoformat()}"
        if now.hour >= TODAY_REMIND_HOUR and key not in self.state["reminded"]:
            due, late = st.due_on(today), st.overdue(today)
            if due or late:
                self._mark(key, today)
                text = f"{title}, " + todos.speak_list(st, "today", today)
                out.append(Event("todo_today", text))
        key = f"tomorrow:{today.isoformat()}"
        if now.hour >= TOMORROW_REMIND_HOUR and key not in self.state["reminded"]:
            due = st.due_on(today + dt.timedelta(days=1))
            if due:
                self._mark(key, today)
                out.append(Event("todo_tomorrow", f"{title}, 미리 알려 드립니다. " + todos.speak_list(st, "tomorrow", today)))
        return out

    # ------------------------------------------------------------------ 아침 브리핑
    def briefing_due(self, now: dt.datetime, idle_seconds: float | None = None) -> bool:
        """오늘 아침 브리핑을 아직 안 했고, 지금이 오전이며, 사용자가 PC 앞에 있다."""
        if not (self._on("proactive") and self._on("daily_briefing")):
            return False
        if self.state["briefing"] == now.date().isoformat():
            return False
        if not BRIEFING_HOURS[0] <= now.hour < BRIEFING_HOURS[1] or in_quiet(now.hour, self.cfg["quiet_hours"]):
            return False
        return idle_seconds is None or idle_seconds < BRIEF_ACTIVE_SECONDS

    def mark_briefed(self, now: dt.datetime) -> None:
        today = now.date()
        with self._lock:
            self.state["briefing"] = today.isoformat()
            # 브리핑에서 오늘 할 일을 이미 말했으므로 9시 알림은 건너뛴다
            try:
                st = self.store_fn()
                if st.due_on(today) or st.overdue(today):
                    self.state["reminded"][f"today:{today.isoformat()}"] = today.isoformat()
            except Exception:
                pass
            self._save()


def briefing_text(now: dt.datetime, title: str, weather: str | None,
                  st: todos.TodoStore | None, greet: bool = True, agenda_lines: list[str] | None = None) -> str:
    """날짜 · 날씨 · 일정 · 메일 · 할 일을 한 번에. weather 는 이미 말로 다듬은 날씨 문장 (없으면 건너뜀),
    agenda_lines 는 agenda.Agenda.briefing_lines 가 만든 일정 · 메일 문장."""
    today = now.date()
    parts = []
    if greet:
        parts.append(persona.pick(persona.BRIEF_GREET[persona.part_of_day(now.hour)], title=title))
    parts.append(f"오늘은 {today.month}월 {today.day}일 {todos.WEEKDAYS[today.weekday()]}요일입니다.")
    if weather:
        parts.append(weather.rstrip(".") + ".")
    parts.extend(agenda_lines or [])
    if st is not None:
        due, late = st.due_on(today), st.overdue(today)
        week = [t for t in st.within(today, 6) if t.due_date and t.due_date > today]
        if due:
            parts.append(f"오늘 마감인 할 일은 {', '.join(t.text for t in due[:5])}입니다.")
        if late:
            parts.append(f"마감이 지난 일도 {len(late)}개 있습니다: {', '.join(t.text for t in late[:3])}.")
        if week:
            nxt = week[0]
            parts.append(f"일주일 안에 마감인 일이 {len(week)}개 있고, 가장 가까운 것은 "
                         f"{todos.due_words(nxt.due_date, today)} 마감인 {nxt.text}입니다.")
        if not (due or late or week):
            parts.append("가까운 마감은 없습니다.")
    return " ".join(parts)
