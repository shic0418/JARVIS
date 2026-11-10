"""자비스 앱 내부의 로컬 도구 서버 (127.0.0.1 전용, 토큰 인증).

Claude Code(Pro 계정 모드)가 MCP 브리지를 통해 이 서버로 도구 실행을 요청한다.
"""
from __future__ import annotations

import json
import logging
import secrets
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Callable

log = logging.getLogger("jarvis.toolserver")


class ToolServer:
    def __init__(self, list_tools: Callable[[], list[dict]],
                 call_tool: Callable[[str, dict], tuple[object, bool]]) -> None:
        self.token = secrets.token_hex(16)
        self.list_tools = list_tools
        self.call_tool = call_tool
        server = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                if self.headers.get("X-Jarvis-Token") != server.token:
                    self.send_error(403)
                    return
                try:
                    body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0)) or 0) or b"{}")
                    if self.path == "/tools":
                        out = {"tools": server.list_tools()}
                    elif self.path == "/call":
                        out = server._call(body.get("name", ""), body.get("arguments") or {})
                    else:
                        self.send_error(404)
                        return
                except Exception as e:
                    log.exception("도구 서버 오류")
                    out = {"content": [{"type": "text", "text": f"오류: {e}"}], "isError": True}
                data = json.dumps(out, ensure_ascii=False).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *a):
                pass

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.httpd.server_port}"
        threading.Thread(target=self.httpd.serve_forever, daemon=True, name="toolserver").start()

    def _call(self, name: str, args: dict) -> dict:
        content, is_error = self.call_tool(name, args)
        if isinstance(content, list):   # Claude API 형식(이미지 포함) → MCP 형식
            blocks = []
            for b in content:
                if b.get("type") == "image":
                    blocks.append({"type": "image", "data": b["source"]["data"],
                                   "mimeType": b["source"]["media_type"]})
                elif b.get("type") == "text":
                    blocks.append({"type": "text", "text": b["text"]})
        else:
            blocks = [{"type": "text", "text": str(content)}]
        return {"content": blocks, "isError": bool(is_error)}

    def stop(self) -> None:
        self.httpd.shutdown()
