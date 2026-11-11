"""화면 작업용 모델 고르기 (brain.py) — Pro 모드에서 화면을 보고 조작하는 요청에만 더 정확한 모델을 쓴다."""
import threading

import pytest

from tests.test_cmd_session import FakeSession, brain as cmd_brain  # noqa: F401  (픽스처)

import jarvis.brain as bm
from jarvis.config import DEFAULTS


class Cfg(dict):
    def __getitem__(self, k):
        return self.get(k, DEFAULTS.get(k))

    def api_key(self):
        return ""


class Tools:
    def __init__(self):
        self.models = []

    def set_vision_model(self, model):
        self.models.append(model)

    def schemas(self):
        return []


def brain(**cfg):
    return bm.Brain(Cfg(cfg), Tools(), on_action=lambda *a: None, context_fn=lambda: "")


@pytest.mark.parametrize("text", [
    "이 페이지에서 로그인 버튼 눌러 줘", "화면에 뭐가 보여?", "여기 검색창에 고양이라고 입력해 줘", "이 글 요약해 줘",
    "설정 메뉴 어디 있어?", "아래로 스크롤해서 댓글 읽어 줘", "저거 클릭해", "이 사이트에서 장바구니 들어가 줘",
])
def test_screen_requests_use_the_screen_model(text):
    assert brain()._pro_model(text) == "sonnet"


@pytest.mark.parametrize("text", ["오늘 일정 정리해 줘", "피보나치 수열 설명해 줘", "내일 날씨 어때", "농담 하나 해 줘", ""])
def test_other_requests_keep_the_everyday_model(text):
    assert brain()._pro_model(text) == "haiku"


def test_screen_model_never_downgrades_and_can_be_turned_off():
    assert brain(pro_model="opus")._pro_model("이 버튼 눌러 줘") == "opus"                    # 평소 모델이 더 높으면 그대로
    assert brain(pro_model="sonnet")._pro_model("이 버튼 눌러 줘") == "sonnet"
    assert brain(pro_screen_model="")._pro_model("이 버튼 눌러 줘") == "haiku"                # 끈 경우
    assert brain(pro_screen_model="opus")._pro_model("이 버튼 눌러 줘") == "opus"
    assert brain(pro_screen_model="이상한값")._pro_model("이 버튼 눌러 줘") == "haiku"


def test_only_real_model_ids_reach_the_screen_tools():
    b = brain()
    for m in ("claude-sonnet-5-5", None, "", "haiku", "<synthetic>", 42, "claude-haiku-4-5-20251001"):
        b._vision_model(m)
    assert b.tools.models == ["claude-sonnet-5-5", "claude-haiku-4-5-20251001"]



# ---------------------------------------------------------------- 켜 둔 Claude Code 안에서 모델 바꾸기
def model_of(args):
    return args[args.index("--model") + 1]


def test_screen_request_switches_the_model_in_the_running_session(cmd_brain, monkeypatch):
    switched = []
    monkeypatch.setattr(FakeSession, "set_model", lambda self, m, timeout=4.0: switched.append(m) or self.alive, raising=False)
    cancel = threading.Event()
    cmd_brain.handle("오늘 뉴스 알려 줘", cancel)
    cmd_brain.handle("이 화면에서 확인 버튼 눌러 줘", cancel)
    cmd_brain.handle("고마워 이제 됐어", cancel)
    assert switched == ["sonnet", "haiku"]                       # 같은 프로세스에서 모델만 바꿨다 바꿔 돌아온다
    assert len(FakeSession.made) == 1 and len(FakeSession.made[0].prompts) == 3


def test_failed_switch_restarts_with_the_new_model_and_keeps_the_conversation(cmd_brain, monkeypatch):
    def refuse(self, m, timeout=4.0):
        self.close()
        return False
    monkeypatch.setattr(FakeSession, "set_model", refuse, raising=False)
    cancel = threading.Event()
    cmd_brain.handle("오늘 뉴스 알려 줘", cancel)
    cmd_brain.handle("이 화면에서 확인 버튼 눌러 줘", cancel)
    sess = FakeSession.made[0]
    assert len(FakeSession.made) == 1                             # 대화는 그대로 (--resume 으로 이어 감)
    assert model_of(sess.args_fn(sess.session_id)) == "sonnet"   # 다시 켤 때는 새 모델로


def test_turning_off_the_screen_model_keeps_one_model(cmd_brain, monkeypatch):
    switched = []
    monkeypatch.setattr(FakeSession, "set_model", lambda self, m, timeout=4.0: switched.append(m) or True, raising=False)
    cmd_brain.cfg["pro_screen_model"] = ""
    cmd_brain.handle("이 화면에서 확인 버튼 눌러 줘", threading.Event())
    assert switched == [] and model_of(FakeSession.made[0].args_fn(None)) == "haiku"
