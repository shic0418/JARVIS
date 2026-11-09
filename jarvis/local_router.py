"""로컬 명령 처리기 — Claude 토큰 없이 자주 쓰는 명령을 즉시 처리.

짧고 명확한 명령만 '문장 전체'가 패턴에 맞을 때 처리한다.
여러 동작이 섞였거나 애매하면 None 을 돌려주어 Claude 에게 넘긴다.
"""
from __future__ import annotations

import datetime as dt
import re
from typing import Callable

WEEKDAYS = "월화수목금토일"

# 끝맺음 표현 제거: "열어 줘요" → "열어"
_TAIL = re.compile(
    r"(?:\s*(?:좀|빨리|한\s*번|당장))?\s*(?:해\s*)?"
    r"(?:줘|줘요|주세요|줄래|줄래요|주라|줄\s*수\s*있어|줄\s*수\s*있어요|봐|봐요|라|줘봐|주실래요)$")
_PUNCT = re.compile(r"[\s.!?~,]+$")
# 여러 동작이 섞인 문장 → Claude
_COMPOUND = re.compile(r"(하고\s|그리고|다음에|한\s*뒤|한\s*후|해서\s|면서|열고|켜고|틀고|닫고|끄고|찾아서|보고\s|뒤에\s*\S|후에\s*\S|랑\s.*(열|켜|틀))")
_NOT_APP = re.compile(r"(컴퓨터|피씨|pc|시스템|자비스|너|화면|소리|음악|노래|영상|불|타이머|알람|파일|폴더|창|전원)$", re.I)
_SITES = {"구글": "google", "네이버": "naver", "유튜브": "youtube", "지도": "maps"}


def has_batchim(word: str) -> bool:
    w = word.strip()
    if not w:
        return False
    ch = w[-1]
    if "가" <= ch <= "힣":
        return (ord(ch) - 0xAC00) % 28 != 0
    return ch.lower() in "lmnr0136789"   # 영문/숫자 대략적 처리


def obj(word: str) -> str:
    """목적격 조사: 크롬을 / 메모장을 / 카톡을"""
    return f"{word}{'을' if has_batchim(word) else '를'}"


def normalize(text: str) -> str:
    t = _PUNCT.sub("", text.strip())
    t = re.sub(r"^(자비스|쟈비스|jarvis)\s*(야|아)?[,\s]*", "", t, flags=re.I)
    for _ in range(2):
        t = _PUNCT.sub("", _TAIL.sub("", t))
    return re.sub(r"\s+", " ", t).strip()


def parse_duration(s: str) -> int:
    total = 0
    for n, unit in re.findall(r"(\d+)\s*(시간|분|초)", s):
        total += int(n) * {"시간": 3600, "분": 60, "초": 1}[unit]
    return total


class LocalRouter:
    def __init__(self, execute: Callable[[str, dict], tuple[object, bool]], title_fn: Callable[[], str]) -> None:
        self.execute = execute       # (도구 이름, 인자) -> (결과, 오류 여부)
        self.title = title_fn
        self.handled = 0             # 로컬로 처리한 횟수 (토큰 절약)

    def unknown_reply(self) -> str:
        return ("그건 로컬 모드에서 처리할 수 없는 요청입니다. "
                "설정에서 Claude 연결을 켜시면 도와드릴 수 있습니다.")

    def try_handle(self, text: str, fallback: bool = True) -> str | None:
        """처리했으면 음성으로 읽을 답, 아니면 None (→ Claude).
        fallback=True 면 도구가 실패했을 때도 None 을 돌려 Claude 가 다시 시도하게 한다."""
        c = normalize(text)
        if not c or len(c) > 40:
            return None
        r = self._route(c, fallback)
        if r is not None:
            self.handled += 1
        return r

    # ------------------------------------------------------------------
    def _run(self, tool: str, args: dict) -> tuple[str, bool]:
        out, err = self.execute(tool, args)
        return str(out), err

    def _route(self, c: str, fallback: bool) -> str | None:
        title = self.title()
        lc = c.lower()

        # ---- 인사/짧은 대답 ----
        if re.fullmatch(r"(고마워|고맙다|고마워요|감사해|감사합니다|땡큐|thank you|thanks|수고했어|잘했어|잘했다)", lc):
            return f"별말씀을요, {title}."
        if re.fullmatch(r"(안녕|안녕하세요|하이|헬로|hello|hi|좋은 아침|굿모닝)", lc):
            h = dt.datetime.now().hour
            part = "좋은 아침입니다" if 5 <= h < 12 else "좋은 오후입니다" if h < 18 else "좋은 저녁입니다"
            return f"{part}, {title}. 무엇을 도와드릴까요?"
        if re.fullmatch(r"(됐어|됐다|아니야|아니|괜찮아|그만|취소|아무것도 아니야|없어)", c):
            return "알겠습니다."

        # ---- 타이머 (복합 문장 검사보다 먼저: '5분 후에 알려줘') ----
        m = re.fullmatch(r"(?:타이머\s*)?((?:\d+\s*(?:시간|분|초)\s*)+)(?:\s*(?:뒤에|후에|뒤|후))?"
                         r"\s*(?:알려|알람|타이머|깨워|불러)?\s*(?:맞춰|설정|해|맞춰놔)?", c)
        if m and parse_duration(m.group(1)) > 0:
            secs = parse_duration(m.group(1))
            out, err = self._run("set_timer", {"seconds": secs, "label": "타이머"})
            return out if err else f"{m.group(1).strip()} 타이머를 맞췄습니다."

        if _COMPOUND.search(c):
            return None

        # ---- 시간/날짜 ----
        if len(c) <= 15 and re.search(r"몇\s*시(?!간)|지금\s*시간|시간\s*알려|현재\s*시각", c):
            n = dt.datetime.now()
            ampm = "오전" if n.hour < 12 else "오후"
            return f"지금은 {ampm} {n.hour % 12 or 12}시 {n.minute}분입니다."
        if len(c) <= 15 and re.search(r"며칠|날짜|무슨\s*요일|몇\s*월\s*몇\s*일", c) and not re.search(r"내일|모레|어제", c):
            n = dt.datetime.now()
            return f"오늘은 {n.month}월 {n.day}일 {WEEKDAYS[n.weekday()]}요일입니다."

        # ---- 날씨 (오늘만, 내일/주말은 Claude) ----
        m = re.fullmatch(r"(?:(?:오늘|지금|현재)\s*)?(?:(\S+?)\s*)?날씨\s*(?:는|가)?\s*(?:어때|어떄|알려|어떻게\s*돼|좋아|확인)?", c)
        if m and not re.search(r"내일|모레|주말|이번\s*주|다음\s*주", c):
            loc = m.group(1)
            if loc in (None, "오늘", "지금", "현재", "바깥", "밖", "우리", "여기", "동네"):
                loc = None
            args = {"location": loc} if loc else {}
            out, err = self._run("get_weather", args)
            if err:
                return None if fallback else out
            return self._weather_speech(out)

        # ---- 볼륨 ----
        m = re.fullmatch(r"(?:볼륨|소리|음량)\s*(?:을|를)?\s*(\d{1,3})\s*(?:퍼센트|%)?\s*(?:으로|로)?\s*(?:맞춰|해|설정|조절)?", c)
        if m:
            return self._volume_speech(*self._run("volume", {"action": "set", "level": int(m.group(1))}))
        m = re.fullmatch(r"(?:볼륨|소리|음량)\s*(?:을|를)?\s*(많이\s*)?(?:좀\s*)?(?:더\s*)?(올려|키워|크게|높여|업|내려|줄여|작게|낮춰|다운)", c)
        if m:
            up = m.group(2) in ("올려", "키워", "크게", "높여", "업")
            return self._volume_speech(*self._run("volume", {"action": "up" if up else "down",
                                                             "level": 20 if m.group(1) else 10}))
        if re.fullmatch(r"(음소거(?:\s*해)?|소리\s*꺼|조용히\s*해|뮤트)", c):
            self._run("volume", {"action": "mute"})
            return "음소거했습니다."
        if re.fullmatch(r"(음소거\s*(?:해제|풀어|꺼)|소리\s*켜)", c):
            self._run("volume", {"action": "unmute"})
            return "음소거를 해제했습니다."
        if re.fullmatch(r"(?:볼륨|소리|음량)\s*(?:이|은|는)?\s*(?:몇|얼마)(?:야|이야|니|지|예요)?", c):
            return self._volume_speech(*self._run("volume", {"action": "get"}))

        # ---- 화면 밝기 ----
        m = re.fullmatch(r"(?:화면|모니터)?\s*밝기\s*(?:를|을)?\s*(\d{1,3})\s*(?:퍼센트|%)?\s*(?:으로|로)?\s*(?:맞춰|해|설정|조절)?", c)
        if m:
            return self._bright_speech(*self._run("brightness", {"action": "set", "level": int(m.group(1))}))
        m = re.fullmatch(r"(?:(?:화면|모니터)\s*(?:밝기)?|밝기)\s*(?:를|을|가)?\s*(?:좀\s*)?(?:더\s*)?(많이\s*)?(?:좀\s*)?"
                         r"(올려|높여|밝게|키워|낮춰|내려|줄여|어둡게)", c)
        if m:
            up = m.group(2) in ("올려", "높여", "밝게", "키워")
            return self._bright_speech(*self._run("brightness", {"action": "up" if up else "down",
                                                                 "level": 30 if m.group(1) else 20}))
        if re.fullmatch(r"(?:화면|모니터)?\s*밝기\s*(?:가|는)?\s*(?:몇|얼마)(?:야|이야|니|지|예요)?", c):
            return self._bright_speech(*self._run("brightness", {"action": "get"}))

        # ---- 미디어 ----
        if re.fullmatch(r"(다음\s*(?:곡|노래|트랙|영상)(?:으로)?|넘겨|스킵|skip)", lc):
            self._run("media_control", {"action": "next"})
            return "다음 곡입니다."
        if re.fullmatch(r"(이전\s*(?:곡|노래|트랙|영상)|전\s*곡|앞\s*곡)(?:으로)?", c):
            self._run("media_control", {"action": "previous"})
            return "이전 곡입니다."
        if re.fullmatch(r"(?:(?:노래|음악|영상|동영상)\s*(?:좀\s*)?(?:일시\s*정지|멈춰|정지|스톱|꺼)|일시\s*정지)", c):
            self._run("media_control", {"action": "play_pause"})
            return "멈췄습니다."
        if re.fullmatch(r"(?:(?:노래|음악|영상|동영상)\s*)?다시\s*(?:재생|틀어)|(?:노래|음악|영상)\s*재생", c):
            self._run("media_control", {"action": "play_pause"})
            return "다시 재생합니다."

        # ---- 유튜브 / 노래 ----
        m = re.fullmatch(r"(?:유튜브|youtube)\s*(?:에서)?\s*(.{1,30}?)\s*(?:을|를)?\s*(?:좀\s*)?(?:틀어|재생|재생해|보여|들려|켜)", c, re.I)
        if not m:
            m2 = re.fullmatch(r"(.{1,25}?)\s*(노래|음악|뮤비|뮤직비디오|플레이리스트)\s*(?:좀\s*)?(?:틀어|재생|재생해|들려)", c)
            q = f"{m2.group(1)} {m2.group(2)}" if m2 else None
        else:
            q = m.group(1)
        if q:
            out, err = self._run("play_youtube", {"query": q})
            if err:
                return None if fallback else out
            title_ = out.removeprefix("재생: ").strip()
            return f"{title_}, 재생합니다." if out.startswith("재생:") else "유튜브에서 찾아 재생합니다."

        # ---- 검색 ----
        m = re.fullmatch(r"(?:(구글|네이버|유튜브|지도)\s*(?:에서)?\s*)?(.{1,30}?)\s*(?:을|를)?\s*(?:좀\s*)?검색(?:해)?", c)
        if m and not re.search(r"파일|폴더", m.group(2)):
            site = _SITES.get(m.group(1) or "구글", "google")
            self._run("browser_search", {"query": m.group(2), "site": site})
            return f"{m.group(1) or '구글'}에서 {m.group(2)} 검색 결과를 열었습니다."

        # ---- 폴더 ----
        m = re.fullmatch(r"(다운로드|내\s*문서|문서|바탕\s*화면|사진|음악|동영상|비디오)\s*폴더\s*(?:좀\s*)?(?:열어|보여)", c)
        if m:
            name = m.group(1).replace(" ", "")
            out, err = self._run("open_folder", {"target": name})
            return out if err else f"{name} 폴더를 열었습니다."

        # ---- 창/화면/전원 ----
        if re.fullmatch(r"(바탕\s*화면\s*(?:보여|보기|으로)|창\s*(?:다|전부)\s*(?:내려|최소화))", c):
            self._run("window_action", {"action": "show_desktop"})
            return "바탕화면입니다."
        if re.fullmatch(r"(?:화면|컴퓨터|피씨|pc)\s*(?:잠가|잠궈|잠금|잠금해|잠가놔)", lc):
            self._run("power", {"action": "lock"})
            return "잠갔습니다."
        if re.fullmatch(r"(?:스크린\s*샷|화면\s*캡처|캡처)\s*(?:찍어|저장|해)?", c):
            out, err = self._run("save_screenshot", {})
            return out if err else "스크린샷을 사진 폴더의 Jarvis에 저장했습니다."
        if re.fullmatch(r"(?:컴퓨터|시스템|피씨|pc)\s*(?:상태|성능)\s*(?:어때|알려|확인|체크)?|(?:cpu|씨피유|메모리|램)\s*(?:사용량|상태)?\s*(?:어때|알려|확인|몇)?", lc):
            out, err = self._run("system_status", {})
            return out if err else self._status_speech(out)

        # ---- 앱 닫기 / 열기 ----
        m = re.fullmatch(r"(.{1,15}?)\s*(?:을|를)?\s*(?:좀\s*)?(?:닫아|꺼|종료|종료해|끝내)", c)
        if m and not _NOT_APP.search(m.group(1).strip()) and len(m.group(1).split()) <= 2:
            name = m.group(1).strip()
            out, err = self._run("close_app", {"name": name})
            if err:
                return f"열려 있는 {name} 창이 없습니다." if "열린 창이 없" in out else (None if fallback else out)
            return f"{obj(name)} 닫았습니다."
        m = re.fullmatch(r"(.{1,20}?)\s*(?:을|를)?\s*(?:좀\s*)?(?:열어|실행|실행해|켜)", c)
        if m and not _NOT_APP.search(m.group(1).strip()) and len(m.group(1).split()) <= 3:
            name = m.group(1).strip()
            out, err = self._run("open_app", {"name": name})
            if err:
                return None if fallback else out
            return f"{obj(name)} 열었습니다."
        return None

    # ------------------------------------------------------------------ 말하기용 요약
    @staticmethod
    def _weather_speech(out: str) -> str:
        m = re.search(r"^(.+?): (.+?), 기온 (-?\d+)°C \(체감 (-?\d+)°C\).*?최고 (-?\d+)°C / 최저 (-?\d+)°C, 강수확률 최대 (\d+)%", out)
        if not m:
            return out
        loc, desc, t, feel, hi, lo, rain = m.groups()
        desc = _WEATHER_KO.get(desc.strip().lower(), desc)
        s = f"지금 {desc}, 기온은 {t}도이고 체감 {feel}도입니다. 오늘 최고 {hi}도, 최저 {lo}도"
        s += f", 비 올 확률은 {rain}퍼센트입니다." if int(rain) >= 30 else "입니다."
        return s

    @staticmethod
    def _volume_speech(out: str, err: bool = False) -> str:
        if err:
            return out
        m = re.search(r"→\s*(\d+)%", out)
        if m:
            return f"볼륨을 {m.group(1)}퍼센트로 맞췄습니다."
        m = re.search(r"현재 볼륨 (\d+)%", out)
        if m:
            return f"현재 볼륨은 {m.group(1)}퍼센트입니다." + (" 음소거 상태입니다." if "음소거" in out else "")
        return out.replace("%", "퍼센트")

    @staticmethod
    def _bright_speech(out: str, err: bool = False) -> str:
        if err:
            return out
        m = re.search(r"→\s*(\d+)%", out)
        if m:
            return f"화면 밝기를 {m.group(1)}퍼센트로 맞췄습니다."
        m = re.search(r"현재 밝기 (\d+)%", out)
        return f"현재 화면 밝기는 {m.group(1)}퍼센트입니다." if m else out.replace("%", "퍼센트")

    @staticmethod
    def _status_speech(out: str) -> str:
        cpu = re.search(r"CPU (\d+)%", out)
        mem = re.search(r"메모리 (\d+)%", out)
        bat = re.search(r"배터리 (\d+)%", out)
        parts = []
        if cpu:
            parts.append(f"CPU {cpu.group(1)}퍼센트")
        if mem:
            parts.append(f"메모리 {mem.group(1)}퍼센트")
        if bat:
            parts.append(f"배터리 {bat.group(1)}퍼센트")
        s = ", ".join(parts) + "입니다."
        if mem and int(mem.group(1)) >= 85:
            s += " 메모리가 꽤 빠듯합니다."
        return s


_WEATHER_KO = {
    "sunny": "맑고", "clear": "맑고", "partly cloudy": "구름 조금 있고", "cloudy": "흐리고",
    "overcast": "잔뜩 흐리고", "mist": "안개가 끼었고", "fog": "안개가 짙고",
    "patchy rain nearby": "곳에 따라 비가 오고", "patchy rain possible": "비가 올 수 있고",
    "light rain": "약한 비가 오고", "light drizzle": "이슬비가 오고", "moderate rain": "비가 오고",
    "heavy rain": "비가 많이 오고", "light rain shower": "가벼운 소나기가 오고",
    "patchy light rain": "가끔 약한 비가 오고", "light snow": "눈이 조금 오고", "moderate snow": "눈이 오고",
    "heavy snow": "눈이 많이 오고", "thundery outbreaks possible": "천둥 번개 가능성이 있고",
    "patchy snow possible": "눈이 올 수 있고", "blizzard": "눈보라가 치고",
}
