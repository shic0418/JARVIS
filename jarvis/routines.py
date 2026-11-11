"""루틴 — 자주 쓰는 명령 묶음에 이름을 붙여 한마디로 실행한다 (Claude 를 거치지 않아 바로 실행되고 토큰을 쓰지 않는다).

    루틴 추가 아침 준비: 크롬 열어, 볼륨 30, 오늘 날씨        ← 입력창에 글로 치는 것이 정확하다
    아침 준비  /  아침 준비 해 줘  /  아침 준비 루틴 실행      ← 말이나 글로 실행
    루틴 목록  ·  루틴 삭제 아침 준비

각 단계는 로컬 명령 처리기가 아는 명령(앱 열기 · 볼륨 · 밝기 · 음악 · 날씨 · 타이머 · 사이트 열기 …)이어야 한다.
승인이 필요한 동작(종료 등)은 루틴 안에서도 승인 카드를 거친다. 순수 함수만 있다 — 실행은 brain.py 가 한다.
"""
from __future__ import annotations

import re

MAX_STEPS = 8
MAX_ROUTINES = 30
_ADD = re.compile(r"^루틴\s*(?:추가|등록|만들어|만들기|저장)\s*[:：]?\s*(.+?)\s*[:：]\s*(.+)$")
_DEL = re.compile(r"^루틴\s*(?:삭제|지워|제거|없애)\s*[:：]?\s*(.+)$|^(.+?)\s*루틴\s*(?:삭제|지워|제거|없애)(?:\s*줘)?$")
_LIST = re.compile(r"^(?:루틴\s*(?:목록|뭐\s*있어|보여|알려)|내\s*루틴)(?:\s*(?:보여|알려))?(?:\s*줘)?$")
_RUN_TAIL = re.compile(r"\s*(?:루틴)?\s*(?:좀\s*)?(?:실행|시작|돌려|켜|해)?(?:\s*해)?(?:\s*(?:줘|줘요|주세요|봐))?$")
# 다른 기능과 헷갈리는 이름은 받지 않는다
_RESERVED = re.compile(r"^(?:루틴|목록|삭제|추가|취소|네|아니|응|자비스)$")


def squash(s: str) -> str:
    return re.sub(r"[\s.,!?~]+", "", s or "").lower()


def parse_add(text: str) -> tuple[str, list[str]] | None:
    """'루틴 추가 이름: 명령, 명령' → (이름, 명령들). 모양이 아니면 None."""
    m = _ADD.match((text or "").strip())
    if not m:
        return None
    name = m.group(1).strip()
    steps = [s.strip() for s in re.split(r"\s*[,，;]\s*|\s+그리고\s+", m.group(2)) if s.strip()]
    if not 2 <= len(squash(name)) <= 20 or _RESERVED.match(name) or not steps:
        return None
    return name, steps[:MAX_STEPS]


def parse_delete(text: str) -> str | None:
    m = _DEL.match((text or "").strip())
    return (m.group(1) or m.group(2)).strip() if m else None


def is_list(text: str) -> bool:
    return bool(_LIST.match((text or "").strip()))


def match(text: str, routines: dict) -> str | None:
    """말한 것이 저장된 루틴 이름이면 그 이름 ('아침 준비', '아침 준비 해 줘', '아침준비 루틴 실행')."""
    if not routines:
        return None
    t = (text or "").strip().rstrip(".!?~ ")
    for cand in (t, _RUN_TAIL.sub("", t)):
        key = squash(cand)
        for name in routines:
            if key and key == squash(name):
                return name
    return None
