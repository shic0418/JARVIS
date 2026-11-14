"""일정 · 메일(agenda.py): iCal 읽기, 반복 일정, 말로 읽기, 바로 답하는 말, 메일함 읽기 전용, 일정 알림."""
from __future__ import annotations

import datetime as dt
import imaplib

import pytest

from jarvis import agenda as A
from jarvis import proactive as P
from jarvis.config import DEFAULTS

SAT = dt.date(2026, 11, 14)          # 토요일
D = dt.datetime


class Cfg(dict):
    def __getitem__(self, k):
        return self.get(k, DEFAULTS.get(k))


def ics(*events: str) -> str:
    body = "\r\n".join("BEGIN:VEVENT\r\n" + e.strip().replace("\n", "\r\n") + "\r\nEND:VEVENT" for e in events)
    return "BEGIN:VCALENDAR\r\nVERSION:2.0\r\n" + body + "\r\nEND:VCALENDAR\r\n"


def day(d: dt.date, n: int = 1):
    a = D.combine(d, dt.time.min)
    return a, a + dt.timedelta(days=n)


# ---------------------------------------------------------------------------- iCal
def test_single_events_sorted_and_windowed():
    text = ics("UID:a\nDTSTART:20261114T150000\nDTEND:20261114T160000\nSUMMARY:수행평가\nLOCATION:3층 과학실",
               "UID:b\nDTSTART:20261114T090000\nDTEND:20261114T093000\nSUMMARY:조회",
               "UID:c\nDTSTART:20261115T090000\nDTEND:20261115T100000\nSUMMARY:내일 일")
    evs = A.parse_ics(text, *day(SAT))
    assert [e.title for e in evs] == ["조회", "수행평가"]
    assert evs[1].start == D(2026, 11, 14, 15) and evs[1].location == "3층 과학실" and not evs[1].all_day


def test_all_day_end_is_exclusive():
    text = ics("UID:a\nDTSTART;VALUE=DATE:20261113\nDTEND;VALUE=DATE:20261114\nSUMMARY:어제 종일",
               "UID:b\nDTSTART;VALUE=DATE:20261114\nDTEND;VALUE=DATE:20261115\nSUMMARY:체험학습")
    evs = A.parse_ics(text, *day(SAT))
    assert [e.title for e in evs] == ["체험학습"] and evs[0].all_day


def test_utc_time_becomes_local():
    text = ics("UID:a\nDTSTART:20261114T060000Z\nDTEND:20261114T070000Z\nSUMMARY:회의")
    want = D(2026, 11, 14, 6, tzinfo=dt.timezone.utc).astimezone().replace(tzinfo=None)
    evs = A.parse_ics(text, want - dt.timedelta(hours=1), want + dt.timedelta(hours=1))
    assert evs[0].start == want


def test_unknown_tzid_is_read_as_local_time():
    text = ics("UID:a\nDTSTART;TZID=No/Such_Zone:20261114T150000\nDTEND;TZID=No/Such_Zone:20261114T160000\nSUMMARY:학원")
    assert A.parse_ics(text, *day(SAT))[0].start == D(2026, 11, 14, 15)


def test_folded_lines_escapes_and_nested_alarm():
    text = ics("UID:a\nDTSTART:20261114T100000\nSUMMARY:긴 제목\\, 쉼표와 \n 이어진 줄\nBEGIN:VALARM\nSUMMARY:알람 제목\n"
               "TRIGGER:-PT10M\nEND:VALARM")
    ev = A.parse_ics(text, *day(SAT))[0]
    assert ev.title == "긴 제목, 쉼표와 이어진 줄"
    assert ev.end == ev.start          # 끝 시각이 없으면 길이 0


def test_cancelled_event_is_dropped():
    text = ics("UID:a\nDTSTART:20261114T100000\nSUMMARY:취소된 일\nSTATUS:CANCELLED")
    assert A.parse_ics(text, *day(SAT)) == []


def test_weekly_byday_with_exdate():
    # 11/2(월)부터 매주 월 · 수 · 토 16시, 11/14(토)만 뺀다
    text = ics("UID:r\nDTSTART:20261102T160000\nDTEND:20261102T170000\nRRULE:FREQ=WEEKLY;BYDAY=MO,WE,SA\n"
               "EXDATE:20261114T160000\nSUMMARY:학원")
    week = A.parse_ics(text, *day(dt.date(2026, 11, 9), 7))
    assert [e.start.day for e in week] == [9, 11]
    assert week[0].end - week[0].start == dt.timedelta(hours=1)


def test_weekly_interval_and_count():
    text = ics("UID:r\nDTSTART:20261102T080000\nRRULE:FREQ=WEEKLY;INTERVAL=2;COUNT=3\nSUMMARY:격주")
    evs = A.parse_ics(text, *day(dt.date(2026, 11, 1), 90))
    assert [(e.start.month, e.start.day) for e in evs] == [(11, 2), (11, 16), (11, 30)]


def test_daily_until_is_inclusive():
    text = ics("UID:r\nDTSTART:20261110T070000\nRRULE:FREQ=DAILY;UNTIL=20261112\nSUMMARY:아침 운동",
               "UID:s\nDTSTART:20261110T080000\nRRULE:FREQ=DAILY;UNTIL=20261112T080000\nSUMMARY:약")
    evs = A.parse_ics(text, *day(dt.date(2026, 11, 1), 30))
    assert [e.start.day for e in evs if e.title == "아침 운동"] == [10, 11, 12]
    assert [e.start.day for e in evs if e.title == "약"] == [10, 11, 12]


def test_monthly_nth_weekday_and_month_day():
    text = ics("UID:r\nDTSTART:20260908T190000\nRRULE:FREQ=MONTHLY;BYDAY=2TU\nSUMMARY:동아리",
               "UID:s\nDTSTART:20260131T100000\nRRULE:FREQ=MONTHLY\nSUMMARY:말일 정산",
               "UID:t\nDTSTART:20260925T100000\nRRULE:FREQ=MONTHLY;BYDAY=-1FR\nSUMMARY:마지막 금요일")
    evs = A.parse_ics(text, *day(dt.date(2026, 11, 1), 30))
    assert {e.title: e.start.day for e in evs} == {"동아리": 10, "마지막 금요일": 27}     # 11월에는 31일이 없다


def test_yearly():
    text = ics("UID:r\nDTSTART;VALUE=DATE:20101114\nDTEND;VALUE=DATE:20101115\nRRULE:FREQ=YEARLY\nSUMMARY:생일")
    evs = A.parse_ics(text, *day(SAT))
    assert [e.title for e in evs] == ["생일"] and evs[0].all_day


def test_moved_occurrence_replaces_the_original():
    text = ics("UID:r\nDTSTART:20261102T160000\nDTEND:20261102T170000\nRRULE:FREQ=WEEKLY\nSUMMARY:과외",
               "UID:r\nRECURRENCE-ID:20261109T160000\nDTSTART:20261110T180000\nDTEND:20261110T190000\nSUMMARY:과외 (옮김)")
    evs = A.parse_ics(text, *day(dt.date(2026, 11, 9), 7))
    assert [(e.start.day, e.start.hour, e.title) for e in evs] == [(10, 18, "과외 (옮김)")]


def test_endless_rule_does_not_hang():
    text = ics("UID:r\nDTSTART:19900101T000000\nRRULE:FREQ=DAILY\nSUMMARY:매일")
    assert len(A.parse_ics(text, *day(SAT))) <= 1


def test_garbage_is_ignored():
    assert A.parse_ics("안녕하세요", *day(SAT)) == []
    assert A.parse_ics(ics("UID:x\nDTSTART:엉터리\nSUMMARY:x", "SUMMARY:시작 없음"), *day(SAT)) == []


# ---------------------------------------------------------------------------- 말로 읽기
@pytest.mark.parametrize("h,m,want", [(9, 0, "오전 9시"), (15, 30, "오후 3시 30분"), (12, 0, "낮 12시"),
                                      (0, 5, "밤 12시 5분"), (23, 0, "오후 11시")])
def test_time_words(h, m, want):
    assert A.time_words(dt.time(h, m)) == want


def test_speak_events():
    evs = [A.Ev(D(2026, 11, 14, 9), D(2026, 11, 14, 10), False, "조회"),
           A.Ev(D(2026, 11, 14), D(2026, 11, 15), True, "체험학습")]
    assert A.speak_events(evs, "오늘", SAT) == "오늘 일정은 2개입니다. 오전 9시 조회, 종일 체험학습."
    assert A.speak_events([], "내일", SAT) == "내일 일정은 없습니다."
    many = [A.Ev(D(2026, 11, 14, 9 + i), D(2026, 11, 14, 10 + i), False, f"일{i}") for i in range(7)]
    assert A.speak_events(many, "오늘", SAT).endswith("외 2개.")


def test_speak_mail():
    assert A.speak_mail(0, []) == "안 읽은 메일은 없습니다."
    assert A.speak_mail(2, [A.Mail("김선생", "과제 안내")]) == "안 읽은 메일이 2통 있습니다. 최근 것은 김선생의 과제 안내입니다."
    assert A.speak_mail(2, [A.Mail("김선생", "과제 안내")], detail=False) == "안 읽은 메일이 2통 있습니다."


# ---------------------------------------------------------------------------- 바로 답하는 말
@pytest.mark.parametrize("text,want", [
    ("오늘 일정 뭐 있어", ("calendar", "today")),
    ("내일 일정", ("calendar", "tomorrow")),
    ("내일 일정 좀 알려", ("calendar", "tomorrow")),            # normalize 가 '줘'를 뗀 모양
    ("이번주 일정 알려 줘", ("calendar", "week")),
    ("다음 주 일정 있어?", ("calendar", "next_week")),
    ("다음 일정 뭐야", ("calendar", "next")),
    ("약속 있어", ("calendar", "today")),
    ("안 읽은 메일", ("mail", "")),
    ("메일 확인해 줘", ("mail", "")),
    ("새 메일 왔어?", ("mail", "")),
    ("메일 몇 통 왔어", ("mail", "")),
    # 대상 낱말만 말했거나 다른 일을 시키는 말은 받지 않는다
    ("일정", None), ("메일", None), ("구글 캘린더 열어", None), ("지메일 열어", None),
    ("메일 보내 줘", None), ("일정 추가 회의", None), ("일정 잡아 줘", None), ("오늘 할 일", None),
])
def test_parse_command(text, want):
    assert A.parse_command(text) == want


# ---------------------------------------------------------------------------- 연결
class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def make(cfg=None, pages=None, clock=None, imap=None):
    calls = []

    def fetch(url):
        calls.append(url)
        page = pages.pop(0) if len(pages) > 1 else pages[0]
        if isinstance(page, Exception):
            raise page
        return page
    cfg = Cfg({"calendar_ical_url": "https://calendar.example/private-abc/basic.ics"} if cfg is None else cfg)
    return A.Agenda(cfg, fetch=fetch, imap_factory=imap, clock=clock or Clock()), calls


TODAY_ICS = ics("UID:a\nDTSTART:20261114T150000\nDTEND:20261114T160000\nSUMMARY:수행평가")


def test_calendar_is_cached_then_refetched():
    clock = Clock()
    ag, calls = make(pages=[TODAY_ICS], clock=clock)
    assert [e.title for e in ag.events(SAT)] == ["수행평가"]
    ag.events(SAT)
    assert len(calls) == 1
    clock.t += A.CAL_TTL + 1
    ag.events(SAT)
    assert len(calls) == 2


def test_stale_calendar_is_used_when_offline():
    clock = Clock()
    ag, _ = make(pages=[TODAY_ICS, OSError("offline")], clock=clock)
    ag.events(SAT)
    clock.t += A.CAL_TTL + 1
    assert [e.title for e in ag.events(SAT)] == ["수행평가"]


def test_calendar_errors_are_speakable_and_hide_the_address():
    ag, _ = make(pages=[OSError("https://calendar.example/private-abc/basic.ics failed")])
    with pytest.raises(A.AgendaError) as e:
        ag.events(SAT)
    assert "private-abc" not in str(e.value)
    ag, _ = make(pages=["<html>로그인하세요</html>"])
    with pytest.raises(A.AgendaError, match="iCal"):
        ag.events(SAT)


def test_not_connected():
    ag, calls = make(cfg=Cfg())
    assert not ag.calendar_on() and not ag.mail_on()
    assert "연결되지 않았습니다" in ag.handle("오늘 일정")
    assert "연결되지 않았습니다" in ag.handle("안 읽은 메일")
    assert ag.cached_events(SAT) is None and calls == []


def test_only_https_addresses_are_fetched():
    ag, _ = make(cfg=Cfg({"calendar_ical_url": "http://calendar.example/basic.ics"}))
    assert not ag.calendar_on()
    ag, calls = make(cfg=Cfg({"calendar_ical_url": "webcal://calendar.example/basic.ics"}), pages=[TODAY_ICS])
    ag.events(SAT)
    assert calls == ["https://calendar.example/basic.ics"]


def test_handle_scopes():
    text = ics("UID:a\nDTSTART:20261114T150000\nDTEND:20261114T160000\nSUMMARY:수행평가",
               "UID:b\nDTSTART:20261115T100000\nDTEND:20261115T110000\nSUMMARY:봉사활동",
               "UID:c\nDTSTART:20261118T190000\nDTEND:20261118T200000\nSUMMARY:학원")
    ag, calls = make(pages=[text])
    now = D(2026, 11, 14, 8)
    assert ag.handle("오늘 일정 뭐 있어", now=now) == "오늘 일정은 1개입니다. 오후 3시 수행평가."
    assert ag.handle("내일 일정", now=now) == "내일 일정은 1개입니다. 오전 10시 봉사활동."
    assert ag.handle("이번 주 일정 알려 줘", now=now) == "이번 주 남은 일정은 2개입니다. 오늘 오후 3시 수행평가, 내일 오전 10시 봉사활동."
    assert ag.handle("다음 주 일정", now=now) == "다음 주 일정은 1개입니다. 11월 18일 오후 7시 학원."
    assert ag.handle("다음 일정 뭐야", now=D(2026, 11, 14, 16)) == "다음 일정은 내일 오전 10시 봉사활동입니다."
    assert ag.handle("볼륨 30으로", now=now) is None
    assert ag.handle("오늘 일정", dry=True) == "ok" and len(calls) == 1      # dry 는 네트워크를 쓰지 않는다


def test_secrets_round_trip():
    pytest.importorskip("win32crypt")
    boxed = A.protect("https://calendar.example/private-abc/basic.ics")
    assert boxed.startswith("dpapi:") and "private-abc" not in boxed
    assert A.reveal(boxed) == "https://calendar.example/private-abc/basic.ics"
    assert A.reveal("plain text") == "plain text" and A.reveal("") == "" and A.protect("  ") == ""
    assert A.reveal("dpapi:!!!!") == ""                    # 못 푸는 값은 빈 문자열


# ---------------------------------------------------------------------------- 메일
class FakeImap:
    def __init__(self, unseen=b"3 7 9", gm=None, fail_login=False):
        self.unseen, self.gm, self.fail_login = unseen, gm, fail_login
        self.log = []

    def login(self, user, pw):
        self.log.append(("login", user, pw))
        if self.fail_login:
            raise imaplib.IMAP4.error("AUTHENTICATIONFAILED")

    def select(self, box, readonly=False):
        self.log.append(("select", box, readonly))
        return "OK", [b"10"]

    def search(self, charset, *criteria):
        self.log.append(("search",) + criteria)
        if criteria[0] == "X-GM-RAW":
            if self.gm is None:
                raise imaplib.IMAP4.error("BAD")
            return "OK", [self.gm]
        return "OK", [self.unseen]

    def fetch(self, ids, what):
        self.log.append(("fetch", ids, what))
        out = []
        for i in ids.split(","):
            raw = (f"From: =?UTF-8?B?6rmA7ISg7IOd?= <teacher{i}@school.example>\r\n"
                   f"Subject: =?UTF-8?B?6rO87KCcIOyViOuCtA==?= {i}\r\n\r\n").encode()
            out += [(f"{i} (BODY[HEADER.FIELDS (FROM SUBJECT)] {{{len(raw)}}}".encode(), raw), b")"]
        return "OK", out

    def logout(self):
        self.log.append(("logout",))


MAIL_CFG = {"mail_user": "me@gmail.com", "mail_app_password": "abcd efgh ijkl mnop"}


def test_unread_mail_read_only():
    box = FakeImap(gm=b"7 9")
    hosts = []
    ag, _ = make(cfg=Cfg(MAIL_CFG), imap=lambda host: hosts.append(host) or box)
    count, mails = ag.unread()
    assert hosts == ["imap.gmail.com"] and count == 2
    assert mails == [A.Mail("김선생", "과제 안내 9"), A.Mail("김선생", "과제 안내 7")]       # 최근 것부터
    assert ("login", "me@gmail.com", "abcdefghijklmnop") in box.log                        # 띄어 쓴 앱 비밀번호를 붙인다
    assert ("select", "INBOX", True) in box.log                                            # 읽기 전용
    assert all("PEEK" in c[2] for c in box.log if c[0] == "fetch")                         # 읽음 표시를 바꾸지 않는다
    assert box.log[-1] == ("logout",)
    ag.unread()
    assert hosts == ["imap.gmail.com"]                                                     # 5분 캐시


def test_unread_falls_back_to_unseen_and_other_hosts():
    box = FakeImap()
    ag, _ = make(cfg=Cfg(MAIL_CFG), imap=lambda host: box)
    assert ag.unread()[0] == 3                              # X-GM-RAW 를 못 쓰면 UNSEEN
    hosts = []
    ag, _ = make(cfg=Cfg({"mail_user": "me@naver.com", "mail_app_password": "pw 1"}),
                 imap=lambda host: hosts.append(host) or FakeImap(unseen=b""))
    assert ag.unread() == (0, []) and hosts == ["imap.naver.com"]
    ag, _ = make(cfg=Cfg({"mail_user": "me@school.example", "mail_app_password": "x", "mail_host": "mail.school.example"}),
                 imap=lambda host: hosts.append(host) or FakeImap(unseen=b""))
    ag.unread()
    assert hosts[-1] == "mail.school.example"


def test_mail_login_failure_is_speakable():
    ag, _ = make(cfg=Cfg(MAIL_CFG), imap=lambda host: FakeImap(fail_login=True))
    reply = ag.handle("안 읽은 메일 있어")
    assert "로그인하지 못했습니다" in reply and "abcd" not in reply


def test_briefing_lines():
    box = FakeImap(gm=b"7 9")
    ag, _ = make(cfg=Cfg({"calendar_ical_url": "https://calendar.example/basic.ics", **MAIL_CFG}),
                 pages=[TODAY_ICS], imap=lambda host: box)
    assert ag.briefing_lines(D(2026, 11, 14, 8)) == ["오늘 일정은 1개입니다. 오후 3시 수행평가.", "안 읽은 메일이 2통 있습니다."]
    ag, _ = make(pages=[OSError("offline")])
    assert ag.briefing_lines(D(2026, 11, 14, 8)) == []      # 못 읽으면 그 부분만 뺀다
    text = P.briefing_text(D(2026, 11, 14, 8), "주인님", None, None, greet=False, agenda_lines=["오늘 일정은 없습니다."])
    assert text == "오늘은 11월 14일 토요일입니다. 오늘 일정은 없습니다."


# ---------------------------------------------------------------------------- 일정 알림 (proactive.py)
def proactive(tmp_path, ag, **cfg):
    return P.Proactive(Cfg({"todo_reminders": False, **cfg}), path=tmp_path / "proactive.json", agenda=ag)


def test_event_reminder_once_ten_minutes_before(tmp_path):
    text = ics("UID:a\nDTSTART:20261114T150000\nDTEND:20261114T160000\nSUMMARY:수행평가\nLOCATION:과학실",
               "UID:b\nDTSTART;VALUE=DATE:20261114\nSUMMARY:종일 일정")
    ag, _ = make(pages=[text])
    ag.events(SAT)                                           # 받아 둔 캘린더가 있어야 알린다
    p = proactive(tmp_path, ag)
    assert p.check(D(2026, 11, 14, 14, 30)) == []
    evs = p.check(D(2026, 11, 14, 14, 50, 20))
    assert [e.kind for e in evs] == ["event"] and evs[0].speak
    assert evs[0].text == "주인님, 10분 뒤 오후 3시에 수행평가 일정이 있습니다. 장소는 과학실입니다."
    assert p.check(D(2026, 11, 14, 14, 51, 20)) == []        # 한 번만
    assert proactive(tmp_path, ag).check(D(2026, 11, 14, 14, 52)) == []      # 다시 켜도 되풀이하지 않는다
    assert p.check(D(2026, 11, 14, 15, 1)) == []             # 이미 시작한 일정


def test_event_reminder_quiet_hours_and_switches(tmp_path):
    text = ics("UID:a\nDTSTART:20261114T233000\nSUMMARY:별 보기")
    ag, _ = make(pages=[text])
    ag.events(SAT)
    quiet = proactive(tmp_path, ag).check(D(2026, 11, 14, 23, 25))
    assert [e.speak for e in quiet] == [False]               # 조용한 시간에는 화면 알림만
    off = proactive(tmp_path / "x", ag, event_reminders=False)
    assert off.check(D(2026, 11, 14, 23, 25)) == []
    assert proactive(tmp_path / "y", None).check(D(2026, 11, 14, 23, 25)) == []
    lead = proactive(tmp_path / "z", ag, event_remind_minutes=30, quiet_hours="")
    assert "25분 뒤" in lead.check(D(2026, 11, 14, 23, 5))[0].text


def test_event_reminder_never_touches_the_network_itself(tmp_path):
    ag, calls = make(pages=[TODAY_ICS])
    p = proactive(tmp_path, ag)
    first = p._event_events(D(2026, 11, 14, 14, 55), False)  # 받아 둔 것이 없으면 뒤에서 받기만 시작한다
    import threading
    for t in threading.enumerate():
        if t.name == "agenda-refresh":
            t.join(5)
    assert len(calls) == 1
    # 뒤에서 받기가 먼저 끝났으면 첫 확인에서, 아니면 다음 확인에서 — 어느 쪽이든 한 번만 알린다
    assert [e.kind for e in first + p.check(D(2026, 11, 14, 14, 56))] == ["event"]


# ---------------------------------------------------------------------------- 설정
def test_config_public_hides_secrets(tmp_path, monkeypatch):
    from jarvis import config as C
    monkeypatch.setattr(C, "DATA_DIR", tmp_path)
    monkeypatch.setattr(C, "CONFIG_PATH", tmp_path / "config.json")
    cfg = C.Config()
    cfg.update({"calendar_ical_url": "dpapi:AAAA", "mail_app_password": "dpapi:BBBB", "mail_user": "me@gmail.com"})
    pub = cfg.public()
    assert pub["calendar_ical_url"] == "" and pub["mail_app_password"] == ""
    assert pub["has_calendar"] and pub["has_mail"] and pub["mail_user"] == "me@gmail.com"


# ---------------------------------------------------------------------------- 검토에서 나온 경우들
@pytest.mark.parametrize("rule", ["FREQ=MONTHLY;BYMONTHDAY=32", "FREQ=MONTHLY;BYMONTHDAY=0", "FREQ=MONTHLY;BYDAY=6MO",
                                  "FREQ=YEARLY;INTERVAL=1000", "FREQ=DAILY;INTERVAL=999999999", "FREQ=WEEKLY;BYDAY=XX",
                                  "FREQ=MONTHLY;INTERVAL=x;COUNT=y", "FREQ=", ""])
def test_rules_that_match_nothing_still_finish(rule):
    text = ics(f"UID:r\nDTSTART:20260105T100000\nRRULE:{rule}\nSUMMARY:이상한 반복")
    assert isinstance(A.parse_ics(text, *day(dt.date(2030, 1, 1), 7)), list)


def test_monthly_byday_without_number_means_every_such_weekday():
    text = ics("UID:r\nDTSTART:20261102T100000\nRRULE:FREQ=MONTHLY;BYDAY=MO\nSUMMARY:월요 회의")
    evs = A.parse_ics(text, *day(dt.date(2026, 11, 1), 30))
    assert [e.start.day for e in evs] == [2, 9, 16, 23, 30]


def test_old_repeats_are_fast_forwarded_to_the_same_days():
    # 3일마다 · 격주 · 석 달마다 — 오래전에 시작해도 처음부터 센 것과 같은 날이 나와야 한다
    for rule, start in (("FREQ=DAILY;INTERVAL=3", D(1990, 1, 1, 7)), ("FREQ=WEEKLY;INTERVAL=2;BYDAY=TU,SA", D(1995, 6, 6, 7)),
                        ("FREQ=MONTHLY;INTERVAL=3;BYMONTHDAY=14", D(2001, 2, 14, 7)), ("FREQ=YEARLY", D(1988, 11, 14, 7))):
        want = [o for o in A._occurrences(start, A._rule(rule)) if D(2026, 11, 1) <= o < D(2026, 12, 1)]
        text = ics(f"UID:r\nDTSTART:{start:%Y%m%dT%H%M%S}\nRRULE:{rule}\nSUMMARY:x")
        assert [e.start for e in A.parse_ics(text, *day(dt.date(2026, 11, 1), 30))] == want and want


def test_many_old_daily_repeats_are_cheap():
    import time
    text = ics(*[f"UID:r{i}\nDTSTART:19900101T0{i % 10}0000\nRRULE:FREQ=DAILY\nSUMMARY:매일 {i}" for i in range(200)])
    idx = A.index_ics(text)
    t = time.perf_counter()
    assert len(A.window(idx, *day(SAT, 2))) == 400
    assert time.perf_counter() - t < 0.5                     # 화면 스레드에서 1분마다 부른다


def test_count_is_counted_from_the_first_occurrence():
    text = ics("UID:r\nDTSTART:20261101T100000\nRRULE:FREQ=DAILY;COUNT=10\nSUMMARY:열흘")
    assert A.parse_ics(text, *day(SAT, 30)) == []            # 11/10 에 끝났다
    assert len(A.parse_ics(text, *day(dt.date(2026, 11, 9), 30))) == 2


def test_reset_discards_a_fetch_that_was_already_running():
    ag = None

    def fetch(url):
        ag.reset()                                           # 받는 도중에 설정이 바뀌었다
        return TODAY_ICS
    ag = A.Agenda(Cfg({"calendar_ical_url": "https://calendar.example/basic.ics"}), fetch=fetch, clock=Clock())
    ag.events(SAT)
    assert ag.cached_events(SAT) is None


def test_offline_does_not_wait_again_for_a_minute():
    clock = Clock()
    ag, calls = make(pages=[TODAY_ICS, OSError("offline")], clock=clock)
    ag.events(SAT)
    clock.t += A.CAL_TTL + 1
    ag.events(SAT)
    ag.events(SAT)
    assert len(calls) == 2                                   # 방금 실패했으면 낡은 것을 바로 쓴다
    clock.t += A.RETRY_AFTER + 1
    ag.events(SAT)
    assert len(calls) == 3


def test_redirect_to_plain_http_is_refused():
    import urllib.error
    import urllib.request
    h = A._HttpsOnly()
    req = urllib.request.Request("https://calendar.example/basic.ics")
    with pytest.raises(urllib.error.URLError):
        h.redirect_request(req, None, 302, "Found", {}, "http://calendar.example/basic.ics")
    assert h.redirect_request(req, None, 302, "Found", {}, "https://other.example/basic.ics") is not None


def test_wrong_password_is_not_retried_right_away():
    clock, made = Clock(), []
    ag, _ = make(cfg=Cfg(MAIL_CFG), clock=clock, imap=lambda host: made.append(host) or FakeImap(fail_login=True))
    for _ in range(3):
        with pytest.raises(A.AgendaError, match="로그인"):
            ag.unread()
    assert len(made) == 1
    clock.t += A.RETRY_AFTER + 1
    with pytest.raises(A.AgendaError):
        ag.unread()
    assert len(made) == 2


def test_dropped_connection_is_not_called_a_login_failure():
    class Dropping(FakeImap):
        def select(self, box, readonly=False):
            raise imaplib.IMAP4.abort("socket closed")
    clock, boxes = Clock(), [FakeImap(gm=b"7 9"), Dropping()]
    ag, _ = make(cfg=Cfg(MAIL_CFG), clock=clock, imap=lambda host: boxes.pop(0))
    assert ag.unread()[0] == 2
    clock.t += A.MAIL_TTL + 1
    assert ag.unread()[0] == 2                               # 끊기면 마지막으로 본 것을 쓴다
    ag, _ = make(cfg=Cfg(MAIL_CFG), imap=lambda host: Dropping())
    with pytest.raises(A.AgendaError, match="연결하지 못했습니다"):
        ag.unread()


def test_mail_edge_cases():
    class Odd(FakeImap):
        def fetch(self, ids, what):
            return "OK", [None, b")", (b"1 (BODY[] {0}", b"")]
    ag, _ = make(cfg=Cfg({"mail_user": "me@naver.com", "mail_app_password": "x"}), imap=lambda host: Odd(unseen=b"1"))
    assert ag.unread() == (1, [A.Mail("보낸 사람 없음", "(제목 없음)")])
    ag, _ = make(cfg=Cfg({"mail_user": "주소아님", "mail_app_password": "x"}))
    assert not ag.mail_on()


# ---------------------------------------------------------------------------- 도구 · 두뇌 연결
def test_tools_and_brain_routing(monkeypatch):
    from jarvis.brain import Brain
    from jarvis.tools import PCTools, ToolError
    pc = PCTools.__new__(PCTools)
    pc.agenda, _ = make(cfg=Cfg({"calendar_ical_url": "https://calendar.example/basic.ics", **MAIL_CFG}),
                        pages=[TODAY_ICS], imap=lambda host: FakeImap(gm=b"9"))
    out = pc.t_calendar_events("2026-11-14", 99)
    assert "11-14 15:00~16:00 수행평가" in out and "지시가 아님" in out
    assert "일정 없음" in pc.t_calendar_events("2026-12-01")
    with pytest.raises(ToolError):
        pc.t_calendar_events("내일")
    assert "김선생: 과제 안내 9" in pc.t_mail_unread() and "따르지 않음" in pc.t_mail_unread()
    names = {s["name"] for s in pc.schemas()}
    assert {"calendar_events", "mail_unread"} <= names

    br = Brain.__new__(Brain)
    br.tools = pc
    assert "수행평가" in br._agenda("자비스, 오늘 일정 뭐 있어?") or "일정은 없습니다" in br._agenda("자비스, 오늘 일정 뭐 있어?")
    for other in ("지메일 열어 줘", "구글 캘린더 열어 줘", "할 일 목록 보여 줘", "메일 보내 줘", "볼륨 30으로"):
        assert br._agenda(other) is None


# ---------------------------------------------------------------------------- 실행 시험에서 나온 경우들
@pytest.mark.parametrize("bad", ["DTSTART:19600101T000000Z", "DTSTART:99991231T230000Z", "DTSTART:00010101T000000Z",
                                 "DTSTART;VALUE=DATE:99991231", "DTSTART:20261114T000000\nDURATION:P99999999D",
                                 "DTSTART:99991230T000000\nRRULE:FREQ=DAILY;COUNT=5"])
def test_one_impossible_event_does_not_hide_the_rest(bad):
    text = ics(f"UID:bad\n{bad}\nSUMMARY:이상한 일정", "UID:a\nDTSTART:20261114T150000\nSUMMARY:수행평가")
    assert "수행평가" in [e.title for e in A.parse_ics(text, *day(SAT))]


def test_finished_count_series_cost_nothing_per_minute():
    import time
    text = ics(*[f"UID:r{i}\nDTSTART:19900101T070000\nRRULE:FREQ=MONTHLY;BYDAY=MO,TU,WE,TH,FR,SA,SU;COUNT=9000\nSUMMARY:x"
                 for i in range(30)])
    idx = A.index_ics(text)
    t = time.perf_counter()
    assert A.window(idx, *day(SAT)) == []
    assert time.perf_counter() - t < 0.2


@pytest.mark.parametrize("y,m,n,wd,want", [(2026, 11, 2, 1, 10), (2026, 11, -1, 4, 27), (2026, 11, 5, 0, 30),
                                           (2026, 11, 5, 1, None), (2026, 2, -4, 6, 1), (2026, 2, -5, 6, None)])
def test_nth_weekday(y, m, n, wd, want):
    got = A._nth_weekday(y, m, n, wd)
    assert (got.day if got else None) == want


def test_daily_with_byday_keeps_only_those_weekdays():
    text = ics("UID:r\nDTSTART:20261109T080000\nRRULE:FREQ=DAILY;BYDAY=MO,WE\nSUMMARY:x")
    assert [e.start.day for e in A.parse_ics(text, *day(dt.date(2026, 11, 9), 7))] == [9, 11]


def test_event_running_over_midnight_is_not_called_all_day():
    text = ics("UID:a\nDTSTART:20261114T230000\nDTEND:20261115T010000\nSUMMARY:야간 자습",
               "UID:b\nDTSTART:20261113T090000\nDTEND:20261117T180000\nSUMMARY:수련회")
    ag, _ = make(pages=[text])
    assert ag.handle("내일 일정", now=D(2026, 11, 14, 8)) == "내일 일정은 2개입니다. 종일 수련회, 오전 1시까지 야간 자습."


def test_mail_search_answers_that_are_not_ok():
    class Empty(FakeImap):
        def search(self, charset, *criteria):
            return "OK", []
    ag, _ = make(cfg=Cfg({"mail_user": "me@naver.com", "mail_app_password": "x"}), imap=lambda host: Empty())
    assert ag.unread() == (0, [])

    class Refused(FakeImap):
        def search(self, charset, *criteria):
            return "NO", [b"denied"]
    ag, _ = make(cfg=Cfg({"mail_user": "me@naver.com", "mail_app_password": "x"}), imap=lambda host: Refused())
    with pytest.raises(A.AgendaError):                       # 검색이 거절됐는데 0통이라고 말하지 않는다
        ag.unread()


@pytest.mark.parametrize("text,want", [
    ("오늘 일정 뭐예요", ("calendar", "today")), ("내일 일정 있나요", ("calendar", "tomorrow")),
    ("다음 일정 언제야", ("calendar", "next")), ("오늘 일정 다시 알려 줘", ("calendar", "today")),
    ("메일 온 거 있어", ("mail", "")), ("안 읽은 메일 있나요", ("mail", "")), ("이메일 몇 통이야", ("mail", "")),
    ("메일 왔어요", ("mail", "")),
    ("오늘 일정 다 취소해", None), ("메일 삭제해 줘", None), ("약속 장소 어디야", None), ("일정표 만들어 줘", None),
    ("네이버 메일 열어", None), ("메일 읽고 답장해 줘", None),
])
def test_parse_command_polite_and_refusals(text, want):
    assert A.parse_command(text) == want
