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
FOUND = [C.Found(5, "U.L.T.R.O.N", "python.exe")]


def repel_steps(**kw):
    steps = []
    args = dict(finder=lambda: FOUND, locate=lambda fs: steps.append("locate") or (1, 2, 3, 4),
                stop=lambda fs: steps.append("freeze") or True, start=lambda fs: steps.append("thaw") or True,
                settle=lambda: None, grab=lambda spot: steps.append(("grab", spot)) or "shot",
                killer=lambda fs: steps.append("kill") or True, fullscreen=lambda: False)

    def play(shot, kill):
        steps.append(("play", shot))
        steps.append(("killed", kill()))
        kill()                                               # 두 번 불러도 한 번만 지운다
    args["play"] = play
    args.update(kw)
    return D.repel(**args), steps


def test_ultron_is_frozen_on_the_spot_and_removed_only_inside_the_scene():
    out, steps = repel_steps()
    assert out == "repelled"
    # 자리를 잰다(메시지를 보낼 수 있으므로 멈추기 전) → 멈춘다 → 멈춘 진짜 울트론을 찍는다 → 장면 속에서 지운다
    assert steps == ["locate", "freeze", ("grab", (1, 2, 3, 4)), ("play", "shot"), "kill", ("killed", True)]


def test_ultron_is_always_removed_even_if_the_scene_breaks():
    def boom(shot, kill):
        raise RuntimeError("그리기 실패")
    out, steps = repel_steps(play=boom)
    assert out == "repelled" and steps[-1] == "kill"


def test_quiet_defense_freezes_and_removes_without_a_scene():
    for kw in ({"show": False}, {"fullscreen": lambda: True}):
        out, steps = repel_steps(play=lambda *a: pytest.fail("장면을 보여 주면 안 된다"), **kw)
        assert out == "repelled" and steps == ["freeze", "kill"]


def test_ultron_that_cannot_be_removed_is_unfrozen_not_left_hanging():
    out, steps = repel_steps(killer=lambda fs: False)
    assert out == "denied" and steps[-1] == "thaw"
    out, steps = repel_steps(stop=lambda fs: False, killer=lambda fs: False)      # 멈추게도 못 한다 (관리자 권한)
    assert out == "denied" and "grab" not in str(steps)
    assert D.repel(finder=lambda: [], killer=lambda fs: pytest.fail("끌 것이 없다")) == "gone"


def test_timeline_freezes_then_strikes_the_real_window_then_swaps_then_shatters():
    assert D.BEAM[0] == 0 < D.SHIELD[0] < D.INFECT[0] < D.INFECT[1] < D.SWAP < D.SWEEP[0] < D.SWEEP[1] < D.END
    assert D.END >= 7.0                                                 # 예전(약 3.7초)보다 느리게
    assert D.SWAP < 4.5                                                 # 멈춘 창이 '응답 없음' 으로 바뀌기(5초) 전에 지운다


def test_infection_covers_the_red_from_the_hit_point_and_hands_over_seamlessly():
    img = red_card(120, 160)
    inf = D.Infect(img, (60, 40))
    assert inf.layer(0.0)[..., 3].max() == 0                            # 처음엔 아무것도 덮지 않는다
    mid = inf.layer(0.35)[..., 3]
    assert mid[40, 60] > 200 and mid[150, 15] == 0                      # 꽂힌 자리부터 번진다
    full = inf.layer(1.0)
    assert (full[..., 3] == img[..., 3]).all()                          # 다 번지면 울트론 전체를 덮는다
    final = inf.final()
    vis = img[..., 3] > 0
    assert (final[vis][:, 2].astype(int) - final[vis][:, 0]).mean() > 50     # 덮인 모습은 푸르다


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
    f = s.frame(D.SWEEP[0] + 0.9).astype(int)
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
    assert lines[0].startswith("J.A.R.V.I.S") and "동결" in lines[1] and "100%" in lines[3]
    assert "100%" in lines[5] and "사라졌습니다" in lines[-1]


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


def render(scene, t, bg, real_until=None):
    """화면에 보이는 모습: SWAP 전에는 멈춘 진짜 울트론 창이 그 자리에 있고, 덮개가 그 위에 그린다."""
    from PySide6.QtGui import QColor, QImage, QPainter
    area = scene.area.toAlignedRect()
    im = QImage(area.width(), area.height(), QImage.Format_RGBA8888)
    im.fill(QColor(*bg))
    g = QPainter(im)
    if scene.live and t < (D.SWAP if real_until is None else real_until):
        g.drawImage(scene.hud.translated(-scene.area.x(), -scene.area.y()), scene.raw())    # 진짜 울트론 (멈춤)
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
    covered = render(s, D.SWAP - 0.05, bg)[hud.y():hud.bottom(), hud.x():hud.right()].astype(int)
    after = render(s, D.END, bg)[hud.y():hud.bottom(), hud.x():hud.right()].astype(int)
    assert (before[..., 0] - before[..., 2]).mean() > 10              # 처음엔 붉은 (진짜) 울트론이 있고
    assert (covered[..., 2] - covered[..., 0]).mean() > 10            # 푸른빛이 덮었다가
    assert np.abs(after - np.array(bg)).mean() < 3                    # 끝엔 사라졌다


def test_overlay_draws_nothing_where_the_real_ultron_is_until_it_turns_blue(qt):
    s = make_scene(qt)
    hud = s.hud.translated(-s.area.x(), -s.area.y()).toAlignedRect()
    bg = (40, 40, 40)
    only_overlay = render(s, 0.3, bg, real_until=0)[hud.y():hud.bottom(), hud.x():hud.right()].astype(int)
    assert ((only_overlay[..., 0] - only_overlay[..., 2]) > 30).sum() == 0     # 덮개는 울트론을 따로 그리지 않는다


@pytest.mark.parametrize("bg", [(20, 20, 20), (240, 240, 240)])
def test_swapping_the_real_ultron_for_its_copy_is_invisible(qt, bg):
    """SWAP 직전(진짜 울트론 + 덮개) 과 직후(덮개만 — 진짜는 꺼짐) 가 같은 모습이어야 한다."""
    s = make_scene(qt)
    hud = s.hud.translated(-s.area.x(), -s.area.y()).toAlignedRect()
    a = render(s, D.SWAP - 0.001, bg)[hud.y():hud.bottom(), hud.x():hud.right()].astype(int)
    b = render(s, D.SWAP + 0.001, bg)[hud.y():hud.bottom(), hud.x():hud.right()].astype(int)
    assert np.abs(a - b).mean() < 2.0 and np.percentile(np.abs(a - b), 99) < 24


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
