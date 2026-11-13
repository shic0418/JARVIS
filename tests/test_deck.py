"""발표 자료의 디자인 (deck.py · office.py 의 스타일 고르기) — 스타일 7가지 · 장 형식 12가지 · 번호 줄 · 줄 수 어림."""
import pytest

from jarvis import office

pptx = pytest.importorskip("pptx")
from jarvis import deck as D  # noqa: E402

LONG = "아주 길게 늘어지는 설명 문장이 계속 이어져서 한 줄에는 도저히 들어가지 않는 경우"
FULL = [
    {"layout": "section", "title": "1. 광합성이란?", "bullets": ["식물이 스스로 양분을 만드는 방법"], "notes": "첫 부분."},
    {"title": "재료와 결과", "bullets": ["재료: 이산화탄소, 물, 빛에너지", "결과물: 포도당과 산소", "장소: 엽록체"], "notes": "설명."},
    {"layout": "process", "title": "이렇게 일어난다", "steps": [{"title": "빛 흡수", "text": "엽록소가 햇빛을 붙잡는다"},
                                                           {"title": "물 분해", "text": "산소가 나온다"},
                                                           {"title": "포도당 합성", "text": "이산화탄소로 포도당을 만든다"},
                                                           {"title": "저장 · 이동", "text": LONG}]},
    {"layout": "two_column", "title": "명반응과 암반응", "left": {"heading": "명반응", "bullets": ["빛이 필요하다", "산소가 나온다"]},
     "right": {"heading": "암반응", "bullets": ["빛이 없어도 된다", "포도당이 만들어진다"]}},
    {"layout": "stats", "title": "숫자로 보기", "stats": [{"value": "70%", "label": "바다 식물이 만드는 산소"},
                                                       {"value": "1~2%", "label": "식물이 쓰는 햇빛"}, {"value": "1,200억 톤", "label": LONG}]},
    {"layout": "chart", "title": "빛과 광합성량", "bullets": ["빛이 셀수록 늘다가 일정해진다"],
     "chart": {"type": "line", "categories": ["약함", "보통", "강함"], "series": [{"name": "광합성량", "values": [12, 31, 48]}]}},
    {"layout": "cards", "title": "영향을 주는 것", "cards": [{"title": "빛의 세기", "text": "셀수록 활발하다"},
                                                          {"title": "이산화탄소 농도", "text": LONG}, {"title": "온도", "text": "35도쯤"}]},
    {"layout": "cards", "title": "여섯 가지", "cards": [{"title": f"카드 {i}", "text": "짧은 설명"} for i in range(1, 7)]},
    {"layout": "timeline", "title": "연구의 역사", "events": [{"when": "1771", "title": "프리스틀리", "text": "식물이 공기를 맑게 한다"},
                                                           {"when": "1779", "title": "잉엔하우스", "text": "빛이 있어야 한다"},
                                                           {"when": "1961년 12월", "title": "캘빈", "text": LONG}]},
    {"layout": "table", "title": "광합성과 호흡", "table": {"columns": ["구분", "광합성", "호흡"],
                                                         "rows": [["곳", "엽록체", "미토콘드리아"], ["필요한 것", "빛 · 물", "포도당 · 산소"]]}},
    {"layout": "highlight", "title": "핵심", "statement": "광합성은 지구 모든 생명의 밥상을 차리는 일이다", "detail": "음식과 산소가 여기서 온다"},
    {"layout": "quote", "title": "인용", "quote": "자연은 서두르지 않지만 모든 것을 이룬다.", "by": "노자"},
    {"title": "긴 목록", "bullets": ["먹이사슬의 출발점: 모든 생물의 에너지", "- 초식 동물도 육식 동물도 식물에 기댄다", "산소 공급", "기후 조절",
                                  "- 숲이 줄면 온난화가 빨라진다", "화석 연료도 광합성의 결과다"]},
    {"layout": "closing", "title": "감사합니다", "bullets": ["질문 있으신가요?"]},
]


def texts(slide) -> str:
    return "\n".join(sh.text_frame.text for sh in slide.shapes if sh.has_text_frame)


def build(tmp_path, style, slides=FULL, theme="", title="식물의 요리법, 광합성이라는 아주 긴 제목이 들어가도 괜찮다"):
    path = tmp_path / f"{style}.pptx"
    theme = theme or office.pick_theme("", style, title)
    info = office.build_presentation(path, title, slides, "중학교 2학년 과학 발표",
                                     [f"자료 {i} — https://example.kr/{'x' * 50}" for i in range(12)], theme, None, style)
    return pptx.Presentation(str(path)), info


# ---------------------------------------------------------------- 스타일
@pytest.mark.parametrize("style", office.STYLES)
def test_every_style_draws_every_layout_inside_the_slide(tmp_path, style):
    from pptx.enum.shapes import MSO_SHAPE, MSO_SHAPE_TYPE
    prs, info = build(tmp_path, style)
    slides = list(prs.slides)
    assert info["style"] == style and info["slides"] == len(slides)
    assert len(slides) in (1 + 1 + len(FULL) + 1, 1 + 1 + len(FULL) + 2)       # 표지 · 목차 · 본문 · 참고 자료 (좁은 칸에서는 두 장)
    W_, H_ = prs.slide_width, prs.slide_height
    checked = charts = tables = 0
    for n, slide in enumerate(slides, 1):
        for sh in slide.shapes:
            if sh.shape_type == MSO_SHAPE_TYPE.AUTO_SHAPE and sh.auto_shape_type == MSO_SHAPE.OVAL:
                continue                                                         # 장식 원은 일부러 가장자리에 걸친다
            assert sh.left >= 0 and sh.top >= -1 and sh.left + sh.width <= W_ + 1 and sh.top + sh.height <= H_ + 1, (style, n, sh.name)
            checked += 1
            charts += bool(getattr(sh, "has_chart", False) and sh.has_chart)
            tables += bool(getattr(sh, "has_table", False) and sh.has_table)
    assert checked > 150 and charts == 1 and tables == 1
    everything = "\n".join(texts(s) for s in slides)
    for word in ("목차", "광합성이란?", "빛 흡수", "명반응", "70%", "이산화탄소 농도", "카드 6", "프리스틀리", "1961년 12월",
                 "지구 모든 생명의 밥상", "— 노자", "감사합니다", "참고 자료"):
        assert word in everything, (style, word)
    assert "1. 광합성이란?" not in everything                                     # 장 구분의 번호는 떼고 디자인이 그린다
    assert [s.notes_slide.notes_text_frame.text for s in slides if s.has_notes_slide] == ["첫 부분.", "설명."]


def test_styles_really_look_different(tmp_path):
    """같은 내용이라도 스타일마다 표지와 본문 장의 도형 배치가 다르다."""
    covers, pages = {}, {}
    for style in office.STYLES:
        prs, _ = build(tmp_path, style, theme="light")
        slides = list(prs.slides)
        covers[style] = tuple((sh.shape_type, sh.left, sh.top, sh.width, sh.height) for sh in slides[0].shapes)
        pages[style] = tuple((sh.shape_type, sh.left, sh.top, sh.width, sh.height) for sh in slides[3].shapes)
    assert len(set(covers.values())) == len(office.STYLES) and len(set(pages.values())) == len(office.STYLES)
    wide, narrow = D.Deck.AREA["clean"], D.Deck.AREA["side"]
    assert narrow[0] > wide[0] + 3 and narrow[2] < wide[2] - 3                   # 사이드바 스타일은 본문 칸이 오른쪽으로 좁다


@pytest.mark.parametrize("style", office.STYLES)
def test_korean_fonts_follow_the_schema_in_every_style(tmp_path, style):
    prs, _ = build(tmp_path, style)
    order = ["latin", "ea", "cs"]
    runs = 0
    for slide in prs.slides:
        for el in slide._element.iter():
            if el.tag.split("}")[1] != "rPr":
                continue
            fonts = [c.tag.split("}")[1] for c in el if c.tag.split("}")[1] in order]
            assert fonts == order, (style, fonts)                                # 순서: latin → ea → cs
            ea = next(c for c in el if c.tag.endswith("}ea")).get("typeface")
            assert ea in (office.FONT, D.SERIF)                                  # 한글은 늘 한글 글꼴로 (Consolas 는 영문 · 숫자만)
            runs += 1
    assert runs > 100


def test_accent_that_cannot_be_read_as_text_falls_back_to_the_title_colour():
    yellow = D.Deck(office.THEMES["mono"], "제목")
    blue = D.Deck(office.THEMES["light"], "제목")
    assert yellow.ink == office.THEMES["mono"].title and blue.ink == office.THEMES["light"].accent
    assert D.contrast("FFFFFF", "000000") == pytest.approx(21, abs=0.1) and D.contrast("FFC400", "FFFFFF") < 2.6


# ---------------------------------------------------------------- 장 형식
def test_short_lists_become_numbered_rows_and_keywords_are_bold(tmp_path):
    prs, _ = build(tmp_path, "clean", [
        {"title": "짧은 목록", "bullets": ["재료: 이산화탄소와 물", "결과물: 포도당", "설명 없는 줄"]},
        {"title": "긴 목록", "bullets": ["핵심어: 설명이 붙은 줄", "- 하위 줄", "둘째", "셋째", "넷째", "다섯째", "여섯째"]},
    ], title="줄")
    rows, plain = list(prs.slides)[1], list(prs.slides)[2]
    boxes = [sh.text_frame.text for sh in rows.shapes if sh.has_text_frame]
    for word in ("01", "02", "03", "재료", "이산화탄소와 물", "결과물", "포도당", "설명 없는 줄"):
        assert word in boxes                                                     # 번호 · 핵심어 · 설명이 각자의 칸에
    runs = [r for sh in plain.shapes if sh.has_text_frame for p in sh.text_frame.paragraphs for r in p.runs]
    bold = [r.text for r in runs if r.font.bold]
    assert "핵심어" in bold and ": 설명이 붙은 줄" in [r.text for r in runs] and "둘째" not in bold
    assert D.keyword("엽록체: 빛을 흡수하는 곳") == ("엽록체", "빛을 흡수하는 곳")
    assert D.keyword("산소 — 우리가 마시는 공기") == ("산소", "우리가 마시는 공기")
    assert D.keyword("https://a.kr 참고")[0] is None and D.keyword("비율은 3:1 이다")[0] is None
    assert D.keyword("이것은 아주 아주 아주 긴 앞부분이라 핵심어가 아니다: 설명")[0] is None


def test_new_layouts_have_their_own_shapes(tmp_path):
    from pptx.enum.shapes import MSO_SHAPE, MSO_SHAPE_TYPE
    prs, _ = build(tmp_path, "clean", title="형식")
    slides = list(prs.slides)
    by_title = {texts(s).split("\n")[0]: s for s in slides}

    def autos(slide, kind):
        return [sh for sh in slide.shapes if sh.shape_type == MSO_SHAPE_TYPE.AUTO_SHAPE and sh.auto_shape_type == kind]

    assert len(autos(by_title["이렇게 일어난다"], MSO_SHAPE.CHEVRON)) == 3      # 네 단계 사이의 화살표 셋
    table = next(sh.table for sh in by_title["광합성과 호흡"].shapes if getattr(sh, "has_table", False) and sh.has_table)
    assert len(table.rows) == 3 and len(table.columns) == 3 and table.cell(0, 1).text_frame.text == "광합성"
    assert table.cell(2, 2).text_frame.text == "포도당 · 산소"
    assert len(autos(by_title["여섯 가지"], MSO_SHAPE.ROUNDED_RECTANGLE)) == 6   # 카드 여섯 장 (2줄 × 3칸)
    timeline = texts(by_title["연구의 역사"])
    assert all(w in timeline for w in ("1771", "1779", "프리스틀리", "빛이 있어야 한다"))


def test_narrow_area_stacks_steps_and_events_downwards(tmp_path):
    """사이드바 스타일은 본문 칸이 좁다 — 단계 넷은 세로 목록으로, 사건이 많은 연표도 세로로."""
    from pptx.enum.shapes import MSO_SHAPE, MSO_SHAPE_TYPE
    years = ("1771", "1779", "1845", "1930", "1961년 12월")
    prs, _ = build(tmp_path, "side", [FULL[2], {"layout": "timeline", "title": "연구의 역사",
                                                "events": [{"when": y, "title": f"사건 {y}", "text": "한 줄 설명"} for y in years]}],
                   title="좁은 칸")
    by_title = {}
    for s in prs.slides:
        for sh in s.shapes:
            if sh.has_text_frame and sh.text_frame.text in ("이렇게 일어난다", "연구의 역사"):
                by_title[sh.text_frame.text] = s
    steps = by_title["이렇게 일어난다"]
    assert not [sh for sh in steps.shapes if sh.shape_type == MSO_SHAPE_TYPE.AUTO_SHAPE and sh.auto_shape_type == MSO_SHAPE.CHEVRON]
    tops = [sh.top for sh in steps.shapes if sh.has_text_frame and sh.text_frame.text in ("빛 흡수", "물 분해", "포도당 합성")]
    assert tops == sorted(tops) and len(set(tops)) == 3                           # 위에서 아래로
    whens = [sh for sh in by_title["연구의 역사"].shapes if sh.has_text_frame and sh.text_frame.text in years]
    assert len({sh.left for sh in whens}) == 1 and len({sh.top for sh in whens}) == 5


def test_outline_only_slides_still_make_a_deck(tmp_path):
    """작가가 쓰지 못했을 때: 개요(points)만으로도 그 형식에 맞게 그린다."""
    prs, info = build(tmp_path, "bold", [
        {"layout": "process", "title": "순서", "points": ["빛 흡수: 엽록소", "물 분해", "포도당 합성"]},
        {"layout": "timeline", "title": "역사", "points": ["1771: 프리스틀리 — 공기를 맑게", "1779 | 잉엔하우스"]},
        {"layout": "cards", "title": "종류", "points": ["명반응", "암반응"]},
        {"layout": "stats", "title": "숫자", "points": ["70% | 바다", "2배 — 증가"]},
        {"layout": "two_column", "title": "비교", "points": ["하나", "둘", "셋"]},
        {"layout": "highlight", "title": "한마디", "points": ["가장 중요한 문장", "보충"]},
        {"layout": "table", "title": "표가 없으면", "points": ["목록으로"]},
        {"layout": "timeline", "title": "하나뿐이면", "points": ["1771: 하나"]},
    ], title="개요")
    assert info["slides"] == 1 + 1 + 8 + 1
    everything = "\n".join(texts(s) for s in prs.slides)
    for word in ("빛 흡수", "엽록소", "프리스틀리", "공기를 맑게", "잉엔하우스", "암반응", "70%", "바다", "셋", "가장 중요한 문장",
                 "보충", "목록으로", "하나"):
        assert word in everything, word
    assert office.pairs(["제목: 설명", {"heading": "다른 이름", "desc": "풀이"}, "- 기호는 뗀다"]) == [
        {"title": "제목", "text": "설명"}, {"title": "다른 이름", "text": "풀이"}, {"title": "기호는 뗀다", "text": ""}]
    assert office.events(["1950년 6월: 전쟁 발발 — 새벽", {"year": 1953, "event": "휴전"}, "날짜 없음"]) == [
        {"when": "1950년 6월", "title": "전쟁 발발", "text": "새벽"}, {"when": "1953", "title": "휴전", "text": ""},
        {"when": "", "title": "날짜 없음", "text": ""}]


def test_agenda_uses_sections_only_when_there_are_several(tmp_path):
    two = [{"layout": "section", "title": "1부 · 원인"}, {"title": "가"}, {"layout": "section", "title": "Part 2: 대책"}, {"title": "나"},
           {"title": "다"}]
    prs, _ = build(tmp_path, "clean", two, title="목차")
    agenda = texts(list(prs.slides)[1]).split("\n")
    assert "원인" in agenda and "대책" in agenda and "가" not in agenda          # 장 구분이 둘 이상이면 그 제목들로 (번호는 뗀다)
    one = [{"layout": "section", "title": "원인"}, {"title": "가"}, {"title": "나"}, {"title": "다"}]
    prs, _ = build(tmp_path, "clean", one, title="목차2")
    agenda = texts(list(prs.slides)[1]).split("\n")
    assert "원인" in agenda and "가" in agenda and "다" in agenda                # 하나뿐이면 모든 장의 제목으로
    assert [office.unnumbered(t) for t in ("1. 원인", "2부 · 영향", "제3장 결론", "2026년 전망", "7")] == \
        ["원인", "영향", "결론", "2026년 전망", "7"]


# ---------------------------------------------------------------- 스타일 · 색 고르기, 줄 수 어림
def test_style_is_picked_by_request_topic_and_never_twice_in_a_row():
    assert office.pick_style("tech", "아무 제목") == "tech" and office.pick_style("귀엽게", "x") == "pastel"
    assert office.pick_style("회사 보고용", "x") == "corporate" and office.pick_style("매거진 느낌", "x") == "editorial"
    assert office.pick_style("", "우리 동네 소개", "초등학교 3학년") in ("pastel", "bold", "clean")
    assert office.pick_style("", "3분기 실적", "임원 보고") in ("corporate", "side", "clean", "bold")
    assert office.pick_style("", "인공지능의 미래") in ("tech", "side", "bold", "clean")
    assert office.pick_style("", "한국 전쟁의 원인") in ("editorial", "clean", "side", "corporate")
    plain = {office.pick_style("", f"주제 {i}") for i in range(60)}
    assert plain == {"clean", "bold", "side", "editorial", "corporate"}          # 평범한 주제에는 무난한 다섯 가지를 고루
    title = "광합성"
    first = office.pick_style("", title)
    second = office.pick_style("", title, avoid=first)
    assert first == office.pick_style("", title) and second != first             # 같은 제목은 같은 스타일, 바로 앞 것은 피한다
    assert office.pick_theme("navy", "pastel", title) == "navy"
    assert office.pick_theme("", "tech", title) in office.STYLE_THEMES["tech"] and office.pick_theme("없는색", "clean", title) in office.THEMES
    assert set(office.STYLE_THEMES) == set(office.STYLES) == set(office.STYLE_NAMES) == set(D.Deck.AREA)
    assert all(t in office.THEMES for names in office.STYLE_THEMES.values() for t in names)


def test_line_count_follows_word_wrapping():
    assert office._lines("짧은 글", 24, 5) == 1 and office._lines("", 20, 3) == 1
    assert office._lines("인위적 배출로 농도 증가", 24, 1.85) == 3               # 낱말 단위로 넘어가서 글자 수 어림(2줄)보다 많다
    assert office._lines("가" * 40, 20, 3) == 4                                   # 한 줄보다 긴 낱말은 글자 단위로
    assert office._lines("가나다 라마바", 20, 10) == 1


# ---------------------------------------------------------------- 아이콘 · 채움 · 명암
def _pictures(slide):
    from pptx.enum.shapes import MSO_SHAPE_TYPE
    return [sh for sh in slide.shapes if sh.shape_type == MSO_SHAPE_TYPE.PICTURE]


def _slide_with(prs, text):
    return next(s for s in prs.slides if text in texts(s))


@pytest.mark.parametrize("style", office.STYLES)
def test_cards_steps_and_stats_get_icons_that_do_not_repeat(tmp_path, style):
    from jarvis import icons
    if not icons.available():
        pytest.skip("아이콘 글꼴 없음")
    prs, _ = build(tmp_path, style)
    for marker, n in (("빛 흡수", 4), ("빛의 세기", 3), ("70", 3), ("프리스틀리", 3), ("카드 1", 6)):
        pics = _pictures(_slide_with(prs, marker))
        if style == "editorial" or not pics:      # 매거진은 번호가 글자 모양이라 아이콘도 글자 위치에 — 그림이 있으면 개수만 본다
            continue
        assert len(pics) >= n - 1, (style, marker, len(pics))
        blobs = [p.image.sha1 for p in pics]
        assert len(blobs) == len(set(blobs)), (style, marker)            # 한 장 안에서 같은 아이콘이 겹치지 않는다


def test_steps_start_with_flag_and_end_with_task_alt_unless_given(tmp_path, monkeypatch):
    from jarvis import icons
    if not icons.available():
        pytest.skip("아이콘 글꼴 없음")
    drawn = []
    real = icons.png.__wrapped__ if hasattr(icons.png, "__wrapped__") else icons.png
    monkeypatch.setattr(icons, "png", lambda name, *a, **k: (drawn.append(name), real(name, *a, **k))[1])
    steps = [{"title": "시작", "text": "a"}, {"title": "가운데", "text": "b"}, {"title": "끝", "text": "c"}]
    build(tmp_path, "clean", [{"layout": "process", "title": "단계", "steps": steps}])
    steps_icons = drawn[-3:]
    assert steps_icons[0] == "flag" and steps_icons[-1] == "task_alt" and len(set(steps_icons)) == 3
    drawn.clear()
    steps[-1]["icon"] = "star"
    build(tmp_path, "clean", [{"layout": "process", "title": "단계", "steps": steps}])
    assert drawn[-3:][-1] == "star" and drawn[-3:][0] == "flag"


def test_slides_and_items_accept_an_icon_and_unknown_names_fall_back(tmp_path):
    from jarvis import icons
    slides = [{"layout": "section", "title": "1. 시작", "icon": "bedtime"}, {"layout": "cards", "title": "카드",
              "cards": [{"title": "가", "icon": "rocket_launch"}, {"title": "나", "icon": "없는-아이콘"}]},
              {"layout": "closing", "title": "끝", "icon": "Local Cafe"}]
    prs, info = build(tmp_path, "clean", slides)
    assert info["slides"] >= 4
    if icons.available():
        assert _pictures(_slide_with(prs, "시작")) and _pictures(_slide_with(prs, "끝"))
        assert len(_pictures(_slide_with(prs, "카드"))) == 2


def test_everything_works_without_the_icon_font(tmp_path, monkeypatch):
    from jarvis import icons
    monkeypatch.setattr(icons, "available", lambda: False)
    monkeypatch.setattr(icons, "png", lambda *a, **k: None)
    for style in office.STYLES:
        prs, info = build(tmp_path, style)
        assert not any(_pictures(s) for s in prs.slides), style
        assert info["slides"] == len(list(prs.slides))


def test_stats_split_value_and_unit():
    assert D.Deck.split_value("72%") == ("72", "%")
    assert D.Deck.split_value("3.5시간") == ("3.5", "시간")
    assert D.Deck.split_value("1,200억 톤") == ("1,200", "억 톤")
    assert D.Deck.split_value("1~2%") == ("1~2", "%")
    assert D.Deck.split_value("약 70%") == ("약 70%", "")                # 숫자로 시작하지 않으면 그대로
    assert D.Deck.split_value("42") == ("42", "")


def test_stat_slide_shows_big_number_with_smaller_unit(tmp_path):
    prs, _ = build(tmp_path, "clean", [{"layout": "stats", "title": "숫자", "stats": [{"value": "72%", "label": "비율"},
                                                                                       {"value": "3.5시간", "label": "시간"}]}])
    s = _slide_with(prs, "비율")
    sizes = [(r.text, r.font.size.pt) for sh in s.shapes if sh.has_text_frame for p in sh.text_frame.paragraphs for r in p.runs
             if r.text in ("72", "%", "3.5", "시간")]
    big = {t: z for t, z in sizes}
    assert big["72"] > big["%"] and big["3.5"] > big["시간"]


def test_cards_fill_the_body_height_and_content_is_vertically_centred(tmp_path):
    from pptx.util import Inches
    prs, _ = build(tmp_path, "clean", [{"layout": "cards", "title": "셋", "cards": [{"title": f"제목{i}", "text": "짧다"} for i in range(3)]}])
    s = _slide_with(prs, "제목0")
    x, y, w, h = D.Deck.AREA["clean"]
    tops = [sh.top for sh in s.shapes if sh.shape_type == 1 and sh.height > Inches(2.5) and sh.width > Inches(2.5)]   # 카드 바탕
    assert tops and max(sh.height for sh in s.shapes if sh.shape_type == 1) >= Inches(h * 0.9)
    card = max((sh for sh in s.shapes if sh.shape_type == 1), key=lambda sh: sh.height)
    title = next(sh for sh in s.shapes if sh.has_text_frame and sh.text_frame.text == "제목0")
    gap_top, gap_bottom = title.top - card.top, card.top + card.height - (title.top + title.height)
    assert gap_top > Inches(0.6) and gap_bottom > Inches(0.6)           # 위 · 아래에 여유 (한쪽에 몰려 있지 않다)


def test_text_on_light_pastel_cards_keeps_readable_contrast(tmp_path):
    from pptx.dml.color import RGBColor
    for theme in office.THEMES:
        prs, _ = build(tmp_path, "pastel", [{"layout": "stats", "title": "숫자", "stats": [{"value": f"{i}0%", "label": "라벨"} for i in range(1, 5)]}], theme)
        s = _slide_with(prs, "라벨")
        fills = [sh.fill.fore_color.rgb for sh in s.shapes if sh.shape_type == 1 and sh.fill.type == 1]
        for sh in s.shapes:
            if sh.has_text_frame and sh.text_frame.text.strip():
                for p in sh.text_frame.paragraphs:
                    for r in p.runs:
                        if r.font.color and r.font.color.type is not None and r.text.strip() in ("10", "20", "30", "40"):
                            ink = str(r.font.color.rgb)
                            assert max(D.contrast(ink, str(f)) for f in fills) >= 3, (theme, ink)


def test_readable_moves_a_pale_colour_until_it_reads():
    assert D.contrast(D.Deck.readable("E2A100", "FFF0C2"), "FFF0C2") >= 3
    assert D.Deck.readable("16213A", "FFFFFF") == "16213A"             # 이미 읽히면 그대로
    assert D.contrast(D.Deck.readable("DDDDDD", "15171D"), "15171D") >= 3


def test_presentation_author_is_jarvis(tmp_path):
    prs, _ = build(tmp_path, "clean")
    assert prs.core_properties.author == "J.A.R.V.I.S"
