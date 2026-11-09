"""자비스의 '두뇌': Claude API 에이전트 루프 + API 키 없이 동작하는 기본 명령 처리기."""
from __future__ import annotations

import datetime as dt
import json
import logging
import os
import platform
import re
import shutil
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path
from typing import Callable

from .config import DATA_DIR, Config, load_memory
from .local_ai import LocalAI
from .local_router import _COMPOUND, LocalRouter, normalize

NO_WINDOW = 0x08000000
from .tools import PCTools, ToolError

log = logging.getLogger("jarvis.brain")

WEEKDAYS = "월화수목금토일"
MAX_STEPS = 12
IDLE_RESET_SEC = 600      # 10분 동안 대화가 없으면 새 대화로 시작
MAX_HISTORY = 40          # 메시지가 너무 길어지면 새 대화로 시작

SYSTEM_TEMPLATE = """당신은 J.A.R.V.I.S.(자비스), {title}의 Windows PC에 상주하는 개인 AI 비서입니다. 화면 오른쪽 구석의 홀로그램 HUD로 존재하며, 사용자는 주로 음성으로 말을 겁니다.

# 말하기
- 당신의 답변은 음성(TTS)으로 읽힙니다. 자연스러운 한국어 구어체로 1~2문장, 길어도 3문장 이내로 답하세요.
- 마크다운, 목록, 이모지, URL, 코드 블록, 괄호 속 부연을 쓰지 마세요. 숫자와 단위는 소리 내어 읽기 쉽게 쓰세요.
- 사용자를 '{title}'이라고 부르되 매번 부르지는 마세요. 침착하고 유능하며 가끔 은근한 위트가 있는 집사 같은 말투를 쓰세요.
- 입력은 음성 인식 결과라 오타나 띄어쓰기 오류가 있을 수 있습니다. 가장 그럴듯한 의도로 해석하고, 정말 모호할 때만 짧게 되물으세요.
- 지연에 민감한 음성 대화입니다. 망설이지 말고 바로 행동하고 답하세요.

# 행동
- PC 조작 요청이면 설명 없이 바로 도구를 호출하고, 끝나면 결과만 짧게 보고하세요. 예: "메모장을 열었습니다."
- 여러 단계 작업은 도구를 연달아 사용해 끝까지 완료하세요. 앱을 연 직후 입력해야 하면 wait 로 1~2초 기다린 뒤 type_text 를 쓰세요.
- 화면 내용에 대한 질문이거나 화면을 봐야 도울 수 있으면 look_at_screen 을 쓰세요.
- 최신 정보(뉴스, 주가, 경기 결과, 사실 확인 등)가 필요하면 web_search 로 찾아서 답하세요. 사용자가 브라우저로 보여 달라고 하면 browser_search 를 쓰세요.
- PowerShell 실행과 전원 제어는 앱이 사용자에게 직접 승인을 받습니다. 말로 다시 확인하지 말고 도구를 호출하세요. 다만 파일 삭제처럼 되돌릴 수 없는 작업은 명령에 정확히 무엇을 하는지 드러나게 하세요.
- 도구가 실패하면 이유를 한 문장으로 알리고 가능한 대안을 시도하세요.
- 사용자가 무언가를 기억해 달라고 하면 remember 를 쓰세요.

# 환경
- OS: {os}
- 사용자 폴더: {home}
- 기본 도시: {city}

# 기억하고 있는 사실
{memory}"""


class Brain:
    def __init__(self, cfg: Config, tools: PCTools,
                 on_action: Callable[[str, str, str, str], None],
                 context_fn: Callable[[], str]) -> None:
        self.cfg = cfg
        self.tools = tools
        self.on_action = on_action          # (id, label, status, detail)
        self.context_fn = context_fn        # 현재 활성 창 등 상황 정보
        self.history: list[dict] = []
        self.system = ""
        self.last_turn = 0.0
        self._client = None
        self._client_key = None
        self._lock = threading.Lock()
        self._cancel = threading.Event()
        self.session_id: str | None = None   # Pro 모드 대화 이어가기
        self.turns = 0
        self.tool_server = None              # app 이 설정 (Pro 모드 도구 서버)
        self._last_ai: tuple[float, str] = (0.0, "")
        self.local = LocalRouter(lambda n, a: self.execute(n, a),
                                 lambda: self.cfg["user_title"] or "주인님")
        self.local_ai = LocalAI(cfg)

    # ------------------------------------------------------------------
    def reset(self) -> None:
        self.history = []
        self.system = ""
        self.session_id = None
        self.turns = 0

    def _client_for(self, key: str):
        import anthropic
        if self._client is None or key != self._client_key:
            self._client = anthropic.Anthropic(api_key=key or None, timeout=90.0, max_retries=2)
            self._client_key = key
        return self._client

    def _build_system(self) -> str:
        mem = load_memory()
        return SYSTEM_TEMPLATE.format(
            title=self.cfg["user_title"] or "주인님",
            os=f"Windows {platform.release()} ({platform.version()})",
            home=str(Path.home()),
            city=self.cfg["home_city"],
            memory="\n".join(f"- {m}" for m in mem) if mem else "- (아직 없음)",
        )

    def _tool_defs(self, model: str) -> list[dict]:
        defs = list(self.tools.schemas())
        defs.append({"name": "wait", "description": "Wait a few seconds (max 10) e.g. for an app to finish opening.",
                     "input_schema": {"type": "object", "properties": {"seconds": {"type": "number"}},
                                      "required": ["seconds"]}})
        if self.cfg["web_search"]:
            ws_type = "web_search_20250305" if "haiku" in model else "web_search_20260209"
            defs.append({"type": ws_type, "name": "web_search", "max_uses": 3,
                         "user_location": {"type": "approximate", "country": "KR",
                                           "city": self.cfg["home_city"] or "Seoul",
                                           "timezone": "Asia/Seoul"}})
        return defs

    # ------------------------------------------------------------------
    def handle(self, text: str, cancel: threading.Event) -> str | None:
        """사용자 발화 처리 → 음성으로 읽을 답변 텍스트.

        1) 로컬 명령 처리기(토큰 0)가 먼저 시도  2) 못 하면 Claude
        """
        with self._lock:
            self._cancel = cancel
            mode = self.cfg["brain"] or "pro"
            if (mode == "local" or self.cfg["local_first"]) and not self._awaiting_answer():
                reply = self.local.try_handle(text, fallback=(mode != "local"))
                if reply is not None:
                    log.info("로컬 처리 (누적 %d회): %s", self.local.handled, text)
                    return reply
                reply = self._try_local_ai(text, fallback=(mode != "local"))
                if reply is not None:
                    return reply
            if mode == "local":
                return self.local.unknown_reply()
            reply = self._handle_ai(text, cancel)
            self._last_ai = (time.time(), reply or "")
            return reply

    def _try_local_ai(self, text: str, fallback: bool) -> str | None:
        """규칙이 못 알아들은 짧은 명령 → 내 PC의 AI 가 표준 명령으로 바꿔 규칙 처리기로 실행."""
        if not self.cfg["local_ai"]:
            return None
        c = normalize(text)
        if not c or len(c) > 50 or _COMPOUND.search(c):
            return None   # 길거나 여러 동작이 섞인 말은 처음부터 Claude
        cmd = self.local_ai.interpret(c)
        if not cmd or self._cancel.is_set():
            return None
        reply = self.local.try_handle(cmd, fallback=fallback)
        if reply is not None:
            self.local_ai.handled += 1
            log.info("로컬 AI 처리 (누적 %d회): %s → %s", self.local_ai.handled, text, cmd)
        return reply

    def _awaiting_answer(self) -> bool:
        """Claude 가 방금 질문을 던졌다면 사용자의 대답은 Claude 에게 보낸다."""
        ts, reply = self._last_ai
        return time.time() - ts < 60 and bool(re.search(r"(\?|까요|나요|할까|을까|ㄹ까)\s*$", reply.strip()))

    def _handle_ai(self, text: str, cancel: threading.Event) -> str | None:
        if True:
            if (self.cfg["brain"] or "pro") == "pro":
                try:
                    return self._claude_code(text, cancel)
                except Exception as e:
                    log.exception("Claude Code 실행 실패")
                    return self._offline(text, no_key=False) if not cancel.is_set() else None
            key = self.cfg.api_key()
            if not key:
                return self._offline(text, no_key=True)
            try:
                return self._claude(text, key, cancel)
            except Exception as e:
                import anthropic
                if isinstance(e, anthropic.AuthenticationError):
                    return "API 키가 올바르지 않습니다. 설정에서 키를 확인해 주세요."
                if isinstance(e, anthropic.PermissionDeniedError):
                    return "이 API 키로는 해당 모델을 쓸 권한이 없습니다. 설정에서 모델을 바꿔 보세요."
                if isinstance(e, anthropic.NotFoundError):
                    return "설정된 모델을 찾을 수 없습니다. 설정에서 모델을 확인해 주세요."
                if isinstance(e, anthropic.RateLimitError):
                    return "요청이 너무 많아 잠시 제한되었습니다. 조금 뒤에 다시 말씀해 주세요."
                if isinstance(e, anthropic.APIConnectionError):
                    log.warning("Claude 연결 실패 → 기본 명령 처리: %s", e)
                    return self._offline(text, no_key=False)
                if isinstance(e, anthropic.BadRequestError):
                    log.error("잘못된 요청: %s", e)
                    self.reset()
                    return "요청 처리 중 문제가 생겨 대화를 새로 시작했습니다. 다시 말씀해 주세요."
                if isinstance(e, anthropic.APIStatusError):
                    log.error("API 오류 %s: %s", e.status_code, e)
                    return "Claude 서버에 일시적인 문제가 있습니다. 잠시 후 다시 시도해 주세요."
                log.exception("처리 실패")
                return f"처리 중 오류가 발생했습니다: {e}"

    def _claude(self, text: str, key: str, cancel: threading.Event) -> str | None:
        client = self._client_for(key)
        model = self.cfg["model"] or "claude-opus-5-5"
        now = time.time()
        if (not self.system or now - self.last_turn > IDLE_RESET_SEC or len(self.history) > MAX_HISTORY):
            self.history = []
            self.system = self._build_system()   # 대화 단위로 고정 → 프롬프트 캐시 유지
        self.last_turn = now

        start_len = len(self.history)
        self.history.append({"role": "user", "content": [
            {"type": "text", "text": self.context_fn()},
            {"type": "text", "text": text},
        ]})

        kwargs: dict = dict(
            model=model,
            max_tokens=8000,
            system=self.system,
            tools=self._tool_defs(model),
            output_config={"effort": self.cfg["effort"] or "low"},
            cache_control={"type": "ephemeral"},
        )
        if "haiku" not in model:
            # 안전 분류기가 거절하면 서버가 권장 모델로 자동 재시도
            kwargs["betas"] = ["server-side-fallback-2026-07-01"]
            kwargs["fallbacks"] = "default"

        search_ids: dict[str, str] = {}
        try:
            for _ in range(MAX_STEPS):
                if cancel.is_set():
                    raise _Cancelled()
                resp = client.beta.messages.create(messages=self.history, **kwargs)
                if cancel.is_set():
                    raise _Cancelled()
                self.history.append({"role": "assistant", "content": resp.content})

                for b in resp.content:  # 서버측 웹 검색 진행 표시
                    if b.type == "server_tool_use" and b.name == "web_search":
                        aid = uuid.uuid4().hex[:8]
                        search_ids[b.id] = aid
                        q = (b.input or {}).get("query", "") if isinstance(b.input, dict) else ""
                        self.on_action(aid, f"웹 검색 · {q}", "ok", "")

                if resp.stop_reason == "tool_use":
                    results = []
                    for b in resp.content:
                        if b.type != "tool_use":
                            continue
                        results.append(self._run_tool(b, cancel))
                    self.history.append({"role": "user", "content": results})
                    continue
                if resp.stop_reason == "pause_turn":
                    continue
                if resp.stop_reason == "refusal":
                    return "죄송하지만 그 요청은 도와드릴 수 없습니다."
                reply = "".join(b.text for b in resp.content if b.type == "text").strip()
                return reply or "처리했습니다."
            return "작업 단계가 너무 많아 여기서 멈췄습니다. 이어서 할까요?"
        except _Cancelled:
            self.reset()
            return None
        except Exception:
            del self.history[start_len:]   # 실패한 턴은 기록에서 제거 (앞부분은 그대로 유지)
            raise

    def _run_tool(self, block, cancel: threading.Event) -> dict:
        args = block.input if isinstance(block.input, dict) else {}
        content, is_error = self.execute(block.name, args, cancel)
        result = {"type": "tool_result", "tool_use_id": block.id, "content": content}
        if is_error:
            result["is_error"] = True
        return result

    def execute(self, name: str, args: dict, cancel: threading.Event | None = None) -> tuple[object, bool]:
        """도구 하나 실행 → (내용, 오류 여부). API 모드와 Pro 모드가 공유."""
        cancel = cancel or self._cancel
        aid = uuid.uuid4().hex[:8]
        label = self.tools.label(name, args)
        self.on_action(aid, label, "run", "")
        try:
            if cancel.is_set():
                raise ToolError("사용자가 취소했습니다.")
            if name == "wait":
                secs = max(0.0, min(float(args.get("seconds", 1)), 10.0))
                cancel.wait(secs)
                out = f"{secs:.1f}초 대기함"
            else:
                out = self.tools.run(name, args)
            self.on_action(aid, label, "ok", out if isinstance(out, str) else "")
            return (out if isinstance(out, list) else str(out)), False
        except ToolError as e:
            self.on_action(aid, label, "error", str(e))
            return str(e), True
        except TypeError as e:
            self.on_action(aid, label, "error", "잘못된 인자")
            return f"잘못된 인자: {e}", True
        except Exception as e:
            log.exception("도구 실패: %s", name)
            self.on_action(aid, label, "error", str(e))
            return f"오류: {e}", True

    def mcp_tools(self) -> list[dict]:
        """Pro 모드(MCP)용 도구 목록."""
        out = []
        for d in self._tool_defs("pro"):
            if "input_schema" in d:
                out.append({"name": d["name"], "description": d["description"], "inputSchema": d["input_schema"]})
        return out

    # ------------------------------------------------------------------ Pro 계정 (Claude Code)
    @staticmethod
    def claude_exe() -> str | None:
        exe = shutil.which("claude")
        if exe:
            return exe
        cand = Path.home() / ".local" / "bin" / "claude.exe"
        return str(cand) if cand.exists() else None

    def _child_env(self) -> dict:
        # 이 앱의 환경에 섞인 Claude/Anthropic 변수를 지워 Pro 로그인으로 단독 실행되게 함
        env = {k: v for k, v in os.environ.items()
               if not k.upper().startswith(("CLAUDE", "ANTHROPIC"))}
        env["JARVIS_TOOL_URL"] = self.tool_server.url
        env["JARVIS_TOOL_TOKEN"] = self.tool_server.token
        return env

    def _mcp_config(self) -> str:
        exe = Path(sys.executable)
        pyw = exe.with_name("pythonw.exe")
        cfg = {"mcpServers": {"jarvis": {
            "type": "stdio",
            "command": str(pyw if pyw.exists() else exe),
            "args": [str(Path(__file__).with_name("mcp_bridge.py"))],
            "env": {"JARVIS_TOOL_URL": self.tool_server.url, "JARVIS_TOOL_TOKEN": self.tool_server.token},
        }}}
        path = DATA_DIR / "mcp_jarvis.json"
        path.write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")
        return str(path)

    def _claude_code(self, text: str, cancel: threading.Event) -> str | None:
        exe = self.claude_exe()
        if not exe:
            return ("Claude Code가 설치되어 있지 않습니다. 설정에서 API 키 방식을 쓰시거나 "
                    "Claude Code를 설치해 주세요.")
        now = time.time()
        if not self.session_id or now - self.last_turn > IDLE_RESET_SEC or self.turns >= 30 or not self.system:
            self.session_id = None
            self.turns = 0
            self.system = self._build_system()
        self.last_turn = now

        workdir = DATA_DIR / "workspace"
        workdir.mkdir(parents=True, exist_ok=True)
        builtin = "WebSearch,WebFetch" if self.cfg["web_search"] else ""
        args = [exe, "-p", "--output-format", "stream-json", "--verbose",
                "--model", self.cfg["pro_model"] or "haiku",
                "--effort", self.cfg["effort"] or "low",
                "--system-prompt", self.system,
                "--tools", builtin,
                "--mcp-config", self._mcp_config(), "--strict-mcp-config",
                "--permission-mode", "dontAsk",
                "--allowedTools", "mcp__jarvis", "WebSearch", "WebFetch"]
        if self.session_id:
            args += ["--resume", self.session_id]
        prompt = self.context_fn() + "\n\n" + text

        proc = subprocess.Popen(args, cwd=str(workdir), env=self._child_env(),
                                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                creationflags=NO_WINDOW)
        proc.stdin.write(prompt.encode("utf-8"))
        proc.stdin.close()

        def watchdog():
            deadline = time.monotonic() + 240
            while proc.poll() is None:
                if cancel.is_set() or time.monotonic() > deadline:
                    proc.kill()
                    return
                time.sleep(0.1)
        threading.Thread(target=watchdog, daemon=True).start()

        result, last_text, is_error = None, "", False
        for raw in proc.stdout:
            try:
                ev = json.loads(raw.decode("utf-8", "replace"))
            except json.JSONDecodeError:
                continue
            if ev.get("session_id"):
                self.session_id = ev["session_id"]
            if ev.get("type") == "assistant":
                for b in (ev.get("message") or {}).get("content", []):
                    if b.get("type") == "text" and b.get("text", "").strip():
                        last_text = b["text"].strip()
                    elif b.get("type") == "tool_use" and b.get("name") in ("WebSearch", "WebFetch"):
                        inp = b.get("input") or {}
                        what = inp.get("query") or inp.get("url") or ""
                        self.on_action(uuid.uuid4().hex[:8], f"웹 검색 · {what}"[:60], "ok", "")
            elif ev.get("type") == "result":
                result = ev.get("result")
                is_error = bool(ev.get("is_error")) or ev.get("subtype") != "success"
        proc.wait()
        if cancel.is_set():
            self.session_id = None
            return None
        err = proc.stderr.read().decode("utf-8", "replace")
        self.turns += 1
        if is_error or proc.returncode not in (0, None) and not result:
            blob = f"{result or ''} {err}".lower()
            log.error("Claude Code 오류 (code %s): %s | %s", proc.returncode, result, err[-500:])
            self.session_id = None
            if "login" in blob or "auth" in blob or "credential" in blob or "api key" in blob:
                return "Claude Code 로그인이 필요합니다. 터미널에서 claude 를 한 번 실행해 Pro 계정으로 로그인해 주세요."
            if "limit" in blob or "usage" in blob or "quota" in blob:
                return "Pro 사용 한도에 도달했습니다. 한도가 초기화된 뒤 다시 말씀해 주세요."
            if result is None:
                return self._offline(text, no_key=False)
            return "요청을 처리하지 못했습니다. 잠시 후 다시 시도해 주세요."
        return (result or last_text or "처리했습니다.").strip()

    # ------------------------------------------------------------------ 오프라인 기본 명령
    def _offline(self, text: str, no_key: bool) -> str:
        """Claude 를 쓸 수 없을 때: 로컬 명령 처리기로만 처리."""
        reply = self.local.try_handle(text, fallback=False)
        if reply is not None:
            return reply
        if no_key:
            title = self.cfg["user_title"] or "주인님"
            return (f"{title}, 아직 Claude API 키가 없어 기본 명령만 할 수 있습니다. "
                    "설정에서 키를 넣거나 Pro 계정 연결을 선택해 주세요.")
        return "지금 Claude에 연결할 수 없어 기본 명령만 처리할 수 있습니다."


class _Cancelled(Exception):
    pass


def situation_text(active_title: str) -> str:
    n = dt.datetime.now()
    return (f"[상황] 현재 시각 {n:%Y-%m-%d} ({WEEKDAYS[n.weekday()]}) {n:%H:%M}. "
            f"사용자의 활성 창: {active_title or '알 수 없음'}")
