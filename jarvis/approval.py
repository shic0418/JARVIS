"""승인 카드에 대한 음성 대답 판정.

예전에는 '네 · 예 · 응 · 확인'이 문장 어딘가에 들어 있기만 하면 승인으로 받았다. 그래서 카드가 떠 있을 때
"그게 뭔지 잘 모르겠네", "예약 확인해 봐" 같은 말도 승인이 됐다 (PowerShell 실행 · Sentinel 검사 권한 확인 포함).

이제는
  · 거부 표현이 하나라도 들어 있으면 거부 (잘못 거부되는 쪽이 안전하다)
  · 문장 전체가 짧은 승인 표현일 때만 승인  ("네", "승인", "응 실행해 줘", "네 승인합니다")
  · 그 밖의 말은 대답으로 보지 않는다 → 카드는 그대로 떠 있고, 다시 말하거나 버튼을 누르면 된다
"""
from __future__ import annotations

import re

from .local_router import normalize

NO_RE = re.compile(r"(취소|아니|거부|하지\s*마|안\s*돼|안\s*된다|중지|멈춰|그만|no|노)", re.I)

_SUFFIX = r"(?:해|해줘|해라|한다|합니다|할게|할게요|하세요|해주세요|해요|하자|하지)?"
_YES_TOKEN = re.compile(
    r"(?:네|넵|넹|예|응|어|엉|그래|그럼|좋아|좋다|오케이|오키|ok|okay|yes|yep)요?"
    rf"|(?:승인|확인|허가|허락|실행|진행|동의){_SUFFIX}"
    r"|맞아|맞아요|맞다|맞습니다"
    r"|해|해줘|해라|해요|하세요|줘|주세요|부탁해|부탁해요|부탁합니다", re.I)


def answer(text: str) -> bool | None:
    """True = 승인, False = 거부, None = 대답이 아님."""
    raw = (text or "").strip()
    if not raw:
        return None
    if NO_RE.search(raw):
        return False
    # 호출어 · 끝말을 뗀 모양("자비스, 승인해 줘" → "승인")과 원래 모양("해 줘") 둘 다 본다
    for t in (normalize(raw), raw):
        tokens = re.sub(r"[\s.,!?~]+", " ", t).strip().lower().split()
        if tokens and len(tokens) <= 4 and all(_YES_TOKEN.fullmatch(tok) for tok in tokens):
            return True
    return None
