"""Pro 계정 명령 경로: Claude Code 를 명령마다 새로 띄우지 않고 켜 둔 세션에 이어서 묻는다."""
from __future__ import annotations

import threading
import time

import pytest

import jarvis.brain as bm
from jarvis.config import DEFAULTS


class Cfg(dict):
    def __getitem__(self, k):
        return self.get(k, DEFAULTS.get(k))

    def api_key(self):
        return ""


class Tools:
    def schemas(self):
        return []


class FakeSession:
    """ClaudeSession 대역: 프로세스 없이 정해 둔 답을 돌려준다."""
    made: list["FakeSession"] = []
    answer = ("메모장을 열었습니다.", False, "")

    def __init__(self, args_fn, env_fn, cwd):
        self.args_fn, self.alive, self.session_id = args_fn, False, None
        self.prompts: list[str] = []
        self.closed: list[bool] = []
        self.busy = False
        FakeSession.made.append(self)

    def warm(self):
        self.alive = True

    def ask(self, prompt, cancel, on_text=None, on_event=None, timeout=240):
        self.alive = True
        self.session_id = "sid-1"
        self.prompts.append(prompt)
        result, is_error, detail = FakeSession.answer
        if on_text and result and not is_error:
            on_text(result)
        return result, is_error, detail

    def set_model(self, model, timeout=4.0):
        return self.alive

    def close(self, forget=False):
        self.alive = False
        self.closed.append(forget)
        if forget:
            self.session_id = None

    def close_if_idle(self):
        was = self.alive
        self.close()
        return was


class Server:
    url, token = "http://127.0.0.1:1", "t"


@pytest.fixture
def brain(monkeypatch, tmp_path):
    FakeSession.made = []
    FakeSession.answer = ("메모장을 열었습니다.", False, "")
    monkeypatch.setattr(bm, "ClaudeSession", FakeSession)
    monkeypatch.setattr(bm, "DATA_DIR", tmp_path)
    monkeypatch.setattr(bm.Brain, "claude_exe", staticmethod(lambda: "claude"))
    b = bm.Brain(Cfg(local_first=False, local_ai=False), Tools(), on_action=lambda *a: None, context_fn=lambda: "")
    b.tool_server = Server()
    yield b
    b.shutdown()


def test_commands_reuse_one_session(brain):
    cancel = threading.Event()
    assert brain.handle("메모장 열고 할 일 써 줘", cancel) == "메모장을 열었습니다."
    assert brain.handle("거기에 우유 사기도 추가해 줘", cancel) == "메모장을 열었습니다."
    assert len(FakeSession.made) == 1
    assert len(FakeSession.made[0].prompts) == 2
    assert brain.turns == 2


def test_command_reply_is_streamed(brain):
    got: list[str] = []
    brain.handle("오늘 뉴스 알려 줘", threading.Event(), on_text=got.append)
    assert "".join(got) == "메모장을 열었습니다."


def test_session_args_stream_and_resume(brain):
    brain.handle("뉴스 알려 줘", threading.Event())
    args = FakeSession.made[0].args_fn("sid-1")
    assert "--include-partial-messages" in args and args[args.index("--input-format") + 1] == "stream-json"
    assert args[-2:] == ["--resume", "sid-1"]
    assert args[args.index("--model") + 1] == "haiku"
    assert args[args.index("--system-prompt") + 1] == brain.system != ""


def test_idle_starts_new_conversation(brain):
    brain.handle("뉴스 알려 줘", threading.Event())
    brain.last_turn -= bm.IDLE_RESET_SEC + 1
    brain.handle("주가 알려 줘", threading.Event())
    assert len(FakeSession.made) == 2
    assert FakeSession.made[0].closed == [True]


def test_setting_change_restarts_process_but_keeps_conversation(brain):
    brain.handle("뉴스 알려 줘", threading.Event())
    brain.cfg["pro_model"] = "sonnet"
    brain.handle("주가 알려 줘", threading.Event())
    assert len(FakeSession.made) == 1
    assert FakeSession.made[0].closed == [False]          # 프로세스만 닫고 session_id 는 유지
    assert FakeSession.made[0].args_fn(None)[FakeSession.made[0].args_fn(None).index("--model") + 1] == "sonnet"


def test_cancel_forgets_conversation(brain):
    cancel = threading.Event()
    cancel.set()
    assert brain._claude_code("뉴스 알려 줘", cancel) is None
    assert brain.session_id is None and FakeSession.made[0].session_id is None


def test_error_drops_session_and_reports(brain):
    FakeSession.answer = ("Usage limit reached", True, "")
    assert "한도" in brain.handle("뉴스 알려 줘", threading.Event())
    assert brain.cmd_session is None
    FakeSession.answer = (None, True, "not logged in: please login")
    assert "로그인" in brain.handle("뉴스 알려 줘", threading.Event())


def test_reset_closes_session(brain):
    brain.handle("뉴스 알려 줘", threading.Event())
    brain.reset()
    assert brain.cmd_session is None and FakeSession.made[0].closed == [True]


def test_idle_process_is_reaped(brain):
    brain.cfg["pro_keep_alive"] = 0.05
    brain.handle("뉴스 알려 줘", threading.Event())
    sess = FakeSession.made[0]
    assert sess.alive
    time.sleep(0.4)
    assert not sess.alive and sess.session_id == "sid-1"   # 프로세스만 닫힘 — 대화는 이어 갈 수 있다
    assert brain.cmd_session is sess


def test_prewarm_starts_process(brain):
    brain.prewarm()
    for _ in range(50):
        if FakeSession.made and FakeSession.made[0].alive:
            break
        time.sleep(0.02)
    assert FakeSession.made[0].alive and not FakeSession.made[0].prompts


def test_prewarm_skipped_outside_pro(brain):
    brain.cfg["brain"] = "api"
    brain.prewarm()
    time.sleep(0.1)
    assert not FakeSession.made
