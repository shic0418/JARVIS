"""방어 프로토콜 (defense.py · defense_view.py · guard.py): 반격으로 되살아난 자비스는 울트론의 다음 흡수를 막고 울트론을 지운다."""
from __future__ import annotations

import os

import numpy as np
import pytest

from jarvis import counter as C
from jarvis import defense as D
from jarvis import guard


# ---------------------------------------------------------------- 언제 막는가
def test_only_a_jarvis_revived_by_the_counterattack_is_armed():
    assert D.armed(["--no-mic", "--revived", "counter", "--revive-count", "1"])
    assert D.armed(["--revived=counter"])
    assert not D.armed(["--no-mic"])
    assert not D.armed(["--revived", "other", "--revive-count", "0"])
    assert not D.armed(["--revived"])
    # 반격 뒤 다시 켤 때의 인자가 그대로 방어 프로토콜을 켠다
    assert D.armed(guard.relaunch_args(["--no-mic"], "counter", 1))


# ---------------------------------------------------------------- 울트론의 가디언 찾기 (좁게)
ULTRON = os.path.normcase(os.path.normpath(r"C:\Users\me\Desktop\Ultron-main"))


def test_guardian_is_recognised_only_by_module_and_ultrons_folder():
    roots = {ULTRON}
    assert D.is_guardian(["pythonw.exe", "-m", "jarvis.guardian"], r"C:\Users\me\Desktop\Ultron-main", roots)
    assert not D.is_guardian(["pythonw.exe", "-m", "jarvis.guard", "--pid", "1"], ULTRON, roots)   # 자비스의 감시 프로세스
    assert not D.is_guardian(["python.exe", "jarvis.guardian"], ULTRON, roots)                     # -m 으로 띄운 것만
    assert not D.is_guardian(["pythonw.exe", "-m", "jarvis.guardian"], r"C:\Other", roots)          # 다른 폴더 (비전 등)
    assert not D.is_guardian(["pythonw.exe", "-m", "jarvis.guardian"], ULTRON, roots, own_root=ULTRON)  # 자비스 자신의 폴더
    assert not D.is_guardian(["pythonw.exe", "-m", "jarvis.guardian"], "", roots)


def test_ultron_roots_come_from_its_folder_script_and_exe():
    info = {1: ("C:/py/python.exe", ["python.exe", "main.py"], r"C:\Users\me\Desktop\Ultron-main"),
            2: (r"D:\apps\Ultron\Ultron.exe", [r"D:\apps\Ultron\Ultron.exe"], "")}
    roots = D.ultron_roots([C.Found(1, "U.L.T.R.O.N", "python.exe"), C.Found(2, "U.L.T.R.O.N", "Ultron.exe")],
                           info=lambda pid: info[pid])
    assert ULTRON in roots and os.path.normcase(r"D:\apps\Ultron") in roots and "" not in roots


def test_find_guardians_skips_ourselves_and_other_programs():
    rows = [(10, "pythonw.exe", ["pythonw.exe", "-m", "jarvis.guardian"], ULTRON),
            (11, "pythonw.exe", ["pythonw.exe", "-m", "jarvis.guardian"], r"C:\Vision"),
            (os.getpid(), "python.exe", ["python.exe", "-m", "jarvis.guardian"], ULTRON),
            (12, "python.exe", ["python.exe", "main.py"], ULTRON)]
    got = D.find_guardians({ULTRON}, procs=lambda: rows)
    assert [g.pid for g in got] == [10] and got[0].exe == "pythonw.exe"
    assert D.find_guardians(set(), procs=lambda: rows) == []


def test_purge_stops_the_guardian_before_ultron_and_checks_again():
    order = []
    ultron = [C.Found(5, "U.L.T.R.O.N", "python.exe")]
    guardians = iter([[C.Found(9, "guardian", "pythonw.exe")], [C.Found(19, "guardian", "pythonw.exe")]])
    later = iter([[C.Found(25, "U.L.T.R.O.N", "python.exe")]])

    def stopper(f):
        order.append(f.pid)
        return True, ""

    ok = D.purge(ultron, stopper=stopper, roots_of=lambda fs: {ULTRON}, guardians=lambda r: next(guardians),
                 finder=lambda: next(later), sleep=lambda s: None)
    assert ok and order == [9, 5, 19, 25]          # 가디언 → 울트론 → (그 사이 되살아난) 가디언 → 울트론


def test_purge_fails_when_ultron_runs_as_administrator():
    ok = D.purge([C.Found(5, "U.L.T.R.O.N", "python.exe")], stopper=lambda f: (False, "denied"),
                 roots_of=lambda fs: set(), guardians=lambda r: [], finder=lambda: [], sleep=lambda s: None)
    assert ok is False


# ---------------------------------------------------------------- 막기
def test_repel_snaps_ultron_then_removes_it_then_plays_the_scene():
    steps = []
    found = [C.Found(5, "U.L.T.R.O.N", "python.exe")]
    out = D.repel(finder=lambda: found, grab=lambda fs: steps.append("grab") or "shot",
                  killer=lambda fs: steps.append("kill") or True, fullscreen=lambda: False,
                  play=lambda shot: steps.append(("play", shot)))
    assert out == "repelled" and steps == ["grab", "kill", ("play", "shot")]


def test_repel_quietly_or_denied_or_gone():
    found = [C.Found(5, "U.L.T.R.O.N", "python.exe")]
    played = []
    assert D.repel(show=False, finder=lambda: found, killer=lambda fs: True, play=played.append) == "repelled"
    assert D.repel(finder=lambda: found, killer=lambda fs: True, fullscreen=lambda: True, play=played.append) == "repelled"
    assert played == []
    assert D.repel(finder=lambda: found, grab=lambda fs: None, killer=lambda fs: False, fullscreen=lambda: False,
                   play=played.append) == "denied" and played == []
    assert D.repel(finder=lambda: [], killer=lambda fs: pytest.fail("끌 것이 없다")) == "gone"


def test_sentry_defends_while_jarvis_lives_and_stops_after_a_refusal():
    life = iter([True] * 6 + [False])
    attacks = iter([False, True, False, True, False, False, False, False])
    calls = []
    guard.sentry(lambda: next(life), lambda: next(attacks, False), lambda: calls.append(1) or len(calls) < 2,
                 sleep=lambda s: None)
    assert calls == [1, 1]                         # 두 번째에 False(관리자 권한 등) — 그 뒤로는 막지 않는다


def test_defend_records_and_tells_jarvis_and_steps_aside_after_three(tmp_path):
    state, event = tmp_path / "s.json", tmp_path / "e.json"
    assert guard.defend(lambda: 1000.0, repel=lambda: "repelled", state_file=state, event_file=event) is True
    st = guard._load(state)
    assert st.defended == [1000.0] and st.total == 1
    ev = D.take_event(event)
    assert ev and ev["kind"] == "repelled" and ev["count"] == 1 and not event.exists()
    guard._save(guard.State(defended=[900.0, 950.0, 990.0]), state)
    assert guard.defend(lambda: 1000.0, repel=lambda: pytest.fail("물러나야 한다"), state_file=state, event_file=event) is False
    guard._save(guard.State(), state)
    assert guard.defend(lambda: 1000.0, repel=lambda: "denied", state_file=state, event_file=event) is False
    assert not event.exists()


def test_old_events_are_dropped(tmp_path):
    e = tmp_path / "e.json"
    e.write_text('{"kind": "repelled", "count": 1, "at": 1}', encoding="utf-8")
    assert D.take_event(e) is None and not e.exists()
    assert D.take_event(tmp_path / "none.json") is None


def test_armed_jarvis_that_is_struck_without_warning_counterattacks_and_removes_the_guardian(tmp_path, monkeypatch):
    seen = []
    monkeypatch.setattr(guard, "_counterattack", lambda launch, quick, purge=False, since=None: seen.append(purge) or "countered")
    for argv in (["--revived", "counter", "--revive-count", "1"], ["--no-mic"]):
        guard.watch(42, argv, wait=lambda p: None, launch=lambda a: None, clock=lambda: 5000.0, killer=lambda: True,
                    stop_file=tmp_path / "stop", state_file=tmp_path / f"s{len(seen)}.json")
    assert seen == [True, False]


def test_strikes_the_moment_ultrons_revive_cutscene_ends_or_when_it_reaches_for_jarvis():
    absorb, revive = [False], [False]
    th = D.Threat(lambda: absorb[0], lambda: revive[0])
    assert th() is False                               # 아무 일도 없다
    revive[0] = True
    assert th() is False and th() is False             # 컷신이 흐르는 동안은 기다린다
    revive[0] = False
    assert th() is True                                # 컷신이 끝난 바로 그 순간
    assert th() is False                               # 한 번만
    absorb[0] = True
    assert th() is True                                # 흡수 덮개가 보이면 촉수가 닿기 전에


def test_comeback_line_after_a_defense():
    import random
    line = D.repelled_line("주인님", random.Random(1))
    assert "주인님" in line and "울트론" in line


# ---------------------------------------------------------------- 부서지는 장면 (numpy)
def red_card(w=80, h=120):
    img = np.zeros((h, w, 4), np.uint8)
    img[10:h - 10, 10:w - 10] = (230, 40, 50, 255)
    return img


def test_shatter_starts_whole_breaks_from_the_top_and_ends_empty():
    s = D.Shatter(red_card(), 1.0)
    m = s.margin
    first = s.frame(0.0)
    assert (first[m:m + 120, m:m + 80, 3] > 0).sum() == (red_card()[..., 3] > 0).sum()   # 처음엔 온전하다
    mid = s.frame((D.SWEEP[0] + D.SWEEP[1]) / 2)
    top = mid[m + 10:m + 40, m + 10:m + 70, 3].mean()
    bottom = mid[m + 80:m + 110, m + 10:m + 70, 3].mean()
    assert top < bottom                                 # 위쪽부터 떨어져 나간다
    assert s.frame(D.END)[..., 3].max() == 0            # 끝엔 아무것도 남지 않는다


def test_falling_pieces_turn_blue():
    s = D.Shatter(red_card(), 1.0)
    f = s.frame(D.SWEEP[0] + 0.5).astype(int)
    vis = f[..., 3] > 40
    m = s.margin
    loose = vis.copy()
    loose[m:m + 120, m:m + 80] = False                   # 그림 밖으로 날아간 조각들
    assert loose.any() and (f[loose][:, 2] - f[loose][:, 0]).mean() > 0


def test_sound_is_gentle(tmp_path):
    s = D.sound()
    assert np.abs(s).max() <= 1.0 and abs(len(s) / C.SOUND_RATE - (D.END + 0.4)) < 0.01
    head = int(0.02 * C.SOUND_RATE)
    assert np.abs(s[:head]).max() < 0.05 and np.abs(s[-head:]).max() < 0.05


def test_console_reports_the_defense():
    assert D.console_lines(0.0) == []
    lines = D.console_lines(D.END)
    assert lines[0].startswith("J.A.R.V.I.S") and "100%" in lines[3] and "사라졌습니다" in lines[-1]


# ---------------------------------------------------------------- 덮개 장면 (Qt, 화면 없이)
@pytest.fixture(scope="module")
def qt():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def make_scene(qt):
    from PySide6.QtCore import QRectF
    from jarvis import defense_view as V
    return V.DefenseScene(C.ultron_core_image(220), QRectF(1500, 760, 220, 220), QRectF(0, 0, 1920, 1040))


def render(scene, t, bg):
    from PySide6.QtGui import QColor, QImage, QPainter
    area = scene.area.toAlignedRect()
    im = QImage(area.width(), area.height(), QImage.Format_RGBA8888)
    im.fill(QColor(*bg))
    g = QPainter(im)
    scene.paint(g, t, 1.0, scene.area.topLeft())
    g.end()
    ptr = im.constBits()
    return np.frombuffer(ptr, np.uint8, im.sizeInBytes()).reshape(im.height(), im.bytesPerLine() // 4, 4)[:, :im.width(), :3].copy()


def test_scene_keeps_the_console_beside_and_ultron_vanishes(qt):
    s = make_scene(qt)
    assert s.panel.right() <= s.hud.left() and s.area.contains(s.panel)
    hud = s.hud.translated(-s.area.x(), -s.area.y()).toAlignedRect()
    bg = (40, 40, 40)
    before = render(s, 0.2, bg)[hud.y():hud.bottom(), hud.x():hud.right()].astype(int)
    after = render(s, D.END, bg)[hud.y():hud.bottom(), hud.x():hud.right()].astype(int)
    assert (before[..., 0] - before[..., 2]).mean() > 10              # 처음엔 붉은 울트론이 있고
    assert np.abs(after - np.array(bg)).mean() < 3                    # 끝엔 사라졌다


@pytest.mark.parametrize("bg", [(20, 20, 20), (240, 240, 240)])
def test_no_flashing_over_large_areas(qt, bg):
    s = make_scene(qt)
    fps = 30
    lum = []
    for i in range(int((D.END + D.FADE) * fps)):
        frame = render(s, i / fps, bg).astype(np.float32) / 255
        lum.append(float((frame * [0.2126, 0.7152, 0.0722]).sum(-1).mean()))
    lum = np.array(lum)
    flips, last, ref = [], 0, lum[0]
    for i, v in enumerate(lum):
        d = v - ref
        if abs(d) >= 0.10:
            sign = 1 if d > 0 else -1
            if sign != last:
                flips.append(i / fps)
                last = sign
            ref = v
    worst = max((sum(1 for f in flips if a <= f < a + 1) for a in np.arange(0, lum.size / fps, 0.1)), default=0)
    assert worst <= 1, flips
    assert np.abs(np.diff(lum)).max() < 0.05


def test_defense_scene_comes_out_of_the_jarvis_emblem_and_follows_it(qt):
    from PySide6.QtCore import QPointF
    s = make_scene(qt)
    assert s.dirty() == s.area
    s.set_anchor(QPointF(300, 300), 107)
    assert s.dirty().contains(QPointF(300, 300))
    a = render_rect(s, 1.2, (20, 20, 20), 280, 280, 40, 40)              # 자비스 엠블럼 안쪽은 비워 둔다
    s.set_anchor(QPointF(600, 500), 107)                                  # 자비스 HUD 를 옮기면 빛줄기도 옮겨 간다
    assert s.dirty().contains(QPointF(600, 500))
    ring = render_rect(s, 1.2, (20, 20, 20), 600 - 125, 500 - 125, 250, 250)
    assert a.max() <= 21 and ring.max() > 120


def render_rect(scene, t, bg, x, y, w, h):
    from PySide6.QtCore import QPointF
    from PySide6.QtGui import QColor, QImage, QPainter
    im = QImage(w, h, QImage.Format_RGBA8888)
    im.fill(QColor(*bg))
    g = QPainter(im)
    scene.paint(g, t, 1.0, QPointF(x, y))
    g.end()
    return np.frombuffer(im.constBits(), np.uint8, im.sizeInBytes()).reshape(h, im.bytesPerLine() // 4, 4)[:, :w, :3].copy()
