"""자가 점검이 cp949 콘솔에서도 첫 줄('—' 포함)에서 죽지 않는지."""
import io
import sys

from jarvis import selftest


def test_safe_console_survives_cp949(monkeypatch):
    buf = io.BytesIO()
    out = io.TextIOWrapper(buf, encoding="cp949")
    monkeypatch.setattr(sys, "stdout", out)
    monkeypatch.setattr(sys, "stderr", io.TextIOWrapper(io.BytesIO(), encoding="cp949"))
    monkeypatch.setattr(selftest, "LINES", [])
    selftest._safe_console()
    selftest.say("자비스 자가 점검 — 2026 · Python")
    out.flush()
    assert buf.getvalue().decode("cp949").rstrip() == "자비스 자가 점검 ? 2026 · Python"   # '·' 는 cp949 에 있음
    assert selftest.LINES == ["자비스 자가 점검 — 2026 · Python"]   # 파일에는 원문 그대로


def test_safe_console_tolerates_streams_without_reconfigure(monkeypatch):
    monkeypatch.setattr(sys, "stdout", io.StringIO())
    monkeypatch.setattr(sys, "stderr", io.StringIO())
    selftest._safe_console()   # 예외 없이 지나가야 함


def test_safe_console_tolerates_missing_streams(monkeypatch):
    """pythonw 로 실행하면 stdout · stderr 가 None 이다."""
    monkeypatch.setattr(sys, "stdout", None)
    monkeypatch.setattr(sys, "stderr", None)
    monkeypatch.setattr(selftest, "LINES", [])
    selftest._safe_console()
    selftest.say("자가 점검 — 계속")
    assert selftest.LINES == ["자가 점검 — 계속"]
