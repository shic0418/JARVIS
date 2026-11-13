"""파일 정리 — 폴더 보기 · 옮기기 · 복사 · 이름 바꾸기 · 새 폴더 · 압축 · 종류별 정리 · 되돌리기.

지키는 것:
  · 덮어쓰지 않는다 — 같은 이름이 있으면 '이름 (2).pdf' 처럼 새 이름을 붙인다.
  · 지우기는 휴지통으로만 보낸다 (완전히 지우지 않는다).
  · Windows · 프로그램 폴더 · AppData · 드라이브 맨 위 · 사용자 폴더 자체는 건드리지 않는다.
  · 옮기기 · 이름 바꾸기 · 정리는 직전 것을 되돌릴 수 있다 (undo).
PowerShell 로도 할 수 있는 일이지만, 명령마다 승인을 받아야 하고 한글 경로 · 덮어쓰기 실수가 잦아 따로 만들었다.
"""
from __future__ import annotations

import datetime as dt
import os
import shutil
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

# 종류별 정리에 쓰는 폴더 이름 ← 확장자
KINDS: dict[str, set[str]] = {
    "문서": {".pdf", ".doc", ".docx", ".hwp", ".hwpx", ".ppt", ".pptx", ".xls", ".xlsx", ".csv", ".txt", ".md", ".rtf",
           ".odt", ".ods", ".odp", ".epub"},
    "사진": {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".heic", ".svg", ".tif", ".tiff", ".ico", ".psd", ".ai"},
    "동영상": {".mp4", ".mkv", ".avi", ".mov", ".wmv", ".webm", ".flv", ".m4v"},
    "음악": {".mp3", ".wav", ".flac", ".m4a", ".ogg", ".aac", ".wma"},
    "압축": {".zip", ".7z", ".rar", ".tar", ".gz", ".egg", ".alz"},
    "설치 파일": {".exe", ".msi", ".msix", ".appx"},
    "코드": {".py", ".js", ".ts", ".html", ".css", ".json", ".xml", ".java", ".c", ".cpp", ".cs", ".ipynb", ".sh", ".bat",
           ".ps1", ".yml", ".yaml"},
}
OTHER = "기타"
SKIP_NAMES = {"desktop.ini", "thumbs.db"}
MAX_UNZIP_BYTES = 4 * 1024 ** 3       # 압축을 풀 때 이보다 커지면 멈춘다 (압축 폭탄)
MAX_UNZIP_FILES = 20000


class FileError(Exception):
    pass


def kind_of(path: Path) -> str:
    ext = path.suffix.lower()
    return next((k for k, exts in KINDS.items() if ext in exts), OTHER)


def human(size: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.0f}{unit}" if unit in ("B", "KB") else f"{size:.1f}{unit}"
        size /= 1024
    return f"{size:.1f}GB"


# ---------------------------------------------------------------------- 건드려도 되는 곳인가
def _protected() -> list[Path]:
    out = []
    for var in ("SystemRoot", "windir", "ProgramFiles", "ProgramFiles(x86)", "ProgramW6432", "ProgramData"):
        v = os.environ.get(var)
        if v:
            out.append(Path(v))
    home = Path.home()
    out.append(home / "AppData")
    return out


def guard(path: Path, source: bool = True) -> Path:
    """고쳐도 되는 경로인지 확인하고 절대 경로로 돌려준다. source=True 는 옮기거나 지울 '대상' (더 엄격)."""
    p = Path(os.path.abspath(str(path)))
    if len(p.parts) <= 1:
        raise FileError(f"드라이브 맨 위({p})는 건드리지 않습니다.")
    low = str(p).lower()
    for bad in _protected():
        b = str(bad).lower()
        if low == b or low.startswith(b.rstrip("\\/") + os.sep):
            raise FileError(f"시스템 폴더 안은 건드리지 않습니다: {p}")
    if source:
        home = Path(os.path.abspath(str(Path.home())))
        if p == home:
            raise FileError("사용자 폴더 자체는 옮기거나 지울 수 없습니다.")
        if p.parent == home and p.name.lower() in {"desktop", "documents", "downloads", "pictures", "music", "videos",
                                                   "onedrive"}:
            raise FileError(f"'{p.name}' 폴더 자체는 옮기거나 지울 수 없습니다. 그 안의 파일을 고르세요.")
    return p


def unique(dest: Path) -> Path:
    """같은 이름이 있으면 '이름 (2).확장자' 로."""
    if not dest.exists():
        return dest
    stem, suffix = dest.stem, dest.suffix
    for i in range(2, 1000):
        cand = dest.with_name(f"{stem} ({i}){suffix}")
        if not cand.exists():
            return cand
    raise FileError(f"새 이름을 만들지 못했습니다: {dest}")


# ---------------------------------------------------------------------- 폴더 보기
def listing(folder: Path, sort: str = "name", kind: str = "", query: str = "", limit: int = 60) -> str:
    folder = Path(folder)
    if not folder.is_dir():
        raise FileError(f"폴더가 없습니다: {folder}")
    rows = []
    try:
        with os.scandir(folder) as it:
            for e in it:
                if e.name.startswith(".") or e.name.lower() in SKIP_NAMES:
                    continue
                try:
                    st = e.stat()
                except OSError:
                    continue
                is_dir = e.is_dir()
                rows.append((e.name, is_dir, 0 if is_dir else st.st_size, st.st_mtime,
                             "폴더" if is_dir else kind_of(Path(e.name))))
    except OSError as e:
        raise FileError(f"폴더를 읽지 못했습니다: {e}")
    total = len(rows)
    counts: dict[str, int] = {}
    for r in rows:
        counts[r[4]] = counts.get(r[4], 0) + 1
    if kind:
        rows = [r for r in rows if r[4] == kind]
    if query:
        q = query.lower()
        rows = [r for r in rows if q in r[0].lower()]
    key = {"date": lambda r: -r[3], "size": lambda r: -r[2], "type": lambda r: (r[4], r[0].lower())}.get(
        sort, lambda r: (not r[1], r[0].lower()))
    rows.sort(key=key)
    limit = max(1, min(int(limit or 60), 200))
    lines = [f"{folder} — 항목 {total}개 (" + ", ".join(f"{k} {v}" for k, v in sorted(counts.items(), key=lambda kv: -kv[1]))
             + ")" if total else f"{folder} — 비어 있음"]
    for name, is_dir, size, mtime, k in rows[:limit]:
        when = dt.datetime.fromtimestamp(mtime).strftime("%Y-%m-%d")
        lines.append(f"- {name}{os.sep if is_dir else ''}  [{k}{'' if is_dir else ' · ' + human(size)} · {when}]")
    if len(rows) > limit:
        lines.append(f"…(이하 {len(rows) - limit}개 생략 — kind · query 로 좁히거나 limit 을 늘리세요)")
    return "\n".join(lines)


# ---------------------------------------------------------------------- 되돌리기 기록
@dataclass
class Journal:
    """직전 작업 하나를 기억한다: 옮긴 것 [(지금 위치, 원래 위치)] 과 그때 새로 만든 폴더."""
    what: str = ""
    moves: list[tuple[Path, Path]] = field(default_factory=list)
    made: list[Path] = field(default_factory=list)

    def clear(self) -> None:
        self.what, self.moves, self.made = "", [], []

    def undo(self) -> str:
        if not self.moves and not self.made:
            raise FileError("되돌릴 작업이 없습니다 (옮기기 · 이름 바꾸기 · 정리만 되돌릴 수 있습니다).")
        back = lost = 0
        for now, was in reversed(self.moves):
            if not now.exists() or was.exists():
                lost += 1
                continue
            try:
                was.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(now), str(was))
                back += 1
            except OSError:
                lost += 1
        for d in reversed(self.made):          # 그때 만든 폴더가 비었으면 지운다
            try:
                d.rmdir()
            except OSError:
                pass
        what = self.what
        self.clear()
        return f"'{what}' 되돌림: {back}개를 원래 자리로" + (f" (못 되돌린 것 {lost}개 — 그새 옮겨졌거나 같은 이름이 생김)" if lost else "")


# ---------------------------------------------------------------------- 옮기기 · 복사 · 이름 바꾸기
def _ensure_dir(dest: Path, journal: Journal | None) -> None:
    missing = []
    d = dest
    while not d.exists():
        missing.append(d)
        d = d.parent
    dest.mkdir(parents=True, exist_ok=True)
    if journal is not None:
        journal.made.extend(reversed(missing))


def move(paths: list[Path], dest: Path, journal: Journal | None = None, what: str = "옮기기") -> list[tuple[Path, Path]]:
    dest = guard(dest, source=False)
    srcs = [guard(p) for p in paths]
    for s in srcs:
        if not s.exists():
            raise FileError(f"파일이 없습니다: {s}")
        if dest == s or str(dest).startswith(str(s) + os.sep):
            raise FileError(f"폴더를 자기 자신 안으로 옮길 수 없습니다: {s.name}")
    if journal is not None:
        journal.clear()
        journal.what = what
    _ensure_dir(dest, journal)
    done = []
    for s in srcs:
        if s.parent == dest:
            continue                              # 이미 그 폴더에 있다
        target = unique(dest / s.name)
        shutil.move(str(s), str(target))
        done.append((s, target))
        if journal is not None:
            journal.moves.append((target, s))
    return done


def copy(paths: list[Path], dest: Path) -> list[tuple[Path, Path]]:
    dest = guard(dest, source=False)
    srcs = [Path(os.path.abspath(str(p))) for p in paths]
    for s in srcs:
        if not s.exists():
            raise FileError(f"파일이 없습니다: {s}")
        if s.is_dir() and (dest == s or str(dest).startswith(str(s) + os.sep)):
            raise FileError(f"폴더를 자기 자신 안으로 복사할 수 없습니다: {s.name}")
    dest.mkdir(parents=True, exist_ok=True)
    done = []
    for s in srcs:
        target = unique(dest / s.name)
        if s.is_dir():
            shutil.copytree(str(s), str(target))
        else:
            shutil.copy2(str(s), str(target))
        done.append((s, target))
    return done


_BAD_NAME = set('\\/:*?"<>|')


def rename(path: Path, new_name: str, journal: Journal | None = None) -> Path:
    src = guard(path)
    if not src.exists():
        raise FileError(f"파일이 없습니다: {src}")
    new_name = (new_name or "").strip().rstrip(".")
    if not new_name or any(ch in _BAD_NAME for ch in new_name):
        raise FileError('새 이름에 \\ / : * ? " < > | 는 쓸 수 없습니다.')
    if src.is_file() and not Path(new_name).suffix and src.suffix:
        new_name += src.suffix                    # 확장자를 말하지 않았으면 그대로 둔다
    target = src.with_name(new_name)
    if target == src:
        return src
    if target.exists():
        raise FileError(f"같은 이름이 이미 있습니다: {target.name}")
    src.rename(target)
    if journal is not None:
        journal.clear()
        journal.what = "이름 바꾸기"
        journal.moves.append((target, src))
    return target


def new_folder(path: Path) -> Path:
    p = guard(path, source=False)
    if p.exists():
        raise FileError(f"이미 있습니다: {p}")
    p.mkdir(parents=True)
    return p


# ---------------------------------------------------------------------- 종류별 · 달별 정리
def organize_plan(folder: Path, by: str = "type") -> dict[str, list[Path]]:
    """폴더 바로 아래의 '파일'만 하위 폴더로 나눈 계획 {하위 폴더 이름: [파일]} (폴더 · 바로가기 · 숨김 파일은 그대로 둔다)."""
    folder = guard(folder, source=False)
    if not folder.is_dir():
        raise FileError(f"폴더가 없습니다: {folder}")
    plan: dict[str, list[Path]] = {}
    for p in sorted(folder.iterdir(), key=lambda x: x.name.lower()):
        if not p.is_file() or p.name.startswith(".") or p.name.lower() in SKIP_NAMES:
            continue
        if p.suffix.lower() in (".lnk", ".url", ".tmp", ".crdownload", ".part"):
            continue                              # 바로가기 · 받는 중인 파일
        if by == "month":
            name = dt.datetime.fromtimestamp(p.stat().st_mtime).strftime("%Y-%m")
        else:
            name = kind_of(p)
        plan.setdefault(name, []).append(p)
    return plan


def organize(folder: Path, plan: dict[str, list[Path]], journal: Journal | None = None) -> int:
    folder = guard(folder, source=False)
    if journal is not None:
        journal.clear()
        journal.what = "정리"
    n = 0
    for name, files in plan.items():
        dest = folder / name
        _ensure_dir(dest, journal)
        for s in files:
            if not s.exists():
                continue
            target = unique(dest / s.name)
            shutil.move(str(s), str(target))
            n += 1
            if journal is not None:
                journal.moves.append((target, s))
    return n


# ---------------------------------------------------------------------- 압축
def zip_paths(paths: list[Path], dest: Path | None = None) -> Path:
    srcs = [Path(os.path.abspath(str(p))) for p in paths]
    for s in srcs:
        if not s.exists():
            raise FileError(f"파일이 없습니다: {s}")
    if not srcs:
        raise FileError("압축할 파일이 없습니다.")
    if dest is None:
        dest = srcs[0].parent / ((srcs[0].stem if len(srcs) == 1 else srcs[0].parent.name) + ".zip")
    dest = Path(os.path.abspath(str(dest)))
    if dest.suffix.lower() != ".zip":
        dest = dest / (srcs[0].stem + ".zip") if dest.is_dir() else dest.with_name(dest.name + ".zip")
    dest = unique(guard(dest, source=False))
    dest.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as z:
        for s in srcs:
            if s.is_dir():
                for f in sorted(s.rglob("*")):
                    if f.is_file() and f != dest:
                        z.write(f, str(Path(s.name) / f.relative_to(s)))
            else:
                z.write(s, s.name)
    return dest


def unzip(path: Path, dest: Path | None = None) -> tuple[Path, int]:
    src = Path(os.path.abspath(str(path)))
    if not src.is_file():
        raise FileError(f"파일이 없습니다: {src}")
    if not zipfile.is_zipfile(src):
        raise FileError("zip 파일만 풀 수 있습니다 (7z · rar · egg 는 압축 프로그램으로 여세요).")
    dest = unique(guard(Path(dest) if dest else src.with_suffix(""), source=False))
    with zipfile.ZipFile(src) as z:
        infos = z.infolist()
        if len(infos) > MAX_UNZIP_FILES or sum(i.file_size for i in infos) > MAX_UNZIP_BYTES:
            raise FileError("압축을 풀면 너무 커집니다. 압축 프로그램으로 직접 풀어 주세요.")
        root = os.path.abspath(str(dest))
        for i in infos:                           # 압축 안의 경로가 밖으로 나가는지 (../) 확인
            name = i.filename
            if (i.flag_bits & 0x800) == 0:        # 한글 Windows 에서 만든 zip: 이름이 cp949 로 들어 있다
                try:
                    name = name.encode("cp437").decode("cp949")
                except (UnicodeEncodeError, UnicodeDecodeError):
                    pass
            target = os.path.abspath(os.path.join(root, name))
            if target != root and not target.startswith(root + os.sep):
                raise FileError("압축 파일 안에 수상한 경로가 있어 풀지 않았습니다.")
            if i.is_dir():
                os.makedirs(target, exist_ok=True)
                continue
            os.makedirs(os.path.dirname(target), exist_ok=True)
            with z.open(i) as fsrc, open(target, "wb") as fdst:
                shutil.copyfileobj(fsrc, fdst)
    return dest, sum(1 for i in infos if not i.is_dir())


# ---------------------------------------------------------------------- 휴지통
def trash(paths: list[Path]) -> int:
    """휴지통으로 보낸다 (Windows 전용 — 완전히 지우지 않는다)."""
    srcs = [guard(p) for p in paths]
    for s in srcs:
        if not s.exists():
            raise FileError(f"파일이 없습니다: {s}")
    if os.name != "nt":
        raise FileError("휴지통은 Windows 에서만 쓸 수 있습니다.")
    import ctypes
    import ctypes.wintypes as wt

    class SHFILEOPSTRUCTW(ctypes.Structure):
        _fields_ = [("hwnd", wt.HWND), ("wFunc", wt.UINT), ("pFrom", ctypes.c_void_p), ("pTo", wt.LPCWSTR),
                    ("fFlags", ctypes.c_uint16), ("fAnyOperationsAborted", wt.BOOL),
                    ("hNameMappings", ctypes.c_void_p), ("lpszProgressTitle", wt.LPCWSTR)]

    FO_DELETE, FOF_SILENT, FOF_NOCONFIRMATION, FOF_ALLOWUNDO, FOF_NOERRORUI = 3, 0x4, 0x10, 0x40, 0x400
    op = SHFILEOPSTRUCTW()
    op.wFunc = FO_DELETE
    names = ctypes.create_unicode_buffer("\0".join(str(s) for s in srcs) + "\0")   # 경로 사이는 NUL, 끝은 NUL 두 개
    op.pFrom = ctypes.cast(names, ctypes.c_void_p)
    op.fFlags = FOF_ALLOWUNDO | FOF_NOCONFIRMATION | FOF_SILENT | FOF_NOERRORUI
    rc = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(op))
    if rc != 0 or op.fAnyOperationsAborted:
        raise FileError(f"휴지통으로 보내지 못했습니다 (오류 {rc}).")
    return len(srcs)
