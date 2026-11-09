"""화자 인식: 누가 말했는지 목소리로 확인한다.

- 화자 임베딩: 발화를 192차원 '목소리 지문' 벡터로 바꾼다 (sherpa-onnx + 3D-Speaker CAM++ 모델, CPU, 오프라인).
  음높이(주파수)만이 아니라 음색·포먼트·발성 습관이 함께 반영되어 같은 성별끼리도 구분된다.
- 주인 등록: 문장 5개를 읽어 평균 벡터(프로필)를 data/voice_profile.json 에 저장한다. 이 파일은 PC 밖으로 나가지 않는다.
- SpeakerGate: 명령을 실행하기 전에 목소리를 확인한다.
    · 주인 전용 모드: 등록된 프로필과 비교
    · 세션 잠금: "자비스"라고 부른 사람의 목소리를 기억해, 이어지는 명령은 같은 사람의 것만 받는다
"""
from __future__ import annotations

import hashlib
import json
import logging
import threading
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import numpy as np

from .config import DATA_DIR

log = logging.getLogger("jarvis.voiceid")

RATE = 16000
MODEL_NAME = "3dspeaker_speech_campplus_sv_zh_en_16k-common_advanced.onnx"
MODEL_URLS = [   # 같은 파일 (아래 SHA-256 으로 검증). GitHub 서버가 가끔 504 를 내서 번갈아 시도한다
    f"https://github.com/k2-fsa/sherpa-onnx/releases/download/speaker-recongition-models/{MODEL_NAME}",
    f"https://huggingface.co/csukuangfj/speaker-embedding-models/resolve/main/{MODEL_NAME}",
]
MODEL_SHA256 = "aa3cfc16963a10586a9393f5035d6d6b57e98d358b347f80c2a30bf4f00ceba2"
MODEL_PATH = DATA_DIR / "models" / MODEL_NAME
PROFILE_PATH = DATA_DIR / "voice_profile.json"

MIN_SECONDS = 0.5            # 이보다 짧은 소리는 판별하지 않음
ENROLL_MIN_SECONDS = 1.0     # 등록 문장은 최소 이만큼은 말해야 함
ENROLL_CONSISTENCY = 0.40    # 등록 중 앞 녹음들과 이 정도는 닮아야 같은 사람으로 봄
ABSORB_MARGIN = 0.15         # 세션 기준보다 이만큼 더 높게 일치할 때만 세션 기준을 보강
SHORT_WAKE_SECONDS = 1.2     # 이보다 짧은 "자비스" 한 마디는 주인 확인을 다음 명령으로 미룸
# 기준값 근거 (실제 녹음 3명으로 측정): 등록 프로필 vs 1.5초 발화 → 0.40에서 오거부 2%·오수락 1%,
# 발화 1개 vs 발화 1개(세션 잠금) → 0.40에서 오거부 0~7%·오수락 1~5%. 실제 마이크·소음 환경에서는 달라질 수 있다.

ENROLL_SENTENCES = [
    "자비스, 오늘 날씨 어때?",
    "내일 아침 일곱 시에 알람을 맞춰 줘.",
    "자비스, 좋아하는 음악 좀 틀어 줄래?",
    "인터넷 브라우저를 열고 최신 뉴스를 검색해 줘.",
    "자비스, 화면 밝기를 조금만 낮춰 줘.",
]


@dataclass
class Voice:
    emb: np.ndarray      # 길이 1로 정규화된 임베딩
    seconds: float


def cosine(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.dot(a, b))   # 둘 다 정규화되어 있음


def _normalize(v: np.ndarray) -> np.ndarray:
    return (v / (np.linalg.norm(v) + 1e-9)).astype(np.float32)


def _short_path(p: Path) -> str:
    """onnx 런타임이 한글 경로를 못 여는 경우를 대비해 8.3 짧은 경로로 바꾼다."""
    s = str(p)
    if s.isascii():
        return s
    try:
        import win32api
        return win32api.GetShortPathName(s)
    except Exception:
        return s


# ============================================================================ 임베딩 추출
class VoiceID:
    """화자 임베딩 모델. 처음 쓸 때 모델(약 28MB)을 내려받는다."""

    def __init__(self, on_status: Callable[[], None] | None = None) -> None:
        self.on_status = on_status or (lambda: None)
        self.state = "off"           # off | downloading | loading | ready | error
        self.progress = 0            # 다운로드 진행률 %
        self.error = ""
        self._ex = None
        self._lock = threading.Lock()
        self._loader: threading.Thread | None = None

    @property
    def ready(self) -> bool:
        return self.state == "ready"

    def _set(self, state: str, error: str = "") -> None:
        self.state, self.error = state, error
        self.on_status()

    def start_loading(self) -> None:
        """백그라운드에서 모델 준비 (이미 준비 중/완료면 무시)."""
        if self.state in ("downloading", "loading", "ready"):
            return
        self._loader = threading.Thread(target=self._load, daemon=True, name="voiceid-load")
        self._loader.start()

    def _load(self) -> None:
        try:
            if not MODEL_PATH.exists():
                self._download()
            self._set("loading")
            import sherpa_onnx
            cfg = sherpa_onnx.SpeakerEmbeddingExtractorConfig(
                model=_short_path(MODEL_PATH), num_threads=2)
            if not cfg.validate():
                raise RuntimeError("모델 설정이 올바르지 않습니다")
            self._ex = sherpa_onnx.SpeakerEmbeddingExtractor(cfg)
            self._set("ready")
            log.info("화자 인식 모델 준비 완료 (dim=%d)", self._ex.dim)
        except ImportError:
            self._set("error", "sherpa-onnx 패키지가 없습니다 (setup.bat 다시 실행)")
            log.error("sherpa-onnx 가 설치되어 있지 않습니다")
        except Exception as e:
            log.exception("화자 인식 모델 준비 실패")
            self._set("error", str(e)[:120])

    def _download(self) -> None:
        MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
        part = MODEL_PATH.with_suffix(".part")
        last_err: Exception | None = None
        attempts = 6
        for attempt in range(attempts):
            url = MODEL_URLS[attempt % len(MODEL_URLS)]
            try:
                self.progress = 0
                self._set("downloading")
                req = urllib.request.Request(url, headers={"User-Agent": "jarvis-voiceid"})
                sha = hashlib.sha256()
                with urllib.request.urlopen(req, timeout=30) as r, open(part, "wb") as f:
                    total = int(r.headers.get("Content-Length") or 0)
                    got, last_pct = 0, -1
                    while chunk := r.read(1 << 16):
                        f.write(chunk)
                        sha.update(chunk)
                        got += len(chunk)
                        pct = int(got * 100 / total) if total else 0
                        if pct >= last_pct + 5:
                            last_pct = self.progress = pct
                            self.on_status()
                if sha.hexdigest() != MODEL_SHA256:
                    raise RuntimeError("모델 파일 검증 실패 (체크섬 불일치)")
                part.replace(MODEL_PATH)
                log.info("화자 인식 모델 다운로드 완료: %s", MODEL_PATH)
                return
            except Exception as e:
                last_err = e
                log.warning("모델 다운로드 실패 (%d/%d, %s): %s", attempt + 1, attempts, url.split("/")[2], e)
                part.unlink(missing_ok=True)
                if attempt + 1 < attempts:
                    time.sleep(1 + attempt * 2)
        raise RuntimeError(f"모델 다운로드 실패 — 인터넷 연결을 확인하세요 ({last_err})")

    def embed(self, pcm: np.ndarray) -> Voice | None:
        """int16 16kHz 모노 PCM → Voice. 모델이 준비되지 않았거나 너무 짧으면 None."""
        if not self.ready or pcm is None:
            return None
        seconds = len(pcm) / RATE
        if seconds < MIN_SECONDS:
            return None
        x = pcm.astype(np.float32) / 32768.0
        try:
            with self._lock:
                s = self._ex.create_stream()
                s.accept_waveform(RATE, x)
                s.input_finished()
                if not self._ex.is_ready(s):
                    return None
                v = np.asarray(self._ex.compute(s), dtype=np.float32)
        except Exception as e:
            log.warning("임베딩 계산 실패: %s", e)
            return None
        return Voice(_normalize(v), seconds)


# ============================================================================ 주인 프로필
class VoiceProfile:
    def __init__(self, path: Path = PROFILE_PATH) -> None:
        self.path = path
        self.samples: list[np.ndarray] = []
        self.created = ""
        self.centroid: np.ndarray | None = None
        self.load()

    @property
    def exists(self) -> bool:
        return self.centroid is not None

    def load(self) -> None:
        self.samples, self.created, self.centroid = [], "", None
        try:
            d = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return
        except Exception as e:
            log.warning("목소리 프로필을 읽을 수 없습니다: %s", e)
            return
        if d.get("model") != MODEL_NAME:
            log.warning("다른 모델로 만든 목소리 프로필이라 사용하지 않습니다 — 다시 등록하세요")
            return
        self.samples = [_normalize(np.asarray(s, dtype=np.float32)) for s in d.get("samples", [])]
        self.created = str(d.get("created", ""))
        if self.samples:
            self.centroid = _normalize(np.mean(self.samples, axis=0))

    def save(self, samples: list[np.ndarray]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "model": MODEL_NAME,
            "created": time.strftime("%Y-%m-%d %H:%M"),
            "samples": [[round(float(x), 5) for x in s] for s in samples],
        }
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data), encoding="utf-8")
        tmp.replace(self.path)
        self.load()

    def clear(self) -> None:
        self.path.unlink(missing_ok=True)
        self.load()

    def score(self, voice: Voice) -> float | None:
        return cosine(voice.emb, self.centroid) if self.exists else None


# ============================================================================ 명령 전 목소리 확인
@dataclass
class Verdict:
    ok: bool
    mode: str = ""               # owner | session | "" (확인 안 함)
    reason: str = ""             # 거부 사유: owner | session | short
    score: float | None = None
    threshold: float | None = None


class SpeakerGate:
    def __init__(self, vid: VoiceID, profile: VoiceProfile, cfg) -> None:
        self.vid = vid
        self.profile = profile
        self.cfg = cfg
        self.session: np.ndarray | None = None
        self._weight = 0.0

    def owner_mode(self) -> bool:
        return bool(self.cfg["owner_only"]) and self.profile.exists

    def threshold(self) -> float:
        try:
            return float(self.cfg["speaker_threshold"])
        except (TypeError, ValueError):
            return 0.40

    def reset(self) -> None:
        """세션 종료 (대기 상태로 돌아가면 호출)."""
        self.session, self._weight = None, 0.0

    def _absorb(self, voice: Voice) -> None:
        """세션 기준에 같은 사람의 발화를 더해 점점 정확하게 만든다."""
        w = min(voice.seconds, 4.0)
        if self.session is None:
            self.session, self._weight = voice.emb.copy(), w
        else:
            self.session = _normalize(self.session * self._weight + voice.emb * w)
            self._weight = min(self._weight + w, 12.0)

    def check(self, voice: Voice | None, wake: bool = False, wake_only: bool = False) -> Verdict:
        """wake=True 는 호출어가 들어 있는 발화 (세션 잠금에서는 새 세션을 시작한다).
        wake_only=True 는 "자비스" 한 마디뿐인 발화 — 아무것도 실행하지 않고 듣기만 시작한다."""
        owner = self.owner_mode()
        lock = bool(self.cfg["speaker_lock"])
        if not (owner or lock) or not self.vid.ready:
            return Verdict(True)
        th = self.threshold()
        if owner:
            if wake_only and (voice is None or voice.seconds < SHORT_WAKE_SECONDS):
                # 짧은 "자비스"는 판별이 부정확해 주인도 자주 거부되므로 듣기만 시작하고, 이어지는 명령에서 확인한다
                return Verdict(True, "owner")
            if voice is None:
                return Verdict(False, "owner", "short")
            s = self.profile.score(voice)
            return Verdict(s >= th, "owner", "" if s >= th else "owner", s, th)
        # ---- 세션 잠금 (주인 미등록) ----
        if voice is None:
            return Verdict(True, "session")       # 판별 불가 → 기존처럼 통과
        if wake or self.session is None:
            self.reset()
            self._absorb(voice)                   # 이 사람이 이번 대화의 주인
            return Verdict(True, "session")
        s = cosine(voice.emb, self.session)
        if s < th:
            return Verdict(False, "session", "session", s, th)
        if s >= th + ABSORB_MARGIN:
            # 확실히 같은 사람일 때만 기준에 더한다 — 아슬아슬하게 통과한 다른 사람이 섞이면 기준이 오염된다
            self._absorb(voice)
        return Verdict(True, "session", "", s, th)


# ============================================================================ 등록 절차
class Enrollment:
    """문장을 하나씩 읽게 해서 목소리 샘플을 모은다."""

    def __init__(self, sentences: list[str] | None = None) -> None:
        self.sentences = list(sentences or ENROLL_SENTENCES)
        self.samples: list[np.ndarray] = []
        self.fails = 0
        self.total_fails = 0

    @property
    def n(self) -> int:
        return len(self.sentences)

    @property
    def index(self) -> int:
        return len(self.samples)

    @property
    def sentence(self) -> str:
        return self.sentences[min(self.index, self.n - 1)]

    def feed(self, voice: Voice | None) -> tuple[str, str]:
        """→ (결과, 안내 문구). 결과: ok | retry | abort | done"""
        problem = ""
        if voice is None or voice.seconds < ENROLL_MIN_SECONDS:
            problem = "너무 짧게 들렸습니다. 문장을 끝까지 읽어 주세요."
        elif self.samples:
            ref = _normalize(np.mean(self.samples, axis=0))
            s = cosine(voice.emb, ref)
            log.info("등록 샘플 %d 일관성: %.2f", self.index + 1, s)
            if s < ENROLL_CONSISTENCY:
                problem = "앞서 녹음한 목소리와 달라요. 주변을 조용히 하고 다시 읽어 주세요."
        if problem:
            self.fails += 1
            self.total_fails += 1
            if self.fails >= 3 or self.total_fails >= 6:
                return "abort", ("목소리를 안정적으로 녹음하지 못해 등록을 중단합니다. "
                                 "조용한 곳에서 마이크 가까이 다시 시도해 주세요.")
            return "retry", problem
        self.samples.append(voice.emb)
        self.fails = 0
        if self.index >= self.n:
            return "done", ""
        return "ok", ""
