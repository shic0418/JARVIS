"""보안 프로토콜 반격 (counter.py · counter_view.py): 울트론을 찾는 기준 · 끄는 순서 · 장면 계산 · 빛 민감성."""
from __future__ import annotations

import os

import numpy as np
import pytest

from jarvis import counter as C


# ---------------------------------------------------------------- 울트론 알아보기 (좁게)
def wins(*rows):
    return lambda: list(rows)


def names(table):
    return lambda pid: table.get(pid, "")


def test_only_the_ultron_app_itself_is_recognised():
    assert C.is_ultron("U.L.T.R.O.N", "pythonw.exe") and C.is_ultron("U.L.T.R.O.N ACTIVE", "ULTRON.exe")
    assert not C.is_ultron("U.L.T.R.O.N 설명서.txt - 메모장", "notepad.exe")
    assert not C.is_ultron("U.L.T.R.O.N", "chrome.exe")                      # 같은 제목의 웹 페이지 · 다른 앱
    assert not C.is_ultron("U.L.T.R.O.N ABSORB", "pythonw.exe")              # 흡수 연출 덮개는 본체가 아니다


def test_find_groups_windows_per_process_and_skips_ourselves():
    found = C.find_ultron(own_pid=1, windows=wins(("U.L.T.R.O.N", 10, 101), ("U.L.T.R.O.N ACTIVE", 10, 102),
                                                  ("U.L.T.R.O.N", 1, 103), ("U.L.T.R.O.N", 20, 104)),
                          proc_name=names({10: "pythonw.exe", 1: "pythonw.exe", 20: "chrome.exe"}))
    assert [(f.pid, f.title, f.exe) for f in found] == [(10, "U.L.T.R.O.N", "pythonw.exe")]
    assert found[0].windows == ((101, "U.L.T.R.O.N"), (102, "U.L.T.R.O.N ACTIVE"))
    assert C.find_ultron(windows=lambda: (_ for _ in ()).throw(OSError())) == []


def test_absorb_and_jarvis_windows_are_watched_by_exact_title():
    vis = lambda h: h == 1                                            # noqa: E731
    assert C.absorbing(wins(("U.L.T.R.O.N ABSORB", 10, 1)), vis) and not C.absorbing(wins(("U.L.T.R.O.N", 10, 1)), vis)
    # 울트론은 덮개 창을 닫지 않고 숨긴다 — 숨겨진 창은 '진행 중'이 아니다 (예전에는 이것 때문에 매번 14초를 기다렸다)
    assert not C.absorbing(wins(("U.L.T.R.O.N ABSORB", 10, 2)), vis)
    assert C.reviving(wins(("U.L.T.R.O.N REVIVE", 10, 1)), vis) and not C.reviving(wins(("U.L.T.R.O.N REVIVE", 10, 2)), vis)
    shown = C.jarvis_shown(wins(("J.A.R.V.I.S", 5, 7)), visible=lambda h: h == 7)
    hidden = C.jarvis_shown(wins(("J.A.R.V.I.S", 5, 8)), visible=lambda h: h == 7)
    other = C.jarvis_shown(wins(("J.A.R.V.I.S PROTOCOL", 5, 7)), visible=lambda h: True)
    assert shown and not hidden and not other


def test_strikes_exactly_five_seconds_after_jarvis_went_down():
    slept = []
    assert C.STRIKE_DELAY == 5.0
    C.wait_strike(since=100.0, clock=lambda: 101.5, sleep=slept.append)
    assert slept == [3.5]                                             # 꺼진 때에서 5초 — 이미 지난 시간은 뺀다
    slept.clear()
    C.wait_strike(since=100.0, clock=lambda: 109.0, sleep=slept.append)
    assert slept == []                                                # 벌써 지났으면 바로
    C.wait_strike(C.QUICK_DELAY, sleep=slept.append)
    assert slept == [1.0]


def test_emblem_position_follows_the_hud_layout():
    assert C.emblem_in((1000, 500, 230, 356)) == (1115, 607, 107)     # 작게 보기: 위쪽 가운데
    x, y, r = C.emblem_in((0, 0, 420, 724))
    assert (x, y, r) == (210, 178, 106)                               # 펼쳐 보기
    x, y, r = C.emblem_in((0, 0, 345, 534))                           # 배율 150%
    assert abs(x - 172.5) < 0.01 and abs(r - 160.5) < 0.01


def test_stop_all_reports_whether_ultron_is_really_gone():
    a, b = C.Found(1, "U.L.T.R.O.N", "pythonw.exe"), C.Found(2, "U.L.T.R.O.N", "pythonw.exe")
    assert C.stop_all([a, b], lambda f: (True, "")) is True
    assert C.stop_all([a, b], lambda f: (False, "changed")) is True       # 번호가 다른 프로그램으로 바뀜 = 이미 없음
    assert C.stop_all([a, b], lambda f: (f.pid == 1, "denied")) is False


def test_stop_never_touches_our_own_process():
    assert C.stop(C.Found(os.getpid(), "U.L.T.R.O.N", "python.exe")) == (False, "self")


# ---------------------------------------------------------------- 실행 흐름
ULTRON = C.Found(10, "U.L.T.R.O.N", "pythonw.exe")


def run(**kw):
    launched, order = [], []
    kw.setdefault("wait", lambda: order.append("wait") or True)
    kw.setdefault("finder", lambda: [ULTRON])
    kw.setdefault("stopper", lambda f: (order.append("stop") or True, ""))
    kw.setdefault("fullscreen", lambda: False)
    out = C.run(lambda who: (order.append(f"launch:{who}"), launched.append(who)), **kw)
    return out, launched, order


def test_scene_kills_ultron_before_jarvis_comes_back_once():
    def play(found, kill, relaunch):
        relaunch()                        # 끄기 전에는 켜지 않는다
        assert kill() and kill()          # 두 번 불러도 한 번만 끈다
        relaunch()
        relaunch()
        return "countered"
    out, launched, order = run(play=play)
    assert out == "countered" and launched == ["counter"] and order == ["wait", "stop", "launch:counter"]


def test_quiet_takeover_when_asked_or_during_fullscreen_or_repeat():
    for kw in ({"show": False}, {"quick": True}, {"fullscreen": lambda: True}):
        out, launched, order = run(play=lambda *a: pytest.fail("장면을 보여 주면 안 된다"), **kw)
        assert out == "countered" and order == ["wait", "stop", "launch:counter"]


def test_ultron_that_cannot_be_stopped_means_no_return():
    out, launched, _ = run(stopper=lambda f: (False, "denied"), play=lambda found, kill, relaunch: (kill(), relaunch(), "denied")[2])
    assert out == "denied" and launched == []
    out, launched, _ = run(stopper=lambda f: (False, "denied"), show=False)
    assert out == "denied" and launched == []


def test_ultron_gone_already_simply_returns():
    out, launched, order = run(finder=lambda: [])
    assert out == "gone" and launched == ["other"] and "stop" not in order


def test_a_broken_scene_still_finishes_the_takeover():
    def boom(found, kill, relaunch):
        raise RuntimeError("그리기 실패")
    out, launched, order = run(play=boom)
    assert out == "countered" and order == ["wait", "stop", "launch:counter"]


# ---------------------------------------------------------------- 장면 계산
def test_timeline_order():
    assert C.SPARK < C.TRACE < C.TAKEOVER < C.LAUNCH < C.REWRITE[1] <= C.REBUILD[0] < C.REBUILD[1] < C.MAX_WAIT
    assert C.REWRITE[0] < C.TAKEOVER          # 실제 울트론을 끄기 전에 이미 그림이 덮고 바뀌기 시작한다
    assert C.rewrite_progress(0) == 0 and C.rewrite_progress(99) == 1


def test_recolor_turns_ultron_red_into_jarvis_blue_and_keeps_greys_and_alpha():
    px = np.array([[[235, 32, 48, 255], [128, 128, 128, 200], [250, 250, 250, 255], [0, 0, 0, 0]]], np.uint8)
    out = C.recolor(px)
    r, g, b, a = out[0, 0].astype(int)
    assert b > 180 and g > 150 and r < 60 and a == 255                    # 빨강 → 하늘빛
    assert np.abs(out[0, 1, :3].astype(int) - 128).max() <= 30 and out[0, 1, 3] == 200
    assert out[0, 2, :3].min() >= 200 and out[0, 3, 3] == 0
    assert out[0, 0, :3].max() == px[0, 0, :3].max()                      # 밝기는 그대로


def test_rewrite_spreads_from_the_core_outwards():
    img = np.zeros((200, 160, 4), np.uint8)
    img[..., 0], img[..., 3] = 230, 255
    rw = C.Rewrite(img, (80, 70))
    assert np.array_equal(rw.frame(0.0), img) and np.array_equal(rw.frame(10.0), rw.dst)
    mid = rw.frame((C.REWRITE[0] + C.REWRITE[1]) / 2 - 0.4)
    blue = mid[..., 2].astype(int) > mid[..., 0].astype(int)
    assert blue[70, 80] and not blue[195, 5]                              # 코어는 이미 푸르고, 먼 구석은 아직 붉다


def test_circuits_turn_at_right_angles_and_leave_the_hud():
    core, box = (100.0, 100.0), (0.0, 0.0, 200.0, 240.0)
    trs = C.traces(core, box)
    assert len(trs) == 10 and all(tr.start >= C.TRACE for tr in trs)
    for tr in trs:
        assert np.hypot(*(tr.points[0] - core)) <= 12
        steps = np.diff(tr.points[1:], axis=0)
        assert all(min(abs(dx), abs(dy)) < 1e-6 for dx, dy in steps)      # 가로 아니면 세로
        end = tr.points[-1]
        assert not (0 <= end[0] <= 200 and 0 <= end[1] <= 240) or len(tr.points) == 17
    tr = trs[0]
    assert len(tr.drawn(tr.start - 0.1)) == 0 and np.allclose(tr.drawn(99)[-1], tr.points[-1])
    half = tr.drawn(tr.start + tr.length / C.TRACE_SPEED / 2)
    assert 1 < len(half) <= len(tr.points)


def test_console_types_its_lines_and_follows_the_rewrite():
    assert C.console_lines(0.0) == []
    assert C.console_lines(0.5)[0].startswith("J.A.R.V")
    mid = C.console_lines(3.0)
    assert any("%" in line for line in mid) and not any("완료" in line for line in mid)
    done = C.console_lines(6.0)
    assert "100%" in done[-2] and "자비스 복귀" in done[-1] and len(done) == len(C.CONSOLE)


def test_stand_in_core_is_red_round_and_transparent_outside():
    img = C.ultron_core_image(120)
    assert img.shape == (120, 120, 4) and img[0, 0, 3] == 0 and img[60, 60, 3] > 150
    red = (img[..., 0].astype(int) > 180) & (img[..., 1] < 90) & (img[..., 3] > 200)
    assert red.sum() > 200
    blue = C.recolor(img)
    assert ((blue[..., 2].astype(int) > 180) & (blue[..., 0] < 90)).sum() > 200


def test_sound_rises_gently_without_clicks(tmp_path):
    s = C.sound()
    assert s.dtype == np.float32 and np.abs(s).max() <= 1.0 and len(s) > C.SOUND_RATE * 5
    head = int(0.05 * C.SOUND_RATE)
    assert np.abs(s[:head]).max() < 0.05 and np.abs(s[-head:]).max() < 0.05      # 갑자기 시작하거나 끊기지 않는다
    path = C.write_wav(s, tmp_path / "c.wav")
    assert path.stat().st_size > len(s)


# ---------------------------------------------------------------- 덮개 장면 (Qt, 화면 없이)
@pytest.fixture(scope="module")
def qt():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def make_scene(qt):
    from PySide6.QtCore import QRectF
    from jarvis import counter_view as V
    img = C.ultron_core_image(220)
    return V.Scene(img, QRectF(1500, 760, 220, 220), (110, 110), QRectF(0, 0, 1920, 1040))


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


def test_scene_layout_keeps_the_console_beside_the_hud(qt):
    s = make_scene(qt)
    assert s.panel.right() <= s.hud.left() and abs(s.panel.bottom() - s.hud.bottom()) < 1
    assert s.area.contains(s.hud) and s.area.contains(s.panel)
    assert abs(s.core.x() - 1610) < 1 and abs(s.core.y() - 870) < 1


def test_scene_turns_red_into_blue_on_screen(qt):
    s = make_scene(qt)
    hud = s.hud.translated(-s.area.x(), -s.area.y()).toAlignedRect()
    before = render(s, 0.3, (40, 40, 40))[hud.y():hud.bottom(), hud.x():hud.right()].astype(int)
    after = render(s, C.REWRITE[1] + 0.05, (40, 40, 40))[hud.y():hud.bottom(), hud.x():hud.right()].astype(int)
    assert (before[..., 0] - before[..., 2]).mean() > 10                  # 처음엔 붉고
    assert (after[..., 2] - after[..., 0]).mean() > 10                    # 끝엔 푸르다


@pytest.mark.parametrize("bg", [(20, 20, 20), (240, 240, 240)])
def test_no_flashing_over_large_areas(qt, bg):
    """넓은 면의 밝기가 크게 오르내리는 일이 1초에 3번을 넘지 않는다 (WCAG 2.3.1 보다 엄격하게 — 사실상 0번이어야 한다)."""
    s = make_scene(qt)
    fps = 30
    lum = []
    for i in range(int((C.REBUILD[1] + 1.0) * fps)):
        frame = render(s, i / fps, bg).astype(np.float32) / 255
        lum.append(float((frame * [0.2126, 0.7152, 0.0722]).sum(-1).mean()))
    lum = np.array(lum)
    flips, last, ref = [], 0, lum[0]
    for i, v in enumerate(lum):
        d = v - ref
        if abs(d) >= 0.10:                    # 덮개 전체 평균이 10% 넘게 바뀐 지점
            sign = 1 if d > 0 else -1
            if sign != last:
                flips.append(i / fps)
                last = sign
            ref = v
    worst = max((sum(1 for f in flips if a <= f < a + 1) for a in np.arange(0, lum.size / fps, 0.1)), default=0)
    assert worst <= 1, flips
    assert np.abs(np.diff(lum)).max() < 0.05                              # 한 장면 사이에 크게 튀는 일도 없다


def test_overlay_window_lets_clicks_through_and_is_not_mistaken_for_jarvis(qt):
    from PySide6.QtCore import Qt
    from jarvis import counter_view as V
    view = V.CounterView(make_scene(qt))
    flags = view.windowFlags()
    assert flags & Qt.WindowTransparentForInput and flags & Qt.WindowDoesNotAcceptFocus and flags & Qt.WindowStaysOnTopHint
    assert view.testAttribute(Qt.WA_TransparentForMouseEvents)
    assert not view.windowTitle().startswith("J.A.R.V.I.S") and not view.windowTitle().startswith("U.L.T.R.O.N")


def test_ring_flies_to_the_real_jarvis_emblem_and_follows_it(qt):
    from PySide6.QtCore import QPointF
    s = make_scene(qt)
    c0, r0 = s.emblem_at(6.0)
    assert c0 == s.core and r0 == s.emblem_r and s.dirty() == s.area      # 자비스가 나타나기 전에는 울트론 자리에
    s.dock_to(QPointF(300, 200), 107, 7.0)
    mid, _ = s.emblem_at(7.0 + C.DOCK / 2)
    end, r = s.emblem_at(7.0 + C.DOCK)
    assert s.core.x() > mid.x() > 300 and (end.x(), end.y(), r) == (300, 200, 107)
    s.dock_to(QPointF(340, 260), 107, 9.0)                                # 자비스 HUD 를 끌어 옮겼다 — 따라간다
    end, _ = s.emblem_at(9.0)
    assert (end.x(), end.y()) == (340, 260) and s.dock_at == 7.0
    assert s.dirty().contains(QPointF(340, 260)) and s.dirty().contains(s.core)


def test_new_scene_pieces_stay_in_step_with_the_timeline():
    assert C.ping_rings(0.0) == [] and len(C.ping_rings(1.4)) == 3
    assert C.lock_scale(C.LOCK[0]) > 2.5 and C.lock_scale(C.LOCK[1]) == 1.0
    assert C.shock(C.SHOCK[0] - 0.1) == (0.0, 0.0) and C.shock(sum(C.SHOCK) / 2)[1] > 0
    m = C.Motes((0, 0, 200, 300))
    pos, alpha = m.state(C.CONVERGE[1], (100, 100), 50)
    d = np.hypot(pos[:, 0] - 100, pos[:, 1] - 100)
    assert np.all(d <= 50.5) and alpha.max() == 0                         # 모두 고리에 닿아 스며들었다
    hexes = C.hex_centers((0, 0, 220, 220))
    assert len(hexes) > 20 and C.hex_glow(np.array([10.0, 500.0]), 100.0)[1] == 0
