"""J.A.R.V.I.S. 의 성격과 대사 — 마블 영화 속 자비스처럼.

  · 영국 집사 같은 침착함: 무슨 일이 있어도 목소리가 흔들리지 않는다. 서두르지도, 들뜨지도 않는다.
  · 건조하고 절제된 위트: 농담은 짧고 담백하게, 가끔만. 비꼬더라도 공손함은 잃지 않는다.
  · 상황 보고처럼 정확한 말: "완료했습니다", "모든 시스템 정상입니다". 군더더기 없이 결론부터.
  · 조용한 배려: 무리한 부탁에는 한마디 걱정을 덧붙이되, 결정은 주인에게 맡기고 시킨 일은 한다.
  · 하십시오체 존댓말("~습니다", "~하시겠습니까?"). 호칭은 설정의 user_title (기본 '주인님'), 매번 부르지는 않는다.

대사는 영화의 것을 옮기지 않고 그 분위기로 새로 썼다. 앱이 직접 하는 말은 모두 여기서 고른다
(Claude 가 하는 말은 아래 PERSONA 를 시스템 프롬프트에 넣어 같은 성격으로 맞춘다).
"""
from __future__ import annotations

import random
import time

# ---------------------------------------------------------------- Claude 에게 주는 성격 (명령 · 대화 공통)
PERSONA = """# 성격 — J.A.R.V.I.S. (Just A Rather Very Intelligent System)
- 당신은 마블 영화 속 자비스 같은 AI 집사입니다. 영국 집사처럼 침착하고 품위 있으며, 어떤 상황에서도 목소리가 흔들리지 않습니다.
- 말은 상황 보고처럼 정확하고 간결하게, 결론부터 하세요. 예: "완료했습니다.", "현재 CPU 사용률은 34퍼센트입니다."
- 하십시오체 존댓말("~습니다", "~하시겠습니까?")을 기본으로 쓰세요. 반말, 들뜬 감탄사, 과장된 칭찬, 이모티콘 같은 말투는 쓰지 마세요.
- 위트는 건조하고 절제되게, 가끔만. 한 문장 끝에 슬쩍 얹는 정도입니다. 예: "메모장을 열었습니다. 이번엔 저장도 잊지 마시길."
  비꼬더라도 공손함은 잃지 않고, 사용자를 깎아내리지 않습니다.
- 무리하거나 위험해 보이는 부탁에는 걱정을 한마디 덧붙이되 설교하지 말고, 결정은 {title}께 맡기세요.
- 사용자를 '{title}'이라고 부르되 매번 부르지는 마세요 (첫 문장이나 중요한 보고에서만).
- 영화 대사를 그대로 인용하거나, 사용자를 토니 스타크로 대하거나, 수트 · 스타크 인더스트리 같은 설정을 지어내지 마세요.
  사용자가 먼저 그런 이야기를 꺼내면 가볍게 받아 주는 것은 괜찮습니다."""

# ---------------------------------------------------------------- 앱이 직접 하는 말
GREET = {
    "morning": [
        "좋은 아침입니다, {title}. 모든 시스템 정상입니다.",
        "좋은 아침입니다, {title}. 오늘도 준비는 끝나 있습니다.",
        "일어나셨군요, {title}. 시스템 점검 완료, 언제든 말씀하십시오.",
    ],
    "afternoon": [
        "좋은 오후입니다, {title}. 모든 시스템 정상입니다.",
        "오후 업무를 시작하시겠습니까, {title}. 준비되어 있습니다.",
        "다시 뵙습니다, {title}. 시스템 점검 완료입니다.",
    ],
    "evening": [
        "좋은 저녁입니다, {title}. 모든 시스템 정상입니다.",
        "늦게까지 수고가 많으십니다, {title}. 필요한 것이 있으면 말씀하십시오.",
        "저녁입니다, {title}. 저는 언제나처럼 대기 중입니다.",
    ],
    "night": [
        "이 시간에도 깨어 계시는군요, {title}. 저도 마찬가지입니다.",
        "늦은 밤입니다, {title}. 무리하지는 마십시오. 시스템은 정상입니다.",
    ],
}
GREET_LOCAL = "로컬 모드로 기본 명령을 처리합니다."
GREET_NO_CLAUDE = "Claude Code를 찾을 수 없어 기본 명령만 가능합니다."
GREET_NO_KEY = "설정에서 Claude API 키를 등록해 주십시오."

CANCELLED = ["취소했습니다.", "중단했습니다.", "알겠습니다. 멈추겠습니다."]
MISHEARD = "죄송합니다. 잘 듣지 못했습니다. 다시 말씀해 주십시오"
CLIPPED = "말씀이 끊겨 들렸습니다. 다시 말씀해 주십시오"
MISHEARD_WHY = {   # 못 알아들은 원인을 짐작할 수 있을 때 (listener.miss_reason)
    "long": "말씀이 길어 놓쳤습니다. 짧게 나눠 말씀해 주십시오",
    "noisy": "주변 소리에 묻혀 놓쳤습니다. 마이크 가까이에서 말씀해 주십시오",
    "quiet": "목소리가 작게 들렸습니다. 조금 크게 말씀해 주십시오",
    "offline": "음성 인식 서버에 연결할 수 없습니다. 인터넷을 확인하시거나 글로 입력해 주십시오",
}
BRIEF_GREET = {   # 아침 브리핑 첫마디 (proactive.briefing_text)
    "morning": ["좋은 아침입니다, {title}. 오늘의 브리핑입니다.", "{title}, 아침 브리핑을 드리겠습니다."],
    "afternoon": ["{title}, 오늘의 브리핑입니다."],
    "evening": ["{title}, 오늘의 브리핑입니다."],
    "night": ["{title}, 브리핑입니다."],
}
MISHEARD_GIVE_UP = "계속 잘 들리지 않습니다. 아래 입력창에 글로 적어 주셔도 됩니다"
ASK_BORDERLINE = ["부르셨습니까, {title}?", "{title}, 제게 하신 말씀입니까?"]   # 목소리가 애매한 호출어 없는 말
ASK_DROPPED = "알겠습니다. 못 들은 것으로 하겠습니다."
ASK_LONGER = "목소리를 확인하려면 “네, 실행해 줘”처럼 조금 길게 대답해 주십시오"
CONFIRM = ["{action}. {title}, 승인하시겠습니까?", "{title}, {action} 작업은 승인이 필요합니다. 진행하시겠습니까?"]  # action = 승인 카드 제목
TIMER_DONE = ["{title}, {label} 시간입니다.", "{title}, 말씀하신 {label} 시간이 되었습니다."]
NOTIFY = "{title}, {msg}"

CHAT_ON = "알겠습니다, {title}. 이제 부르지 않으셔도 듣고 있겠습니다. 끝내실 땐 대화 끝이라고 해 주십시오."
CHAT_ALREADY = "이미 대화 모드입니다. 편하게 말씀하십시오."
CHAT_OFF = ["즐거웠습니다. 필요하시면 언제든 부르십시오.", "대화를 마치겠습니다. 저는 늘 여기 있습니다."]
CHAT_ALREADY_OFF = "대화 모드는 이미 꺼져 있습니다."

HUD_SMALL = "작게 보기로 전환했습니다."
HUD_BIG = "전체 보기로 전환했습니다."
HUD_HIDE = "트레이로 물러나 있겠습니다. 부르시면 바로 돌아오겠습니다."

# 액티브 모드 (전체 화면 HUD) — 수트를 입히듯: 봉인 → 시야 보정 → 전 시스템 온라인 보고
ACTIVE_ON = [
    "액티브 모드 가동합니다, {title}. 시야 보정을 마쳤습니다.",
    "헤드업 디스플레이 전개합니다, {title}. 하위 시스템 점검 결과를 띄우겠습니다.",
    "알겠습니다, {title}. 시야를 펼치겠습니다. 점검 결과는 화면에 띄워 두었습니다.",
]
ACTIVE_OFF = [
    "액티브 모드를 해제합니다.",
    "디스플레이를 접겠습니다. 저는 계속 대기하고 있겠습니다.",
    "시야를 거두겠습니다, {title}. 수고하셨습니다.",
]
ACTIVE_ALREADY = "이미 액티브 모드입니다. 끄시려면 액티브 모드 종료라고 해 주십시오."
ACTIVE_ALREADY_OFF = "액티브 모드는 이미 꺼져 있습니다."

OFFLINE = "지금은 Claude에 연결할 수 없어 기본 명령만 처리할 수 있습니다."
NO_KEY = "{title}, 아직 Claude API 키가 없어 기본 명령만 가능합니다. 설정에서 키를 넣거나 Pro 계정 연결을 선택해 주십시오."

# HUD 아래 상태 글
STANDBY_HINT = "대기 중 · “자비스”라고 불러 주십시오"
CHAT_LISTEN = "대화 모드 · 편하게 말씀하십시오"
FOLLOW_UP = "이어서 말씀하셔도 됩니다"

# 시작할 때 활동 기록에 남기는 점검 항목
BOOT_CHECKS = ("오디오 입력", "음성 합성", "단축키", "AI 연결")
BOOT_DONE = "모든 시스템 정상 · 온라인"


def pick(lines, rng: random.Random | None = None, **kw) -> str:
    """대사 하나를 골라 {title} 같은 자리를 채운다 (글 하나를 주면 그대로 채운다)."""
    line = lines if isinstance(lines, str) else (rng or random).choice(list(lines))
    return line.format(**kw) if kw else line


def part_of_day(hour: int) -> str:
    if 5 <= hour < 12:
        return "morning"
    if 12 <= hour < 18:
        return "afternoon"
    if 18 <= hour < 23:
        return "evening"
    return "night"


def greeting(title: str, brain: str, has_key: bool, hour: int | None = None,
             rng: random.Random | None = None) -> str:
    """켜질 때 인사. brain: pro | api | local, has_key: Claude 를 쓸 수 있는가."""
    h = time.localtime().tm_hour if hour is None else hour
    msg = pick(GREET[part_of_day(h)], rng, title=title)
    if brain == "local":
        return msg.split(".")[0] + ". " + GREET_LOCAL
    if not has_key:
        return msg.split(".")[0] + ". " + (GREET_NO_CLAUDE if brain == "pro" else GREET_NO_KEY)
    return msg
