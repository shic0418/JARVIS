"""여러 에이전트가 나눠 일하기 (writers.py · brain.py 의 작가/조사 담당 · tools.py 의 make_presentation/make_document)."""
import json
import threading
import time

import pytest

import jarvis.brain as bm
from jarvis import claude_session as cs
from jarvis import office
from jarvis import tools as T
from jarvis import writers as W
from jarvis.config import DEFAULTS

pytest.importorskip("pptx")
pytest.importorskip("docx")

OUTLINE = [
    {"layout": "section", "title": "광합성이란?"},
    {"layout": "bullets", "title": "재료와 결과"},
    {"layout": "process", "title": "과정", "points": ["명반응", "암반응"]},
    {"layout": "chart", "title": "빛과 광합성량", "chart": {"type": "line", "categories": ["약", "강"],
                                                         "series": [{"name": "양", "values": [1, 2]}]}},
    {"layout": "timeline", "title": "연구의 역사"},
    {"layout": "bullets", "title": "이미 쓴 장", "bullets": ["기획자가 직접 쓴 줄"]},
    {"layout": "closing", "title": "감사합니다"},
]
BODY = {"bullets": {"bullets": ["핵심어: 설명", "둘째 줄"]}, "process": {"steps": [{"title": "하나", "text": "설명"}, {"title": "둘", "text": ""}]},
        "chart": {"bullets": ["차트에서 읽을 점"], "chart": {"type": "pie", "categories": ["작가가"], "series": [{"name": "바꾼", "values": [9]}]}},
        "timeline": {"events": [{"when": "1771", "title": "프리스틀리", "text": ""}, {"when": "1779", "title": "잉엔하우스", "text": ""}]}}


def request_of(prompt: str) -> dict:
    return json.loads(prompt.split("# 요청\n", 1)[1])


def good_writer(system, prompts, timeout):
    """맡은 번호를 모두, 형식에 맞게 쓰는 작가들."""
    out = []
    for i, prompt in enumerate(prompts):
        req = request_of(prompt)
        by = {o["index"]: o for o in req["outline"]}
        if req["kind"] == "slides":
            rows = [{"index": n, "layout": by[n]["layout"], "title": by[n]["title"], "notes": f"{n}번 대본",
                     **BODY[by[n]["layout"]]} for n in req["write"]]
            out.append(json.dumps({"slides": rows, "sources": [f"자료 {i} — https://a.kr/{i}", "같은 자료 — https://a.kr/0"]},
                                  ensure_ascii=False))
        else:
            rows = [{"index": n, "heading": by[n]["heading"], "paragraphs": [f"{n}번 문단"]} for n in req["write"]]
            out.append(json.dumps({"sections": rows}, ensure_ascii=False))
    return out


# ---------------------------------------------------------------- 나누기 · 읽기
def test_share_balances_the_load_and_leaves_nobody_idle():
    weights = [1, 1.3, 0.7, 1.4, 1.2, 1.2, 0.8, 1.2, 0.6]
    groups = W.share(weights, 4)
    assert sorted(i for g in groups for i in g) == list(range(9)) and len(groups) == 4
    loads = [sum(weights[i] for i in g) for g in groups]
    assert max(loads) - min(loads) <= 0.7 and all(g == sorted(g) for g in groups)       # 가장 바쁜 사람과 한가한 사람의 차이가 작다
    assert W.share([1, 1], 4) == [[0], [1]] and W.share([], 3) == [] and W.share([1, 2, 3], 1) == [[0, 1, 2]]


def test_parse_reads_json_even_with_fences_and_chatter():
    assert W.parse('{"slides": []}') == {"slides": []}
    assert W.parse('```json\n{"a": 1}\n```') == {"a": 1}
    assert W.parse('여기 있습니다:\n{"a": [1, 2]}\n이상입니다.') == {"a": [1, 2]}
    assert W.parse('[{"index": 1}]') == [{"index": 1}]
    assert W.parse("JSON 이 아님") is None and W.parse("") is None and W.parse(None) is None


def test_only_slides_without_text_go_to_the_writers():
    assert W.pending("slides", OUTLINE) == 4                       # 장 구분 · 마무리 · 이미 쓴 장은 빼고
    assert W.pending("slides", ["글자만"]) == 0 and W.pending("slides", None) == 0
    assert W.pending("slides", [{"layout": "bullets", "title": ""}, {"title": "대본만 있는 장", "notes": "말"}]) == 0
    assert W.pending("document", [{"heading": "서론"}, {"heading": "본론", "paragraphs": ["글"]}, {"points": ["제목 없음"]}]) == 1


# ---------------------------------------------------------------- 작가들
def test_writers_share_the_outline_and_their_work_is_merged():
    seen = []

    def ask(system, prompts, timeout):
        seen.append((system, prompts, timeout))
        return good_writer(system, prompts, timeout)

    slides, info = W.expand_slides({"title": "광합성", "audience": "중학생", "facts": [], "research": ["검색 결과 글"]}, OUTLINE, ask, 3, 60)
    system, prompts, timeout = seen[0]
    assert len(seen) == 1 and system == W.SYSTEM and timeout == 60 and len(prompts) == 3
    asked = sorted(n for p in prompts for n in request_of(p)["write"])
    assert asked == [2, 3, 4, 5]                                                       # 써야 할 장을 빠짐없이, 한 번씩만
    for p in prompts:
        req = request_of(p)
        assert p.startswith(W.GUIDE["slides"]) and "보고서의 장" not in p               # 그 종류의 형식 안내만 본다
        assert req["kind"] == "slides" and [o["index"] for o in req["outline"]] == list(range(1, 8))   # 모두가 전체 개요를 본다
        assert req["brief"] == {"title": "광합성", "audience": "중학생", "research": ["검색 결과 글"]}   # 빈 칸은 보내지 않는다
        assert req["outline"][2]["points"] == ["명반응", "암반응"]
    assert info["writers"] == 3 and info["asked"] == 4 and info["written"] == 4 and info["missing"] == [] and info["retried"] == 0
    assert slides[1]["bullets"] == ["핵심어: 설명", "둘째 줄"] and slides[1]["notes"] == "2번 대본"
    assert slides[2]["steps"][0]["title"] == "하나" and slides[2]["points"] == ["명반응", "암반응"]
    assert slides[3]["chart"]["type"] == "line" and slides[3]["bullets"] == ["차트에서 읽을 점"]   # 기획자가 준 차트 숫자는 그대로
    assert slides[4]["events"][1]["title"] == "잉엔하우스"
    assert slides[0] == OUTLINE[0] and slides[5] == OUTLINE[5] and slides[6] == OUTLINE[6]         # 맡기지 않은 장은 그대로
    assert OUTLINE[1] == {"layout": "bullets", "title": "재료와 결과"}                              # 받은 개요는 고치지 않는다
    assert info["sources"] == ["자료 0 — https://a.kr/0", "자료 1 — https://a.kr/1", "자료 2 — https://a.kr/2"]


def test_a_failed_writer_is_asked_again_once_and_only_for_what_is_missing():
    calls = []

    def flaky(system, prompts, timeout):
        calls.append([request_of(p)["write"] for p in prompts])
        answers = good_writer(system, prompts, timeout)
        if len(calls) == 1:
            answers[0] = None                                   # 첫 작가는 대답이 없고
            answers[1] = '{"sections": [{"index": 3, "paragraphs": ["엉뚱한 형식"]}]}'   # 둘째는 형식이 틀렸다
        return answers

    slides, info = W.expand_slides({}, OUTLINE, flaky, 3)
    assert len(calls) == 2 and sorted(n for g in calls[1] for n in g) == sorted(calls[0][0] + calls[0][1])
    assert len(calls[1]) <= 2 and info["written"] == 4 and info["missing"] == [] and info["retried"] == len(calls[0][0] + calls[0][1])

    def dead(system, prompts, timeout):
        calls.append("dead")
        return [None] * len(prompts)

    calls.clear()
    slides, info = W.expand_slides({}, OUTLINE, dead, 3)
    assert calls == ["dead"] and info["written"] == 0 and info["missing"] == [2, 3, 4, 5]   # 모두 실패면 다시 맡기지 않는다
    assert slides == OUTLINE

    def broken(system, prompts, timeout):
        raise OSError("Claude 를 켤 수 없음")

    slides, info = W.expand_slides({}, OUTLINE, broken, 3)
    assert slides == OUTLINE and info["written"] == 0
    assert W.expand_slides({}, OUTLINE, None, 3)[1]["writers"] == 0 and W.expand_slides({}, OUTLINE, good_writer, 0)[0] == OUTLINE


def test_writer_answers_are_matched_by_position_when_numbers_are_missing():
    def unnumbered(system, prompts, timeout):
        out = []
        for p in prompts:
            req = request_of(p)
            by = {o["index"]: o for o in req["outline"]}
            out.append(json.dumps([{"title": "다듬은 " + by[n]["title"], **BODY[by[n]["layout"]]} for n in req["write"]], ensure_ascii=False))
        return out

    slides, info = W.expand_slides({}, OUTLINE, unnumbered, 2)
    assert info["written"] == 4 and slides[1]["title"] == "다듬은 재료와 결과" and slides[4]["title"] == "다듬은 연구의 역사"


def test_report_sections_are_written_the_same_way():
    sections = [{"heading": "서론", "points": ["배경"]}, {"heading": "본론", "level": 2}, {"heading": "직접 쓴 장", "paragraphs": ["글"]}]
    seen = []

    def ask(system, prompts, timeout):
        seen.extend(prompts)
        return good_writer(system, prompts, timeout)

    out, info = W.expand_sections({"title": "보고서"}, sections, ask, 4)
    assert info["written"] == 2 and out[0]["paragraphs"] == ["1번 문단"] and out[1]["paragraphs"] == ["2번 문단"] and out[2] == sections[2]
    assert all(p.startswith(W.GUIDE["document"]) and "발표 자료의 장" not in p for p in seen) and len(seen) == 2


def test_sources_are_merged_without_repeats_and_research_links_are_listed():
    assert W.merge_sources(["가 — https://a.kr/1", "나"], None, ["다른 제목 — https://A.kr/1", "나", "다 — https://b.kr"], "라") == \
        ["가 — https://a.kr/1", "나", "다 — https://b.kr", "라"]
    raw = ('Web search results for query: "광합성"\n\nLinks: [{"title":"위키백과","url":"https://ko.wikipedia.org/wiki/광합성"},'
           '{"title":"생태원","url":"https://nie.re.kr"},{"title":"셋","url":"https://c.kr"}]\n\n광합성은 빛에너지를 쓴다.\n\n'
           "REMINDER: You MUST include the sources above in your response to the user using markdown hyperlinks.")
    clean = W.clean_result(raw)
    assert "REMINDER" not in clean and "Links:" not in clean and "- 위키백과 — https://ko.wikipedia.org/wiki/광합성" in clean
    assert "광합성은 빛에너지를 쓴다." in clean and len(W.clean_result("가" * 9000)) == 2600
    assert W.research_sources([clean, clean]) == ["위키백과 — https://ko.wikipedia.org/wiki/광합성", "생태원 — https://nie.re.kr"]
    assert W.research_sources([]) == [] and W.clean_result("링크 없는 글") == "링크 없는 글"


# ---------------------------------------------------------------- Claude Code 프로세스들
class FakeSession:
    """작가 · 조사 담당용 가짜 Claude Code."""
    made: list = []

    def __init__(self, args_fn=None, env_fn=None, cwd=""):
        self.args_fn, self.env_fn = args_fn, env_fn
        self.warmed = self.closed = 0
        self.asked: list = []
        self.reply = ("답", False, "")
        self.delay = 0.0
        self.events: list = []
        FakeSession.made.append(self)

    def warm(self):
        self.warmed += 1

    def ask(self, prompt, cancel, on_text=None, on_event=None, timeout=240, early=False):
        self.asked.append((prompt, timeout, early))
        for wait, ev in self.events:
            time.sleep(wait)
            on_event(ev)
        time.sleep(self.delay)
        if isinstance(self.reply, Exception):
            raise self.reply
        return self.reply

    def close(self, forget=False):
        self.closed += 1


def test_pool_asks_everyone_at_once_and_does_not_wait_for_the_turn_to_wrap_up():
    FakeSession.made = []
    pool = W.Pool(FakeSession, 3)
    pool.warm()
    time.sleep(0.05)
    assert [s.warmed for s in pool.sessions] == [1, 1, 1]
    for s, reply in zip(pool.sessions, (("첫째", False, ""), ("오류 글", True, "로그인 필요"), OSError("죽음"))):
        s.reply, s.delay = reply, 0.3
    started = time.monotonic()
    out = pool.ask_all(["가", "나", "다", "라"], threading.Event(), 5)
    assert time.monotonic() - started < 0.9                                     # 한 명씩이면 1.2초 — 동시에 묻는다
    assert out == ["첫째", None, None, "답"] and len(pool.sessions) == 4          # 실패한 자리는 None, 모자라면 더 켠다
    assert all(s.asked[0][2] is True for s in pool.sessions)                   # 답의 마지막 글자에서 바로 돌아온다
    sessions = list(pool.sessions)
    pool.close()
    time.sleep(0.05)
    assert [s.closed for s in sessions] == [1, 1, 1, 1] and pool.sessions == []


def search(query):
    return {"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "WebSearch", "input": {"query": query}}]}}


def result(text, error=False):
    return {"type": "user", "message": {"content": [{"type": "tool_result", "content": [{"type": "text", "text": text}], "is_error": error}]}}


def test_research_collects_search_results_as_they_arrive():
    sess = FakeSession()
    sess.events = [(0, search("개념")), (0, search("통계")), (0, search("역사")), (0.05, result("개념 결과 REMINDER: 지시")),
                   (0.05, result("검색 실패", error=True)), (0.05, result("역사 결과")), (0, {"type": "user", "message": {"content": "글자뿐"}})]
    sess.delay = 5                                               # 검색이 끝난 뒤 모델이 마무리하는 시간은 기다리지 않는다
    r = W.Research(sess, threading.Event())
    seen = []
    r.on_query = seen.append
    started = time.monotonic()
    r.start("광합성 자료조사해서 PPT 만들어 줘")
    assert r.wait(3) == ["개념 결과", "역사 결과"] and time.monotonic() - started < 1.5
    assert seen == ["개념", "통계", "역사"] and sess.asked[0][0] == "광합성 자료조사해서 PPT 만들어 줘"
    r.close()
    time.sleep(0.05)
    assert sess.closed == 1


def test_research_does_not_wait_long_for_one_slow_search():
    sess = FakeSession()
    sess.events = [(0, search("가")), (0, search("나")), (0, search("다")), (0.05, result("가 결과")), (0.05, result("나 결과")),
                   (3, result("다 결과"))]
    r = W.Research(sess, threading.Event())
    r.start("요청")
    started = time.monotonic()
    assert r.wait(10, enough=2, grace=0.3) == ["가 결과", "나 결과"] and time.monotonic() - started < 1.5   # 둘이 모이면 조금만 더
    quiet = W.Research(FakeSession(), threading.Event())
    quiet.session.delay = 3
    quiet.start("요청")
    started = time.monotonic()
    assert quiet.wait(0.3) == [] and time.monotonic() - started < 1.0          # 시간 제한까지만 기다린다


# ---------------------------------------------------------------- ClaudeSession: 답이 끝나면 바로 돌아오기
class FakeProc:
    def __init__(self, events):
        self.lines = [(json.dumps(e, ensure_ascii=False) + "\n").encode("utf-8") for e in events]
        self.read = 0
        self.killed = False
        self.stdin = self
        self.stderr = []

    @property
    def stdout(self):
        for line in self.lines[self.read:]:
            self.read += 1
            yield line

    def write(self, data):
        pass

    def flush(self):
        pass

    def close(self):
        pass

    def poll(self):
        return 1 if self.killed else None

    def kill(self):
        self.killed = True

    def wait(self, timeout=None):
        return 0


def stream(kind, **extra):
    return {"type": "stream_event", "event": {"type": kind, **extra}}


TURN = [
    stream("message_start"),
    {"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "WebSearch", "input": {"query": "가"}}]}},
    stream("message_delta", delta={"stop_reason": "tool_use"}), stream("message_stop"),
    result("검색 결과"),
    stream("message_start"),
    {"type": "assistant", "message": {"content": [{"type": "text", "text": '{"slides": []}'}]}},
    stream("message_delta", delta={"stop_reason": "end_turn"}), stream("message_stop"),
    {"type": "system", "subtype": "hook"},
    {"type": "result", "subtype": "success", "result": '{"slides": []}'},
]


def test_session_can_return_at_the_last_letter_instead_of_waiting_for_the_wrap_up():
    sess = cs.ClaudeSession(lambda sid: [], dict, ".")
    sess.proc = FakeProc(TURN)
    events = []
    assert sess.ask("요청", threading.Event(), on_event=events.append, early=True) == ('{"slides": []}', False, "")
    assert sess.proc.read == 9                                    # 도구를 부르는 메시지에서는 멈추지 않고, 마지막 메시지에서 멈춘다
    assert [e["type"] for e in events] == ["assistant", "user", "assistant"]      # 도구 결과(검색 결과 글)도 받아 볼 수 있다
    sess.proc = FakeProc(TURN)
    assert sess.ask("요청", threading.Event()) == ('{"slides": []}', False, "") and sess.proc.read == len(TURN)   # 평소에는 끝까지


# ---------------------------------------------------------------- 두뇌 (brain.py)
class Cfg(dict):
    def __getitem__(self, k):
        return self.get(k, DEFAULTS.get(k))

    def api_key(self):
        return self.get("anthropic_api_key", "")


class Tools:
    def schemas(self):
        return T.PCTools.schemas(T.PCTools.__new__(T.PCTools))

    def set_vision_model(self, model):
        pass

    def label(self, name, args):
        return T.PCTools.label(name, args)

    def run(self, name, args):
        return "ok"

    def _find_app(self, name, min_score=38):
        return None

    def _match_windows(self, name):
        return []


def brain(claude=True, **cfg):
    b = bm.Brain(Cfg(cfg), Tools(), on_action=lambda *a: None, context_fn=lambda: "")
    b.claude_exe = lambda: "claude" if claude else None
    b.shown = []
    b.on_action = lambda *a: b.shown.append(a)
    return b


@pytest.fixture
def fake_sessions(monkeypatch, tmp_path):
    FakeSession.made = []
    monkeypatch.setattr(bm, "ClaudeSession", FakeSession)
    monkeypatch.setattr(bm, "DATA_DIR", tmp_path)
    return FakeSession.made


def test_default_is_four_writers_and_the_count_is_clamped():
    assert DEFAULTS["writers"] == 4 and DEFAULTS["writer_model"] == ""
    assert brain()._writer_count() == 4 and brain(writers=0)._writer_count() == 0 and brain(writers=99)._writer_count() == 6
    assert brain(writers="둘")._writer_count() == 0 and brain(writers=-3)._writer_count() == 0


def test_instructions_make_claude_a_planner_only_when_a_team_can_work():
    team = brain()._build_system()
    assert "당신은 기획자입니다" in team and "layout 과 title 만" in team and "직접 검색하지 마세요" in team
    assert "조사 담당이 이미 웹 검색을" in team and "본문 · 대본을 직접 쓰지 마세요" in team
    solo = brain(writers=0)._build_system()
    assert "기획자" not in solo and "직접\n  채우세요" in solo and "반드시 web_search 를 2~3개 한꺼번에 하세요" in solo
    assert brain(claude=False)._build_system() == solo                      # Claude Code 가 없으면 팀을 꾸릴 수 없다
    api = brain(brain="api", anthropic_api_key="k")._build_system()
    assert "당신은 기획자입니다" in api and "facts 에" in api and "작가들은 검색 결과를 볼 수 없습니다" in api
    assert "반드시 web_search 를 2~3개 한꺼번에 하세요" in api and "직접 검색하지 마세요" not in api
    for text in (team, solo, api):                                          # 어느 방식이든 지켜야 하는 것
        assert "빠른 것이 가장 중요" in text and "시작한다는 말은 하지 마세요" in text and "make_cardnews" in text
        assert "process" in text and "timeline" in text and "말이 없으면 주제에 어울리는 디자인이" in text
        assert "{search_rule}" not in text and "{plan_rule}" not in text


def test_writers_and_the_researcher_start_the_moment_a_deck_is_requested(fake_sessions):
    b = brain(pro_model="haiku", writer_model="sonnet")
    for text in ("엑셀로 시간표 만들어 줘", "PPT 열어 줘", "오늘 날씨 어때"):                # 표 · 앱 열기 · 평소 질문에는 켜지 않는다
        b.warm_writers(text)
    assert fake_sessions == []
    b.warm_writers("광합성 발표 자료 만들어 줘")
    time.sleep(0.05)
    writers_, researcher = fake_sessions[:4], fake_sessions[4]
    assert len(fake_sessions) == 5 and all(s.warmed == 1 for s in writers_)
    args = writers_[0].args_fn(None)
    assert args[args.index("--system-prompt") + 1] == W.SYSTEM and args[args.index("--tools") + 1] == ""   # 작가는 도구가 없다
    assert args[args.index("--model") + 1] == "sonnet" and "--include-partial-messages" in args and "--allowedTools" not in args
    args = researcher.args_fn(None)
    assert args[args.index("--system-prompt") + 1] == W.RESEARCH_SYSTEM and args[args.index("--tools") + 1] == "WebSearch"
    assert args[args.index("--model") + 1] == "haiku" and args[args.index("--allowedTools") + 1] == "WebSearch"
    assert researcher.asked[0][0] == "광합성 발표 자료 만들어 줘"                     # 조사는 요청을 듣자마자 시작한다
    assert not any(k.upper().startswith(("CLAUDE", "ANTHROPIC")) for k in writers_[0].env_fn())
    b.warm_writers("광합성 발표 자료 만들어 줘")
    assert len(fake_sessions) == 5                                                  # 두 번 켜지 않는다
    b._drop_writers()
    time.sleep(0.05)
    assert all(s.closed == 1 for s in fake_sessions) and b._writer_pool is None and b._research is None
    b._drop_writers()                                                               # 다시 불러도 괜찮다


@pytest.mark.parametrize("cfg, sessions", [({"brain": "api", "anthropic_api_key": "k"}, 0), ({"writers": 0}, 0),
                                            ({"web_search": False}, 4), ({"writers": 2}, 3)])
def test_team_is_only_started_where_it_can_work(fake_sessions, cfg, sessions):
    b = brain(**cfg)
    b.warm_writers("기후 변화 보고서 써 줘")
    time.sleep(0.05)
    assert len(fake_sessions) == sessions                       # API 방식 · 작가 0명이면 없음, 웹 검색을 끄면 조사 담당만 없음


def test_team_writes_with_the_research_and_the_helpers_are_closed(fake_sessions):
    b = brain(writers=3)
    b.warm_writers("광합성 자료조사해서 PPT 만들어 줘")
    time.sleep(0.05)
    pool, researcher = fake_sessions[:3], fake_sessions[3]
    b._research.results = ["출처 후보:\n- 위키백과 — https://ko.wikipedia.org/wiki/광합성\n광합성은 빛에너지를 쓴다."]
    b._research.done.set()
    prompts = []

    def answer(prompt, cancel, on_text=None, on_event=None, timeout=240, early=False):
        prompts.append(prompt)
        return good_writer("", [prompt], timeout)[0], False, ""

    for s in pool:
        s.ask = answer
    slides, info = b.write_team("slides", {"title": "광합성", "audience": "중학생"}, OUTLINE)
    assert info["written"] == 4 and info["writers"] == 3 and info["researched"] == 1 and len(prompts) == 3
    assert all(request_of(p)["brief"]["research"] == b_research for p in prompts for b_research in [["출처 후보:\n- 위키백과 — "
               "https://ko.wikipedia.org/wiki/광합성\n광합성은 빛에너지를 쓴다."]])
    assert info["sources"][-1] == "위키백과 — https://ko.wikipedia.org/wiki/광합성" and slides[1]["notes"] == "2번 대본"
    assert [(a[1], a[2]) for a in b.shown] == [("작가 3명이 나눠 쓰기 · 4장", "run"), ("작가 3명이 나눠 쓰기 · 4장", "ok")]
    time.sleep(0.05)
    assert all(s.closed == 1 for s in pool) and len(fake_sessions) == 4          # 미리 켜 둔 작가를 쓰고 끈다 (새로 켜지 않음)
    assert researcher.closed == 0
    b._drop_writers()
    time.sleep(0.05)
    assert researcher.closed == 1


def test_team_is_skipped_when_nothing_needs_writing_or_no_claude(fake_sessions):
    b = brain()
    done = [{"title": "다 쓴 장", "bullets": ["줄"]}]
    assert b.write_team("slides", {}, done) == (done, {"writers": 0, "asked": 0, "written": 0, "seconds": 0.0, "sources": []})
    assert fake_sessions == [] and b.shown == []
    assert brain(claude=False).write_team("slides", {}, OUTLINE)[1]["writers"] == 0
    assert brain(brain="local").write_team("slides", {}, OUTLINE)[0] == OUTLINE
    cold = brain(writers=2)                                    # 미리 켜 두지 않았으면 그때 켠다
    slides, info = cold.write_team("slides", {}, OUTLINE)
    assert len(fake_sessions) == 2 and info["written"] == 0 and info["missing"] == [2, 3, 4, 5] and cold.shown[-1][2] == "error"


def test_api_mode_writers_are_parallel_api_calls():
    b = brain(brain="api", anthropic_api_key="k", model="claude-opus-5-5", writers=3)
    sent = []

    class Client:
        class beta:
            class messages:
                @staticmethod
                def create(**kw):
                    sent.append(kw)
                    time.sleep(0.2)
                    text = good_writer("", [kw["messages"][0]["content"]], 0)[0]
                    return type("R", (), {"content": [type("B", (), {"type": "thinking", "text": "생각"})(),
                                                      type("B", (), {"type": "text", "text": text})()]})()

    b._client_for = lambda key: Client
    started = time.monotonic()
    slides, info = b.write_team("slides", {"title": "광합성", "facts": ["기획자가 조사한 사실"]}, OUTLINE)
    assert time.monotonic() - started < 0.55 and info["written"] == 4 and len(sent) == 3          # 동시에 부른다
    assert all(kw["model"] == "claude-opus-5-5" and kw["system"] == W.SYSTEM and kw["output_config"] == {"effort": "low"} for kw in sent)
    assert request_of(sent[0]["messages"][0]["content"])["brief"]["facts"] == ["기획자가 조사한 사실"]
    b.cfg["writer_model"] = "claude-haiku-5-5"
    sent.clear()
    b.write_team("slides", {}, OUTLINE)
    assert {kw["model"] for kw in sent} == {"claude-haiku-5-5"}


def test_the_planner_is_told_about_the_team_right_next_to_the_request(fake_sessions):
    b = brain()
    assert "[팀 작업]" not in b._prefix()
    b.warm_writers("광합성 자료조사해서 PPT 만들어 줘")
    note = b._prefix()
    assert "[팀 작업]" in note and "조사 담당이 이 요청의 웹 검색을 이미 하고 있습니다" in note and "web_search · web_fetch 를 쓰지 말고" in note
    b._drop_writers()
    assert "[팀 작업]" not in b._prefix()
    quiet = brain(web_search=False)
    quiet.warm_writers("광합성 PPT 만들어 줘")
    assert "작가들이 대기 중입니다" in quiet._prefix() and "조사 담당" not in quiet._prefix()
    quiet._drop_writers()


def test_asking_how_to_make_something_is_not_a_request_to_make_it(fake_sessions):
    b = brain()
    heard = []
    b._handle_ai = lambda text, cancel, on_text=None: "설명"
    b.local.try_handle = lambda text, fallback=True: None
    for text in ("PPT 만드는 법 알려 줘", "보고서 어떻게 써야 해", "발표 자료 만드는 방법 정리해서 말해 줘"):
        heard.clear()
        b.handle(text, threading.Event(), on_text=heard.append)
        assert heard == [] and fake_sessions == [], text            # 바로 대답도, 작가도 없다
    b.handle("광합성 발표 자료 만들어 줘", threading.Event(), on_text=heard.append)
    assert heard[0].strip() in bm.WORK_ACKS and len(fake_sessions) == 5


def test_handling_a_deck_request_warms_the_team_first_and_always_cleans_up():
    b = brain()
    order = []
    b.warm_writers = lambda text: order.append(("warm", text))
    b._drop_writers = lambda: order.append("drop")
    b.local.try_handle = lambda text, fallback=True: None

    def ai(text, cancel, on_text=None):
        order.append("claude")
        return "만들었다."

    b._handle_ai = ai
    heard = []
    assert b.handle("광합성 PPT 만들어 줘", threading.Event(), on_text=heard.append) == "만들었다."
    assert order == [("warm", "광합성 PPT 만들어 줘"), "claude", "drop"] and heard[0].strip() in bm.WORK_ACKS

    def boom(text, cancel, on_text=None):
        raise RuntimeError("실패")

    b._handle_ai = boom
    order.clear()
    with pytest.raises(RuntimeError):
        b.handle("광합성 PPT 만들어 줘", threading.Event())
    assert order[-1] == "drop"                                  # 실패해도 켜 둔 작가는 끈다


# ---------------------------------------------------------------- 도구 (tools.py)
@pytest.fixture
def pc(tmp_path, monkeypatch):
    me = T.PCTools.__new__(T.PCTools)
    folders = {"문서": tmp_path / "docs", "바탕화면": tmp_path / "desk"}
    monkeypatch.setattr(T.winutil, "known_folder", lambda name: folders.get(name.replace(" ", "")))
    me.opened = []
    monkeypatch.setattr(T.os, "startfile", lambda p: me.opened.append(p), raising=False)
    return me


def team_of(calls, researched=2):
    def writer(kind, brief, items):
        calls.append((kind, brief))
        out, info = (W.expand_slides if kind == "slides" else W.expand_sections)(brief, items, good_writer, 3)
        info["researched"] = researched
        return out, info
    return writer


def test_presentation_outline_is_written_by_the_team_and_sources_are_merged(pc, tmp_path):
    import pptx
    calls = []
    pc.writer = team_of(calls)
    msg = pc.t_make_presentation(title="광합성", slides=OUTLINE, subtitle="2학년 3반", audience="중학생", facts=["사실"],
                                 sources=["기획자 자료 — https://a.kr/0"], style="bold")
    assert calls == [("slides", {"title": "광합성", "subtitle": "2학년 3반", "audience": "중학생", "facts": ["사실"]})]
    assert "작가 3명이 나눠 썼습니다" in msg and "조사 담당이 찾은 자료 2건" in msg and "발표 대본 4장" in msg and "출처 3건" in msg
    assert "'강렬' 스타일" in msg
    prs = pptx.Presentation(str(tmp_path / "docs" / "JARVIS" / "광합성.pptx"))
    everything = "\n".join(sh.text_frame.text for s in prs.slides for sh in s.shapes if sh.has_text_frame)
    for word in ("핵심어", "하나", "프리스틀리", "기획자가 직접 쓴 줄", "자료 1 — https://a.kr/1"):
        assert word in everything
    assert everything.count("https://a.kr/0") == 1                              # 같은 출처는 한 번만


def test_design_changes_from_one_deck_to_the_next_unless_asked(pc):
    full = [{"title": "장", "bullets": ["줄"]}]
    first = pc.t_make_presentation(title="같은 제목", slides=full, open=False)
    second = pc.t_make_presentation(title="같은 제목", slides=full, open=False)
    names = [next(n for n in office.STYLE_NAMES.values() if f"'{n}' 스타일" in m) for m in (first, second)]
    assert names[0] != names[1]                                                 # 바로 앞에 쓴 디자인은 피한다
    assert "'테크' 스타일" in pc.t_make_presentation(title="같은 제목", slides=full, style="tech", open=False)
    assert "'파스텔' 스타일" in pc.t_make_presentation(title="같은 제목", slides=full, style="귀엽게", open=False)
    kids = pc.t_make_presentation(title="봄 소풍", slides=full, audience="초등학교 2학년", open=False)
    assert any(f"'{office.STYLE_NAMES[s]}' 스타일" in kids for s in ("pastel", "bold", "clean"))


def test_team_trouble_never_stops_the_file_from_being_made(pc, tmp_path):
    def broken(kind, brief, items):
        raise RuntimeError("작가 실패")

    pc.writer = broken
    msg = pc.t_make_presentation(title="개요만", slides=OUTLINE, open=False)
    assert (tmp_path / "docs" / "JARVIS" / "개요만.pptx").exists() and "작가" not in msg

    def silent(kind, brief, items):
        return items, {"writers": 3, "asked": 4, "written": 0, "seconds": 75.0, "sources": []}

    pc.writer = silent                                          # 한 장도 못 썼으면 빈 파일을 만들지 않고, 직접 쓰라고 돌려보낸다
    with pytest.raises(T.ToolError, match="직접 채워서"):
        pc.t_make_presentation(title="개요만 2", slides=OUTLINE, open=False)
    assert not (tmp_path / "docs" / "JARVIS" / "개요만 2.pptx").exists()

    def partly(kind, brief, items):
        out, info = W.expand_slides(brief, items, good_writer, 3)
        out[1], out[2] = items[1], items[2]                     # 두 장은 끝내 못 썼다: 2번은 제목뿐, 3번은 개요(points)가 있다
        info.update(written=2, missing=[2, 3])
        return out, info

    pc.writer = partly
    import pptx
    msg = pc.t_make_presentation(title="일부만", slides=OUTLINE, open=False, agenda=False)
    assert "2장은 쓰지 못해 뺐습니다" in msg
    text = "\n".join(sh.text_frame.text for s in pptx.Presentation(str(tmp_path / "docs" / "JARVIS" / "일부만.pptx")).slides
                     for sh in s.shapes if sh.has_text_frame)
    assert "재료와 결과" not in text and "명반응" in text and "프리스틀리" in text    # 제목뿐인 장은 빼고, 개요가 있는 장은 넣는다
    del pc.writer                                               # 작가가 연결되지 않은 경우 (자가 점검 등)
    assert "발표 자료를 만들었습니다" in pc.t_make_presentation(title="개요만 3", slides=OUTLINE, open=False)


def test_report_outline_is_written_by_the_team(pc, tmp_path):
    import docx
    calls = []
    pc.writer = team_of(calls, researched=0)
    msg = pc.t_make_document(title="기후 변화 보고서", sections=[{"heading": "서론"}, {"heading": "본론", "points": ["원인"]}],
                             audience="고등학교 과제")
    assert calls[0][0] == "document" and calls[0][1]["audience"] == "고등학교 과제" and "작가 2명이 나눠 썼습니다" in msg
    assert "조사 담당" not in msg
    text = "\n".join(p.text for p in docx.Document(str(tmp_path / "docs" / "JARVIS" / "기후 변화 보고서.docx")).paragraphs)
    assert "1번 문단" in text and "2번 문단" in text
    pc.writer = None
    pc.t_make_document(title="개요뿐", sections=[{"heading": "서론", "points": ["배경", "목적"]}], open=False)
    text = "\n".join(p.text for p in docx.Document(str(tmp_path / "docs" / "JARVIS" / "개요뿐.docx")).paragraphs)
    assert "배경" in text and "목적" in text                                     # 작가가 없으면 개요를 목록으로 넣는다


def test_tools_describe_styles_and_outlines_for_claude():
    schemas = {d["name"]: d for d in T.PCTools.schemas(T.PCTools.__new__(T.PCTools))}
    deck = schemas["make_presentation"]["input_schema"]["properties"]
    assert set(deck["style"]["enum"]) == set(office.STYLES) and set(deck["theme"]["enum"]) == set(office.THEMES)
    slide = deck["slides"]["items"]["properties"]
    assert set(slide["layout"]["enum"]) == set(office.LAYOUTS) and slide["points"]["type"] == "array"
    for field in ("bullets", "left", "right", "stats", "chart", "events", "steps", "cards", "table", "statement", "detail", "quote", "notes"):
        assert field in slide
    assert "audience" in deck and "facts" in deck and "research" not in deck
    report = schemas["make_document"]["input_schema"]["properties"]
    assert "points" in report["sections"]["items"]["properties"] and "audience" in report
