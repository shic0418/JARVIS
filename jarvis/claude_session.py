"""계속 켜 두는 Claude Code 대화 세션 (자유 대화 모드 · 일반 명령 공용).

매 질문마다 `claude -p` 를 새로 띄우면 프로세스 시작에만 2~5초가 걸린다. 대화 모드에서는
프로세스 하나를 켜 두고 stdin 으로 말을 계속 넣는다(stream-json 입력). 답은 글자 단위로
흘러나오므로(--include-partial-messages) 첫 문장이 완성되는 즉시 읽기 시작할 수 있다.
이 PC 시험: 두 번째 질문부터 첫 글자까지 약 1.6초 (기존 방식은 약 3초 + 전체 답 대기).
"""
from __future__ import annotations

import collections
import json
import logging
import subprocess
import threading
import time
from typing import Callable

log = logging.getLogger("jarvis.claude_session")
NO_WINDOW = 0x08000000


class ClaudeSession:
    def __init__(self, args_fn: Callable[[str | None], list[str]], env_fn: Callable[[], dict], cwd: str) -> None:
        self.args_fn = args_fn          # (이어갈 session_id | None) -> 실행 인자
        self.env_fn = env_fn
        self.cwd = cwd
        self.proc: subprocess.Popen | None = None
        self.session_id: str | None = None
        self._err: collections.deque[str] = collections.deque(maxlen=40)
        self._lock = threading.Lock()
        self._req = 0

    @property
    def busy(self) -> bool:
        """지금 질문을 처리하는 중인가."""
        return self._lock.locked()

    @property
    def alive(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def _start(self) -> None:
        self.proc = subprocess.Popen(self.args_fn(self.session_id), cwd=self.cwd, env=self.env_fn(),
                                     stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                     creationflags=NO_WINDOW)
        self._err.clear()
        proc = self.proc

        def drain():   # stderr 를 읽어 두지 않으면 파이프가 차서 멈춘다
            for line in proc.stderr:
                self._err.append(line.decode("utf-8", "replace").rstrip())
        threading.Thread(target=drain, daemon=True, name="claude-stderr").start()

    def warm(self) -> None:
        """질문 없이 프로세스만 미리 띄운다 (초기화·MCP 연결을 미리 끝내 둠)."""
        with self._lock:
            if not self.alive:
                self._start()

    def close_if_idle(self) -> bool:
        """질문을 처리하는 중이 아니면 프로세스를 닫는다 (대화는 다음에 --resume 으로 이어짐). 닫았으면 True."""
        if not self._lock.acquire(blocking=False):
            return False
        try:
            was = self.alive
            self.close()
            return was
        finally:
            self._lock.release()

    def set_model(self, model: str, timeout: float = 4.0) -> bool:
        """켜져 있는 프로세스의 모델을 바꾼다 (같은 대화를 이어 간다). 안 되면 False —
        그때는 프로세스를 끄고, 다음 질문 때 새 모델로 다시 켜서 대화를 이어 가면 된다."""
        with self._lock:
            if not self.alive:
                return False
            proc = self.proc
            self._req += 1
            rid = f"jarvis_{self._req}"
            msg = {"type": "control_request", "request_id": rid, "request": {"subtype": "set_model", "model": model}}
            try:
                proc.stdin.write((json.dumps(msg) + "\n").encode("utf-8"))
                proc.stdin.flush()
            except OSError:
                self.close()
                return False
            done = threading.Event()

            def watchdog():
                if not done.wait(timeout):
                    proc.kill()                   # 대답이 없다 (control_request 를 모르는 예전 버전) → 다시 켜서 바꾼다
            threading.Thread(target=watchdog, daemon=True, name="claude-setmodel").start()
            ok = False
            try:
                for raw in proc.stdout:
                    try:
                        ev = json.loads(raw.decode("utf-8", "replace"))
                    except json.JSONDecodeError:
                        continue
                    if ev.get("type") == "control_response":
                        r = ev.get("response") or {}
                        if r.get("request_id") == rid:
                            ok = r.get("subtype") == "success"
                            break
            finally:
                done.set()
            if not ok:
                self.close()
            return ok

    def close(self, forget: bool = False) -> None:
        p, self.proc = self.proc, None
        if forget:
            self.session_id = None
        if p and p.poll() is None:
            try:
                p.stdin.close()
            except OSError:
                pass
            try:
                p.wait(timeout=2)
            except subprocess.TimeoutExpired:
                p.kill()

    def ask(self, prompt: str, cancel: threading.Event, on_text: Callable[[str], None] | None = None,
            on_event: Callable[[dict], None] | None = None, timeout: float = 240) -> tuple[str | None, bool, str]:
        """(최종 답, 오류 여부, 오류 설명). 취소되면 (None, False, "")."""
        with self._lock:
            if not self.alive:
                self._start()
            proc = self.proc
            msg = {"type": "user", "message": {"role": "user", "content": [{"type": "text", "text": prompt}]}}
            try:
                proc.stdin.write((json.dumps(msg, ensure_ascii=False) + "\n").encode("utf-8"))
                proc.stdin.flush()
            except OSError as e:
                self.close()
                return None, True, f"세션에 쓰지 못함: {e}"

            done = threading.Event()

            def watchdog():
                deadline = time.monotonic() + timeout
                while not done.is_set():
                    if cancel.is_set() or time.monotonic() > deadline:
                        proc.kill()   # 다음 질문 때 --resume 으로 이어서 다시 켠다
                        return
                    time.sleep(0.1)
            threading.Thread(target=watchdog, daemon=True, name="claude-watchdog").start()

            result, is_error, last_text = None, False, ""
            try:
                for raw in proc.stdout:
                    try:
                        ev = json.loads(raw.decode("utf-8", "replace"))
                    except json.JSONDecodeError:
                        continue
                    if ev.get("session_id"):
                        self.session_id = ev["session_id"]
                    t = ev.get("type")
                    if t == "stream_event":
                        e = ev.get("event") or {}
                        d = e.get("delta") or {}
                        if e.get("type") == "content_block_delta" and d.get("type") == "text_delta" and on_text:
                            on_text(d.get("text", ""))
                        elif e.get("type") == "message_start" and on_text:
                            on_text("\n")   # 도구를 쓰고 난 뒤의 새 메시지는 새 문장으로
                    elif t == "assistant":
                        for b in (ev.get("message") or {}).get("content", []):
                            if b.get("type") == "text" and b.get("text", "").strip():
                                last_text = b["text"].strip()
                        if on_event:
                            on_event(ev)
                    elif t == "system" and on_event and ev.get("model"):
                        on_event(ev)              # 처음 켜질 때 알려 주는 실제 모델 이름
                    elif t == "result":
                        result = ev.get("result")
                        is_error = bool(ev.get("is_error")) or ev.get("subtype") != "success"
                        break
            finally:
                done.set()
            if cancel.is_set():
                self.close()
                return None, False, ""
            if result is None and not self.alive:   # 프로세스가 죽음 (로그인 문제 등)
                err = "\n".join(self._err)
                self.close()
                return None, True, err or "Claude Code 가 응답 없이 종료됨"
            if is_error:
                return result, True, "\n".join(self._err)
            return (result or last_text or "").strip(), False, ""
