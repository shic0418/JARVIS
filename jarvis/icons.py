"""아이콘 — 카드뉴스 · 포스터 · 발표 자료 · 보고서에 넣는 그림 기호.

아이콘은 assets/icons 의 구글 Material Icons Round 글꼴(Apache 2.0, 2,200개)로 그린다. 글자처럼 그리므로 색 · 크기가
자유롭고 가장자리가 매끄럽다. 이 모듈은 '어떤 아이콘을 쓸지 고르기'와 '그리기'만 한다.

고르는 순서
  1. 호출한 쪽(Claude)이 아이콘 이름을 주면 그것 ('bedtime', 'Local Cafe', 'local-cafe' 모두 받는다).
  2. 없거나 모르는 이름이면 글(한국어 · 영어)에서 낱말로 고른다. 제목에서 찾은 것이 본문보다 앞서고,
     같은 글 안에서는 먼저 나온 낱말이 앞선다.
  3. 그래도 없으면 쓰임(kind)에 맞는 기본 아이콘.
여러 칸에 한꺼번에 고를 때(assign)는 칸끼리 같은 아이콘이 겹치지 않게 나눠 준다.
아이콘 글꼴이 없으면(available() == False) 모든 함수가 '아이콘 없음'으로 답하고 그리는 쪽은 아이콘 없이 그린다.
"""
from __future__ import annotations

import io
import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Iterable, Sequence

ROOT = Path(__file__).resolve().parent.parent
FONT = ROOT / "assets" / "icons" / "MaterialIconsRound-Regular.ttf"
CODES = ROOT / "assets" / "icons" / "codepoints.json"

# ---------------------------------------------------------------------------------------------
# 낱말 → 아이콘. 위에 있는 것이 더 구체적이다 (같은 위치에서 겹치면 위의 것).
# 낱말 앞에 '^' 를 붙이면 '낱말의 시작'에서만 맞는다 — 한 글자 낱말이 다른 낱말 속에서 잘못 잡히지 않게
# ('^책' 은 '책상' · '책임' 은 따로 막고, '독서책' 의 '책' 은 안 잡는다). 정규식을 직접 쓰려면 're:' 로 시작한다.
# ---------------------------------------------------------------------------------------------
_TABLE: list[tuple[str, tuple[str, ...]]] = [
    ("bedtime", ("수면", "re:(?<![가-힣])잠(?![깐시])", "숙면", "불면", "졸음", "밤샘", "취침", "sleep")),
    ("smartphone", ("스마트폰", "휴대폰", "핸드폰", "re:(?<![가-힣])폰(?!트)", "모바일", "re:(?<![가-힣])앱(?![가-힣])",
                    "sns", "인스타", "유튜브", "틱톡", "phone", "mobile")),
    ("computer", ("블루라이트", "re:블루\\s*라이트", "모니터", "컴퓨터", "노트북", "re:(?<![a-z])pc(?![a-z])", "화면")),
    ("local_cafe", ("카페인", "커피", "에너지 음료", "coffee", "caffeine")),
    ("record_voice_over", ("강연", "강의", "특강", "연설", "세미나", "토크 콘서트", "lecture")),
    ("how_to_reg", ("신청", "접수", "등록", "가입", "참가 방법", "지원 방법", "register")),
    ("school", ("공부", "학습", "성적", "^시험", "수업", "학교", "교과", "숙제", "과제", "study", "school")),
    ("menu_book", ("re:(?<![가-힣])책(?!임|상)", "독서", "도서", "읽기", "교과서", "book", "reading")),
    ("smart_toy", ("인공지능", "re:인공\\s*지능", "re:(?<![a-z])ai(?![a-z])", "로봇", "챗봇", "자동화", "robot")),
    ("code", ("코딩", "프로그래밍", "소프트웨어", "알고리즘", "coding", "software")),
    ("insights", ("데이터", "통계", "그래프", "조사 결과", "비율", "퍼센트", "%", "statistics", "data")),
    ("payments", ("re:\\d\\s*원", "만 원", "re:(?<![가-힣])돈(?![가-힣])", "돈을", "돈이", "비용", "가격", "요금",
                  "용돈", "경제", "저축", "소비", "지출", "예산", "세금", "money", "cost", "price")),
    ("shopping_cart", ("쇼핑", "구매", "주문", "장바구니", "할인", "shopping")),
    ("health_and_safety", ("건강", "질병", "면역", "감기", "병원", "의사", "치료", "진료", "약국", "처방", "health")),
    ("sentiment_dissatisfied", ("우울", "스트레스", "불안", "짜증", "걱정", "고민", "외로", "stress")),
    ("sentiment_very_satisfied", ("행복", "웃음", "기쁨", "즐거", "만족", "힐링", "happy")),
    ("favorite", ("심장", "사랑", "마음", "감사", "응원", "좋아요", "기부", "나눔", "봉사", "love", "thanks")),
    ("fitness_center", ("re:운동(?!장)", "스트레칭", "헬스", "달리기", "걷기", "re:체육(?!관)", "근육", "요가",
                        "exercise", "fitness")),
    ("restaurant", ("식사", "음식", "^밥", "급식", "요리", "영양", "채소", "과일", "식단", "food", "meal")),
    ("water_drop", ("re:(?<![가-힣])물(?:[이을의은과에도로](?![가-힣])|(?![가-힣]))", "re:물\\s*마시", "수분", "생수",
                    "water")),
    ("eco", ("광합성", "엽록", "새싹", "re:(?<![가-힣])잎", "친환경", "에코", "생태", "지속 가능", "지속가능")),
    ("co2", ("이산화탄소", "re:이산화\\s*탄소", "re:(?<![a-z])co2")),
    ("air", ("산소", "호흡", "공기", "숨 쉬", "숨을", "미세먼지", "re:미세\\s*먼지", "oxygen", "air")),
    ("biotech", ("세포", "미토콘드리아", "세균", "바이러스", "박테리아", "미생물", "현미경", "cell", "virus")),
    ("thermostat", ("온도", "기온", "체온", "temperature")),
    ("recycling", ("분리배출", "re:분리\\s*배출", "재활용", "쓰레기", "플라스틱", "일회용", "recycl")),
    ("public", ("환경", "지구", "기후", "탄소", "온난화", "온실가스", "climate", "earth")),
    ("park", ("^숲", "나무", "식물", "^꽃", "정원", "녹지", "re:(?<![가-힣])자연(?!스)", "tree", "plant")),
    ("bolt", ("에너지", "전기", "전력", "절전", "배터리", "충전", "energy", "battery")),
    ("wb_sunny", ("날씨", "햇빛", "햇볕", "태양", "여름", "더위", "폭염", "re:(?<![가-힣])빛(?!나|깔)", "sun", "weather")),
    ("umbrella", ("^비가", "장마", "우산", "홍수", "폭우", "빗물", "rain")),
    ("ac_unit", ("겨울", "추위", "한파", "폭설", "눈사람", "winter", "snow")),
    ("local_fire_department", ("화재", "소방", "산불", "fire")),
    ("warning", ("위험", "주의", "경고", "금지", "조심", "사고", "danger", "warning")),
    ("shield", ("안전", "보안", "보호", "예방", "지키", "security", "safety")),
    ("schedule", ("시간", "re:\\d\\s*분(?![가-힣])", "일찍", "늦게", "습관", "매일", "루틴", "time", "habit")),
    ("event", ("날짜", "일정", "기간", "마감", "re:\\d+\\s*월", "요일", "캘린더", "date", "deadline")),
    ("place", ("장소", "위치", "주소", "체육관", "강당", "운동장", "교실", "본관", "location", "venue")),
    ("call", ("전화", "연락", "문의", "상담", "contact")),
    ("mail", ("이메일", "메일", "편지", "우편", "email")),
    ("child_care", ("re:(?<![가-힣])아이(?!디어|폰|패드|콘|템)", "어린이", "유아", "청소년", "10대", "child")),
    ("elderly", ("노인", "어르신", "고령", "elderly")),
    ("groups", ("친구", "사람들", "^사람", "re:(?<![가-힣])팀(?![가-힣])", "함께", "모두", "가족", "부모", "이웃",
                "공동체", "학급", "team", "people")),
    ("forum", ("말하기", "대화", "소통", "토론", "의견", "질문", "discussion")),
    ("lightbulb", ("아이디어", "생각", "창의", "발상", "해결", "방법", "^팁", "꿀팁", "비법", "idea", "tip")),
    ("flag", ("목표", "도전", "성공", "성취", "^꿈", "goal")),
    ("emoji_events", ("수상", "우승", "1등", "대회", "경품", "선물", "시상", "상품", "상장", "award", "prize")),
    ("music_note", ("음악", "노래", "공연", "콘서트", "밴드", "music")),
    ("photo_camera", ("영화", "영상", "동영상", "촬영", "사진", "카메라", "photo", "video")),
    ("palette", ("그림", "미술", "디자인", "색깔", "색칠", "그리기", "art", "design")),
    ("science", ("과학", "실험", "연구", "화학", "물리", "생물", "science", "experiment")),
    ("rocket_launch", ("우주", "행성", "로켓", "천문", "별자리", "space", "rocket")),
    ("flight", ("여행", "비행기", "해외", "관광", "휴가", "travel")),
    ("directions_bike", ("자전거", "bike")),
    ("directions_bus", ("교통", "버스", "지하철", "자동차", "운전", "도로", "traffic")),
    ("pets", ("동물", "반려", "강아지", "고양이", "애완", "pet")),
    ("campaign", ("뉴스", "소식", "공지", "안내", "news", "notice")),
    ("history_edu", ("역사", "유래", "전통", "history")),
    ("compare_arrows", ("비교", "차이", "대조", "re:(?<![a-z])vs(?![a-z])", "compare")),
    ("search", ("분석", "원인", "이유", "까닭", "analysis", "cause")),
    ("gavel", ("re:(?<![가-힣])법(?!칙)", "법률", "법원", "헌법", "규칙", "제도", "정책", "권리", "투표", "선거", "law")),
    ("language", ("세계", "국제", "글로벌", "외국", "나라", "global")),
    ("home", ("우리 집", "re:(?<![가-힣])집(?:에|이|은|을|안|밖)", "주거", "가정", "침실", "home")),
    ("work", ("직업", "취업", "회사", "업무", "직장", "진로", "일자리", "출근", "career", "job")),
    ("trending_up", ("개선", "증가", "성장", "늘어", "상승", "growth", "increase")),
    ("trending_down", ("감소", "줄어", "하락", "떨어", "decrease")),
    ("task_alt", ("확인", "체크", "완료", "해야 할", "실천", "점검", "checklist")),
    ("cancel", ("효과 없", "오해", "거짓", "가짜", "잘못", "myth")),
]

# 쓰임별 기본 아이콘 (글에서 고르지 못했을 때)
DEFAULTS = {"cover": "auto_awesome", "point": "tips_and_updates", "list": "checklist", "stat": "insights",
            "steps": "route", "compare": "compare_arrows", "quote": "format_quote", "closing": "favorite",
            "poster": "campaign", "section": "label_important", "summary": "summarize", "report": "description"}
# 여러 칸에 나눠 줄 때 글로 고르지 못한 칸에 차례로 쓰는 무난한 아이콘
SPARE = {"cards": ("tips_and_updates", "star", "bookmark", "push_pin", "lightbulb", "verified"),
         "steps": ("flag", "settings", "sync", "build", "tune", "task_alt"),
         "stats": ("insights", "trending_up", "bar_chart", "pie_chart", "speed", "analytics")}


def _compile(word: str) -> re.Pattern:
    if word.startswith("re:"):
        return re.compile(word[3:], re.I)
    if word.startswith("^"):
        return re.compile(r"(?<![가-힣A-Za-z])" + re.escape(word[1:]), re.I)
    # 띄어쓰기는 있어도 없어도 맞게 ('조사 결과' = '조사결과')
    body = r"\s*".join(re.escape(part) for part in word.split())
    if word.isascii() and word[:1].isalpha():
        return re.compile(r"(?<![a-z])" + body, re.I)          # 'art' 가 'start' 속에서 잡히지 않게
    return re.compile(body, re.I)


_RULES: list[tuple[str, tuple[re.Pattern, ...]]] = [(name, tuple(_compile(w) for w in words)) for name, words in _TABLE]


@lru_cache(maxsize=1)
def codes() -> dict[str, int]:
    """아이콘 이름 → 글자 번호. 파일이 없거나 깨졌으면 빈 사전."""
    try:
        data = json.loads(CODES.read_text(encoding="utf-8"))
        return {str(k): int(v) for k, v in data.items()}
    except (OSError, ValueError, TypeError):
        return {}


def available() -> bool:
    return FONT.exists() and bool(codes())


def normalize(name: str | None) -> str:
    """'Bed Time' · 'bed-time' · ' BEDTIME ' → 'bed_time' / 'bedtime' 꼴로."""
    return re.sub(r"[\s\-]+", "_", str(name or "").strip().lower())


def resolve(name: str | None) -> str | None:
    """아는 아이콘 이름이면 그 정식 이름, 모르면 None ('Local Cafe' → 'local_cafe', 'Bed Time' → 'bedtime')."""
    n = normalize(name)
    if not n:
        return None
    table = codes()
    for cand in (n, n.replace("_", ""), n.removesuffix("_round"), n.removesuffix("_icon")):
        if cand in table:
            return cand
    return None


def known(name: str | None) -> bool:
    return resolve(name) is not None


def candidates(*texts: str) -> list[str]:
    """글에 맞는 아이콘들 (앞의 글 — 보통 제목 — 의 것이 먼저, 같은 글 안에서는 먼저 나온 낱말부터)."""
    table = codes()
    out: list[str] = []
    for text in texts:
        blob = str(text or "")
        if not blob.strip():
            continue
        hits: list[tuple[int, int, str]] = []
        for rank, (name, pats) in enumerate(_RULES):
            if name in out or name not in table:
                continue
            first = min((m.start() for p in pats if (m := p.search(blob))), default=None)
            if first is not None:
                hits.append((first, rank, name))
        out.extend(name for _, _, name in sorted(hits))
    return out


def from_text(*texts: str) -> str | None:
    found = candidates(*texts)
    return found[0] if found else None


def pick(name: str | None, *texts: str, kind: str = "point", avoid: Iterable[str] = ()) -> str | None:
    """아이콘 하나: 준 이름(알면) → 글에서 고른 것(avoid 는 되도록 피함) → 쓰임의 기본. 글꼴이 없으면 None."""
    if not available():
        return None
    given = resolve(name)
    if given:
        return given
    avoid = set(avoid)
    found = candidates(*texts)
    for n in found:
        if n not in avoid:
            return n
    default = DEFAULTS.get(kind, "auto_awesome")
    if default in codes() and (default not in avoid or not found):
        return default
    return found[0] if found else (default if default in codes() else None)


def assign(items: Sequence[tuple[str | None, Sequence[str]]], spare: str = "cards",
           avoid: Iterable[str] = ()) -> list[str | None]:
    """여러 칸의 아이콘을 한꺼번에 고른다 — 칸끼리 겹치지 않게.

    items: (준 이름, 그 칸의 글들) 목록. 준 이름은 겹쳐도 그대로 존중한다(사람이 고른 것).
    글로 고른 것은 다른 칸이 이미 쓴 것을 피하고, 그래도 없으면 SPARE[spare] 에서 아직 안 쓴 것을 차례로 준다.
    글꼴이 없으면 모두 None.
    """
    if not available():
        return [None] * len(items)
    used = set(avoid)
    out: list[str | None] = [None] * len(items)
    for i, (given, _) in enumerate(items):          # 사람이 고른 이름을 먼저 자리 잡게 한다
        r = resolve(given)
        if r:
            out[i] = r
            used.add(r)
    for i, (_, texts) in enumerate(items):
        if out[i]:
            continue
        n = next((c for c in candidates(*texts) if c not in used), None)
        if n:
            out[i] = n
            used.add(n)
    pool = [n for n in SPARE.get(spare, SPARE["cards"]) if n in codes()]
    for i in range(len(out)):
        if out[i] is None:
            n = next((p for p in pool if p not in used), pool[i % len(pool)] if pool else None)
            out[i] = n
            if n:
                used.add(n)
    return out


def glyph(name: str | None) -> str | None:
    """아이콘 글자 하나 (아이콘 글꼴로 그릴 때 쓰는 문자). 모르는 이름이면 None."""
    cp = codes().get(resolve(name) or "")
    return chr(cp) if cp is not None and FONT.exists() else None


@lru_cache(maxsize=64)
def font(size: int):
    from PIL import ImageFont
    return ImageFont.truetype(str(FONT), max(1, int(size)))


def draw(d, name: str | None, center: tuple[float, float], size: float, fill) -> bool:
    """PIL ImageDraw 에 아이콘 하나를 가운데 맞춰 그린다 (size = 한 변 픽셀). 그렸으면 True."""
    g = glyph(name)
    if g is None:
        return False
    d.text(center, g, font=font(round(size)), fill=fill, anchor="mm")
    return True


def _rgb(color: str) -> tuple[int, int, int]:
    c = str(color).lstrip("#")
    if len(c) == 3:
        c = "".join(ch * 2 for ch in c)
    return tuple(int(c[i:i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]


@lru_cache(maxsize=256)
def png(name: str | None, color: str, px: int, alpha: int = 255) -> bytes | None:
    """아이콘 하나 → 투명 바탕 PNG (워드 · 파워포인트에는 아이콘 글꼴이 없으니 그림으로 넣는다).
    모르는 이름이거나 글꼴이 없으면 None. 같은 요청은 기억해 두고 다시 쓴다."""
    g = glyph(name)
    if g is None or px <= 0:
        return None
    from PIL import Image, ImageDraw
    mask = Image.new("L", (px, px), 0)
    ImageDraw.Draw(mask).text((px / 2, px / 2), g, font=font(px), fill=max(0, min(255, alpha)), anchor="mm")
    img = Image.new("RGBA", (px, px), _rgb(color) + (0,))
    img.putalpha(mask)
    buf = io.BytesIO()
    img.save(buf, "PNG", optimize=True)
    return buf.getvalue()
