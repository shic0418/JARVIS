"""일정 · 메일 — 구글 캘린더와 메일함을 읽기 전용으로 본다 (새 패키지 없이 표준 라이브러리만).

· 캘린더: 구글 캘린더 설정의 '비공개 iCal 주소'(…/basic.ics)를 받아 와 직접 읽는다. 반복 일정(RRULE)도 펼친다.
· 메일: IMAP + 앱 비밀번호로 받은편지함을 '읽기 전용'으로 열어 안 읽은 메일의 보낸 사람 · 제목만 본다.
  본문은 읽지 않고, 읽음 표시도 바꾸지 않는다 (BODY.PEEK).
· 주소와 비밀번호는 Windows 암호화(DPAPI)로 감싸 data/config.json 에 넣는다 — 이 PC 의 이 사용자만 풀 수 있다.
· "오늘 일정 뭐 있어", "안 읽은 메일 있어" 같은 말은 Claude 없이 바로 답한다 (토큰 0).

주소 · 비밀번호 · 메일 제목은 로그에 남기지 않는다.
"""
from __future__ import annotations

import base64
import datetime as dt
import email
import email.header
import email.utils
import imaplib
import logging
import re
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Callable, Iterator

from . import todos

log = logging.getLogger("jarvis.agenda")

CAL_TTL = 600            # 초. 캘린더는 이만큼 지나면 다시 받는다
MAIL_TTL = 300           # 초. 메일함은 이만큼 지나면 다시 본다
NET_TIMEOUT = 8
RETRY_AFTER = 60         # 초. 받기 · 로그인에 실패하면 이만큼은 다시 시도하지 않는다 (끊긴 동안 매번 기다리지 않게)
MAX_ICS_BYTES = 8 * 1024 * 1024
MAX_OCCURRENCES = 20000  # 반복 일정 하나를 펼칠 때의 상한 (끝없는 반복 방지)
MAX_MONTHS = 2400        # 매월 반복은 이만큼의 달까지만 본다
MAX_YEARS = 400          # 매년 반복은 이만큼의 해까지만 본다
SPEAK_MAX = 5            # 소리 내어 읽는 일정 · 메일 개수
_PREFIX = "dpapi:"
_WD = {"MO": 0, "TU": 1, "WE": 2, "TH": 3, "FR": 4, "SA": 5, "SU": 6}
_HOSTS = {"gmail.com": "imap.gmail.com", "googlemail.com": "imap.gmail.com", "naver.com": "imap.naver.com",
          "daum.net": "imap.daum.net", "hanmail.net": "imap.daum.net", "kakao.com": "imap.kakao.com"}


class AgendaError(Exception):
    """사용자에게 그대로 말해도 되는 실패 사유."""


# ---------------------------------------------------------------------------- 비밀 값 보관 (DPAPI)
def protect(text: str) -> str:
    """주소 · 비밀번호를 이 Windows 사용자만 풀 수 있게 감싼다."""
    text = (text or "").strip()
    if not text:
        return ""
    import win32crypt
    blob = win32crypt.CryptProtectData(text.encode("utf-8"), "jarvis", None, None, None, 0)
    return _PREFIX + base64.b64encode(blob).decode("ascii")


def reveal(stored: str) -> str:
    """protect 로 감싼 값을 푼다. config.json 에 직접 적은 평문은 그대로 돌려준다. 못 풀면 빈 문자열."""
    s = str(stored or "").strip()
    if not s.startswith(_PREFIX):
        return s
    try:
        import win32crypt
        return win32crypt.CryptUnprotectData(base64.b64decode(s[len(_PREFIX):]), None, None, None, 0)[1].decode("utf-8")
    except Exception as e:
        log.warning("저장된 연결 정보를 풀 수 없습니다 (다른 PC · 다른 계정에서 옮긴 설정): %s", type(e).__name__)
        return ""


# ---------------------------------------------------------------------------- iCal 읽기
@dataclass(frozen=True)
class Ev:
    start: dt.datetime       # 이 PC 의 현지 시각 (tz 없음)
    end: dt.datetime
    all_day: bool
    title: str
    location: str = ""
    uid: str = ""


def _zone(tzid: str):
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo(tzid)
    except Exception:        # Windows 에는 tzdata 패키지가 없을 수 있다 → 현지 시각으로 본다
        return None


def _to_local(naive: dt.datetime, utc: bool, tzid: str = "") -> dt.datetime:
    if utc:
        return naive.replace(tzinfo=dt.timezone.utc).astimezone().replace(tzinfo=None)
    tz = _zone(tzid) if tzid else None
    if tz is not None:
        return naive.replace(tzinfo=tz).astimezone().replace(tzinfo=None)
    return naive


def _when(value: str, params: dict) -> tuple[dt.datetime, bool] | None:
    """DTSTART · DTEND 값 → (현지 시각, 종일 여부)."""
    v = value.strip()
    try:
        if re.fullmatch(r"\d{8}", v):
            return dt.datetime.strptime(v, "%Y%m%d"), True
        m = re.fullmatch(r"(\d{8}T\d{6})(Z?)", v)
        if not m:
            return None
        return _to_local(dt.datetime.strptime(m.group(1), "%Y%m%dT%H%M%S"), bool(m.group(2)), params.get("TZID", "")), False
    except (ValueError, OverflowError, OSError):     # 없는 날짜, 달력 범위 밖, Windows 가 못 바꾸는 1970년 이전 UTC
        return None


def _duration(value: str) -> dt.timedelta | None:
    m = re.fullmatch(r"([+-]?)P(?:(\d+)W)?(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?)?", value.strip())
    if not m:
        return None
    w, d, h, mi, s = (int(x or 0) for x in m.groups()[1:])
    td = dt.timedelta(weeks=w, days=d, hours=h, minutes=mi, seconds=s)
    return -td if m.group(1) == "-" else td


def _text(value: str) -> str:
    out = re.sub(r"\\[nN]", " ", value)
    out = re.sub(r"\\([,;\\])", r"\1", out)
    return re.sub(r"\s+", " ", out).strip()


def _split_line(line: str) -> tuple[str, dict, str] | None:
    """'DTSTART;TZID=Asia/Seoul:2026…' → (이름, 매개변수, 값). 따옴표 안의 ':' 는 구분자가 아니다."""
    quoted = False
    for i, ch in enumerate(line):
        if ch == '"':
            quoted = not quoted
        elif ch == ":" and not quoted:
            head, value = line[:i], line[i + 1:]
            name, *rest = head.split(";")
            params = {}
            for p in rest:
                k, _, v = p.partition("=")
                params[k.strip().upper()] = v.strip().strip('"')
            return name.strip().upper(), params, value
    return None


def _components(text: str) -> Iterator[list[tuple[str, dict, str]]]:
    """VEVENT 하나씩의 속성 목록. 접힌 줄(다음 줄이 공백으로 시작)은 이어 붙인다."""
    lines: list[str] = []
    for raw in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if raw[:1] in (" ", "\t") and lines:
            lines[-1] += raw[1:]
        else:
            lines.append(raw)
    cur: list | None = None
    depth = 0                # VEVENT 안의 VALARM 같은 하위 블록은 건너뛴다
    for line in lines:
        up = line.strip().upper()
        if up == "BEGIN:VEVENT":
            cur, depth = [], 0
        elif cur is None:
            continue
        elif up == "END:VEVENT":
            yield cur
            cur = None
        elif up.startswith("BEGIN:"):
            depth += 1
        elif up.startswith("END:"):
            depth = max(0, depth - 1)
        elif depth == 0:
            prop = _split_line(line)
            if prop:
                cur.append(prop)


def _nth_weekday(year: int, month: int, n: int, wd: int) -> dt.date | None:
    """그 달의 n번째(음수면 뒤에서) wd 요일."""
    first = dt.date(year, month, 1)
    nxt = dt.date(year + (month == 12), month % 12 + 1, 1)
    if n > 0:
        d = first + dt.timedelta(days=(wd - first.weekday()) % 7 + 7 * (n - 1))
    elif n < 0:
        end = nxt - dt.timedelta(days=1)
        d = end - dt.timedelta(days=(end.weekday() - wd) % 7 + 7 * (-n - 1))
    else:
        return None
    return d if d.month == month else None


def _rule(value: str) -> dict:
    return {k.strip().upper(): v.strip() for k, _, v in (p.partition("=") for p in value.split(";")) if k.strip()}


def _occurrences(start: dt.datetime, rule: dict, after: dt.datetime | None = None) -> Iterator[dt.datetime]:
    """반복 규칙의 시작 시각들을 이른 순서로 (COUNT · UNTIL 은 부르는 쪽이 끊는다).
    after 를 주면 그 시각 조금 앞의 회차부터 낸다 — 오래전에 시작한 반복을 처음부터 세지 않게 (COUNT 가 없을 때만 쓴다).
    어떤 규칙이든 정해진 횟수만 돌고 끝난다 (맞는 날이 하나도 없는 규칙이 화면을 멈추지 않게)."""
    freq = rule.get("FREQ", "")
    try:
        step = max(1, int(rule.get("INTERVAL", "1")))
    except ValueError:
        step = 1
    byday = [m.groups() for m in (re.fullmatch(r"([+-]?\d+)?(MO|TU|WE|TH|FR|SA|SU)", x.strip().upper())
                                  for x in rule.get("BYDAY", "").split(",")) if m]
    at = start.time()
    ahead = after if after is not None and after > start else None
    try:
        if freq == "DAILY":
            k0 = max(0, (ahead - start).days // step - 1) if ahead else 0
            only = {_WD[d] for _, d in byday}
            for k in range(k0, k0 + MAX_OCCURRENCES):
                occ = start + dt.timedelta(days=k * step)
                if not only or occ.weekday() in only:
                    yield occ
        elif freq == "WEEKLY":
            days = sorted({_WD[d] for _, d in byday}) or [start.weekday()]
            week0 = start.date() - dt.timedelta(days=start.weekday())
            k0 = max(0, (ahead - start).days // (7 * step) - 1) if ahead else 0
            for k in range(k0, k0 + MAX_OCCURRENCES):
                for wd in days:
                    occ = dt.datetime.combine(week0 + dt.timedelta(weeks=k * step, days=wd), at)
                    if occ >= start:
                        yield occ
        elif freq == "MONTHLY":
            try:
                mdays = [int(x) for x in rule.get("BYMONTHDAY", "").split(",") if x.strip()]
            except ValueError:
                mdays = []
            k0 = max(0, ((ahead.year - start.year) * 12 + ahead.month - start.month) // step - 1) if ahead else 0
            for k in range(k0, k0 + MAX_MONTHS):
                idx = start.month - 1 + k * step
                year, month = start.year + idx // 12, idx % 12 + 1
                if year > 9998:
                    return
                cands: list[dt.date] = []
                if byday and not mdays:
                    for n, d in byday:           # '2TU' 는 둘째 화요일, 숫자가 없으면 그 달의 그 요일 전부
                        for nth in ([int(n)] if n else range(1, 6)):
                            hit = _nth_weekday(year, month, nth, _WD[d]) if nth else None
                            if hit:
                                cands.append(hit)
                else:
                    for md in mdays or [start.day]:
                        try:
                            if md > 0:
                                cands.append(dt.date(year, month, md))
                            elif md < 0:
                                nxt = dt.date(year + (month == 12), month % 12 + 1, 1)
                                cands.append(nxt + dt.timedelta(days=md))
                        except (ValueError, OverflowError):
                            pass                 # 31일이 없는 달은 건너뛴다
                for d in sorted(set(cands)):
                    occ = dt.datetime.combine(d, at)
                    if occ >= start:
                        yield occ
        elif freq == "YEARLY":
            k0 = max(0, (ahead.year - start.year) // step - 1) if ahead else 0
            for k in range(k0, k0 + MAX_YEARS):
                year = start.year + k * step
                if year > 9998:
                    return
                try:
                    yield start.replace(year=year)
                except ValueError:
                    pass                         # 2월 29일
        else:
            yield start                          # 모르는 규칙(HOURLY 등)은 첫 번만
    except OverflowError:                        # 달력이 표현할 수 있는 날짜를 넘었다
        return


@dataclass(frozen=True)
class Index:
    """한 번 읽어 둔 캘린더 — 창(기간)을 바꿔 가며 다시 물을 때 원문을 또 읽지 않는다."""
    singles: tuple
    masters: tuple           # (첫 회차 Ev, 반복 규칙, 빼는 시각들, 횟수가 정해진 반복의 마지막 회차 시각 또는 None)


def index_ics(text: str) -> Index:
    masters, singles = [], []
    moved: dict[str, set[dt.datetime]] = {}       # UID → 따로 고쳐진 회차의 원래 시각 (원래 반복에서 뺀다)
    for props in _components(text):
        try:
            got = _read_event(props, moved)
        except (ValueError, OverflowError, OSError):         # 이 일정만 건너뛴다 (달력 범위를 넘는 길이 등)
            continue
        if got is None:
            continue
        ev, rule, skip = got
        if rule is None:
            singles.append(ev)
        else:
            masters.append((ev, rule, skip))
    out = []
    for ev, rule, skip in masters:
        out.append((ev, rule, frozenset(skip | moved.get(ev.uid, set())), _last_start(ev.start, rule)))
    return Index(tuple(singles), tuple(out))


def _last_start(start: dt.datetime, rule: dict) -> dt.datetime | None:
    """횟수(COUNT)가 정해진 반복의 마지막 회차 시각 — 이미 끝난 반복을 매번 처음부터 세지 않게 한 번만 구해 둔다."""
    try:
        count = int(rule["COUNT"])
    except (KeyError, ValueError):
        return None
    last = None
    for n, occ in enumerate(_occurrences(start, rule)):
        if n >= count or n >= MAX_OCCURRENCES:
            break
        last = occ
    return last


def _read_event(props: list, moved: dict) -> tuple[Ev, dict | None, set] | None:
    """VEVENT 하나 → (일정, 반복 규칙 또는 None, 빼는 시각들). 읽을 수 없거나 취소된 일정은 None."""
    one: dict[str, tuple[dict, str]] = {}
    exdates: list[tuple[dict, str]] = []
    for name, params, value in props:
        if name == "EXDATE":
            exdates.append((params, value))
        else:
            one.setdefault(name, (params, value))
    if "DTSTART" not in one:
        return None
    got = _when(one["DTSTART"][1], one["DTSTART"][0])
    if not got:
        return None
    start, all_day = got
    end = None
    if "DTEND" in one:
        e = _when(one["DTEND"][1], one["DTEND"][0])
        end = e[0] if e else None
    elif "DURATION" in one:
        d = _duration(one["DURATION"][1])
        end = start + d if d else None
    if end is None or end < start:
        end = start + dt.timedelta(days=1) if all_day else start
    uid = one.get("UID", ({}, ""))[1].strip()
    if "RECURRENCE-ID" in one:
        rid = _when(one["RECURRENCE-ID"][1], one["RECURRENCE-ID"][0])
        if rid:
            moved.setdefault(uid, set()).add(rid[0])
    if one.get("STATUS", ({}, ""))[1].strip().upper() == "CANCELLED":
        return None
    ev = Ev(start, end, all_day, _text(one.get("SUMMARY", ({}, ""))[1]) or "(제목 없음)",
            _text(one.get("LOCATION", ({}, ""))[1]), uid)
    if "RRULE" in one and "RECURRENCE-ID" not in one:
        skip = set()
        for params, value in exdates:
            for v in value.split(","):
                x = _when(v, params)
                if x:
                    skip.add(x[0])
        return ev, _rule(one["RRULE"][1]), skip
    return ev, None, set()


def window(idx: Index, win_start: dt.datetime, win_end: dt.datetime) -> list[Ev]:
    """[win_start, win_end) 에 걸치는 일정들을 시작 순으로."""
    def overlaps(s: dt.datetime, e: dt.datetime) -> bool:
        return s < win_end and (e > win_start or s >= win_start)

    out = [ev for ev in idx.singles if overlaps(ev.start, ev.end)]
    for ev, rule, skip, last in idx.masters:
        length = ev.end - ev.start
        if last is not None and last + length < win_start:
            continue                     # 횟수를 다 채우고 끝난 반복
        try:
            count = int(rule["COUNT"]) if "COUNT" in rule else None
        except ValueError:
            count = None
        until = None                     # 이 시각까지의 회차만 (그 시각 포함)
        if "UNTIL" in rule:
            u = _when(rule["UNTIL"], {})
            if u:                        # 날짜만 있으면 그날 끝까지
                until = u[0] + dt.timedelta(days=1, microseconds=-1) if u[1] else u[0]
        if until is not None and until < win_start - length:
            continue                     # 창보다 먼저 끝난 반복
        # 횟수 제한이 없으면 창 근처에서부터 센다 (횟수 제한은 처음부터 세어야 한다)
        after = win_start - length - dt.timedelta(days=1) if count is None else None
        for n, occ in enumerate(_occurrences(ev.start, rule, after)):
            if n >= MAX_OCCURRENCES or (count is not None and n >= count) or occ >= win_end:
                break
            if until is not None and occ > until:
                break
            if occ in skip or not overlaps(occ, occ + length):
                continue
            out.append(Ev(occ, occ + length, ev.all_day, ev.title, ev.location, ev.uid))
    out.sort(key=lambda e: (e.start, not e.all_day, e.title))
    return out


def parse_ics(text: str, win_start: dt.datetime, win_end: dt.datetime) -> list[Ev]:
    """iCal 원문에서 [win_start, win_end) 에 걸치는 일정들을 시작 순으로. 취소된 일정은 뺀다."""
    return window(index_ics(text), win_start, win_end)


# ---------------------------------------------------------------------------- 말로 읽기
def time_words(t: dt.datetime | dt.time) -> str:
    """'오전 9시', '오후 3시 30분', '낮 12시', '밤 12시'."""
    h, m = t.hour, t.minute
    if h == 0:
        head = "밤 12시"
    elif h == 12:
        head = "낮 12시"
    else:
        head = f"{'오전' if h < 12 else '오후'} {h if h < 12 else h - 12}시"
    return head + (f" {m}분" if m else "")


def _ev_words(ev: Ev, today: dt.date, with_day: bool, win_start: dt.datetime | None = None) -> str:
    began_before = win_start is not None and ev.start < win_start       # 어제부터 이어지는 일정
    if ev.all_day:
        when = "종일"
    elif began_before:
        when = "종일" if ev.end - win_start >= dt.timedelta(days=1) else f"{time_words(ev.end)}까지"
    else:
        when = time_words(ev.start)
    if with_day:
        when = f"{todos.due_words(max(ev.start.date(), today), today)} {when}"
    return f"{when} {ev.title}"


def speak_events(evs: list[Ev], label: str, today: dt.date, with_day: bool = False,
                 win_start: dt.datetime | None = None) -> str:
    if not evs:
        return f"{label} 일정은 없습니다."
    head = ", ".join(_ev_words(e, today, with_day, win_start) for e in evs[:SPEAK_MAX])
    more = f" 외 {len(evs) - SPEAK_MAX}개" if len(evs) > SPEAK_MAX else ""
    return f"{label} 일정은 {len(evs)}개입니다. {head}{more}."


@dataclass(frozen=True)
class Mail:
    sender: str
    subject: str


def speak_mail(count: int, mails: list[Mail], detail: bool = True) -> str:
    if count <= 0:
        return "안 읽은 메일은 없습니다."
    head = f"안 읽은 메일이 {count}통 있습니다."
    if not detail or not mails:
        return head
    items = ", ".join(f"{m.sender}의 {m.subject}" for m in mails[:3])
    return f"{head} 최근 것은 {items}입니다."


def _header(raw) -> str:
    try:
        return re.sub(r"\s+", " ", str(email.header.make_header(email.header.decode_header(str(raw or ""))))).strip()
    except Exception:
        return re.sub(r"\s+", " ", str(raw or "")).strip()


# ---------------------------------------------------------------------------- 연결
class _HttpsOnly(urllib.request.HTTPRedirectHandler):
    """https 가 아닌 곳으로 넘기는 리다이렉트는 따라가지 않는다 (비공개 주소가 평문으로 나가지 않게)."""
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not str(newurl).lower().startswith("https://"):
            raise urllib.error.URLError("https 가 아닌 주소로의 이동을 막았습니다")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _http_get(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "calendar-client"})
    with urllib.request.build_opener(_HttpsOnly).open(req, timeout=NET_TIMEOUT) as r:
        return r.read(MAX_ICS_BYTES).decode("utf-8", "replace")


_MAIL_LOGIN = "메일함에 로그인하지 못했습니다. 메일 주소와 앱 비밀번호, IMAP 사용 설정을 확인해 주십시오."
_MAIL_OFFLINE = "메일함에 연결하지 못했습니다. 인터넷 연결을 확인해 주십시오."


class Agenda:
    def __init__(self, cfg, fetch: Callable[[str], str] = _http_get, imap_factory=None,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self.cfg = cfg
        self._fetch = fetch
        self._imap = imap_factory or (lambda host: imaplib.IMAP4_SSL(host, 993, timeout=NET_TIMEOUT))
        self._clock = clock
        self._lock = threading.Lock()
        self._ics: tuple[float, Index] | None = None      # (받은 시각, 읽어 둔 캘린더)
        self._mail: tuple[float, int, list[Mail]] | None = None
        self._refreshing = False
        self._gen = 0                    # 설정이 바뀔 때마다 오른다 — 바뀌기 전에 시작한 받기의 결과는 버린다
        self._cal_retry = 0.0            # 이 시각 전에는 캘린더를 다시 받지 않는다 (방금 실패)
        self._mail_fail: tuple[float, str] | None = None   # (이 시각까지, 사유) 메일함에 다시 접속하지 않는다

    def reset(self) -> None:
        """설정이 바뀌었다 — 받아 둔 것을 버린다."""
        with self._lock:
            self._gen += 1
            self._ics = self._mail = self._mail_fail = None
            self._cal_retry = 0.0

    # ------------------------------------------------------------------ 캘린더
    def _ical_url(self) -> str:
        url = reveal(self.cfg["calendar_ical_url"])
        if url.lower().startswith("webcal://"):
            url = "https://" + url[len("webcal://"):]
        return url if url.lower().startswith("https://") else ""

    def calendar_on(self) -> bool:
        return bool(self._ical_url())

    def _load_ics(self) -> Index:
        """읽어 둔 캘린더 (10분 캐시). 못 받으면 예전에 받은 것을 쓰고, 그것도 없으면 AgendaError."""
        url = self._ical_url()
        if not url:
            raise AgendaError("캘린더가 아직 연결되지 않았습니다. 설정의 CALENDAR · MAIL 에 구글 캘린더의 비공개 iCal 주소를 넣어 주십시오.")
        failed = AgendaError("캘린더를 읽지 못했습니다. 인터넷 연결과 iCal 주소를 확인해 주십시오.")
        with self._lock:
            cached, gen, wait = self._ics, self._gen, self._clock() < self._cal_retry
        if cached and (wait or self._clock() - cached[0] < CAL_TTL):
            return cached[1]
        if wait:
            raise failed
        try:
            text = self._fetch(url)
            if "BEGIN:VCALENDAR" not in text[:2000].upper():
                raise AgendaError("캘린더 주소가 iCal 형식이 아닙니다. 구글 캘린더 설정의 ‘비공개 주소(iCal 형식)’를 넣어 주십시오.")
            idx = index_ics(text)
        except AgendaError:
            raise
        except Exception as e:
            log.info("캘린더 받기 실패: %s", type(e).__name__)       # 주소가 섞일 수 있어 사유의 종류만 남긴다
            with self._lock:
                if gen == self._gen:
                    self._cal_retry = self._clock() + RETRY_AFTER
            if cached:
                return cached[1]
            raise failed from None
        with self._lock:
            if gen == self._gen:             # 받는 사이에 주소가 바뀌었으면 저장하지 않는다
                self._ics = (self._clock(), idx)
        return idx

    def events(self, start: dt.date, days: int = 1) -> list[Ev]:
        a = dt.datetime.combine(start, dt.time.min)
        return window(self._load_ics(), a, a + dt.timedelta(days=max(1, days)))

    def cached_events(self, start: dt.date, days: int = 1) -> list[Ev] | None:
        """네트워크 없이, 받아 둔 캘린더에서만 (없으면 None). 화면 스레드에서 불러도 된다."""
        with self._lock:
            cached = self._ics
        if not cached:
            return None
        a = dt.datetime.combine(start, dt.time.min)
        return window(cached[1], a, a + dt.timedelta(days=max(1, days)))

    def refresh_async(self) -> None:
        """받아 둔 캘린더가 낡았으면 뒤에서 새로 받는다."""
        with self._lock:
            fresh = self._ics is not None and self._clock() - self._ics[0] < CAL_TTL
            if fresh or self._refreshing or self._clock() < self._cal_retry or not self.calendar_on():
                return
            self._refreshing = True

        def work():
            try:
                self._load_ics()
            except AgendaError:
                pass
            except Exception:
                log.exception("캘린더 새로 받기 실패")
            finally:
                with self._lock:
                    self._refreshing = False
        threading.Thread(target=work, daemon=True, name="agenda-refresh").start()

    # ------------------------------------------------------------------ 메일
    def _mail_login(self) -> tuple[str, str, str]:
        user = str(self.cfg["mail_user"] or "").strip()
        pw = reveal(self.cfg["mail_app_password"])
        if not (user and pw and "@" in user):
            return "", "", ""
        host = str(self.cfg["mail_host"] or "").strip() or _HOSTS.get(user.rsplit("@", 1)[1].lower(), "")
        if not host:
            host = "imap." + user.rsplit("@", 1)[1].lower()
        if host == "imap.gmail.com":
            pw = pw.replace(" ", "")         # 구글은 앱 비밀번호를 네 글자씩 띄워서 보여 준다
        return host, user, pw

    def mail_on(self) -> bool:
        return bool(self._mail_login()[0])

    def unread(self, limit: int = SPEAK_MAX) -> tuple[int, list[Mail]]:
        """(안 읽은 메일 수, 최근 것부터 limit 개의 보낸 사람 · 제목). 5분 캐시."""
        host, user, pw = self._mail_login()
        if not host:
            raise AgendaError("메일이 아직 연결되지 않았습니다. 설정의 CALENDAR · MAIL 에 메일 주소와 앱 비밀번호를 넣어 주십시오.")
        with self._lock:
            cached, gen, failed = self._mail, self._gen, self._mail_fail
        if cached and self._clock() - cached[0] < MAIL_TTL:
            return cached[1], cached[2][:limit]
        if failed and self._clock() < failed[0]:     # 방금 실패했다 — 틀린 비밀번호로 거듭 로그인하지 않는다
            if cached and failed[1] == _MAIL_OFFLINE:
                return cached[1], cached[2][:limit]
            raise AgendaError(failed[1])
        try:
            count, mails = self._fetch_unread(host, user, pw, max(limit, SPEAK_MAX))
        except Exception as e:
            # 중간에 끊긴 연결(IMAP4.abort)은 로그인 실패가 아니라 연결 문제다
            login = isinstance(e, imaplib.IMAP4.error) and not isinstance(e, imaplib.IMAP4.abort)
            why = _MAIL_LOGIN if login else _MAIL_OFFLINE
            log.info("메일함 %s 실패: %s", "로그인" if login else "연결", type(e).__name__)
            with self._lock:
                if gen == self._gen:
                    self._mail_fail = (self._clock() + RETRY_AFTER, why)
            if cached and not login:
                return cached[1], cached[2][:limit]
            raise AgendaError(why) from None
        with self._lock:
            if gen == self._gen:
                self._mail, self._mail_fail = (self._clock(), count, mails), None
        return count, mails[:limit]

    def _fetch_unread(self, host: str, user: str, pw: str, limit: int) -> tuple[int, list[Mail]]:
        m = self._imap(host)
        try:
            m.login(user, pw)
            m.select("INBOX", readonly=True)             # 읽기 전용: 읽음 표시 · 삭제를 할 수 없는 상태로 연다
            ids: list[bytes] | None = None
            if host == "imap.gmail.com":                 # 지메일은 광고 · 소셜 탭을 빼고 '기본' 탭만 센다
                try:
                    typ, data = m.search(None, "X-GM-RAW", '"is:unread category:primary"')
                    if typ == "OK":
                        ids = ((data or [b""])[0] or b"").split()
                except imaplib.IMAP4.error:
                    ids = None
            if ids is None:
                typ, data = m.search(None, "UNSEEN")
                if typ != "OK":
                    raise OSError("메일 검색 실패")          # 0통이라고 단정하지 않는다
                ids = ((data or [b""])[0] or b"").split()
            mails: list[Mail] = []
            if ids:
                typ, data = m.fetch(b",".join(ids[-limit:]).decode("ascii"), "(BODY.PEEK[HEADER.FIELDS (FROM SUBJECT)])")
                for part in (data or []) if typ == "OK" else []:
                    if not isinstance(part, tuple) or len(part) < 2 or not isinstance(part[1], (bytes, bytearray)):
                        continue
                    msg = email.message_from_bytes(part[1])
                    name, addr = email.utils.parseaddr(_header(msg.get("From")))
                    mails.append(Mail((name or addr or "보낸 사람 없음")[:40], (_header(msg.get("Subject")) or "(제목 없음)")[:80]))
                mails.reverse()                          # 최근 것부터
            return len(ids), mails
        finally:
            try:
                m.logout()
            except Exception:
                pass

    # ------------------------------------------------------------------ 브리핑
    def briefing_lines(self, now: dt.datetime) -> list[str]:
        """아침 브리핑에 넣을 문장들. 연결되지 않았거나 못 읽으면 그 부분만 뺀다."""
        out = []
        if self.calendar_on():
            try:
                a = dt.datetime.combine(now.date(), dt.time.min)
                out.append(speak_events(self.events(now.date()), "오늘", now.date(), win_start=a))
            except AgendaError as e:
                log.info("브리핑 일정 건너뜀: %s", e)
        if self.mail_on():
            try:
                count, _ = self.unread()
                if count:
                    out.append(speak_mail(count, [], detail=False))
            except AgendaError as e:
                log.info("브리핑 메일 건너뜀: %s", e)
        return out

    # ------------------------------------------------------------------ 바로 답하는 말 (토큰 0)
    def handle(self, text: str, dry: bool = False, now: dt.datetime | None = None) -> str | None:
        """'오늘 일정 뭐 있어' · '안 읽은 메일 있어' 에 답한다. 상관없는 말이면 None. dry 면 알아듣는지만 본다."""
        cmd = parse_command(text)
        if cmd is None:
            return None
        if dry:
            return "ok"
        now = now or dt.datetime.now()
        try:
            if cmd[0] == "mail":
                return speak_mail(*self.unread())
            return self.speak_scope(cmd[1], now)
        except AgendaError as e:
            return str(e)

    def speak_scope(self, scope: str, now: dt.datetime) -> str:
        today = now.date()
        if scope == "next":
            for ev in self.events(today, 7):
                if not ev.all_day and ev.start >= now:
                    return f"다음 일정은 {_ev_words(ev, today, True)}입니다."
            return "앞으로 일주일 안에 잡힌 일정은 없습니다."
        start, days, label, with_day = SCOPES.get(scope, SCOPES["today"])(today)
        a = dt.datetime.combine(start, dt.time.min)
        return speak_events(self.events(start, days), label, today, with_day, win_start=a)


def _this_week(today: dt.date):
    return today, 7 - today.weekday(), "이번 주 남은", True


def _next_week(today: dt.date):
    return today + dt.timedelta(days=7 - today.weekday()), 7, "다음 주", True


SCOPES: dict[str, Callable[[dt.date], tuple[dt.date, int, str, bool]]] = {
    "today": lambda t: (t, 1, "오늘", False),
    "tomorrow": lambda t: (t + dt.timedelta(days=1), 1, "내일", False),
    "day_after": lambda t: (t + dt.timedelta(days=2), 1, "모레", False),
    "week": _this_week,
    "next_week": _next_week,
}
_SCOPE_WORDS = {"오늘": "today", "내일": "tomorrow", "모레": "day_after", "이번주": "week", "다음주": "next_week",
                "다음": "next", "": "today"}
# 끝의 '줘 · 줄래' 는 normalize 가 떼고 넘기기도 한다 ('알려 줘' → '알려')
_ASK = (r"(?:뭐\s*있(?:어요?|나요?|니)|뭐\s*(?:야|지|예요|에요)|있(?:어요?|나요?|니)|없(?:어요?|나요?)|어때요?|어떻게\s*돼요?|"
        r"언제\s*(?:야|예요|에요)?|(?:다시\s*)?(?:알려|말해|보여|읽어)(?:\s*줘)?|(?:확인|체크)(?:해(?:\s*줘)?)?|목록|브리핑)")
# 대상 낱말만 말한 것('일정', '메일')은 받지 않는다 — 범위(오늘 · 안 읽은)나 묻는 말이 붙어야 한다
_CAL = re.compile(r"^(?:(오늘|내일|모레|이번\s*주|다음\s*주|다음)\s*)?(?:내\s*)?(?:일정|스케줄|약속)\s*(?:이|은|는|을|좀|에)?\s*("
                  + _ASK + r")?$")
_MAIL = re.compile(r"^(?:(안\s*읽은|읽지\s*않은|새로\s*온|새)\s*)?(?:메일|이메일|메일함|편지함)\s*(?:이|은|는|을|좀)?\s*("
                   + _ASK + r"|왔어요?|왔나요?|왔니|뭐\s*왔어요?|온\s*(?:거|게)\s*있(?:어요?|나요?)|"
                   r"몇\s*(?:통|개)\s*(?:(?:이야|야|이에요|예요)|있어요?|왔어요?)?)?$")


def parse_command(text: str) -> tuple[str, str] | None:
    """('calendar', 범위) · ('mail', '') · None."""
    t = re.sub(r"[?!.~,]+", "", str(text or ""))
    t = re.sub(r"\s+", " ", t).strip()
    m = _CAL.match(t)
    if m and (m.group(1) or m.group(2)):
        return "calendar", _SCOPE_WORDS[re.sub(r"\s+", "", m.group(1) or "")]
    m = _MAIL.match(t)
    if m and (m.group(1) or m.group(2)):
        return "mail", ""
    return None
