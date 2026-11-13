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
    return z, z.read("Contents/header.xml").decode(), z.read("Contents/section0.xml").decode()


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
    for part in (header, section, z.read("Contents/content.hpf").decode()):
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
