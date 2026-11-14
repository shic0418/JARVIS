"""파일 정리 (files.py) — 실제 임시 폴더에서: 덮어쓰지 않는다, 되돌릴 수 있다, 건드리면 안 되는 곳은 거절한다."""
import os
import zipfile
from pathlib import Path

import pytest

from jarvis import files
from jarvis.files import FileError, Journal


@pytest.fixture(autouse=True)
def fake_home(tmp_path_factory, monkeypatch):
    """임시 폴더가 사용자 AppData 아래에 있어도 '시스템 폴더' 로 막히지 않게, 사용자 폴더를 다른 곳으로 돌려 둔다."""
    home = tmp_path_factory.mktemp("home")
    for var in ("USERPROFILE", "HOME"):
        monkeypatch.setenv(var, str(home))
    return home


@pytest.fixture
def box(tmp_path):
    for name in ("보고서.pdf", "사진1.jpg", "사진2.PNG", "노래.mp3", "setup.exe", "메모", "바로가기.lnk", "받는중.crdownload"):
        (tmp_path / name).write_bytes(b"x" * 10)
    (tmp_path / "하위").mkdir()
    (tmp_path / "하위" / "안.txt").write_text("안")
    return tmp_path


def test_listing_shows_kinds_sizes_and_counts(box):
    out = files.listing(box)
    assert "항목 9개" in out and "사진 2" in out and "폴더 1" in out
    assert out.splitlines()[1].startswith("- 하위")                       # 폴더가 먼저
    only = files.listing(box, kind="사진")
    assert "사진1.jpg" in only and "보고서.pdf" not in only
    assert "보고서.pdf" in files.listing(box, query="보고")
    assert "안.txt" in files.listing(box / "하위")
    (box / "빈폴더").mkdir()
    assert "비어 있음" in files.listing(box / "빈폴더")
    with pytest.raises(FileError):
        files.listing(box / "없는폴더")


def test_move_never_overwrites_and_can_be_undone(box):
    dest = box / "정리" / "문서"
    (dest).mkdir(parents=True)
    (dest / "보고서.pdf").write_bytes(b"old")
    j = Journal()
    done = files.move([box / "보고서.pdf", box / "노래.mp3"], dest, j)
    assert [d.name for _, d in done] == ["보고서 (2).pdf", "노래.mp3"]
    assert (dest / "보고서.pdf").read_bytes() == b"old"                    # 있던 파일은 그대로
    assert not (box / "보고서.pdf").exists()
    assert "2개를 원래 자리로" in j.undo()
    assert (box / "보고서.pdf").exists() and (box / "노래.mp3").exists() and not (dest / "보고서 (2).pdf").exists()
    with pytest.raises(FileError):
        j.undo()                                                          # 한 번만 되돌린다


def test_move_refuses_a_folder_into_itself_and_missing_files(box):
    with pytest.raises(FileError):
        files.move([box / "하위"], box / "하위" / "더안쪽")
    with pytest.raises(FileError):
        files.move([box / "없는파일.txt"], box / "하위")


def test_copy_keeps_the_original_and_copies_folders(box):
    done = files.copy([box / "보고서.pdf", box / "하위"], box / "복사본")
    assert (box / "보고서.pdf").exists() and (box / "복사본" / "하위" / "안.txt").read_text() == "안"
    assert len(done) == 2


def test_rename_keeps_the_extension_and_refuses_clashes(box):
    j = Journal()
    assert files.rename(box / "보고서.pdf", "최종 보고서", j).name == "최종 보고서.pdf"
    assert files.rename(box / "사진1.jpg", "표지.png").name == "표지.png"   # 확장자를 말하면 그대로
    with pytest.raises(FileError):
        files.rename(box / "노래.mp3", "최종 보고서.pdf")                   # 같은 이름이 있다
    with pytest.raises(FileError):
        files.rename(box / "노래.mp3", "이상한/이름")
    j.undo()
    assert (box / "보고서.pdf").exists()


def test_organize_sorts_loose_files_by_kind_and_undo_puts_everything_back(box):
    plan = files.organize_plan(box)
    assert {k: sorted(p.name for p in v) for k, v in plan.items()} == {
        "문서": ["보고서.pdf"], "사진": ["사진1.jpg", "사진2.PNG"], "음악": ["노래.mp3"], "설치 파일": ["setup.exe"],
        "기타": ["메모"]}                                                 # 폴더 · 바로가기 · 받는 중인 파일은 그대로 둔다
    j = Journal()
    assert files.organize(box, plan, j) == 6
    assert (box / "사진" / "사진2.PNG").exists() and (box / "바로가기.lnk").exists() and (box / "하위" / "안.txt").exists()
    j.undo()
    assert (box / "사진1.jpg").exists() and not (box / "사진").exists()      # 그때 만든 빈 폴더도 지운다


def test_organize_by_month(box):
    os.utime(box / "보고서.pdf", (1_700_000_000, 1_700_000_000))            # 2023-11
    plan = files.organize_plan(box, by="month")
    assert [p.name for p in plan["2023-11"]] == ["보고서.pdf"]


def test_guard_refuses_roots_home_and_system_folders(tmp_path, monkeypatch):
    with pytest.raises(FileError):
        files.guard(Path(os.path.abspath(os.sep)))
    with pytest.raises(FileError):
        files.guard(Path.home())
    monkeypatch.setenv("SystemRoot", str(tmp_path / "Windows"))
    with pytest.raises(FileError):
        files.guard(tmp_path / "Windows" / "System32" / "a.dll")
    with pytest.raises(FileError):
        files.guard(Path.home() / "AppData" / "Roaming" / "x")
    assert files.guard(tmp_path / "내 파일.txt") == tmp_path / "내 파일.txt"
    assert files.guard(tmp_path / "WindowsBackup" / "a.txt")              # 이름만 비슷한 폴더는 괜찮다


def test_zip_and_unzip_round_trip(box):
    z = files.zip_paths([box / "보고서.pdf", box / "하위"])
    assert z.name == f"{box.name}.zip" and zipfile.ZipFile(z).namelist() == ["보고서.pdf", "하위/안.txt"]
    again = files.zip_paths([box / "보고서.pdf"], box / "묶음")
    assert again.name == "묶음.zip"
    out, n = files.unzip(z)
    assert n == 2 and (out / "하위" / "안.txt").read_text() == "안" and out.name == box.name
    out2, _ = files.unzip(z)                                              # 같은 이름의 폴더가 있으면 새 이름
    assert out2.name == f"{box.name} (2)"


def test_unzip_refuses_paths_that_escape_the_folder(tmp_path):
    bad = tmp_path / "bad.zip"
    with zipfile.ZipFile(bad, "w") as z:
        z.writestr("../밖으로.txt", "x")
    with pytest.raises(FileError):
        files.unzip(bad)
    assert not (tmp_path.parent / "밖으로.txt").exists()
    with pytest.raises(FileError):
        files.unzip(tmp_path / "bad.txt")


def test_trash_is_windows_only_and_checks_paths_first(tmp_path):
    with pytest.raises(FileError):
        files.trash([tmp_path / "없는파일"])
    if os.name != "nt":
        (tmp_path / "a.txt").write_text("a")
        with pytest.raises(FileError):
            files.trash([tmp_path / "a.txt"])
        assert (tmp_path / "a.txt").exists()
