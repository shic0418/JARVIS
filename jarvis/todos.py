"""할 일 · 마감 — "경제 과제 금요일까지 할 일 추가"처럼 말하면 저장해 두고, 묻거나(목록) 끝냈다고 하면(완료) 처리한다.

    할 일 추가 경제 과제 금요일까지        경제 과제 금요일까지 할 일에 추가해 줘
    할 일 목록 · 오늘 할 일 · 이번 주 할 일 · 내일 할 일 뭐 있어
    경제 과제 다 했어 · 할 일 완료 경제 과제 · 할 일 삭제 경제 과제

data/todos.json 에만 저장한다 (PC 밖으로 나가지 않음). Claude 도 같은 저장소를 todo_* 도구로 쓴다.
먼저 말 거는 기능(proactive.py)이 마감 전날 · 당일에 알려 준다.
마감 날짜 해석(parse_due)과 명령 해석(parse_command)은 순수 함수 — 실행은 brain.py 가 한다.
"""
from __future__ import annotations

import datetime as dt
import json
import logging
import re
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .config import DATA_DIR

log = logging.getLogger("jarvis.todos")

TODO_PATH = DATA_DIR / "todos.json"
MAX_OPEN = 100            # 끝내지 않은 할 일은 이만큼까지
KEEP_DONE_DAYS = 30       # 끝낸 할 일은 이 기간이 지나면 지운다
WEEKDAYS = "월화수목금토일"

# ---------------------------------------------------------------------------- 마감 날짜
_WD = r"([월화수목금토일])(?:요일)?"
_DUE_TAIL = r"\s*(?:까지|에|마감|전까지|안에|내로)?(?:\s*(?:마감|제출|내야\s*(?:해|돼|함)?))?"
_DUE_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"(\d{1,2})\s*월\s*(\d{1,2})\s*일" + _DUE_TAIL), "md"),
    (re.compile(r"(\d{1,2})\s*/\s*(\d{1,2})" + _DUE_TAIL), "md"),
    (re.compile(r"(\d{1,3})\s*일\s*(?:뒤|후)" + _DUE_TAIL), "after_days"),
    (re.compile(r"(?:(다음|담|다다음)\s*주|이번\s*주|이번주|금주)\s*" + _WD + _DUE_TAIL), "week_wd"),
    (re.compile(r"(이번\s*주말|이번주말|주말)" + _DUE_TAIL), "weekend"),
    (re.compile(r"(이번\s*주|이번주|금주)" + _DUE_TAIL), "this_week"),
    (re.compile(r"(다음\s*주|담주)" + _DUE_TAIL), "next_week"),
    (re.compile(r"(오늘|내일|모레|글피)" + _DUE_TAIL), "rel"),
    # 요일 한 글자만으로는 받지 않는다 ('목 스트레칭' 이 목요일 마감이 되지 않게) — '금요일' 또는 '금까지'
    (re.compile(r"(?<![가-힣\d])([월화수목금토일])(?:요일|(?=\s*(?:까지|마감)))" + _DUE_TAIL), "wd"),
    (re.compile(r"(?<!\d)(\d{1,2})\s*일(?!\s*(?:뒤|후|동안|간))" + _DUE_TAIL), "day"),
]
_REL = {"오늘": 0, "내일": 1, "모레": 2, "글피": 3}


def _safe_date(y: int, m: int, d: int) -> dt.date | None:
    try:
        return dt.date(y, m, d)
    except ValueError:
        return None


class BadDate(ValueError):
    """'2월 30일'처럼 날짜를 말했는데 없는 날짜."""


def parse_due(text: str, today: dt.date | None = None) -> tuple[dt.date | None, str]:
    """말 속의 마감 날짜 → (날짜 또는 None, 날짜 부분을 뺀 나머지 글).
    '2월 30일'처럼 분명히 날짜를 말했는데 없는 날짜면 BadDate (엉뚱한 '30일' 로 바꿔 읽지 않는다)."""
    today = today or dt.date.today()
    s = text or ""
    for pat, kind in _DUE_PATTERNS:
        m = pat.search(s)
        if not m:
            continue
        due: dt.date | None = None
        if kind == "md":
            mo, d = int(m.group(1)), int(m.group(2))
            due = _safe_date(today.year, mo, d)
            if due is None:
                raise BadDate(f"{mo}월 {d}일은 없는 날짜입니다.")
            if due < today - dt.timedelta(days=60):              # 한참 지난 날짜면 내년
                due = _safe_date(today.year + 1, mo, d) or due
        elif kind == "after_days":
            due = today + dt.timedelta(days=int(m.group(1)))
        elif kind == "week_wd":
            wd = WEEKDAYS.index(m.group(2))
            monday = today - dt.timedelta(days=today.weekday())
            weeks = {"다음": 1, "담": 1, "다다음": 2}.get(m.group(1) or "", 0)
            due = monday + dt.timedelta(days=7 * weeks + wd)
            if due < today:          # 토요일에 '이번 주 금요일' → 이미 지났으니 돌아오는 금요일로
                due += dt.timedelta(days=7)
        elif kind == "weekend":
            due = today + dt.timedelta(days=(5 - today.weekday()) % 7)
        elif kind == "this_week":
            due = today + dt.timedelta(days=6 - today.weekday())
        elif kind == "next_week":
            due = today + dt.timedelta(days=13 - today.weekday())
        elif kind == "rel":
            due = today + dt.timedelta(days=_REL[m.group(1)])
        elif kind == "wd":
            due = today + dt.timedelta(days=(WEEKDAYS.index(m.group(1)) - today.weekday()) % 7)
        elif kind == "day":
            d = int(m.group(1))
            due = _safe_date(today.year, today.month, d)
            if due and due < today:
                nm = (today.replace(day=1) + dt.timedelta(days=32)).replace(day=1)
                due = _safe_date(nm.year, nm.month, d)
        if due is None:
            continue
        rest = (s[:m.start()] + " " + s[m.end():]).strip()
        return due, _clean(rest)
    return None, _clean(s)


def _clean(s: str) -> str:
    s = re.sub(r"\s+", " ", s or "").strip(" ,.!?~:：")
    s = re.sub(r"^(?:을|를|은|는|이|가)\s+", "", s)
    return s.strip()


def due_words(due: dt.date | None, today: dt.date | None = None) -> str:
    """말로 읽기 좋은 마감: 오늘 · 내일 · 모레 · 금요일 · 11월 20일 · 이틀 지남."""
    if due is None:
        return "마감 없음"
    today = today or dt.date.today()
    n = (due - today).days
    if n < 0:
        return f"{-n}일 지남"
    if n in (0, 1, 2):
        return ("오늘", "내일", "모레")[n]
    if n < 7 and due.weekday() > today.weekday():
        return f"{WEEKDAYS[due.weekday()]}요일"
    return f"{due.month}월 {due.day}일"


# ---------------------------------------------------------------------------- 저장소
def write_atomic(path: Path, text: str, tries: int = 6) -> None:
    """임시 파일에 쓰고 바꿔 끼운다. Windows 는 백신 · 검색 색인이 막 쓴 파일을 잠깐 잡고 있어
    바꿔 끼우기가 거부될 수 있다(WinError 5) — 잠깐 기다렸다 다시 해 본다."""
    tmp = path.with_suffix(".tmp")
    tmp.write_text(text, encoding="utf-8")
    for i in range(tries):
        try:
            tmp.replace(path)
            return
        except PermissionError:
            if i == tries - 1:
                raise
            time.sleep(0.05 * (i + 1))


@dataclass
class Todo:
    text: str
    due: str = ""                   # YYYY-MM-DD 또는 ""
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    created: str = field(default_factory=lambda: dt.date.today().isoformat())
    done: str = ""                  # 끝낸 날 (YYYY-MM-DD) 또는 ""

    @property
    def due_date(self) -> dt.date | None:
        try:
            return dt.date.fromisoformat(self.due) if self.due else None
        except ValueError:
            return None


def squash(s: str) -> str:
    return re.sub(r"[\s.,!?~]+", "", s or "").lower()


class TodoStore:
    def __init__(self, path: Path = TODO_PATH) -> None:
        self.path = path
        self._lock = threading.RLock()
        self.items: list[Todo] = []
        self.load()

    def load(self) -> None:
        with self._lock:
            self.items = []
            try:
                raw = json.loads(self.path.read_text(encoding="utf-8"))
            except FileNotFoundError:
                return
            except Exception as e:
                log.warning("할 일 파일을 읽을 수 없습니다: %s", e)
                return
            for d in raw if isinstance(raw, list) else []:
                if isinstance(d, dict) and str(d.get("text", "")).strip():
                    self.items.append(Todo(**{k: str(d[k]) for k in ("text", "due", "id", "created", "done") if k in d}))

    def save(self) -> None:
        with self._lock:
            cutoff = (dt.date.today() - dt.timedelta(days=KEEP_DONE_DAYS)).isoformat()
            self.items = [t for t in self.items if not t.done or t.done >= cutoff]
            self.path.parent.mkdir(parents=True, exist_ok=True)
            write_atomic(self.path, json.dumps([asdict(t) for t in self.items], ensure_ascii=False, indent=1))

    def open_items(self) -> list[Todo]:
        """끝내지 않은 할 일 — 마감이 가까운 것부터, 마감 없는 것은 뒤에."""
        with self._lock:
            return sorted((t for t in self.items if not t.done),
                          key=lambda t: (t.due_date is None, t.due_date or dt.date.max, t.created))

    def add(self, text: str, due: dt.date | None = None) -> Todo:
        text = _clean(text)
        if not text:
            raise ValueError("할 일 내용이 비어 있습니다.")
        with self._lock:
            same = self.find(text, exact=True)
            if same is not None:                     # 같은 할 일을 다시 말하면 마감만 바꾼다
                if due is not None:
                    same.due = due.isoformat()
                    self.save()
                return same
            if len(self.open_items()) >= MAX_OPEN:
                raise ValueError("할 일이 너무 많습니다. 끝낸 일을 먼저 정리해 주십시오.")
            t = Todo(text, due.isoformat() if due else "")
            self.items.append(t)
            self.save()
            return t

    def find(self, query: str, exact: bool = False) -> Todo | None:
        """말한 이름에 맞는 끝내지 않은 할 일. 정확히 같은 것 → 포함하는 것(하나뿐일 때) 순서로 찾는다."""
        q = squash(_clean(query))
        if not q:
            return None
        with self._lock:
            opens = self.open_items()
            for t in opens:
                if squash(t.text) == q:
                    return t
            if exact:
                return None
            # 부분 일치는 3글자 이상일 때만 ('과제 얘기 끝냈어' 가 '과제' 를 완료하지 않게)
            hits = [t for t in opens if (len(q) >= 3 and q in squash(t.text))
                    or (len(squash(t.text)) >= 3 and squash(t.text) in q)]
            return hits[0] if len(hits) == 1 else None

    def complete(self, query: str, today: dt.date | None = None) -> Todo | None:
        with self._lock:
            t = self.find(query)
            if t is not None:
                t.done = (today or dt.date.today()).isoformat()
                self.save()
            return t

    def remove(self, query: str) -> Todo | None:
        with self._lock:
            t = self.find(query)
            if t is not None:
                self.items.remove(t)
                self.save()
            return t

    def due_on(self, day: dt.date) -> list[Todo]:
        return [t for t in self.open_items() if t.due_date == day]

    def overdue(self, today: dt.date) -> list[Todo]:
        return [t for t in self.open_items() if t.due_date is not None and t.due_date < today]

    def within(self, today: dt.date, days: int) -> list[Todo]:
        """오늘부터 days 일 안에 마감인 것 (지난 것 제외)."""
        end = today + dt.timedelta(days=days)
        return [t for t in self.open_items() if t.due_date is not None and today <= t.due_date <= end]


_store: TodoStore | None = None
_store_lock = threading.Lock()


def store() -> TodoStore:
    """앱 전체가 같이 쓰는 저장소 (두뇌 · 도구 · 먼저 말 걸기)."""
    global _store
    with _store_lock:
        if _store is None:
            _store = TodoStore()
        return _store


# ---------------------------------------------------------------------------- 말로 읽기
def _join(items: list[Todo], today: dt.date, with_due: bool = True) -> str:
    parts = [f"{t.text}({due_words(t.due_date, today)})" if with_due and t.due_date else t.text for t in items[:6]]
    more = f" 외 {len(items) - 6}개" if len(items) > 6 else ""
    return ", ".join(parts) + more


def speak_list(st: TodoStore, scope: str = "all", today: dt.date | None = None) -> str:
    """scope: all | today | tomorrow | week"""
    today = today or dt.date.today()
    if scope == "today":
        items, late = st.due_on(today), st.overdue(today)
        if not items and not late:
            return "오늘 마감인 할 일은 없습니다."
        out = f"오늘 마감인 할 일은 {_join(items, today, False)}입니다." if items else "오늘 마감인 할 일은 없습니다."
        if late:
            out += f" 마감이 지난 일도 있습니다: {_join(late, today)}."
        return out
    if scope == "tomorrow":
        tom = today + dt.timedelta(days=1)
        items = st.due_on(tom)
        return f"내일 마감인 할 일은 {_join(items, today, False)}입니다." if items else "내일 마감인 할 일은 없습니다."
    if scope == "next_week":
        monday = today + dt.timedelta(days=7 - today.weekday())
        items = [t for t in st.open_items() if t.due_date and monday <= t.due_date <= monday + dt.timedelta(days=6)]
        return f"다음 주 할 일은 {len(items)}개입니다. {_join(items, today)}." if items else "다음 주에 마감인 할 일은 없습니다."
    if scope == "week":
        items = st.within(today, 6 - today.weekday() if today.weekday() < 5 else 7)
        late = st.overdue(today)
        if not items and not late:
            return "이번 주에 마감인 할 일은 없습니다."
        out = f"이번 주 할 일은 {len(items)}개입니다. {_join(items, today)}." if items else "이번 주에 마감인 할 일은 없습니다."
        if late:
            out += f" 마감이 지난 일: {_join(late, today)}."
        return out
    items = st.open_items()
    if not items:
        return "남은 할 일이 없습니다."
    return f"남은 할 일은 {len(items)}개입니다. {_join(items, today)}."


# ---------------------------------------------------------------------------- 명령 해석
_T = r"(?:할\s*일|할일|투두|todo|해야\s*할\s*(?:일|것))"
_ADD = [
    re.compile(r"^" + _T + r"\s*(?:에\s*)?(?:추가|등록|저장|넣어|적어|메모)(?:\s*해)?(?:\s*(?:줘|줘요|주세요))?\s*[:：]?\s*(.+)$", re.I),
    re.compile(r"^(.+?)\s*(?:을|를)?\s*" + _T + r"\s*(?:로|으로|에|목록에)\s*(?:추가|등록|저장|넣어|적어)(?:\s*해)?(?:\s*(?:줘|줘요|주세요|둬|놔))?$", re.I),
]
_LIST = re.compile(
    r"^(?:(오늘|내일|이번\s*주|이번주|금주|다음\s*주|담주)\s*)?(?:(?:내|남은)\s*)?" + _T
    + r"\s*(?:은|는|이|가)?\s*(?:(?:목록|리스트)\s*(?:을|를)?\s*)?"
      r"(?:뭐(?:야|있어|있지|가\s*있어)?|뭐\s*있어|뭐\s*있지|알려(?:\s*줘)?|보여(?:\s*줘)?|"
      r"말해(?:\s*줘)?|읽어(?:\s*줘)?|있어|확인(?:해\s*줘)?)?\s*\??$", re.I)
_DONE_CMD = re.compile(r"^" + _T + r"\s*(?:완료|끝|체크|다\s*했어)\s*[:：]?\s*(.+)$", re.I)
_DONE_SAY = re.compile(r"^(.+?)\s*(?:을|를|은|는)?\s*(?:다\s*)?(?:했어|했어요|했다|끝냈어|끝냈어요|끝났어|마쳤어|완료(?:했어|했어요)?|해치웠어|냈어|제출했어)$")
_DEL = [
    re.compile(r"^" + _T + r"\s*(?:삭제|지워|제거|없애)(?:\s*줘)?\s*[:：]?\s*(.+)$", re.I),
    re.compile(r"^(.+?)\s*(?:을|를)?\s*" + _T + r"\s*(?:에서\s*)?(?:삭제|지워|제거|빼)(?:\s*줘)?$", re.I),
]


def parse_command(text: str, today: dt.date | None = None) -> tuple[str, dict] | None:
    """할 일 명령 → (동작, 인자). 동작: add | list | done | done_say | delete. 할 일 명령이 아니면 None.
    done_say('경제 과제 다 했어')는 그런 이름의 할 일이 있을 때만 완료로 본다 — 실행하는 쪽이 확인한다."""
    t = (text or "").strip().rstrip(".!~ ")
    if not t:
        return None
    for pat in _ADD:
        m = pat.match(t)
        if m:
            try:
                due, rest = parse_due(m.group(1), today)
            except BadDate as e:
                return "error", {"msg": f"{e} 날짜를 다시 말씀해 주십시오."}
            if rest:
                return "add", {"text": rest, "due": due}
    m = _LIST.match(t)
    if m:
        w = re.sub(r"\s+", "", m.group(1) or "")
        scope = {"오늘": "today", "내일": "tomorrow", "이번주": "week", "금주": "week",
                 "다음주": "next_week", "담주": "next_week"}.get(w, "all")
        return "list", {"scope": scope}
    m = _DONE_CMD.match(t)
    if m:
        return "done", {"query": m.group(1)}
    for pat in _DEL:
        m = pat.match(t)
        if m:
            return "delete", {"query": m.group(1)}
    m = _DONE_SAY.match(t)
    if m and len(squash(m.group(1))) >= 2:
        return "done_say", {"query": m.group(1)}
    return None


def handle(text: str, st: TodoStore | None = None, today: dt.date | None = None, dry: bool = False) -> str | None:
    """할 일 명령을 처리하고 읽을 답을 돌려준다. 할 일 명령이 아니면 None. dry=True 면 알아듣는지만 본다."""
    cmd = parse_command(text, today)
    if cmd is None:
        return None
    st = st or store()
    today = today or dt.date.today()
    kind, a = cmd
    if kind == "done_say" and st.find(a["query"]) is None:
        return None                          # '숙제 다 했어' 인데 그런 할 일이 없으면 평범한 말로 넘긴다
    if dry:
        return ""
    if kind == "error":
        return a["msg"]
    if kind == "add":
        try:
            t = st.add(a["text"], a["due"])
        except ValueError as e:
            return str(e)
        when = f" 마감은 {due_words(t.due_date, today)}입니다." if t.due_date else ""
        return f"할 일에 '{t.text}'을(를) 적어 두었습니다.{when}"
    if kind == "list":
        return speak_list(st, a["scope"], today)
    if kind in ("done", "done_say"):
        t = st.complete(a["query"], today)
        if t is None:
            return f"'{_clean(a['query'])}'에 맞는 할 일을 찾지 못했습니다."
        left = len(st.open_items())
        return f"'{t.text}' 완료로 표시했습니다. 수고하셨습니다." + (f" 남은 할 일은 {left}개입니다." if left else " 남은 할 일이 없습니다.")
    if kind == "delete":
        t = st.remove(a["query"])
        return f"'{t.text}'을(를) 할 일에서 지웠습니다." if t else f"'{_clean(a['query'])}'에 맞는 할 일을 찾지 못했습니다."
    return None


def memory_lines(st: TodoStore | None = None, today: dt.date | None = None, limit: int = 12) -> list[str]:
    """Claude 에게 알려 줄 할 일 요약 (시스템 프롬프트의 기억 칸)."""
    st = st or store()
    today = today or dt.date.today()
    lines = [f"(할 일) {t.text} · 마감 {due_words(t.due_date, today)}" + (f" ({t.due})" if t.due else "")
             for t in st.open_items()[:limit]]
    if lines:   # 시스템 지시는 대화를 시작할 때 한 번 만든다 — 그 뒤 바뀐 것은 todo_list 로 확인
        lines.append(f"(할 일 목록은 {today:%m월 %d일} 대화 시작 때 기준 — 최신 목록은 todo_list 도구로 확인)")
    return lines
