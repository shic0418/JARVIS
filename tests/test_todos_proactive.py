"""할 일 · 마감(todos.py)과 먼저 말 걸기(proactive.py)."""
from __future__ import annotations

import datetime as dt

import pytest

from jarvis import proactive as P
from jarvis import todos as T
from jarvis.config import DEFAULTS

SAT = dt.date(2026, 11, 14)          # 토요일


class Cfg(dict):
    def __getitem__(self, k):
        return self.get(k, DEFAULTS.get(k))


@pytest.fixture
def st(tmp_path):
    return T.TodoStore(tmp_path / "todos.json")


# ---------------------------------------------------------------------------- 마감 날짜
@pytest.mark.parametrize("text,due,rest", [
    ("경제 과제 금요일까지", dt.date(2026, 11, 20), "경제 과제"),
    ("영어 단어 외우기 내일까지", dt.date(2026, 11, 15), "영어 단어 외우기"),
    ("보고서 11월 20일 마감", dt.date(2026, 11, 20), "보고서"),
    ("수학 숙제 다음 주 수요일까지", dt.date(2026, 11, 18), "수학 숙제"),
    ("발표 준비 3일 뒤", dt.date(2026, 11, 17), "발표 준비"),
    ("과학 보고서 25일까지", dt.date(2026, 11, 25), "과학 보고서"),
    ("독후감 이번 주까지", dt.date(2026, 11, 15), "독후감"),
    ("동아리 회비 주말까지", SAT, "동아리 회비"),
    ("서류 1월 3일까지", dt.date(2027, 1, 3), "서류"),
    ("시험 공부 토요일", SAT, "시험 공부"),                     # 오늘이 토요일이면 오늘
    ("목 스트레칭", None, "목 스트레칭"),                        # 요일 한 글자는 날짜가 아니다
    ("3월까지 여권 갱신", None, None),
    ("책 반납", None, "책 반납"),
])
def test_parse_due(text, due, rest):
    d, r = T.parse_due(text, SAT)
    if rest is None:                 # 'N월까지' 처럼 일자가 없으면 날짜로 보지 않는다
        assert d is None
        return
    assert d == due and r == rest


def test_due_words():
    assert T.due_words(SAT, SAT) == "오늘"
    assert T.due_words(SAT + dt.timedelta(days=1), SAT) == "내일"
    assert T.due_words(dt.date(2026, 11, 13), SAT) == "1일 지남"
    assert T.due_words(dt.date(2026, 11, 20), SAT) == "11월 20일"            # 토요일 기준 다음 주는 날짜로
    assert T.due_words(dt.date(2026, 11, 13), dt.date(2026, 11, 9)) == "금요일"
    assert T.due_words(None, SAT) == "마감 없음"


# ---------------------------------------------------------------------------- 명령
@pytest.mark.parametrize("text,kind", [
    ("할 일 추가 경제 과제 금요일까지", "add"),
    ("경제 과제 금요일까지 할 일에 추가해 줘", "add"),
    ("할일 추가: 책 반납", "add"),
    ("할 일 목록", "list"), ("오늘 할 일", "list"), ("이번 주 할 일 뭐 있어", "list"),
    ("내일 할 일 알려줘", "list"), ("해야 할 일 뭐 있어", "list"), ("남은 할 일 알려 줘", "list"),
    ("할 일 완료 경제 과제", "done"), ("경제 과제 다 했어", "done_say"),
    ("할 일 삭제 책 반납", "delete"), ("책 반납 할 일에서 지워 줘", "delete"),
    ("크롬 열어 줘", None), ("밥 먹었어", None), ("할 일", "list"),
])
def test_parse_command(text, kind):
    got = T.parse_command(text, SAT)
    assert (got[0] if got else None) == kind


def test_handle_flow(st):
    say = T.handle("할 일 추가 경제 과제 금요일까지", st, SAT)
    assert "경제 과제" in say and "11월 20일" in say
    T.handle("할 일 추가 영어 단어 오늘까지", st, SAT)
    T.handle("할 일 추가 책 반납", st, SAT)
    assert [t.text for t in st.open_items()] == ["영어 단어", "경제 과제", "책 반납"]      # 마감 가까운 순, 마감 없음은 뒤
    assert "영어 단어" in T.handle("오늘 할 일", st, SAT)
    assert "3개" in T.handle("할 일 목록", st, SAT)
    # 같은 할 일을 다시 말하면 새로 만들지 않고 마감만 바꾼다
    T.handle("할 일 추가 책 반납 월요일까지", st, SAT)
    assert len(st.open_items()) == 3 and st.find("책 반납").due == "2026-11-16"
    assert T.handle("밥 먹었어", st, SAT) is None                   # 그런 할 일이 없으면 평범한 말
    assert "완료" in T.handle("경제 과제 다 했어", st, SAT)
    assert "지웠습니다" in T.handle("할 일 삭제 책 반납", st, SAT)
    assert [t.text for t in st.open_items()] == ["영어 단어"]
    assert "찾지 못했습니다" in T.handle("할 일 완료 수학", st, SAT)
    # 다시 읽어도 그대로
    again = T.TodoStore(st.path)
    assert [t.text for t in again.open_items()] == ["영어 단어"]
    assert any(t.done for t in again.items)


def test_find_is_not_ambiguous(st):
    st.add("수학 숙제", None)
    st.add("수학 시험 공부", None)
    assert st.find("수학") is None                                 # 둘 다 맞으면 고르지 않는다
    assert st.find("수학 숙제").text == "수학 숙제"


def test_dry_does_not_change_anything(st):
    st.add("경제 과제", SAT)
    assert T.handle("경제 과제 다 했어", st, SAT, dry=True) == ""
    assert st.open_items()[0].done == ""


def test_old_done_items_are_pruned(st):
    t = st.add("옛날 일", None)
    t.done = (dt.date.today() - dt.timedelta(days=T.KEEP_DONE_DAYS + 1)).isoformat()
    st.save()
    assert st.items == []


def test_corrupt_file_is_ignored(tmp_path):
    p = tmp_path / "todos.json"
    p.write_text("{broken", encoding="utf-8")
    assert T.TodoStore(p).items == []


# ---------------------------------------------------------------------------- 먼저 말 걸기
def pro(st, tmp_path, **cfg):
    return P.Proactive(Cfg(**cfg), lambda: st, tmp_path / "proactive.json")


def at(h, m=0, day=SAT):
    return dt.datetime.combine(day, dt.time(h, m))


def test_quiet_hours():
    assert P.in_quiet(23, "23-7") and P.in_quiet(3, "23-7") and not P.in_quiet(7, "23-7")
    assert P.in_quiet(13, "12-14") and not P.in_quiet(14, "12-14")
    assert not P.in_quiet(3, "") and not P.in_quiet(3, "abc") and not P.in_quiet(3, "5-5")


def test_battery_warns_once_then_rearms(st, tmp_path):
    p = pro(st, tmp_path)
    assert p.check(at(14), (50, False)) == []
    ev = p.check(at(14), (19, False))
    assert [e.kind for e in ev] == ["battery"] and ev[0].speak
    assert p.check(at(14, 1), (18, False)) == []                 # 한 번만
    ev = p.check(at(14, 2), (9, False))
    assert [e.kind for e in ev] == ["battery"] and "곧 꺼질" in ev[0].text
    assert p.check(at(14, 3), (8, False)) == []
    assert p.check(at(14, 4), (9, True)) == []                    # 충전기 연결 → 다시 준비
    assert len(p.check(at(14, 5), (19, False))) == 1


def test_battery_in_quiet_hours_is_silent_unless_critical(st, tmp_path):
    p = pro(st, tmp_path)
    ev = p.check(at(1), (19, False))
    assert len(ev) == 1 and not ev[0].speak
    ev = p.check(at(1, 1), (9, False))
    assert len(ev) == 1 and ev[0].speak


def test_todo_reminders_today_and_tomorrow(st, tmp_path):
    st.add("경제 과제", SAT)
    st.add("영어 단어", SAT + dt.timedelta(days=1))
    p = pro(st, tmp_path)
    assert p.check(at(8, 59)) == []                               # 9시 전에는 말하지 않는다
    ev = p.check(at(9, 0))
    assert [e.kind for e in ev] == ["todo_today"] and "경제 과제" in ev[0].text
    assert p.check(at(10)) == []                                   # 하루 한 번
    ev = p.check(at(19, 5))
    assert [e.kind for e in ev] == ["todo_tomorrow"] and "영어 단어" in ev[0].text
    # 다시 켜도 같은 알림을 되풀이하지 않는다
    assert pro(st, tmp_path).check(at(20)) == []
    # 다음 날에는 다시
    nxt = SAT + dt.timedelta(days=1)
    ev = pro(st, tmp_path).check(at(9, 30, nxt))
    assert [e.kind for e in ev] == ["todo_today"] and "영어 단어" in ev[0].text and "경제 과제" in ev[0].text


def test_reminders_wait_while_away_and_in_quiet_hours(st, tmp_path):
    st.add("경제 과제", SAT)
    p = pro(st, tmp_path)
    assert p.check(at(9, 30), idle_seconds=P.AWAY_SECONDS + 1) == []     # 자리 비움 → 미룬다 (기록하지 않음)
    assert len(p.check(at(9, 45), idle_seconds=3)) == 1                # 돌아오면 알린다
    st.add("밤 할 일", SAT + dt.timedelta(days=1))
    q = pro(st, tmp_path, quiet_hours="18-23")
    assert q.check(at(19, 30)) == []                                    # 조용한 시간


def test_switches(st, tmp_path):
    st.add("경제 과제", SAT)
    assert pro(st, tmp_path, proactive=False).check(at(10), (5, False)) == []
    assert pro(st, tmp_path, todo_reminders=False).check(at(10)) == []
    assert not pro(st, tmp_path, daily_briefing=False).briefing_due(at(8))


def test_briefing_due_once_a_morning(st, tmp_path):
    st.add("경제 과제", SAT)
    p = pro(st, tmp_path)
    assert not p.briefing_due(at(4))                  # 새벽
    assert not p.briefing_due(at(13))                 # 오후
    assert not p.briefing_due(at(8), idle_seconds=P.BRIEF_ACTIVE_SECONDS + 5)    # 켜 둔 채 자리 비움
    assert p.briefing_due(at(8), idle_seconds=10)
    p.mark_briefed(at(8))
    assert not p.briefing_due(at(9))
    assert p.check(at(9, 10)) == []                   # 브리핑에서 오늘 할 일을 말했으니 9시 알림은 건너뛴다
    assert not pro(st, tmp_path).briefing_due(at(10))   # 다시 켜도
    assert pro(st, tmp_path).briefing_due(at(8, day=SAT + dt.timedelta(days=1)))


def test_briefing_text(st, tmp_path):
    st.add("경제 과제", SAT)
    st.add("밀린 일", SAT - dt.timedelta(days=2))
    st.add("영어 발표", SAT + dt.timedelta(days=3))
    text = P.briefing_text(at(8), "주인님", "지금 맑음, 기온은 5도입니다.", st)
    assert "주인님" in text and "11월 14일 토요일" in text and "맑음" in text
    assert "경제 과제" in text and "밀린 일" in text and "영어 발표" in text
    empty = T.TodoStore(tmp_path / "empty.json")
    text = P.briefing_text(at(8), "주인님", None, empty, greet=False)
    assert text.startswith("오늘은") and "가까운 마감은 없습니다" in text


# ---------------------------------------------------------------------------- 두뇌 연결 (토큰 0 으로 바로 처리)
def test_brain_routes_todos_and_briefing_locally(tmp_path, monkeypatch):
    import threading

    import jarvis.brain as bm
    store = T.TodoStore(tmp_path / "todos.json")
    monkeypatch.setattr(T, "_store", store)

    class Tools:
        def _find_app(self, name, min_score=38):
            return None

        def _match_windows(self, name):
            return []

        def schemas(self):
            return []

        def t_get_weather(self, location=None):
            return "Seoul: Sunny, 기온 5°C (체감 3°C), 습도 40%, 바람 5km/h. 오늘 최고 9°C / 최저 1°C, 강수확률 최대 0%"

    b = bm.Brain(Cfg(brain="local"), Tools(), on_action=lambda *a: None, context_fn=lambda: "")
    stop = threading.Event()
    assert "경제 과제" in b.handle("할 일 추가 경제 과제 금요일까지", stop)
    assert b.recognizes("오늘 할 일 뭐 있어") and b.recognizes("브리핑 해 줘")
    assert not b.recognizes("밥 먹었어")
    assert b.recognizes("경제 과제 다 했어")
    reply = b.handle("오늘 브리핑 해 줘", stop)
    assert "오늘은" in reply and "기온은 5도" in reply and "경제 과제" in reply
    assert "(할 일) 경제 과제" in b._build_system()
    assert "완료" in b.handle("경제 과제 다 했어", stop)
    assert store.open_items() == []


# ---------------------------------------------------------------------------- 검토에서 나온 경우들
@pytest.mark.parametrize("text,scope", [
    ("할 일 목록 보여줘", "all"), ("할 일 목록 보여 줘", "all"), ("할 일 목록을 알려 줘", "all"),
    ("다음 주 할 일 뭐 있어", "next_week"), ("담주 할 일", "next_week"),
])
def test_more_list_phrasings(text, scope):
    assert T.parse_command(text, SAT) == ("list", {"scope": scope})


def test_this_week_weekday_already_past_rolls_forward():
    assert T.parse_due("이번 주 금요일까지 과제", SAT)[0] == dt.date(2026, 11, 20)
    assert T.parse_due("이번 주 일요일까지 과제", SAT)[0] == dt.date(2026, 11, 15)


def test_impossible_date_is_refused(st):
    with pytest.raises(T.BadDate):
        T.parse_due("2월 30일 시험", SAT)
    say = T.handle("2월 30일 시험 할 일에 추가해 줘", st, SAT)
    assert "없는 날짜" in say and st.open_items() == []


def test_short_names_need_exact_match(st):
    st.add("과제", None)
    assert T.handle("과제 얘기 끝냈어", st, SAT) is None          # 두 글자 이름은 부분 일치로 완료하지 않는다
    assert "완료" in T.handle("과제 다 했어", st, SAT)


def test_next_week_list(st):
    st.add("발표", dt.date(2026, 11, 18))
    st.add("먼 일", dt.date(2026, 12, 1))
    say = T.speak_list(st, "next_week", SAT)
    assert "발표" in say and "먼 일" not in say
