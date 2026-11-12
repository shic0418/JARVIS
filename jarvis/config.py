"""설정 파일(data/config.json) 로드/저장."""
from __future__ import annotations

import json
import os
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
UI_DIR = ROOT / "ui"
CONFIG_PATH = DATA_DIR / "config.json"
MEMORY_PATH = DATA_DIR / "memory.json"
LOG_PATH = DATA_DIR / "jarvis.log"

DEFAULTS: dict = {
    # --- 두뇌(Claude) ---
    "brain": "pro",                   # pro = Claude Pro 계정 | api = API 키 | local = Claude 사용 안 함
    "local_first": True,              # 자주 쓰는 명령은 Claude 없이 즉시 처리 (토큰 0)
    "local_ai": True,                 # 규칙으로 못 알아들은 말을 내 PC의 AI(Ollama)가 해석 (토큰 0)
    "local_ai_model": "qwen2.5:1.5b", # Ollama 모델 이름 (이 PC 테스트에서 3b 보다 빠르고 정확)
    "local_ai_timeout": 12,           # 초. 넘기면 Claude 에게 넘김
    "pro_model": "haiku",             # Pro 모드 모델: haiku | sonnet | opus
    "pro_screen_model": "sonnet",     # Pro 모드에서 화면을 보고 조작하는 요청에 쓸 모델 (비우면 pro_model 그대로)
    "routines": {},                   # 루틴: {"아침 준비": ["크롬 열어", "볼륨 30", "오늘 날씨"]} — '루틴 추가 이름: 명령, 명령' 으로 만든다
    "pro_keep_alive": 600,            # 초. 마지막 명령 뒤 이만큼 Claude Code 를 켜 둠 (다음 명령이 빨라짐, 메모리 수백 MB). 0 = 바로 닫음
    "writers": 4,                     # 발표 자료 · 보고서를 나눠서 동시에 쓰는 작가 수 1~6 (0 = 끔: 혼자 조사하고 혼자 쓴다)
    "writer_model": "",               # 작가가 쓸 모델 (비우면 평소 모델). Pro: haiku | sonnet | opus
    "screen_follow": True,            # 누른 뒤 화면이 바뀌었으면 바뀐 화면(요소 목록 · 캡처)을 결과에 같이 보냄
    "screen_detail": "auto",          # 화면 캡처 크기: auto(모델이 볼 수 있는 최대 크기) | standard(항상 작게 — 토큰 절약)
    "anthropic_api_key": "",          # 비워두면 ANTHROPIC_API_KEY 환경변수 사용
    "model": "claude-opus-5-5",
    "effort": "low",                  # low | medium | high  (음성 비서는 low 권장: 빠른 응답)
    "web_search": True,               # Claude 서버측 웹 검색 사용 (검색당 별도 과금)
    # --- 음성 ---
    "wake_word_enabled": True,        # '자비스' 호출어 상시 대기
    "wake_words": ["자비스", "쟈비스", "자비즈", "자비스야", "jarvis", "저비스"],
    "stt_language": "ko-KR",
    "stt_engine": "auto",             # auto = 대기 중엔 오프라인 인식, 호출 후엔 Google | local = 항상 오프라인 | google
    "tts_voice": "ko-KR-InJoonNeural",
    "tts_rate": "+3%",               # 자비스는 서두르지 않지만 늘어지지도 않는다 — 또박또박 정확한 속도
    "tts_pitch": "-3Hz",             # 조금 낮고 차분한 목소리 (edge-tts 음높이)
    "voice_fx": True,                # 자비스 음색: 깨끗하게 다듬은 목소리 + 옅은 디지털 광택 + 짧은 공간감 (speech.jarvis_tone)
    "mic_device": None,               # None = 기본 마이크
    "mic_sensitivity": 1.0,           # 높을수록 작은 소리에도 반응
    "noise_robust": True,             # 소음 환경 모드: 음성 감지 AI + 소음 제거 AI (시끄러운 곳에서 작은 목소리)
    "beamforming": True,              # 마이크가 2개 이상이면 정면에서 온 목소리만 강조 (옆 사람·TV 소리 줄임)
    "agc": True,                      # 자동 음량 조절: 멀리서 작게 들어오는 목소리를 실시간으로 키움
    "follow_up_seconds": 7,           # 대답 후 호출어 없이 이어 말할 수 있는 시간
    # --- 자유 대화 모드 ---
    "chat_idle_seconds": 40,          # 대화 모드에서 이 시간 동안 아무 말이 없으면 대화 모드 종료
    "chat_model": "",                 # 대화 모드 모델 (비우면 pro_model). Pro: haiku | sonnet | opus
    # --- 화자 인식 (목소리 확인) ---
    "speaker_lock": True,             # 세션 잠금: '자비스'라고 부른 사람의 목소리만 이어서 인식
    "owner_only": False,              # 등록된 주인 목소리에만 반응 (목소리 등록 후 켜짐)
    "speaker_threshold": 0.40,        # 목소리 판별 기준 0.25~0.60 (높을수록 엄격)
    # --- 동작 ---
    "user_title": "주인님",
    "home_city": "Seoul",
    "auto_approve": False,            # True면 위험 명령(PowerShell, 종료 등)을 확인 없이 실행
    "hotkey": "ctrl+alt+j",
    # --- 화면 ---
    "position": "bottom-right",       # bottom-right | top-right
    "compact": False,
    "self_guard": True,               # 보안 프로토콜: 울트론에게 흡수되면 반격해 울트론을 자비스로 되돌린다 (guard.py · counter.py)
    "counter_show": True,             # 반격 연출: 울트론 HUD 가 서서히 자비스로 바뀌는 장면 (끄면 조용히 되찾기만)
    # --- Sentinel 웹 보안 분석기 (sentinel.py) ---
    "sentinel_server": "http://127.0.0.1:8000",
    "sentinel_api_key": "",           # 비워두면 SENTINEL_API_KEY 환경변수 사용
    "sentinel_requester": "",         # Sentinel 감사 기록에 남는 요청자 이름 (비워두면 Windows 사용자 이름)
    "sentinel_basis": "owner",        # 검사 근거 기본값: owner | written_permission | bug_bounty_scope | internal_lab
    "hud_motion": "auto",             # 액티브 모드 회전 · 스캔 연출: auto = Windows '애니메이션 효과' 설정을 따름 | on | off
}

_lock = threading.Lock()


# 예전 버전의 기본값 → 지금 기본값으로 옮겨도 되는 값들
_OLD_DEFAULTS = {
    "tts_rate": ("+8%",),
}


class Config:
    def __init__(self) -> None:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        self._data = dict(DEFAULTS)
        if CONFIG_PATH.exists():
            try:
                loaded = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    self._data.update(loaded)
                    # 예전 기본값을 그대로 쓰던 항목만 새 기본값(마블 자비스 목소리)으로 옮긴다 — 직접 바꾼 값은 건드리지 않는다
                    for k, old in _OLD_DEFAULTS.items():
                        if loaded.get(k) in old:
                            self._data[k] = DEFAULTS[k]
            except Exception:
                pass
        self.save()

    def __getitem__(self, key: str):
        return self._data.get(key, DEFAULTS.get(key))

    def get(self, key: str, default=None):
        return self._data.get(key, default)

    def update(self, values: dict) -> None:
        with _lock:
            for k, v in values.items():
                if k in DEFAULTS:
                    self._data[k] = v
        self.save()

    def save(self) -> None:
        with _lock:
            CONFIG_PATH.write_text(
                json.dumps(self._data, ensure_ascii=False, indent=2), encoding="utf-8"
            )

    def api_key(self) -> str:
        return (self._data.get("anthropic_api_key") or os.environ.get("ANTHROPIC_API_KEY") or "").strip()

    def public(self) -> dict:
        """UI로 보낼 설정 (API 키는 마스킹)."""
        d = dict(self._data)
        key = self.api_key()
        d["anthropic_api_key"] = ""
        d["has_api_key"] = bool(key)
        d["api_key_hint"] = (key[:7] + "…" + key[-4:]) if len(key) > 12 else ""
        d["sentinel_api_key"] = ""
        d["has_sentinel_key"] = bool((self._data.get("sentinel_api_key") or os.environ.get("SENTINEL_API_KEY") or "").strip())
        return d


# ---- 장기 기억 (사용자가 "기억해" 라고 한 사실들) ----
def load_memory() -> list[str]:
    try:
        data = json.loads(MEMORY_PATH.read_text(encoding="utf-8"))
        return [str(x) for x in data][-50:]
    except Exception:
        return []


def save_memory(items: list[str]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    MEMORY_PATH.write_text(json.dumps(items[-50:], ensure_ascii=False, indent=2), encoding="utf-8")
