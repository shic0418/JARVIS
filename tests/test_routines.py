"""루틴 (routines.py · brain._routine) — 명령 묶음을 만들고, 한마디로 실행한다."""
import threading

import jarvis.brain as bm
from jarvis import routines
from jarvis.config import DEFAULTS


def test_parse_add_delete_list():
    assert routines.parse_add("루틴 추가 아침 준비: 크롬 열어, 볼륨 30, 오늘 날씨") == ("아침 준비", ["크롬 열어", "볼륨 30", "오늘 날씨"])
    assert routines.parse_add("루틴 만들어 퇴근: 음악 멈춰 그리고 화면 잠가") == ("퇴근", ["음악 멈춰", "화면 잠가"])
    assert routines.parse_add("루틴 추가 아침 준비") is None                # 명령이 없다
    assert routines.parse_add("루틴 추가 루틴: 크롬 열어") is None          # 헷갈리는 이름
    assert routines.parse_add("크롬 열어") is None
    assert len(routines.parse_add("루틴 추가 많이: " + ", ".join(["볼륨 올려"] * 20))[1]) == routines.MAX_STEPS
    assert routines.parse_delete("루틴 삭제 아침 준비") == "아침 준비" and routines.parse_delete("아침 준비 루틴 지워 줘") == "아침 준비"
    assert routines.parse_delete("메모장 닫아") is None
    assert routines.is_list("루틴 목록") and routines.is_list("내 루틴 보여 줘") and not routines.is_list("목록 보여 줘")


def test_match_by_name_with_or_without_run_words():
    r = {"아침 준비": ["크롬 열어"], "퇴근": ["화면 잠가"]}
    for t in ("아침 준비", "아침준비", "아침 준비 해 줘", "아침 준비 루틴 실행", "아침 준비 루틴 시작해 줘", "퇴근!"):
        assert routines.match(t, r), t
    for t in ("아침", "아침 준비물 뭐야", "퇴근 시간 알려 줘", "", "크롬 열어"):
        assert routines.match(t, r) is None, t
    assert routines.match("아침 준비", {}) is None


class Cfg(dict):
    def __getitem__(self, k):
        return self.get(k, DEFAULTS.get(k))

    def api_key(self):
        return ""

    def update(self, values):
        dict.update(self, values)


class Tools:
    def __init__(self):
        self.ran = []

    def schemas(self):
        return []

    def label(self, name, args):
        return name

    def run(self, name, args):
        self.ran.append((name, args))
        if name == "volume":
            return "볼륨 50% → 30%"
        return "ok"

    def _find_app(self, name, min_score=38):
        return ("Chrome", "id") if name == "크롬" else None

    def _match_windows(self, name):
        return []


def brain():
    b = bm.Brain(Cfg(local_ai=False, brain="local"), Tools(), on_action=lambda *a: None, context_fn=lambda: "")
    return b


def test_define_run_list_and_delete_through_the_brain():
    b = brain()
    assert "저장했습니다" in b.handle("루틴 추가 아침 준비: 크롬 열어, 볼륨 30", threading.Event())
    assert b.cfg["routines"] == {"아침 준비": ["크롬 열어", "볼륨 30"]}
    reply = b.handle("아침 준비 해 줘", threading.Event())
    assert [n for n, _ in b.tools.ran] == ["open_app", "volume"] and "아침 준비 루틴" in reply and "30퍼센트" in reply
    assert b.recognizes("아침 준비")                                       # 음성 인식 후보를 고를 때도 아는 명령으로 본다
    assert "아침 준비" in b.handle("루틴 목록", threading.Event())
    assert "지웠습니다" in b.handle("루틴 삭제 아침 준비", threading.Event()) and b.cfg["routines"] == {}
    assert "없습니다" in b.handle("루틴 삭제 아침 준비", threading.Event())


def test_routine_only_takes_commands_it_can_run_itself():
    b = brain()
    reply = b.handle("루틴 추가 공부: 크롬 열어, 양자역학 설명해 줘", threading.Event())
    assert "넣을 수 없습니다" in reply and not b.cfg["routines"]


def test_ordinary_commands_are_untouched_and_chat_mode_skips_routines():
    b = brain()
    b.cfg.update({"routines": {"퇴근": ["볼륨 30"]}})
    b.handle("크롬 열어", threading.Event())
    assert [n for n, _ in b.tools.ran] == ["open_app"]
    b.chat_mode = True
    assert b._route.__self__ is b and routines.match("퇴근", b.cfg["routines"]) == "퇴근"
