"""Claude Code 가 실행하는 MCP 서버(stdio).

자비스 앱 안의 도구 서버(toolserver.py)로 요청을 그대로 전달한다.
도구 실행·승인 카드·작업 로그는 모두 자비스 앱에서 처리된다.
이 파일은 자비스 패키지를 import 하지 않는다 (별도 프로세스, 표준 라이브러리만 사용).
"""
import json
import os
import sys
import urllib.request

URL = os.environ.get("JARVIS_TOOL_URL", "")
TOKEN = os.environ.get("JARVIS_TOOL_TOKEN", "")

# Windows 에서 stdin/stdout 을 UTF-8 로
sys.stdin.reconfigure(encoding="utf-8")
sys.stdout.reconfigure(encoding="utf-8", newline="\n")


def call_app(path: str, payload: dict | None = None, timeout: float = 300):
    data = json.dumps(payload or {}, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(URL + path, data=data, method="POST",
                                 headers={"Content-Type": "application/json", "X-Jarvis-Token": TOKEN})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def send(msg: dict) -> None:
    sys.stdout.write(json.dumps(msg, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def handle(req: dict):
    method = req.get("method")
    params = req.get("params") or {}
    if method == "initialize":
        return {"protocolVersion": params.get("protocolVersion", "2025-06-18"),
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "jarvis", "version": "1.0"}}
    if method == "ping":
        return {}
    if method == "tools/list":
        return {"tools": call_app("/tools", timeout=15)["tools"]}
    if method == "tools/call":
        try:
            return call_app("/call", {"name": params.get("name"), "arguments": params.get("arguments") or {}})
        except Exception as e:
            return {"content": [{"type": "text", "text": f"자비스 앱에 연결할 수 없습니다: {e}"}], "isError": True}
    raise KeyError(method)


def main() -> None:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError:
            continue
        if "id" not in req:          # 알림(notification)은 응답하지 않음
            continue
        try:
            send({"jsonrpc": "2.0", "id": req["id"], "result": handle(req)})
        except KeyError:
            send({"jsonrpc": "2.0", "id": req["id"], "error": {"code": -32601, "message": "Method not found"}})
        except Exception as e:
            send({"jsonrpc": "2.0", "id": req["id"], "error": {"code": -32603, "message": str(e)}})


if __name__ == "__main__":
    main()
