"""한글(HWPX) 보고서 — hwpx.py 와 make_document(format="hwpx")."""
import re
import zipfile
import xml.etree.ElementTree as ET

import pytest

from jarvis import hwpx

SECTIONS = [
    {"heading": "1. 연구 배경", "paragraphs": ["기후 변화는 **전 지구적** 문제다. <특수문자> & \"따옴표\"도 그대로."]},
    {"heading": "세부 원인", "level": 2, "bullets": ["• 화석 연료", "- 석탄 발전", "산림 파괴"]},
    {"heading": "2. 현황", "points": ["개요만 받은 장"],
     "table": {"columns": ["연도", "기온 상승(℃)"], "rows": [["2000", "0.6"], ["2020", 1.1]], "caption": "표 1"}},
    "글자만 준 장",
]


def _open(path):
    z = zipfile.ZipFile(path)
    return z, z.read("Contents/header.xml").decode(), z.read("Contents/section1.xml").decode()      # 본문 구역 (표지는 section0)


def test_hwpx_package_layout_and_content(tmp_path):
    p = tmp_path / "보고서.hwpx"
    info = hwpx.build_hwpx(p, "기후 변화 보고서", SECTIONS, "과학 · 3학년", ["기상청 https://climate.go.kr"])
    assert info == {"sections": 4, "tables": 1}
    z, header, section = _open(p)
    first = z.infolist()[0]
    assert first.filename == "mimetype" and first.compress_type == zipfile.ZIP_STORED     # 한글이 형식을 알아보는 첫 항목
    assert z.read("mimetype") == b"application/hwp+zip"
    for name in ("version.xml", "settings.xml", "Contents/content.hpf", "META-INF/container.xml", "Preview/PrvText.txt"):
        assert name in z.namelist()
    for part in (header, section, z.read("Contents/section0.xml").decode(), z.read("Contents/content.hpf").decode()):
        ET.fromstring(part.encode())                                                    # 올바른 XML
    # 덧붙인 모양 수와 실제 개수가 맞아야 한글이 연다
    for tag, item in (("charProperties", "charPr"), ("paraProperties", "paraPr"), ("borderFills", "borderFill")):
        declared = int(re.search(rf'<hh:{tag} itemCnt="(\d+)"', header).group(1))
        assert declared == len(re.findall(rf"<hh:{item} ", header))
    assert "&lt;특수문자&gt; &amp; &quot;따옴표&quot;" in section
    assert 'rowCnt="3" colCnt="2"' in section and "<hp:t>1.1</hp:t>" in section
    assert "<hp:t>전 지구적</hp:t>" in section                                          # **굵게** → 굵은 글자 따로
    assert "<hp:t>참고 자료</hp:t>" in section and "pageNum" in section
    assert "<hp:t>글자만 준 장</hp:t>" in section and "<hp:t>개요만 받은 장</hp:t>" in section
    assert "<opf:title>기후 변화 보고서</opf:title>" in z.read("Contents/content.hpf").decode()


def test_hwpx_has_cover_toc_body_sections_and_every_reference_exists(tmp_path):
    p = tmp_path / "r.hwpx"
    secs = SECTIONS + [{"heading": "3. 결론", "paragraphs": ["끝."], "callout": "핵심: 강조 상자"}]
    hwpx.build_hwpx(p, "기후 변화 보고서", secs, "과학 · 홍길동", ["자료"], summary=["첫째 요약", "둘째 요약"])
    z, header, _ = _open(p)
    sec0, sec1 = z.read("Contents/section0.xml").decode(), z.read("Contents/section1.xml").decode()
    for part in (sec0, sec1, z.read("META-INF/container.rdf").decode()):
        ET.fromstring(part.encode())
    assert 'secCnt="2"' in header and "section1" in z.read("Contents/content.hpf").decode()
    assert "<hp:t>REPORT</hp:t>" in sec0 and "pageNum" not in sec0 and 'hideFirstPageNum="1"' in sec0     # 표지: 쪽 번호 없음
    assert "pageNum" in sec1 and '<hp:startNum pageStartsOn="BOTH" page="1"' in sec1                       # 본문: 1쪽부터
    assert "<hp:t>목차</hp:t>" in sec1 and "<hp:t>핵심 요약</hp:t>" in sec1 and "<hp:t>강조 상자</hp:t>" not in sec1
    assert 'pageBreak="1"' in sec1                                                                         # 목차 다음 쪽에서 본문
    assert "<hp:t>2026" in sec0 or re.search(r"<hp:t>\d{4}\. \d\d\. \d\d</hp:t>", sec0)                  # 부제에 연도가 없으면 오늘 날짜
    # 쓰인 모든 번호가 header.xml 에 있어야 한다 (없으면 한글이 연다 해도 모양이 깨진다)
    have = {k: set(re.findall(rf'<hh:{k} id="(\d+)"', header)) for k in ("charPr", "paraPr", "borderFill")}
    for part in (sec0, sec1):
        for attr, k in (("charPrIDRef", "charPr"), ("paraPrIDRef", "paraPr")):
            assert set(re.findall(rf'{attr}="(\d+)"', part)) <= have[k], attr
    assert set(re.findall(r'borderFillIDRef="(\d+)"', header + sec0 + sec1)) <= have["borderFill"]
    assert 'connect="1"' in header                                                                         # 요약 · 강조 상자는 이어진 문단이 한 상자로


def test_hwpx_without_three_headings_has_no_toc(tmp_path):
    p = tmp_path / "s.hwpx"
    hwpx.build_hwpx(p, "짧은 글", [{"heading": "하나", "paragraphs": ["본문"]}], "")
    _, _, section = _open(p)
    assert "<hp:t>목차</hp:t>" not in section and 'pageBreak="1"' not in section


def test_hwpx_refuses_empty_input(tmp_path):
    with pytest.raises(ValueError, match="제목"):
        hwpx.build_hwpx(tmp_path / "a.hwpx", "", SECTIONS)
    with pytest.raises(ValueError, match="sections"):
        hwpx.build_hwpx(tmp_path / "a.hwpx", "제목", [])


# 아래는 도구(tools.py — Windows 전용 모듈을 불러옴) 테스트
@pytest.fixture
def T():
    from jarvis import tools
    return tools


@pytest.fixture
def pc(T, tmp_path, monkeypatch):
    me = T.PCTools.__new__(T.PCTools)
    folders = {"문서": tmp_path / "docs"}
    monkeypatch.setattr(T.winutil, "known_folder", lambda name: folders.get(name.replace(" ", "")))
    me.opened = []
    monkeypatch.setattr(T.os, "startfile", lambda p: me.opened.append(p), raising=False)
    return me


def test_make_document_can_save_hangul(T, pc, tmp_path, monkeypatch):
    msg = pc.t_make_document(title="가정통신문", sections=SECTIONS[:1], format="hwpx")
    path = tmp_path / "docs" / "JARVIS" / "가정통신문.hwpx"
    assert path.exists() and pc.opened == [str(path)] and "한글 문서를 만들었습니다" in msg
    assert pc.t_make_document(title="보통 보고서", sections=SECTIONS[:1]).count(".docx") >= 1     # 말이 없으면 워드

    def nothing(p):
        raise OSError("연결된 프로그램 없음")
    monkeypatch.setattr(T.os, "startfile", nothing, raising=False)
    assert "한컴오피스 뷰어" in pc.t_make_document(title="뷰어 안내", sections=SECTIONS[:1], format="hwpx")


def test_make_document_schema_offers_hwpx(T):
    schemas = {d["name"]: d for d in T.PCTools.schemas(T.PCTools.__new__(T.PCTools))}
    doc = schemas["make_document"]
    assert doc["input_schema"]["properties"]["format"]["enum"] == ["docx", "hwpx"]
    assert "한글" in doc["description"]
