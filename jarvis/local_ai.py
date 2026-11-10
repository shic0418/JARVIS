"""로컬 AI 의도 분석기 — 내 PC의 작은 언어 모델(Ollama)로 토큰 없이 명령을 이해.

규칙(정규식) 처리기가 못 알아들은 짧은 말을 로컬 모델이 '표준 명령'으로 바꿔 준다.
  "좀 시끄럽네"          → "볼륨 내려"
  "크롬 좀 띄워 줄래"     → "크롬 열어"
  "부산은 지금 비 와?"    → "부산 날씨"
바뀐 명령은 다시 규칙 처리기가 실행하므로, 로컬 AI가 할 수 있는 일은 규칙 처리기가
원래 하던 안전한 동작으로만 제한된다. 애매하거나 대화·복잡한 작업이면 Claude 에게 넘긴다.
"""
from __future__ import annotations

import json
import logging
import re
import threading
import time
import urllib.error
import urllib.request

from .local_router import parse_duration

log = logging.getLogger("jarvis.local_ai")

OLLAMA_URL = "http://127.0.0.1:11434"

INTENTS = [
    "open_app", "close_app",
    "volume_set", "volume_up", "volume_down", "mute", "unmute", "volume_get",
    "next_track", "prev_track", "pause", "resume",
    "youtube", "search_google", "search_naver", "open_folder",
    "weather", "timer", "time", "date", "system_status",
    "show_desktop", "lock_screen", "screenshot",
    "brightness_up", "brightness_down", "brightness_set",
    "claude",
]

SCHEMA = {
    "type": "object",
    "properties": {
        "intent": {"type": "string", "enum": INTENTS},
        "target": {"type": "string"},
        "number": {"type": "integer"},
    },
    "required": ["intent", "target", "number"],
}

SYSTEM = """너는 음성 비서의 명령 분류기다. 사용자의 한국어 말을 아래 intent 중 하나로 바꿔 JSON 으로만 답한다.
target 은 사용자가 실제로 말한 단어를 그대로 쓴다(번역·추측 금지). 필요 없으면 "". number 는 필요 없으면 0.

open_app: 앱 실행 (target=앱 이름)        close_app: 앱 닫기 (target=앱 이름)
volume_set: 볼륨을 숫자로 (number=0~100)  volume_up / volume_down: 볼륨 키우기/줄이기
mute / unmute / volume_get: 음소거 / 해제 / 현재 볼륨 묻기
next_track / prev_track / pause / resume: 음악·영상 다음 곡 / 이전 곡 / 멈춤 / 다시 재생
youtube: 유튜브에서 재생 (target=검색어)  search_google / search_naver: 웹 검색 (target=검색어)
open_folder: 폴더 열기 (target=다운로드|문서|바탕화면|사진|음악|동영상)
weather: 오늘 현재 날씨 (target=지역, 없으면 "")
timer: 타이머·알림 (target=시간, 예 "5분", "1시간 30분")
time / date: 지금 몇 시 / 오늘 날짜     system_status: 컴퓨터 상태·CPU·메모리
show_desktop / lock_screen / screenshot: 바탕화면 보기 / 화면 잠금 / 스크린샷
brightness_up / brightness_down: 화면(모니터) 밝기 올리기 / 낮추기   brightness_set: 화면 밝기를 숫자로 (number=0~100)
claude: 위에 정확히 맞지 않는 모든 것. 잡담, 질문, 지식, 설명, 글쓰기, 계산, 내일 날씨,
        여러 동작이 섞인 명령, 컴퓨터 종료·재시작, 파일 작업, 애매한 말은 전부 claude.
확실하지 않으면 claude 를 고른다."""

FEWSHOT = [
    ("좀 시끄럽네", {"intent": "volume_down", "target": "", "number": 0}),
    ("크롬 좀 띄워 줄래", {"intent": "open_app", "target": "크롬", "number": 0}),
    ("소리 반으로 해", {"intent": "volume_set", "target": "", "number": 50}),
    ("부산은 지금 비 와?", {"intent": "weather", "target": "부산", "number": 0}),
    ("뉴진스 하입보이 듣고 싶어", {"intent": "youtube", "target": "뉴진스 하입보이", "number": 0}),
    ("라면 3분 재야 돼", {"intent": "timer", "target": "3분", "number": 0}),
    ("이 노래 별로다 넘겨", {"intent": "next_track", "target": "", "number": 0}),
    ("TV 소리 때문에 잘 안 들려", {"intent": "volume_up", "target": "", "number": 0}),
    ("열린 거 다 내려 봐", {"intent": "show_desktop", "target": "", "number": 0}),
    ("김치찌개 끓이는 법 알아봐", {"intent": "search_google", "target": "김치찌개 끓이는 법", "number": 0}),
    ("사진 모아둔 데 열어", {"intent": "open_folder", "target": "사진", "number": 0}),
    ("눈이 부셔 화면 좀", {"intent": "brightness_down", "target": "", "number": 0}),
    ("모니터가 너무 어둡네", {"intent": "brightness_up", "target": "", "number": 0}),
    ("양자역학이 뭐야", {"intent": "claude", "target": "", "number": 0}),
    ("나 오늘 좀 우울해", {"intent": "claude", "target": "", "number": 0}),
    ("메모장 열고 일기 써 줘", {"intent": "claude", "target": "", "number": 0}),
    ("내일 서울 날씨 어때", {"intent": "claude", "target": "", "number": 0}),
]

_UP = re.compile(r"작아|작다|작네|안\s*들|들려|들리|크게|키워|키우|올려|높여|업")
_DOWN = re.compile(r"커|크다|크네|시끄|줄여|줄이|낮춰|낮게|작게|조용|귀\s*아|내려|다운")
# 화면 밝기 얘기인지 / 소리 얘기인지 (작은 모델이 '밝기 낮춰'를 볼륨으로 바꾸는 실수 방지)
_SCREEN = re.compile(r"화면|밝기|밝아|밝다|밝네|모니터|눈\s*부|눈부|어두|어둡")
_SOUND = re.compile(r"소리|볼륨|음량|시끄|들려|들리|음악|노래|스피커")
_BRIGHT_UP = re.compile(r"어두|어둡|올려|높여|밝게|키워|안\s*보")
_BRIGHT_DOWN = re.compile(r"밝아|밝다|밝네|눈\s*부|눈부|낮춰|내려|줄여|어둡게|낮게")
_FOLDERS = {"다운로드", "문서", "내문서", "바탕화면", "사진", "음악", "동영상", "비디오"}


def _squash(s: str) -> str:
    return re.sub(r"\s+", "", s or "").lower()


def _said(target: str, text: str) -> bool:
    """target 의 모든 단어가 원래 말 안에 있어야 한다 (모델이 지어낸 대상 차단)."""
    words = [w for w in re.split(r"\s+", target.strip()) if w]
    src = _squash(text)
    return bool(words) and all(_squash(w) in src for w in words)


class LocalAI:
    def __init__(self, cfg) -> None:
        self.cfg = cfg
        self.handled = 0
        self.last_ms = 0
        self._ok_until = 0.0          # 서버·모델 확인 결과 캐시
        self._down_until = 0.0        # 연결 실패 후 잠시 시도하지 않음
        self._loaded_until = 0.0      # 모델이 메모리에 올라가 있음을 확인한 시각 + 유효 시간
        self._warming = False
        self._lock = threading.Lock()

    @property
    def model(self) -> str:
        return self.cfg["local_ai_model"] or "qwen2.5:1.5b"

    # ------------------------------------------------------------------ Ollama 통신
    def _post(self, path: str, body: dict, timeout: float) -> dict:
        req = urllib.request.Request(OLLAMA_URL + path, data=json.dumps(body).encode("utf-8"),
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))

    def available(self) -> bool:
        now = time.time()
        if now < self._ok_until:
            return True
        if now < self._down_until:
            return False
        try:
            with urllib.request.urlopen(OLLAMA_URL + "/api/tags", timeout=1.5) as r:
                names = {m.get("name") for m in json.loads(r.read().decode("utf-8")).get("models", [])}
        except Exception as e:
            log.info("Ollama 연결 안 됨: %s", e)
            self._down_until = now + 60
            return False
        if self.model not in names:
            log.warning("로컬 AI 모델 %s 없음 (설치된 모델: %s)", self.model, ", ".join(sorted(names)) or "없음")
            self._down_until = now + 60
            return False
        self._ok_until = now + 300
        return True

    def warmup(self) -> None:
        """모델을 미리 메모리에 올려 첫 명령도 빠르게 (백그라운드에서 호출)."""
        if not self.cfg["local_ai"] or self._warming:
            return
        if not self.available():
            # PC 를 막 켰을 때는 Ollama 가 아직 안 떠 있을 수 있다 → 조금 기다렸다 한 번 더
            # (기록: 시작 직후 '연결 안 됨' → 첫 명령이 로컬 AI 없이 Claude 로 넘어감)
            time.sleep(8)
            self._down_until = 0.0
            if not self.available():
                return
        self._warming = True
        try:
            self.classify("안녕", timeout=120)
            log.info("로컬 AI 준비 완료: %s (%d ms)", self.model, self.last_ms)
        except Exception as e:
            log.warning("로컬 AI 예열 실패: %s", e)
        finally:
            self._warming = False

    def loaded(self) -> bool:
        """모델이 지금 메모리에 있는가. 없으면(오래 안 써서 내려감) 백그라운드로 다시 올리고 False.
        (기록: 1시간 만의 첫 명령에서 모델을 다시 올리느라 12초 기다린 뒤 결국 Claude 로 넘어감)"""
        now = time.time()
        if now < self._loaded_until:
            return True
        try:
            with urllib.request.urlopen(OLLAMA_URL + "/api/ps", timeout=1.0) as r:
                names = {m.get("name") for m in json.loads(r.read().decode("utf-8")).get("models", [])}
        except Exception:
            return False
        if self.model in names:
            self._loaded_until = now + 60
            return True
        log.info("로컬 AI 모델이 메모리에 없어 이번에는 건너뛰고 다시 올립니다")
        threading.Thread(target=self.warmup, daemon=True, name="local-ai-warmup").start()
        return False

    def classify(self, text: str, timeout: float | None = None) -> dict | None:
        messages = [{"role": "system", "content": SYSTEM}]
        for q, a in FEWSHOT:
            messages.append({"role": "user", "content": q})
            messages.append({"role": "assistant", "content": json.dumps(a, ensure_ascii=False)})
        messages.append({"role": "user", "content": text})
        t0 = time.perf_counter()
        with self._lock:
            resp = self._post("/api/chat", {
                "model": self.model,
                "messages": messages,
                "stream": False,
                "format": SCHEMA,
                "keep_alive": "30m",
                "options": {"temperature": 0, "num_predict": 60, "num_ctx": 2048},
            }, timeout=timeout or float(self.cfg["local_ai_timeout"] or 12))
        self._loaded_until = time.time() + 60
        self.last_ms = int((time.perf_counter() - t0) * 1000)
        try:
            out = json.loads(resp["message"]["content"])
        except (KeyError, TypeError, json.JSONDecodeError):
            return None
        return out if isinstance(out, dict) and out.get("intent") in INTENTS else None

    def chat(self, messages: list[dict], timeout: float = 30) -> str | None:
        """Claude 를 쓸 수 없을 때 자유 대화용 (작은 모델이라 짧고 단순한 대화만)."""
        if not self.available():
            return None
        try:
            with self._lock:
                resp = self._post("/api/chat", {
                    "model": self.model, "messages": messages, "stream": False, "keep_alive": "30m",
                    "options": {"temperature": 0.7, "num_predict": 160, "num_ctx": 4096},
                }, timeout=timeout)
            return (resp.get("message") or {}).get("content", "").strip() or None
        except Exception as e:
            log.warning("로컬 AI 대화 실패: %s", e)
            return None

    # ------------------------------------------------------------------ 의도 → 표준 명령
    def interpret(self, text: str) -> str | None:
        """말을 규칙 처리기가 알아듣는 표준 명령으로 바꾼다. 못 하면 None (→ Claude)."""
        if not self.available() or not self.loaded():
            return None
        try:
            out = self.classify(text)
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            log.warning("로컬 AI 응답 없음 → Claude: %s", e)
            self._ok_until = 0
            self._loaded_until = 0
            return None
        if not out:
            return None
        cmd = to_command(out, text)
        log.info("로컬 AI %s (%d ms): %r → %s → %r", self.model, self.last_ms, text, out, cmd)
        return cmd


def to_command(out: dict, text: str) -> str | None:
    intent = out.get("intent")
    target = str(out.get("target") or "").strip()
    try:
        number = int(out.get("number") or 0)
    except (TypeError, ValueError):
        number = 0

    fixed = {
        "volume_up": "볼륨 올려", "volume_down": "볼륨 내려", "mute": "음소거", "unmute": "음소거 해제",
        "volume_get": "볼륨 몇이야", "next_track": "다음 곡", "prev_track": "이전 곡",
        "pause": "일시정지", "resume": "다시 재생", "time": "몇 시야", "date": "오늘 며칠이야",
        "system_status": "컴퓨터 상태 어때", "show_desktop": "바탕화면 보여",
        "lock_screen": "화면 잠가", "screenshot": "스크린샷 찍어",
        "brightness_up": "화면 밝기 올려", "brightness_down": "화면 밝기 낮춰",
    }
    # 화면 밝기 얘기를 볼륨으로 잘못 분류한 경우 → 밝기 명령으로 (방향은 말 속 단서로)
    if intent and (intent.startswith("volume") or intent in ("mute", "unmute")) \
            and _SCREEN.search(text) and not _SOUND.search(text):
        intent = "brightness_set" if intent == "volume_set" and re.search(r"\d", text) else "brightness_dir"
    if intent in ("brightness_up", "brightness_down", "brightness_dir"):
        up, down = bool(_BRIGHT_UP.search(text)), bool(_BRIGHT_DOWN.search(text))
        if up != down:
            return "화면 밝기 올려" if up else "화면 밝기 낮춰"
        if intent == "brightness_dir":
            return None
    # 작은 모델은 '키워/줄여' 방향을 자주 헷갈린다. 모델은 '볼륨 얘기'라는 것만 판단하고,
    # 방향은 말 속 단서로 정한다. 숫자를 말하지 않았는데 volume_set 을 고른 경우도 여기서 처리.
    if intent in ("volume_up", "volume_down") or (intent == "volume_set" and not re.search(r"\d", text)
                                                   and not _half(text, number)):
        up, down = bool(_UP.search(text)), bool(_DOWN.search(text))
        return "볼륨 올려" if up and not down else "볼륨 내려" if down and not up else None
    if intent in fixed:
        return fixed[intent]
    if intent == "brightness_set":
        if not 0 <= number <= 100 or not (str(number) in text or _half(text, number)):
            return None
        return f"화면 밝기 {number}"
    if intent == "volume_set":
        if not 0 <= number <= 100 or not (str(number) in text or _half(text, number)):
            return None
        return f"볼륨 {number}"
    # 파일 얘기를 앱·폴더 열기로 바꾸지 않는다 (기록: '주사위.rld 파일을 열어' → 앱 '주술회전 주사위' 실행 시도)
    if intent in ("open_app", "close_app", "open_folder") and re.search(r"파일|\.[A-Za-z0-9]{2,4}\b", text):
        return None
    if intent in ("open_app", "close_app"):
        if not target or len(target) > 15 or not _said(target, text):
            return None
        return f"{target} {'열어' if intent == 'open_app' else '닫아'}"
    if intent == "youtube":
        return f"유튜브에서 {target} 틀어" if target and _said(target, text) else None
    if intent in ("search_google", "search_naver"):
        if not target or not _said(target, text):
            return None
        site = "네이버" if "네이버" in text else "구글" if "구글" in text else \
            ("구글" if intent == "search_google" else "네이버")   # 말한 사이트가 모델 판단보다 우선
        return f"{site}에서 {target} 검색"
    if intent == "open_folder":
        # 정해진 폴더만 허용하므로 앞 두 글자만 맞으면 됨 ("다운받은 거" → 다운로드)
        name = _squash(target)
        return f"{name} 폴더 열어" if name in _FOLDERS and name[:2] in _squash(text) else None
    if intent == "weather":
        if re.search(r"내일|모레|주말|다음\s*주|이번\s*주", text):
            return None
        if target and not _said(target, text):
            return None
        return f"{target} 날씨".strip()
    if intent == "timer":
        if parse_duration(target) <= 0 or not _said(target, text):
            return None
        return f"{target} 뒤에 알려"
    return None


def _half(text: str, number: int) -> bool:
    """'반으로' 같은 말은 숫자가 문장에 없어도 허용."""
    if number == 50:
        return "반" in text
    return number == 0 and re.search(r"0|영|제로", text) is not None
