"""카드뉴스 · 포스터 (design.py · tools.py 의 make_cardnews / make_poster) — 화면 클릭 없이 그림으로 바로 만든다."""
import re
import time

import pytest

from jarvis import design, office
from jarvis import tools as T

pytest.importorskip("PIL")
from PIL import Image, ImageDraw  # noqa: E402

try:
    design.font_file()
except ValueError:
    pytest.skip("한글 글꼴이 없다", allow_module_level=True)

CARDS = [
    {"title": "분리배출이 왜 중요할까", "bullets": ["재활용률을 높인다", "- 플라스틱은 깨끗이 씻어서", "매립 쓰레기를 줄인다"],
     "highlight": "제대로 버리면 70%가 다시 쓰인다"},
    {"title": "헷갈리는 것들", "bullets": "영수증은 일반 쓰레기\n깨진 유리는 신문지에 싸서"},
    "글자만 준 카드",
]


def pages(pdf) -> int:
    return len(re.findall(rb"/Type\s*/Page\b", pdf.read_bytes()))


def colours(path) -> int:
    with Image.open(path) as im:
        return len(im.convert("RGB").getcolors(1 << 22) or [])


def draw():
    return ImageDraw.Draw(Image.new("RGB", (10, 10)))


# ---------------------------------------------------------------- 글 배치
def test_korean_wraps_at_spaces_and_breaks_long_words_by_letter():
    d, f = draw(), design._font("regular", 40)
    text = "기후 변화는 우리 모두의 문제입니다 지금 행동해야 합니다"
    lines = design.wrap(d, text, f, 300)
    assert len(lines) > 1 and " ".join(lines) == text                        # 낱말 중간에서 끊지 않는다
    assert all(d.textlength(x, font=f) <= 300 for x in lines)
    long = design.wrap(d, "가" * 40, f, 300)
    assert len(long) > 1 and "".join(long) == "가" * 40 and all(d.textlength(x, font=f) <= 300 for x in long)


def test_text_shrinks_to_fit_and_is_cut_with_an_ellipsis_only_when_it_must():
    d = draw()
    f, lines, size = design.fit(d, "짧은 제목", "bold", 800, 200, 100, 40)
    assert size == 100 and lines == ["짧은 제목"]
    f, lines, size = design.fit(d, "조금 긴 제목이라서 한 줄에는 다 들어가지 않는다", "bold", 600, 400, 100, 40)
    assert 40 <= size < 100 and "".join(lines).replace(" ", "") == "조금긴제목이라서한줄에는다들어가지않는다"
    f, lines, size = design.fit(d, "아주 긴 문장 " * 60, "regular", 600, 200, 60, 30, max_lines=3)
    assert size == 30 and len(lines) == 3 and lines[-1].endswith("…")
    assert all(d.textlength(x, font=f) <= 600 for x in lines)


# ---------------------------------------------------------------- 카드뉴스
def test_cardnews_has_cover_cards_closing_and_one_pdf(tmp_path):
    started = time.perf_counter()
    info = design.build_cardnews(tmp_path / "분리배출", "분리배출 제대로 하기", CARDS, subtitle="우리 반 환경 캠페인",
                                 closing="함께 실천해요\n월요일마다 점검합니다",
                                 sources=["환경부 — https://www.me.go.kr/%EC%9E%90%EB%A3%8C"])
    took = time.perf_counter() - started
    files = sorted((tmp_path / "분리배출").glob("*.png"))
    assert info["cards"] == len(CARDS) + 2 == len(files) and info["files"] == files
    assert [f.name for f in files] == ["01.png", "02.png", "03.png", "04.png", "05.png"]
    for f in files:
        with Image.open(f) as im:
            assert im.size == (design.CARD, design.CARD)
        assert colours(f) > 50                                               # 글자 · 도형이 실제로 그려졌다
    assert info["pdf"] == tmp_path / "분리배출" / "분리배출.pdf" and pages(info["pdf"]) == len(files)
    assert took < 15                                                         # 화면을 조작하는 것보다 훨씬 빠르다


def test_rebuilding_the_same_cardnews_leaves_no_stale_cards(tmp_path):
    folder = tmp_path / "카드"
    design.build_cardnews(folder, "처음", CARDS * 3)
    design.build_cardnews(folder, "다시", CARDS[:1])
    assert sorted(p.name for p in folder.iterdir()) == ["01.png", "02.png", "03.png", "카드.pdf"]


@pytest.mark.parametrize("theme", sorted(office.THEMES))
def test_every_theme_paints_cover_cards_and_closing_in_its_own_colours(tmp_path, theme):
    th = office.THEMES[theme]
    files = design.build_cardnews(tmp_path / theme, "테마", CARDS[:1], theme=theme)["files"]
    for f, colour in zip(files, (th.accent, th.bg, th.surface)):
        with Image.open(f) as im:
            assert im.convert("RGB").getpixel((5, 5)) == design._rgb(colour)


def test_unknown_theme_falls_back_and_long_text_never_breaks_the_card(tmp_path):
    long = "아주 길게 늘어지는 설명 문장이 계속 이어진다 " * 12
    info = design.build_cardnews(tmp_path / "긴 글", "제목도 " * 30, [{"title": "카드 제목 " * 15, "bullets": [long] * 8,
                                                                     "highlight": long}], theme="없는테마")
    assert info["cards"] == 3
    with Image.open(info["files"][0]) as im:
        assert im.convert("RGB").getpixel((5, 5)) == design._rgb(office.THEMES["light"].accent)


@pytest.mark.parametrize("title, cards, msg", [("", CARDS, "제목"), ("제목", [], "하나 이상"), ("제목", "카드", "하나 이상"),
                                               ("제목", ["x"] * 13, "12장 이하")])
def test_cardnews_input_errors_are_clear(tmp_path, title, cards, msg):
    with pytest.raises(ValueError, match=msg):
        design.build_cardnews(tmp_path / "x", title, cards)


# ---------------------------------------------------------------- 포스터
def test_poster_is_an_a4_png_and_a_printable_pdf(tmp_path):
    info = design.build_poster(tmp_path / "축제.png", "2026 가을 축제", [
        {"heading": "일시", "bullets": ["11월 20일 (금)", "오후 1시 ~ 5시"]},
        {"heading": "장소", "bullets": ["학교 운동장"]},
        {"heading": "프로그램", "bullets": ["공연", "먹거리 장터", "체험 부스"]},
        "글자만 준 구역"], subtitle="모두 함께 즐겨요", highlight="입장 무료 · 누구나 환영", footer="학생회",
        sources=["https://example.kr/a"], theme="warm")
    assert info["sections"] == 4 and info["size"] == design.A4 and info["pdf"] == tmp_path / "축제.pdf"
    with Image.open(tmp_path / "축제.png") as im:
        assert im.size == design.A4
        assert im.convert("RGB").getpixel((5, 5)) == design._rgb(office.THEMES["warm"].accent)
    assert colours(tmp_path / "축제.png") > 50 and pages(info["pdf"]) == 1


def test_a3_poster_is_bigger_and_bad_input_is_explained(tmp_path):
    info = design.build_poster(tmp_path / "큰.png", "큰 포스터", [], highlight="강조 문구만 있어도 된다", size="A3")
    assert info["size"] == (round(1240 * 1.4142), round(1754 * 1.4142)) and info["sections"] == 0
    with Image.open(tmp_path / "큰.png") as im:
        assert im.size == info["size"]
    with pytest.raises(ValueError, match="내용"):
        design.build_poster(tmp_path / "x.png", "제목", [])
    with pytest.raises(ValueError, match="6개 이하"):
        design.build_poster(tmp_path / "x.png", "제목", ["a"] * 7)
    with pytest.raises(ValueError, match="제목"):
        design.build_poster(tmp_path / "x.png", " ", ["a"])


# ---------------------------------------------------------------- 배치 · 스타일 · 아이콘
def norm(card, i=1):
    return design._norm_card(card, i)


@pytest.mark.parametrize("card, layout", [
    ({"title": "수면 시간 평균 6.5시간"}, "stat"),
    ({"title": "청소년", "highlight": "수면 부족 비율 72%"}, "stat"),
    ({"title": "핵심", "number": "85%", "caption": "만족"}, "stat"),
    ({"title": "습관", "bullets": ["일찍 자기", "화면 끄기", "물 마시기"]}, "steps"),
    ({"title": "숙면 방법", "bullets": ["일정하게 잔다", "카페인을 줄인다", "햇볕을 쬔다"]}, "steps"),
    ({"title": "원인", "bullets": ["카페인 섭취", "늦은 취침", "스마트폰"]}, "list"),
    ({"title": "장단점", "bullets": ["✕ 늦게 잔다", "○ 일찍 잔다"]}, "compare"),
    ({"title": "커피 vs 물", "bullets": ["달다 vs 담백하다", "각성 vs 수분"]}, "compare"),
    ({"title": "비교", "left": {"title": "전", "items": ["a"]}, "right": {"title": "후", "items": ["b"]}}, "compare"),
    ({"title": "한마디", "bullets": ["“잠은 보약이라는 말은 사실입니다” — 의사"]}, "quote"),
    ({"title": "한마디", "quote": "짧은 말", "by": "나"}, "quote"),
    ({"title": "한 줄", "bullets": ["하나만 있다"]}, "point"),
    ({"title": "여럿", "bullets": ["길고 긴 설명 문장이 계속 이어지는 항목입니다 " * 3] * 4}, "point"),
    ({"title": "명시", "layout": "list", "bullets": ["하나"]}, "list"),
    ({"title": "별칭", "layout": "Number", "number": "3배"}, "stat"),
])
def test_layout_is_picked_from_content_when_missing(card, layout):
    assert norm(card)["layout"] == layout


def test_stat_splits_number_and_unit_and_compare_accepts_left_right_or_bullets():
    c = norm({"title": "하루 평균 수면 6.5시간"})
    assert (c["number"], c["unit"], c["title"]) == ("6.5", "시간", "하루 평균 수면")
    c = norm({"title": "x", "number": "72%"})
    assert (c["number"], c["unit"]) == ("72", "%")
    c = norm({"title": "x", "left": "나쁨", "right": ["좋음1", "좋음2"]})
    assert c["left"]["items"] == ["나쁨"] and c["right"]["items"] == ["좋음1", "좋음2"] and c["layout"] == "compare"
    c = norm({"title": "습관", "bullets": ["✕ 늦게 잔다", "✕ 폰을 본다", "○ 일찍 잔다", "○ 책을 읽는다"]})
    assert [len(c["left"]["items"]), len(c["right"]["items"])] == [2, 2]


@pytest.mark.parametrize("bad", [
    {"title": "이상한", "layout": "없는배치", "bullets": ["a", "b"]},
    {"title": "숫자 없음", "layout": "stat", "bullets": ["a"]},
    {"title": "비교 없음", "layout": "compare", "bullets": ["a"]},
    {"title": "내용 없음", "layout": "steps"},
    {"title": "인용 없음", "layout": "quote"},
    {"title": "엉뚱한 값", "layout": 7, "number": 12, "left": 5, "right": None, "quote": None, "icon": "no_such_icon", "bullets": None},
    {"title": "", "bullets": [1, 2, 3]},
    {"title": "겹침", "left": {"title": "L"}, "right": {"items": 5}},
])
def test_unknown_or_unusable_layout_falls_back_and_never_crashes(tmp_path, bad):
    info = design.build_cardnews(tmp_path / "x", "제목", [bad, "글자만"])
    assert info["cards"] == 4 and info["layouts"][0] in design.LAYOUTS and info["layouts"][1] == "point"


LAYOUT_CARDS = [
    {"title": "큰 숫자", "number": "72", "unit": "%", "caption": "청소년 수면 부족"},
    {"title": "목록", "layout": "list", "bullets": ["첫째: 설명이 붙는다", "둘째", "셋째", "넷째"], "highlight": "마무리 한 줄"},
    {"title": "단계", "layout": "steps", "bullets": ["하나", "둘", "셋"]},
    {"title": "비교", "left": {"title": "Before", "items": ["a", "b"]}, "right": {"title": "After", "items": ["c", "d"]}},
    {"title": "인용", "quote": "잠은 하루를 살아내는 힘이다", "by": "누군가"},
    {"title": "포인트", "bullets": ["하나만"], "icon": "bedtime"},
]


@pytest.mark.parametrize("style", design.STYLES)
def test_every_layout_renders_in_every_style(tmp_path, style):
    info = design.build_cardnews(tmp_path / style, "스타일", LAYOUT_CARDS, subtitle="부제", closing="끝\n한 줄 더",
                                 sources=["https://a.kr"], theme="teal", style=style)
    assert info["style"] == style and info["layouts"] == ["stat", "list", "steps", "compare", "quote", "point"]
    assert pages(info["pdf"]) == len(LAYOUT_CARDS) + 2
    for f in info["files"]:
        assert colours(f) > 50


def test_styles_look_different_and_unknown_style_means_clean(tmp_path):
    def card_png(style):
        d = design.build_cardnews(tmp_path / f"s_{style}", "제목", CARDS[:1], style=style)
        with Image.open(d["files"][1]) as im:
            return im.convert("RGB").tobytes()
    seen = {s: card_png(s) for s in design.STYLES}
    assert len(set(seen.values())) == len(design.STYLES)
    assert card_png("없는스타일") == seen["clean"]
    with Image.open(tmp_path / "s_bold" / "02.png") as im:                  # bold: 위에 진한 색 띠
        assert im.convert("RGB").getpixel((540, 40)) == design._rgb(office.THEMES["light"].accent)
    with Image.open(tmp_path / "s_gradient" / "02.png") as im:              # gradient: 위와 아래 색이 다르다
        im = im.convert("RGB")
        assert im.getpixel((540, 5)) != im.getpixel((540, 1070))


@pytest.mark.parametrize("theme", sorted(office.THEMES))
def test_gradient_text_colour_is_readable_on_both_ends_for_every_theme(theme):
    P = design._pal(office.THEMES[theme], "gradient")
    for end in P.grad:
        assert design._contrast(P.title, end) >= 3.0


def test_icons_are_respected_and_not_repeated_across_the_deck(tmp_path, monkeypatch):
    seen = []
    orig = design.Pen.icon

    def spy(self, name, *a, **k):
        seen.append(name)
        return orig(self, name, *a, **k)

    monkeypatch.setattr(design.Pen, "icon", spy)
    design.build_cardnews(tmp_path / "ic", "수면 캠페인", [
        {"title": "수면 부족", "bullets": ["잠을 못 잔다", "짧다", "졸리다"]},
        {"title": "수면 습관", "bullets": ["잠을 일찍 잔다", "좋다", "쉽다"]},
        {"title": "직접 고른", "bullets": ["하나", "둘"], "icon": "Local Cafe"},
    ])
    assert "local_cafe" in seen                                                # 준 이름은 그대로 (대소문자 · 띄어쓰기 달라도)
    badges = [n for n in seen if n not in ("close", "check_circle")]
    sleep_like = [n for n in badges if n == "bedtime"]
    assert len(sleep_like) <= 2                                                # '수면' 두 카드가 같은 아이콘을 거듭 쓰지 않는다 (카드 머리 + 표지 정도)
    assert len(set(badges)) >= 4


def test_translucent_text_icons_and_shapes_really_blend():
    p = design.Pen(100, 100, 2, (255, 255, 255))
    p.text((10, 10), "가나다", p.font("black", 60), (0, 0, 0), a=0.4)
    p.icon("bedtime", (50, 50), 60, (0, 0, 0), a=0.4)
    p.rect((0, 90, 100, 100), (0, 0, 0), a=0.5)
    shades = {v for _, v in p.img.convert("L").getcolors(1 << 20)}
    assert 60 <= min(shades) < 200                                            # 완전 검정이 아니라 ~40% 농도로 섞였다
    assert abs(p.img.getpixel((10, 190))[0] - 127) <= 1                        # 50% 반투명 띠


def test_text_never_leaves_its_box_even_when_squeezed():
    d = draw()
    for text in ("한" * 300, "단어 " * 80, "A" * 120 + " 끝"):
        f, lines, size = design.fit(d, text, "bold", 400, 120, 90, 24, max_lines=3)
        assert len(lines) <= 3 and all(d.textlength(x, font=f) <= 400 for x in lines)
    f, lines, size = design.fit(d, "오늘은 정말 날씨가 좋아서 산책을 갑니다", "bold", 420, 400, 60, 30)
    assert len(lines) >= 2 and len(lines[-1]) > 2                              # 마지막 줄에 한두 글자만 남지 않게 고르게 나눈다


def test_long_text_in_every_layout_stays_in_the_card_and_does_not_crash(tmp_path):
    long = "아주 길게 늘어지는 설명 문장이 계속 이어진다 " * 10
    cards = [{"title": long, "layout": lay, "bullets": [long] * 7, "highlight": long, "quote": long, "by": long, "number": "123456789012",
              "unit": "시간" * 8, "caption": long, "left": {"title": long, "items": [long] * 5}, "right": {"title": long, "items": [long] * 5}}
             for lay in design.LAYOUTS]
    for style in design.STYLES:
        info = design.build_cardnews(tmp_path / f"long_{style}", long, cards, subtitle=long, closing=long + chr(10) + long,
                                     sources=[long] * 5, style=style)
        assert info["cards"] == len(design.LAYOUTS) + 2
    info = design.build_cardnews(tmp_path / "long_clean", long, cards, subtitle=long, sources=[long] * 5, style="clean")
    for f in info["files"][1:-1]:                                              # 오른쪽 바깥 여백(1000~1080)에는 글이 번지지 않는다
        with Image.open(f) as im:
            assert len(im.convert("RGB").crop((1000, 330, 1080, 940)).getcolors(1 << 16) or []) <= 6


def test_poster_styles_info_strip_and_sections(tmp_path):
    secs = [{"heading": "일시", "bullets": ["11월 20일", "오후 1시"]}, {"heading": "장소", "bullets": ["운동장"]},
            {"heading": "프로그램", "bullets": ["공연", "장터"]}, {"heading": "유의", "text": "우천 시 체육관"}]
    out = {}
    for st in design.STYLES:
        info = design.build_poster(tmp_path / f"{st}.png", "축제", secs, subtitle="부제", highlight="무료", footer="학생회",
                                   sources=["https://a.kr"], theme="green", style=st)
        assert info["sections"] == 4 and info["info"] == 2 and info["style"] == st and pages(info["pdf"]) == 1
        with Image.open(tmp_path / f"{st}.png") as im:
            assert im.size == design.A4
            out[st] = im.convert("RGB").tobytes()
    assert len(set(out.values())) == 4
    given = design.build_poster(tmp_path / "i.png", "행사", ["내용"], info=[{"icon": "event", "label": "일시", "text": "11/20"},
                                                                       {"label": "장소", "text": "강당"}, "무료 입장"])
    assert given["info"] == 3 and given["sections"] == 1
    only = design.build_poster(tmp_path / "o.png", "하나", [{"heading": "일시", "bullets": ["오늘"]}])
    assert only["info"] == 0 and only["sections"] == 1                         # 구역이 하나뿐이면 띠로 빼지 않고 구역으로 둔다


def test_poster_header_icon_and_a3_with_a_style(tmp_path):
    info = design.build_poster(tmp_path / "a3.png", "긴 제목 " * 20, ["a"] * 6, subtitle="부제 " * 40, size="a3", style="pastel",
                               icon="rocket_launch")
    assert info["size"] == (round(1240 * 1.4142), round(1754 * 1.4142)) and colours(tmp_path / "a3.png") > 50


def test_pretendard_is_preferred_and_malgun_is_the_fallback(monkeypatch):
    assert design.font_file("regular").name == "Pretendard-Regular.otf"
    assert design.font_file("black").name == "Pretendard-Black.otf"
    malgun, malgun_bd = design._WIN / "malgun.ttf", design._WIN / "malgunbd.ttf"
    if malgun.exists() and malgun_bd.exists():
        monkeypatch.setattr(design, "_FONTS", {"regular": [malgun], "bold": [malgun_bd]})
        assert design.font_file("black").name == "malgunbd.ttf" and design.font_file("semibold").name == "malgunbd.ttf"


def test_fonts_are_cached():
    assert design._font("bold", 40.2) is design._font("bold", 40.9)


# ---------------------------------------------------------------- 도구 (tools.py)
@pytest.fixture
def pc(tmp_path, monkeypatch):
    me = T.PCTools.__new__(T.PCTools)
    folders = {"문서": tmp_path / "docs", "바탕화면": tmp_path / "desk"}
    monkeypatch.setattr(T.winutil, "known_folder", lambda name: folders.get(name.replace(" ", "")))
    me.opened = []
    monkeypatch.setattr(T.os, "startfile", lambda p: me.opened.append(p), raising=False)
    return me


def test_make_cardnews_saves_one_folder_and_opens_it(pc, tmp_path):
    msg = pc.t_make_cardnews(title="분리배출", cards=CARDS, subtitle="캠페인")
    folder = tmp_path / "docs" / "JARVIS" / "분리배출 카드뉴스"
    assert sorted(p.name for p in folder.iterdir()) == [f"0{i}.png" for i in range(1, 6)] + ["분리배출 카드뉴스.pdf"]
    assert pc.opened == [str(folder)]
    assert "카드뉴스를 만들었습니다 — 5장" in msg and "문서의 JARVIS 폴더 안의 '분리배출 카드뉴스' 폴더" in msg
    again = pc.t_make_cardnews(title="분리배출", cards=CARDS[:1], open=False)
    assert "'분리배출 카드뉴스 (2)' 폴더" in again and len(list(folder.glob("*.png"))) == 5      # 예전 것을 지우지 않는다
    pc.t_make_cardnews(title="분리배출", cards=CARDS[:1], overwrite=True, open=False)
    assert len(list(folder.glob("*.png"))) == 3                                                # 고치라면 같은 폴더를 새로 채운다


def test_make_poster_saves_png_and_pdf_and_opens_the_picture(pc, tmp_path):
    msg = pc.t_make_poster(title="가을 축제", sections=[{"heading": "일시", "bullets": ["11월 20일"]}], size="a3",
                           folder="바탕화면")
    png = tmp_path / "desk" / "가을 축제.png"
    assert png.exists() and png.with_suffix(".pdf").exists() and pc.opened == [str(png)]
    assert "포스터를 만들었습니다 — A3 세로, 구역 1개" in msg and "저장한 곳: 바탕화면 " in msg


def test_missing_korean_font_or_pillow_is_explained(pc, monkeypatch):
    monkeypatch.setattr(design, "_FONTS", {"regular": [], "bold": []})
    monkeypatch.setattr(design, "_CACHE", {})
    with pytest.raises(T.ToolError, match="맑은 고딕"):
        pc.t_make_poster(title="x", sections=["a"])

    def no_pillow(*a, **k):
        raise ModuleNotFoundError("No module named 'PIL'", name="PIL")

    monkeypatch.setattr(design, "build_cardnews", no_pillow)
    with pytest.raises(T.ToolError, match="Pillow.*setup.bat"):
        pc.t_make_cardnews(title="x", cards=["a"])


def test_design_tools_are_described_for_claude_with_labels():
    schemas = {d["name"]: d for d in T.PCTools.schemas(T.PCTools.__new__(T.PCTools))}
    assert schemas["make_cardnews"]["input_schema"]["required"] == ["title", "cards"]
    assert schemas["make_poster"]["input_schema"]["required"] == ["title", "sections"]
    for name in ("make_cardnews", "make_poster"):
        assert set(schemas[name]["input_schema"]["properties"]["theme"]["enum"]) == set(office.THEMES)
        assert len(schemas[name]["description"]) > 80
    assert T.PCTools.label("make_cardnews", {"title": "분리배출"}) == "카드뉴스 만들기 · 분리배출"
    assert T.PCTools.label("make_poster", {"title": "축제"}) == "포스터 만들기 · 축제"
