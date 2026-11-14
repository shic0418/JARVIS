"""클래스룸 알림 정리(classroom.py): 지메일 목록 줄 읽기, 마감 찾기, 말로 정리, 할 일에 넣기, 명령 인식.
목록 줄은 실제 지메일(한국어 화면)이 화면 읽기 프로그램에 주는 모양을 본떴다 — 이름과 내용은 지어낸 것."""
from __future__ import annotations

import datetime as dt

import pytest

from jarvis import classroom as C
from jarvis import todos as T
from jarvis.config import DEFAULTS

SAT = dt.date(2026, 11, 14)          # 토요일


class Cfg(dict):
    def __getitem__(self, k):
        return self.get(k, DEFAULTS.get(k))


def row(teacher, subject, date, course, label, body, unread=True):
    head = "읽지 않음, " if unread else ""
    return (f"{head}{teacher}(클래스룸) , {subject} , {date} , 클래스룸 로고. 알림 설정 · {course}. {label}. {body} "
            f"세부정보 보기.")


ROWS = [
    row("가선생", "새 공지: ‘함수 유인물 2종입니다.’", "오후 2:39", "2026학년도 1학년 3반 공통수학", "새 공지사항",
        "함수 유인물 2종입니다."),
    row("나선생", "새 과제: '1차시: 입론서 작성'", "11월 13일", "ICPA 26-2 경제(3반)", "새 과제",
        "1차시: 입론서 작성. 수업 시간 50분 내에 완성하여 제출"),
    row("다선생", "새 공지: ‘11/17 화요일 수업시간에 [독서 탐구 수행평가]가 있습니다. 기사…’", "11월 12일",
        "화학 1-3", "새 공지사항", "11/17 화요일 수업시간에 [독서 탐구 수행평가]가 있습니다. 기사를 읽어 오세요.", unread=False),
    row("라선생", "새 자료: '4단원 문제 모음'", "11월 12일", "화학 1-3", "새 자료", "4단원 문제 모음"),
    row("마선생", '과제물을 돌려받음: "[수행평가 1] Questions"', "11월 12일", "물리학 103", "과제물을 돌려받음",
        "[수행평가 1] Questions"),
    row("바선생", "새 과제: '11월 11일 후기'", "11월 11일", "STP", "새 과제", "11월 11일 후기. 수업 후기를 쓰세요"),
    row("사선생", "새 과제: '스포츠 속 과학 보고서'", "11월 1일", "스포츠문화 3반", "새 과제",
        "스포츠 속 과학 보고서. 11/24까지 제출"),
    row("사선생", "새 과제: '체력운동 자세 평가'", "11월 1일", "스포츠문화 3반", "새 과제", "체력운동 자세 평가. 영상 제출"),
    row("사선생", "내일 기한: '체력운동 자세 평가'", "11월 2일", "스포츠문화 3반", "내일 기한", "체력운동 자세 평가"),
    row("바선생", "내일 기한: '사전질문'", "11월 13일", "STP", "내일 기한", "사전질문"),       # 원래 과제 메일이 없다
    "읽지않음Google Drive알림 1개",                                                           # 클래스룸이 아닌 줄
    "나선생(클래스룸)",                                                                       # 같은 메일의 조각 칸
]


@pytest.fixture
def items():
    return C.parse_rows(ROWS + ROWS[:3], SAT)               # 같은 줄이 두 번 읽혀도 한 번만


# ---------------------------------------------------------------------------- 한 줄 읽기
def test_parse_announcement():
    n = C.parse_row(ROWS[0], SAT)
    assert (n.kind, n.teacher, n.course, n.title, n.sent, n.unread, n.due) == (
        "공지", "가선생", "2026학년도 1학년 3반 공통수학", "함수 유인물 2종입니다.", SAT, True, None)


def test_parse_assignment_keeps_only_the_description_as_body():
    n = C.parse_row(ROWS[1], SAT)
    assert (n.kind, n.title, n.sent) == ("과제", "1차시: 입론서 작성", dt.date(2026, 11, 13))
    assert n.body.startswith("수업 시간 50분")


def test_truncated_title_is_taken_from_the_body():
    n = C.parse_row(ROWS[2], SAT)
    assert n.title == "11/17 화요일 수업시간에 [독서 탐구 수행평가]가 있습니다" and not n.unread
    assert n.due == dt.date(2026, 11, 17)


def test_other_kinds():
    assert C.parse_row(ROWS[3], SAT).kind == "자료"
    returned = C.parse_row(ROWS[4], SAT)
    assert (returned.kind, returned.title, returned.due) == ("반환", "[수행평가 1] Questions", None)


def test_date_in_an_assignment_title_is_not_its_deadline():
    assert C.parse_row(ROWS[5], SAT).due is None
    assert C.parse_row(ROWS[6], SAT).due == dt.date(2026, 11, 24)        # 본문의 '11/24까지' 는 마감


def test_not_classroom_rows_are_ignored():
    assert C.parse_row(ROWS[-1], SAT) is None and C.parse_row(ROWS[-2], SAT) is None
    assert C.parse_row("", SAT) is None


@pytest.mark.parametrize("text,want", [
    ("오후 2:39", SAT), ("오전 9:05", SAT), ("2:39 PM", SAT), ("어제", dt.date(2026, 11, 13)),
    ("11월 13일", dt.date(2026, 11, 13)), ("12월 30일", dt.date(2025, 12, 30)),     # 앞으로의 날짜면 작년
    ("2025. 3. 4.", dt.date(2025, 3, 4)), ("25. 3. 4.", dt.date(2025, 3, 4)), ("Nov 13", dt.date(2026, 11, 13)),
    ("11/13/2026", dt.date(2026, 11, 13)), ("2월 30일", None), ("엉터리", None),
])
def test_mail_date(text, want):
    assert C.mail_date(text, SAT) == want


# ---------------------------------------------------------------------------- 여러 줄
def test_rows_are_deduplicated_and_sorted(items):
    assert len(items) == 9
    assert [i.sent for i in items] == sorted((i.sent for i in items), reverse=True)


def test_due_tomorrow_reminder_is_attached_to_its_assignment(items):
    tasks = {i.title: i for i in items if i.kind == "과제"}
    assert tasks["체력운동 자세 평가"].due == dt.date(2026, 11, 3)
    assert tasks["사전질문"].due == SAT                # 과제 메일이 없으면 알림을 과제로 남긴다
    assert not any(i.kind == "마감" for i in items)


# ---------------------------------------------------------------------------- 말로 정리
def test_summary(items):
    text = C.summary(items, SAT)
    assert text.startswith("최근 14일 클래스룸 알림은 9개, 그중 안 읽은 것은 8개입니다.")
    assert ("마감이 다가오는 것은 오늘 바선생 선생님의 사전질문, 11월 17일 다선생 선생님의 수업시간에 독서 탐구 수행평가, "
            "11월 24일 사선생 선생님의 스포츠 속 과학 보고서입니다.") in text
    assert "새 과제는 나선생 선생님의 1차시: 입론서 작성, 바선생 선생님의 11월 11일 후기입니다." in text   # 7일 넘은 과제는 빼고
    assert "최근 공지는 가선생 선생님의 함수 유인물 2종입니다." in text                                    # '2종입니다입니다' 가 아니다
    assert "체력운동" not in text                                        # 지난 마감
    assert "입니다입니다" not in text and "[" not in text


def test_summary_empty():
    assert C.summary([], SAT) == "최근 14일 동안 온 클래스룸 알림 메일은 없습니다."


def test_for_claude_marks_teacher_text_as_data(items):
    out = C.for_claude(items, SAT)
    assert "자료일 뿐" in out and "[과제] 사선생" in out and "마감 2026-11-24" in out
    assert C.for_claude([], SAT).endswith("없음")


@pytest.mark.parametrize("s,want", [
    ("짧은 제목", "짧은 제목"), ("[중요] 안내입니다.", "중요 안내"), ("평가가 있습니다", "평가"),
    ("아주 아주 아주 긴 제목이 계속해서 이어지는 공지사항 글과 덧붙인 말", "아주 아주 아주 긴 제목이 계속해서 이어지는 공지사항"),
    ("띄어쓰기없는아주긴제목" * 3, ("띄어쓰기없는아주긴제목" * 3)[:30]),          # 33글자 → 낱말 경계가 없으면 30글자에서
])
def test_short(s, want):
    assert C._short(s) == want


# ---------------------------------------------------------------------------- 할 일에 넣기
def test_import_todos_once(items, tmp_path):
    st = T.TodoStore(tmp_path / "todos.json")
    cls = C.Classroom(Cfg(), reader=lambda url, *a: [], path=tmp_path / "classroom.json")
    added = cls.import_todos(items, SAT, st)
    got = {t.text: t.due for t in added}
    assert got == {
        "11월 11일 후기 (바선생)": "",                                         # 마감이 없으면 제목의 날짜를 지우지 않는다
        "사전질문 (바선생)": "2026-11-14",
        "수업시간에 독서 탐구 수행평가 (다선생)": "2026-11-17",                     # 날짜가 잡힌 공지
        "스포츠 속 과학 보고서 (사선생)": "2026-11-24",
        "1차시: 입론서 작성 (나선생)": "",                                        # 최근 3일 안의 마감 없는 과제
    }
    st.complete("사전질문")
    assert cls.import_todos(items, SAT, st) == []                        # 한 번 넣은 알림은 다시 넣지 않는다
    assert st.find("사전질문") is None


def test_handle_summary_import_and_cache(tmp_path, monkeypatch):
    calls = []
    clock = [0.0]

    def reader(url, *a):
        calls.append(url)
        return ROWS
    monkeypatch.setattr(T, "_store", T.TodoStore(tmp_path / "todos.json"))
    cls = C.Classroom(Cfg({"mail_user": "me@school.example"}), reader=reader, clock=lambda: clock[0],
                      path=tmp_path / "classroom.json")
    assert cls.handle("클래스룸 정리해 줘", today=SAT).startswith("최근 14일 클래스룸 알림은 9개")
    assert "authuser=me%40school.example" in calls[0] and "from%3Aclassroom.google.com" in calls[0]
    reply = cls.handle("클래스룸 과제 할 일에 넣어 줘", today=SAT)
    assert reply.startswith("클래스룸 과제 5개를 할 일에 넣었습니다.") and len(calls) == 1      # 5분 안이면 다시 읽지 않는다
    assert cls.handle("클래스룸 과제 할 일에 넣어 줘", today=SAT) == "할 일에 새로 넣을 클래스룸 과제는 없습니다."
    clock[0] += C.CACHE_SECONDS + 1
    cls.handle("클래스룸 확인해 줘", today=SAT)
    assert len(calls) == 2
    assert cls.handle("볼륨 30", today=SAT) is None
    assert cls.handle("클래스룸 정리", dry=True) == "ok" and len(calls) == 2


def test_handle_errors_are_speakable(tmp_path):
    def broken(url, *a):
        raise RuntimeError("uia exploded")
    cls = C.Classroom(Cfg(), reader=broken, path=tmp_path / "c.json")
    assert "지메일 목록을 읽지 못했습니다" in cls.handle("클래스룸 정리해 줘", today=SAT)

    def missing(url, *a):
        raise C.ClassroomError("크롬에서 지메일 검색 화면을 열지 못했습니다.")
    cls = C.Classroom(Cfg(), reader=missing, path=tmp_path / "c.json")
    assert cls.handle("클래스룸 정리해 줘", today=SAT) == "크롬에서 지메일 검색 화면을 열지 못했습니다."


def test_search_url():
    assert C.search_url() == "https://mail.google.com/mail/u/0/#search/from%3Aclassroom.google.com%20newer_than%3A14d"
    assert C.search_url("a@b.kr").startswith("https://mail.google.com/mail/?authuser=a%40b.kr#search/")
    assert C.search_url("이상한값").startswith("https://mail.google.com/mail/u/0/")


# ---------------------------------------------------------------------------- 명령
@pytest.mark.parametrize("text,want", [
    ("클래스룸 정리해 줘", "summary"), ("클래스룸 알림 확인", "summary"), ("구글 클래스룸 공지 알려 줘", "summary"),
    ("클래스룸 뭐 왔어", "summary"), ("클래스룸 과제 있어?", "summary"), ("클래스룸 새 소식 요약해 줘", "summary"),
    ("클래스룸 과제 할 일에 넣어 줘", "import"), ("클래스룸 과제 가져와", "import"), ("클래스룸 할 일에 추가해", "import"),
    ("구글 클래스룸 열어", None), ("클래스룸", None), ("클래스룸 들어가 줘", None), ("클래스룸 과제 제출해 줘", None),
    ("오늘 할 일", None),
])
def test_parse_command(text, want):
    assert C.parse_command(text) == want


def test_brain_routes_classroom_before_todos():
    from jarvis.brain import Brain

    class Fake:
        def __init__(self):
            self.seen = []

        def handle(self, text, dry=False, on_start=None):
            self.seen.append(text)
            return "정리" if C.parse_command(text) else None
    br = Brain.__new__(Brain)
    br.tools = type("Tools", (), {})()
    br.tools.classroom = Fake()
    assert br._classroom("자비스, 클래스룸 과제 할 일에 넣어 줘") == "정리"
    assert br._classroom("구글 클래스룸 열어 줘") is None


# ---------------------------------------------------------------------------- 검토에서 나온 경우들
def test_due_only_from_the_sentence_that_talks_about_a_deadline():
    far = row("가선생", "새 공지: ‘안내’", "11월 12일", "화학", "새 공지사항",
              "수행평가 점수는 20%입니다. 다음 주 수요일에는 체육대회가 있어요.")
    assert C.parse_row(far, SAT).due is None                    # '수행평가' 와 날짜가 다른 문장
    near = row("가선생", "새 공지: ‘안내’", "11월 12일", "화학", "새 공지사항", "다음 주 수요일까지 보고서를 제출하세요.")
    assert C.parse_row(near, SAT).due == dt.date(2026, 11, 18)
    streak = row("가선생", "새 공지: ‘안내’", "11월 12일", "화학", "새 공지사항", "3일 연속 시험이 있습니다.")
    assert C.parse_row(streak, SAT).due is None
    pages = row("가선생", "새 과제: '읽기'", "11월 12일", "영어", "새 과제", "읽기. p123~p136 까지 읽어 오세요.")
    assert C.parse_row(pages, SAT).due is None


def test_course_name_with_a_period():
    n = C.parse_row(row("가선생", "새 공지: ‘안내’", "11월 12일", "공통수학 (Ver. 2)", "새 공지사항", "유인물입니다."), SAT)
    assert n.course == "공통수학 (Ver. 2)" and n.body.startswith("유인물")


def test_same_title_in_two_classes_stays_two_notices():
    a = row("가선생", "새 공지: ‘준비물’", "11월 12일", "1반", "새 공지사항", "준비물")
    b = row("가선생", "새 공지: ‘준비물’", "11월 12일", "2반", "새 공지사항", "준비물")
    assert len(C.parse_rows([a, b], SAT)) == 2


def test_deadline_that_arrives_later_fills_the_todo(tmp_path):
    st = T.TodoStore(tmp_path / "todos.json")
    cls = C.Classroom(Cfg(), reader=lambda url, *a: [], path=tmp_path / "classroom.json")
    task = row("가선생", "새 과제: '보고서'", "11월 13일", "과학", "새 과제", "보고서")
    assert [t.due for t in cls.import_todos(C.parse_rows([task], SAT), SAT, st)] == [""]
    remind = row("가선생", "내일 기한: '보고서'", "오후 3:00", "과학", "내일 기한", "보고서")
    got = cls.import_todos(C.parse_rows([task, remind], SAT), SAT, st)
    assert [(t.text, t.due) for t in got] == [("보고서 (가선생)", "2026-11-15")]
    assert len(st.open_items()) == 1
    assert cls.import_todos(C.parse_rows([task, remind], SAT), SAT, st) == []


def test_failure_is_not_retried_for_a_minute(tmp_path):
    calls, clock = [], [0.0]

    def missing(url, *a):
        calls.append(url)
        raise C.ClassroomError("크롬에서 지메일 검색 화면을 열지 못했습니다.")
    cls = C.Classroom(Cfg(), reader=missing, clock=lambda: clock[0], path=tmp_path / "c.json")
    for _ in range(3):
        assert "열지 못했습니다" in cls.handle("클래스룸 정리해 줘", today=SAT)
    assert len(calls) == 1
    clock[0] += C.RETRY_AFTER + 1
    cls.handle("클래스룸 정리해 줘", today=SAT)
    assert len(calls) == 2


@pytest.mark.parametrize("text,want", [("클래스룸 보여 줘", None), ("클래스룸 과제 보여 줘", "summary"),
                                       ("클래스룸 알림 보여 줘", "summary"), ("클래스룸 열어 줘", None)])
def test_show_alone_is_opening_the_site(text, want):
    assert C.parse_command(text) == want


# ---------------------------------------------------------------------------- 탭을 열고 닫기 (가짜 Windows)
class FakeDesk:
    """크롬 창 하나. open() 이 새 탭을 앞에 띄운다. 사용자 행동은 시험마다 바꿔 끼운다."""

    def __init__(self, tabs=3, user_tab_title="문서 - Chrome", default_is_chrome=True):
        self.hwnd, self.other = 100, 200
        self.tabs = tabs
        self.sel = ("user",)
        self.title = user_tab_title
        self.fg = self.other
        self.keys, self.focused = [], []
        self.default_is_chrome = default_is_chrome
        self.idle = 5.0
        self.on_read = None

    def open(self, url):
        if self.default_is_chrome:
            self.tabs += 1
            self.sel = ("ours",)
            self.title = "검색결과 - me@school.kr - 학교 메일 - Chrome"
            self.fg = self.hwnd

    def install(self, monkeypatch):
        from jarvis import winutil
        monkeypatch.setattr(C.time, "sleep", lambda s: None)
        monkeypatch.setattr(C.webbrowser, "open", self.open)
        monkeypatch.setattr(C, "_tabs", lambda h: (self.tabs, self.sel) if h == self.hwnd else (-1, None))
        monkeypatch.setattr(C, "_wake", lambda h: None)
        monkeypatch.setattr(C, "_row_names", self.rows)
        monkeypatch.setattr(C, "LOAD_TIMEOUT", 0.05)
        monkeypatch.setattr(C, "ROWS_TIMEOUT", 0.05)
        monkeypatch.setattr(winutil, "foreground", lambda: self.fg)
        monkeypatch.setattr(winutil, "list_windows", lambda: [
            {"hwnd": self.hwnd, "title": self.title, "exe": "chrome.exe"},
            {"hwnd": self.other, "title": "J.A.R.V.I.S", "exe": "python.exe"}])
        monkeypatch.setattr(winutil, "window_title", lambda h: self.title if h == self.hwnd else "J.A.R.V.I.S")
        monkeypatch.setattr(winutil, "idle_seconds", lambda: self.idle)
        monkeypatch.setattr(winutil, "press_combo", self.press)
        monkeypatch.setattr(winutil, "force_foreground", lambda h: self.focused.append(h) or True)

    def rows(self, hwnd):
        if self.on_read:
            self.on_read(self)
        return ROWS[:2]

    def press(self, combo):
        self.keys.append((combo, self.sel))
        if combo == "ctrl+w":
            self.tabs -= 1


def test_reads_then_closes_only_our_tab_and_returns_focus(monkeypatch):
    d = FakeDesk()
    d.install(monkeypatch)
    assert C.read_rows_in_browser("https://mail.google.com/x") == ROWS[:2]
    assert d.keys == [("ctrl+w", ("ours",))] and d.focused == [d.other]


def test_existing_search_tab_of_the_user_is_never_closed(monkeypatch):
    # 사용자가 이미 지메일 검색 결과 탭을 앞에 두고 있고, 기본 브라우저가 크롬이 아니라 새 탭이 생기지 않았다
    d = FakeDesk(user_tab_title="검색결과 - me@school.kr - 학교 메일 - Chrome", default_is_chrome=False)
    d.fg = d.hwnd
    d.install(monkeypatch)
    with pytest.raises(C.ClassroomError):
        C.read_rows_in_browser("https://mail.google.com/x")
    assert d.keys == []


def test_tab_is_left_open_when_the_user_moves_or_types(monkeypatch):
    def switch_tab(d):
        d.sel = ("user's other search tab",)            # 같은 제목의 다른 탭으로 옮겼다
    d = FakeDesk()
    d.on_read = switch_tab
    d.install(monkeypatch)
    C.read_rows_in_browser("https://mail.google.com/x")
    assert d.keys == []

    def typing(d):
        d.idle = 0.2
    d = FakeDesk()
    d.on_read = typing
    d.install(monkeypatch)
    C.read_rows_in_browser("https://mail.google.com/x")
    assert d.keys == []

    def other_app(d):
        d.fg = d.other
    d = FakeDesk()
    d.on_read = other_app
    d.install(monkeypatch)
    C.read_rows_in_browser("https://mail.google.com/x")
    assert d.keys == [] and d.focused == []             # 사용자가 이미 다른 창으로 갔으면 포커스도 건드리지 않는다


# ---------------------------------------------------------------------------- 실제로 써 보고 고친 것
@pytest.mark.parametrize("text", ["클래스 룸 정리해 줘", "클레스룸 정리해 줘", "클래스름 알림 확인", "글래스룸 정리해 줘",
                                  "구글 클래스 정리해 줘", "구글 클래스 과제 할 일에 넣어 줘", "classroom 정리해 줘"])
def test_misheard_spellings(text):
    assert C.parse_command(text) is not None


@pytest.mark.parametrize("text", ["클래스 정리해 줘", "클래스 회의 알려 줘", "구글 클래스룸 경제", "구글 클래스에서 경제 탭 들어가 줘"])
def test_spellings_that_are_not_classroom_commands(text):
    assert C.parse_command(text) is None


def test_says_it_is_starting_before_the_slow_read(tmp_path):
    order = []
    cls = C.Classroom(Cfg(), reader=lambda url, *a: order.append("read") or ROWS, path=tmp_path / "c.json")
    cls.handle("클래스룸 정리해 줘", today=SAT, on_start=lambda: order.append("ack"))
    assert order == ["ack", "read"]
    cls.handle("클래스룸 정리해 줘", today=SAT, on_start=lambda: order.append("ack"))    # 방금 읽었으면 바로 답한다
    assert order == ["ack", "read"]
    cls.handle("클래스룸", today=SAT, on_start=lambda: order.append("ack"))              # 상관없는 말
    assert order == ["ack", "read"]


def test_brain_streams_the_ack_then_answers(tmp_path):
    from jarvis.brain import Brain
    br = Brain.__new__(Brain)
    br.tools = type("Tools", (), {})()
    br.tools.classroom = C.Classroom(Cfg(), reader=lambda url, *a: ROWS, path=tmp_path / "c.json")
    said = []
    reply = br._classroom("자비스, 클래스룸 정리해 줘", said.append)
    assert len(said) == 1 and "클래스룸" in said[0] and said[0].endswith("\n")
    assert reply.startswith("최근 14일 클래스룸 알림은")
    br.tools.classroom = C.Classroom(Cfg(), reader=lambda url, *a: ROWS, path=tmp_path / "d.json")
    assert br._classroom("클래스룸 정리해 줘", None).startswith("최근 14일")      # 흘려보낼 곳이 없으면 안내 없이


@pytest.mark.parametrize("text,want", [("Classroom 정리해 줘", "summary"), ("CLASSROOM 과제 가져와", "import"),
                                       ("구글 글래스 알려 줘", None), ("구글 글래스룸 정리해 줘", "summary")])
def test_case_and_google_glass(text, want):
    assert C.parse_command(text) == want


def test_fresh(tmp_path):
    clock = [0.0]
    cls = C.Classroom(Cfg(), reader=lambda url, *a: ROWS, clock=lambda: clock[0], path=tmp_path / "c.json")
    assert not cls.fresh(SAT)
    cls.notices(SAT)
    assert cls.fresh(SAT) and not cls.fresh(SAT + dt.timedelta(days=1))
    clock[0] += C.CACHE_SECONDS + 1
    assert not cls.fresh(SAT)


def test_ack_order_on_failure_and_no_ack_while_waiting(tmp_path):
    order = []

    def missing(url, *a):
        order.append("read")
        raise C.ClassroomError("열지 못했습니다.")
    cls = C.Classroom(Cfg(), reader=missing, clock=lambda: 0.0, path=tmp_path / "c.json")
    assert cls.handle("클래스룸 정리해 줘", today=SAT, on_start=lambda: order.append("ack")) == "열지 못했습니다."
    assert order == ["ack", "read"]
    cls.handle("클래스룸 정리해 줘", today=SAT, on_start=lambda: order.append("ack"))      # 1분 대기 중: 안내도 읽기도 없음
    assert order == ["ack", "read"]


def test_a_broken_ack_does_not_stop_the_answer(tmp_path):
    def boom():
        raise RuntimeError("tts gone")
    cls = C.Classroom(Cfg(), reader=lambda url, *a: ROWS, path=tmp_path / "c.json")
    assert cls.handle("클래스룸 정리해 줘", today=SAT, on_start=boom).startswith("최근 14일")


# ---------------------------------------------------------------------------- 구글 계정 · 크롬 프로필이 여럿일 때
PROFILES = [("Default", "me@gmail.com", ""), ("Profile 17", "kid@school.example.kr", "school.example.kr"),
            ("Profile 18", "other@gmail.com", "")]


def test_pick_account_prefers_the_setting_then_the_only_school_profile():
    assert C.pick_account("", PROFILES) == C.Account("kid@school.example.kr", "Profile 17")
    assert C.pick_account("other@gmail.com", PROFILES) == C.Account("other@gmail.com", "Profile 18")
    assert C.pick_account("KID@school.example.kr", PROFILES).profile == "Profile 17"
    assert C.pick_account("x@else.kr", PROFILES) == C.Account("x@else.kr", "")      # 프로필은 없지만 그 계정으로 연다
    two = PROFILES + [("Profile 20", "t@work.example", "work.example")]
    assert C.pick_account("", two) == C.Account()                                  # 학교 · 회사가 둘이면 고르지 않는다
    assert C.pick_account("", []) == C.Account()


def test_chrome_profiles_reads_local_state(tmp_path):
    import json
    path = tmp_path / "Local State"
    path.write_text(json.dumps({"profile": {"info_cache": {
        "Default": {"user_name": "me@gmail.com", "hosted_domain": "NO_HOSTED_DOMAIN"},
        "Profile 17": {"user_name": "kid@school.example.kr", "hosted_domain": "school.example.kr"},
        "Profile 3": {"user_name": ""}}}}), encoding="utf-8")
    assert sorted(C.chrome_profiles(path)) == [("Default", "me@gmail.com", ""), ("Profile 17", "kid@school.example.kr",
                                                                                   "school.example.kr"), ("Profile 3", "", "")]
    assert C.chrome_profiles(tmp_path / "없음") == []


def test_wrong_account():
    acct = C.Account("kid@school.example.kr", "Profile 17")
    assert C._wrong_account(acct, "검색결과 - me@gmail.com - Gmail") == "gmail.com"
    assert C._wrong_account(acct, "검색결과 - Kid@School.example.kr - 학교 메일") is None
    assert C._wrong_account(C.Account("kid+tag@school.example.kr"), "검색결과 - kid@school.example.kr - 학교") is None
    assert C._wrong_account(acct, "받은편지함 - me@gmail.com - Gmail") is None            # 검색 결과 제목이 아니면 따지지 않는다
    # 누구로 열지 정하지 못했으면 개인 지메일이 열렸을 때만 알린다
    assert C._wrong_account(C.Account(), "검색결과 - me@gmail.com - Gmail") == "gmail.com"
    assert C._wrong_account(C.Account(), "검색결과 - kid@school.example.kr - 학교") is None


def test_top_row_ignores_tabs_inside_the_page():
    strip = [(10, 0, False, ("a",)), (11, 200, True, ("b",))]
    side_panel = [(300, 1800, False, ("cal",)), (360, 1800, False, ("keep",)), (420, 1800, False, ("tasks",))]
    assert C.top_row(strip + side_panel, 0, 1000) == (2, ("b",))
    assert C.top_row(side_panel, 0, 1000) == (0, None)                       # 맨 위 탭 줄이 없다 (전체 화면)
    assert C.top_row([], 0, 1000) == (0, None)


def test_school_profile_is_opened_and_url_names_the_account(tmp_path, monkeypatch):
    seen = []
    monkeypatch.setattr(C, "chrome_profiles", lambda path=None: PROFILES)
    cls = C.Classroom(Cfg(), reader=lambda url, acct: seen.append((url, acct)) or ROWS, path=tmp_path / "c.json")
    cls.notices(SAT)
    url, acct = seen[0]
    assert acct == C.Account("kid@school.example.kr", "Profile 17") and "authuser=kid%40school.example.kr" in url


def test_open_uses_the_chrome_profile(monkeypatch):
    calls = []
    monkeypatch.setattr(C, "chrome_exe", lambda: r"C:\chrome.exe")
    monkeypatch.setattr(C.subprocess, "Popen", lambda args, **kw: calls.append(args))
    monkeypatch.setattr(C.webbrowser, "open", lambda url: calls.append(("default", url)))
    C._open("https://x", C.Account("kid@school.example.kr", "Profile 17"))
    C._open("https://y", C.Account("kid@school.example.kr", ""))
    C._open("https://z", None)
    assert calls == [[r"C:\chrome.exe", "--profile-directory=Profile 17", "https://x"], ("default", "https://y"),
                     ("default", "https://z")]


def test_other_account_is_reported_and_our_tab_closed(monkeypatch):
    d = FakeDesk()
    d.install(monkeypatch)
    monkeypatch.setattr(C, "chrome_exe", lambda: None)
    d.open_title = "검색결과 - me@gmail.com - Gmail - Chrome"
    orig = d.open

    def open_personal(url):
        orig(url)
        d.title = d.open_title
    monkeypatch.setattr(C.webbrowser, "open", open_personal)
    with pytest.raises(C.ClassroomError, match="gmail.com 계정"):
        C.read_rows_in_browser("https://x", C.Account("kid@school.example.kr", "Profile 17"))
    assert d.keys == [("ctrl+w", ("ours",))]                 # 우리가 연 탭이니 닫는다



def test_top_row_edges():
    assert C.top_row([(10, 0, True, ("a",)), (22, 100, False, ("b",)), (23, 200, False, ("c",))], 0, 1000) == (2, ("a",))
    assert C.top_row([(10, 0, False, ("a",)), (40, 0, True, ("x",))], 0, 1000) == (1, None)    # 선택된 것이 줄 밖
    assert C.top_row([(500, 0, True, ("a",))], None, None) == (1, ("a",))                      # 창 크기를 모르면 맨 위 줄


def test_open_falls_back_when_chrome_cannot_start(monkeypatch):
    calls = []

    def broken(args, **kw):
        raise OSError("gone")
    monkeypatch.setattr(C, "chrome_exe", lambda: r"C:\old\chrome.exe")
    monkeypatch.setattr(C.subprocess, "Popen", broken)
    monkeypatch.setattr(C.webbrowser, "open", lambda url: calls.append(url))
    C._open("https://x", C.Account("kid@school.example.kr", "Profile 17"))
    assert calls == ["https://x"]


def test_personal_gmail_opened_without_a_chosen_account(monkeypatch):
    d = FakeDesk()
    d.install(monkeypatch)
    orig = d.open

    def open_personal(url):
        orig(url)
        d.title = "검색결과 - me@gmail.com - Gmail - Chrome"
    monkeypatch.setattr(C.webbrowser, "open", open_personal)
    with pytest.raises(C.ClassroomError, match="개인 gmail.com 계정") as e:
        C.read_rows_in_browser("https://x", C.Account())
    assert "메일 주소 칸" in str(e.value)


def test_why_the_tab_was_left_open_is_logged(monkeypatch, caplog):
    def typing(d):
        d.idle = 0.2
    d = FakeDesk()
    d.on_read = typing
    d.install(monkeypatch)
    with caplog.at_level("INFO", logger="jarvis.classroom"):
        C.read_rows_in_browser("https://mail.google.com/x")
    assert "방금 키보드 · 마우스 입력" in caplog.text
