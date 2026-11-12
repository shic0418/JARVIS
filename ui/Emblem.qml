// J.A.R.V.I.S 엠블럼 — 반투명한 유리 원판 위에 칸으로 나뉜 링과 어두운 코어 (배경 없음)
//
//   유리 원판     r206 옅은 흰빛 원판 + 하늘색 테두리 빛
//   바깥 테두리   r188 가는 링 · r200 밝은 테두리 호
//   바깥 칸 링    r150~173, 60칸 — 회색 유리 칸, 오른쪽 위는 하늘색
//   하늘색 칸 띠  r114~146, 160°→420° 26칸 — 꼭대기가 가장 진하고 양끝으로 옅어짐
//   노란 점/호    r104~114, 위쪽 점 5개 · 왼쪽 점선 호와 캡슐
//   안쪽 링       r99 밝은 링 + r94 어두운 원판 + 점선 무늬
//   워드마크      J.A.R.V.I.S.
//
// 좌표는 지름 440 기준 값이고 u 로 크기를 맞춘다.
// 칸은 크기가 바뀔 때만 다각형으로 계산해 링 하나당 ShapePath 하나로 그린다 (매 프레임 바인딩 없음).
// 움직임은 매 프레임 지수 감쇠로 목표값을 따라가므로 상태가 바뀌어도 툭 끊기지 않는다.
import QtQuick
import QtQuick.Shapes
import QtQuick.Effects

Item {
    id: e
    property color accent: "#3ee6ff"
    property real level: 0             // 0..1 (마이크/음성)
    property string mode: "standby"    // boot | standby | listening | thinking | speaking | offline
    property real size: 214
    property bool voiceBars: false     // 워드마크 아래 음성 파형 (전체 모드)
    width: size; height: size

    readonly property real u: size / 440
    readonly property real cx: width / 2
    readonly property real cy: height / 2

    // ---------------- 상태별 목표값 ----------------
    readonly property real energyTarget: mode === "thinking" ? 1.0 : mode === "listening" ? 0.85
                                       : mode === "speaking" ? 0.7 : mode === "boot" ? 0.5 : mode === "offline" ? 0.3 : 0.2
    readonly property real tintTarget: (mode === "thinking" || mode === "offline") ? 0.8 : 0.0

    // ---------------- 매 프레임 갱신되는 값 ----------------
    property real t: 0
    property real energy: 0.2
    property real tint: 0
    property real amp: 0
    property real listenAmt: 0
    property real thinkAmt: 0
    property real aBand: 0
    property real aOrbit: 0
    readonly property real breath: 0.5 + 0.5 * Math.sin(t * 1.15)

    FrameAnimation {
        running: e.visible
        onTriggered: {
            const dt = Math.min(frameTime, 0.05)
            const f = k => 1 - Math.exp(-dt * k)
            e.t += dt
            e.energy += (e.energyTarget - e.energy) * f(2.4)
            e.tint += (e.tintTarget - e.tint) * f(3)
            e.listenAmt += ((e.mode === "listening" ? 1 : 0) - e.listenAmt) * f(3.5)
            e.thinkAmt += ((e.mode === "thinking" ? 1 : 0) - e.thinkAmt) * f(3.5)
            const target = Math.min(1, e.mode === "standby" ? e.level * 0.5 : e.level)
            e.amp += (target - e.amp) * f(target > e.amp ? 20 : 4.5)   // 빠르게 오르고 천천히 가라앉음
            // 칸 띠: 평소엔 제자리 주변을 천천히 흔들리고, 생각 중엔 돌다가 끝나면 가까운 제자리로 감속해 돌아온다
            const swing = 1 + 0.8 * e.energy + 1.2 * e.amp
            const home = Math.round(e.aBand / 360) * 360 + 5 * swing * Math.sin(e.t * 0.42)
            e.aBand += dt * 120 * e.thinkAmt + (home - e.aBand) * f(1.1) * (1 - e.thinkAmt)
            e.aOrbit += dt * (40 + 140 * e.thinkAmt)
        }
    }

    // 등장 연출: 묶음마다 시차를 두고 나타난다
    property real intro: 0
    NumberAnimation on intro { id: introAnim; from: 0; to: 1; duration: 1500 }
    onVisibleChanged: if (visible) introAnim.restart()
    function stage(a, b) { const x = Math.max(0, Math.min(1, (intro - a) / (b - a))); return 1 - Math.pow(1 - x, 3) }

    // ---------------- 색 ----------------
    function rgba(c, a) { return Qt.rgba(c.r, c.g, c.b, a) }
    function tinted(base, k) { return Qt.tint(base, Qt.rgba(e.accent.r, e.accent.g, e.accent.b, k)) }
    readonly property color ringCol: tinted("#bff4ff", tint)
    readonly property color ringHot: Qt.lighter(ringCol, 1.1 + 0.25 * amp)
    readonly property color bandCol: tinted("#5fb8ec", tint * 0.85)
    readonly property color gold: "#f2c84b"

    // ---------------- 도우미 ----------------
    function s(v) { return v * e.u }                    // 기준 좌표 → 화면
    function lw(v) { return Math.max(1, v * e.u) }       // 선 굵기 (최소 1px)
    function pt(deg, rad) { const r = deg * Math.PI / 180; return Qt.point(e.cx + Math.cos(r) * e.s(rad), e.cy + Math.sin(r) * e.s(rad)) }
    // 링을 n 칸으로 나눈 다각형 목록 (from 부터 sweep 만큼, 칸 사이 gap 도). 호는 칸마다 4점으로 근사
    function cells(r0, r1, from, sweep, n, gap) {
        const out = [], step = sweep / n
        for (let i = 0; i < n; i++) {
            const a0 = from + i * step + gap / 2, a1 = a0 + step - gap, poly = []
            for (let k = 0; k <= 3; k++) poly.push(pt(a0 + (a1 - a0) * k / 3, r1))
            for (let k = 3; k >= 0; k--) poly.push(pt(a0 + (a1 - a0) * k / 3, r0))
            poly.push(poly[0])
            out.push(poly)
        }
        return out
    }
    // 크기가 바뀔 때만 다시 계산된다
    readonly property var outerGrey: cells(150, 173, 50, 280, 47, 1.6)    // 50°→330°
    readonly property var outerBlue: cells(150, 173, 330, 80, 13, 1.6)   // 330°→410°
    readonly property var bandTop: cells(114, 146, 215, 110, 11, 1.4)    // 꼭대기 (가장 진함)
    readonly property var bandSide: cells(114, 146, 160, 55, 5, 1.4)
                                    .concat(cells(114, 146, 325, 50, 5, 1.4))
    readonly property var bandEnd: cells(114, 146, 375, 45, 5, 1.4)       // 오른쪽 아래 끝 (가장 옅음)
    readonly property var innerGrey: cells(114, 146, 60, 100, 10, 1.4)

    // =====================================================================
    // 0) 유리 원판 (밝은 배경 · 어두운 배경 모두에서 읽히도록 옅은 흰빛)
    // =====================================================================
    Shape {
        anchors.fill: parent
        preferredRendererType: Shape.CurveRenderer
        opacity: e.stage(0.0, 0.45)
        ShapePath {
            strokeColor: "transparent"
            fillGradient: RadialGradient {
                centerX: e.cx; centerY: e.cy; centerRadius: e.s(214)
                focalX: e.cx; focalY: e.cy
                GradientStop { position: 0.0; color: Qt.rgba(0.88, 0.94, 0.97, 0.55) }
                GradientStop { position: 0.80; color: Qt.rgba(0.84, 0.93, 0.97, 0.62) }
                GradientStop { position: 0.93; color: Qt.tint(Qt.rgba(0.80, 0.95, 1.0, 0.85), e.rgba(e.accent, 0.25 * e.tint)) }
                GradientStop { position: 1.0; color: e.rgba(e.accent, 0.0) }
            }
            PathAngleArc { centerX: e.cx; centerY: e.cy; radiusX: e.s(214); radiusY: e.s(214); startAngle: 0; sweepAngle: 360 }
        }
    }

    // =====================================================================
    // 1) 어두운 코어 원판 + 점선 무늬 (발광 없음)
    // =====================================================================
    Shape {
        anchors.fill: parent
        preferredRendererType: Shape.CurveRenderer
        opacity: e.stage(0.05, 0.45)
        ShapePath {
            strokeColor: "transparent"
            fillGradient: RadialGradient {
                centerX: e.cx; centerY: e.cy; centerRadius: e.s(95)
                focalX: e.cx; focalY: e.cy - e.s(25)
                GradientStop { position: 0.0; color: Qt.rgba(0.13, 0.17, 0.21, 0.97) }
                GradientStop { position: 0.75; color: Qt.rgba(0.04, 0.06, 0.08, 0.97) }
                GradientStop { position: 1.0; color: Qt.rgba(0.02, 0.03, 0.05, 0.97) }
            }
            PathAngleArc { centerX: e.cx; centerY: e.cy; radiusX: e.s(95); radiusY: e.s(95); startAngle: 0; sweepAngle: 360 }
        }
    }
    Shape {   // 점선 원 + 끊긴 호 (천천히 회전)
        anchors.fill: parent
        preferredRendererType: Shape.CurveRenderer
        rotation: e.aOrbit * 0.15
        opacity: e.stage(0.3, 0.8) * (0.7 + 0.3 * e.energy)
        ShapePath {
            strokeColor: e.rgba(e.ringCol, 0.32); strokeWidth: e.lw(1.2); fillColor: "transparent"
            strokeStyle: ShapePath.DashLine; dashPattern: [3, 2.5]
            PathAngleArc { centerX: e.cx; centerY: e.cy; radiusX: e.s(80); radiusY: e.s(80); startAngle: 0; sweepAngle: 360 }
        }
        ShapePath {
            strokeColor: e.rgba(e.ringCol, 0.16); strokeWidth: e.lw(1); fillColor: "transparent"
            PathAngleArc { centerX: e.cx; centerY: e.cy; radiusX: e.s(66); radiusY: e.s(66); startAngle: 20; sweepAngle: 130 }
            PathAngleArc { centerX: e.cx; centerY: e.cy; radiusX: e.s(66); radiusY: e.s(66); startAngle: 200; sweepAngle: 130 }
        }
    }

    // =====================================================================
    // 2) 링 묶음 + 워드마크 (발광 효과 한 번으로 처리)
    // =====================================================================
    Item {
        anchors.fill: parent
        layer.enabled: true
        layer.smooth: true
        layer.effect: MultiEffect {
            shadowEnabled: true
            shadowColor: e.accent
            shadowBlur: 0.5
            blurMax: 20
            shadowOpacity: Math.min(1, 0.55 + 0.2 * e.energy + 0.3 * e.amp + 0.1 * e.breath)
            shadowHorizontalOffset: 0
            shadowVerticalOffset: 0
        }

        // ---------- 바깥 테두리 ----------
        Shape {
            id: rim
            anchors.fill: parent
            preferredRendererType: Shape.CurveRenderer
            readonly property real p: e.stage(0.0, 0.5)
            ShapePath {
                strokeColor: e.rgba(e.ringCol, 0.75); strokeWidth: e.lw(1.6); fillColor: "transparent"
                PathAngleArc { centerX: e.cx; centerY: e.cy; radiusX: e.s(188); radiusY: e.s(188); startAngle: 270; sweepAngle: 360 * rim.p }
            }
            ShapePath {
                strokeColor: e.ringHot; strokeWidth: e.s(3); fillColor: "transparent"; capStyle: ShapePath.RoundCap
                PathAngleArc { centerX: e.cx; centerY: e.cy; radiusX: e.s(200); radiusY: e.s(200); startAngle: 195; sweepAngle: 95 * rim.p }
                PathAngleArc { centerX: e.cx; centerY: e.cy; radiusX: e.s(200); radiusY: e.s(200); startAngle: 15; sweepAngle: 95 * rim.p }
            }
        }

        // ---------- 칸 링 (흔들림 · 생각 중 회전) ----------
        Item {
            anchors.fill: parent
            rotation: e.aBand
            opacity: e.stage(0.15, 0.7)
            Shape {
                id: cellShape
                anchors.fill: parent
                preferredRendererType: Shape.CurveRenderer
                readonly property color edge: Qt.rgba(0.62, 0.80, 0.90, 0.7)
                ShapePath {   // 회색 유리 칸
                    strokeColor: cellShape.edge; strokeWidth: e.lw(1); fillColor: Qt.rgba(0.82, 0.89, 0.93, 0.5 + 0.15 * e.amp)
                    PathMultiline { paths: e.outerGrey.concat(e.innerGrey) }
                }
                ShapePath {   // 바깥 하늘색 칸
                    strokeColor: cellShape.edge; strokeWidth: e.lw(1); fillColor: e.rgba(e.bandCol, 0.55 + 0.2 * e.amp)
                    PathMultiline { paths: e.outerBlue }
                }
                ShapePath {
                    strokeColor: cellShape.edge; strokeWidth: e.lw(1); fillColor: e.rgba(e.bandCol, 0.92)
                    PathMultiline { paths: e.bandTop }
                }
                ShapePath {
                    strokeColor: cellShape.edge; strokeWidth: e.lw(1); fillColor: e.rgba(e.bandCol, 0.72 + 0.15 * e.amp)
                    PathMultiline { paths: e.bandSide }
                }
                ShapePath {
                    strokeColor: cellShape.edge; strokeWidth: e.lw(1); fillColor: e.rgba(e.bandCol, 0.5 + 0.2 * e.amp)
                    PathMultiline { paths: e.bandEnd }
                }
            }
        }

        // ---------- 생각 중: 칸 띠 위를 훑는 빛 ----------
        Shape {
            anchors.fill: parent
            preferredRendererType: Shape.CurveRenderer
            visible: e.thinkAmt > 0.01
            opacity: e.thinkAmt * 0.55
            rotation: e.aOrbit * 2
            ShapePath {
                strokeColor: "#ffffff"; strokeWidth: e.s(32); fillColor: "transparent"; capStyle: ShapePath.FlatCap
                PathAngleArc { centerX: e.cx; centerY: e.cy; radiusX: e.s(130); radiusY: e.s(130); startAngle: 0; sweepAngle: 22 }
            }
        }

        // ---------- 노란 점 · 점선 호 · 캡슐 ----------
        Item {
            anchors.fill: parent
            rotation: -e.aBand * 0.6
            opacity: e.stage(0.45, 0.85)
            Shape {
                anchors.fill: parent
                preferredRendererType: Shape.CurveRenderer
                ShapePath {   // 왼쪽 점선 호
                    strokeColor: e.rgba(e.gold, 0.9); strokeWidth: e.s(3); fillColor: "transparent"; capStyle: ShapePath.FlatCap
                    strokeStyle: ShapePath.DashLine; dashPattern: [0.8, 1.2]
                    PathAngleArc { centerX: e.cx; centerY: e.cy; radiusX: e.s(107); radiusY: e.s(107); startAngle: 128; sweepAngle: 92 }
                }
                ShapePath {   // 캡슐
                    strokeColor: e.gold; strokeWidth: e.lw(1.8); fillColor: Qt.rgba(0.95, 0.78, 0.29, 0.12)
                    joinStyle: ShapePath.RoundJoin
                    PathAngleArc { centerX: e.cx; centerY: e.cy; radiusX: e.s(113); radiusY: e.s(113); startAngle: 158; sweepAngle: 26 }
                    PathArc { x: e.pt(184, 101).x; y: e.pt(184, 101).y; radiusX: e.s(6); radiusY: e.s(6); direction: PathArc.Clockwise }
                    PathAngleArc { centerX: e.cx; centerY: e.cy; radiusX: e.s(101); radiusY: e.s(101); startAngle: 184; sweepAngle: -26; moveToStart: false }
                    PathArc { x: e.pt(158, 113).x; y: e.pt(158, 113).y; radiusX: e.s(6); radiusY: e.s(6); direction: PathArc.Clockwise }
                }
            }
            Repeater {   // 위쪽 점 5개 (가운데가 가장 큼) — 생각 중엔 차례로 깜빡임
                model: 5
                Rectangle {
                    required property int index
                    readonly property point c: e.pt(250 + index * 10, 106)
                    readonly property real chase: Math.pow(Math.max(0, Math.cos(e.t * 5 - index * 0.9)), 4)
                    width: e.s(index === 2 ? 9 : 6); height: width; radius: width / 2
                    color: e.gold
                    x: c.x - width / 2; y: c.y - height / 2
                    opacity: 0.75 + 0.25 * (e.thinkAmt * (chase - 0.5) * 2 + (1 - e.thinkAmt) * Math.sin(e.t * 1.3 + index))
                }
            }
        }

        // ---------- 안쪽 밝은 링 ----------
        Shape {
            id: innerRing
            anchors.fill: parent
            preferredRendererType: Shape.CurveRenderer
            readonly property real p: e.stage(0.08, 0.55)
            ShapePath {
                strokeColor: e.ringHot; strokeWidth: e.s(7) * (1 + 0.3 * e.amp); fillColor: "transparent"; capStyle: ShapePath.FlatCap
                PathAngleArc { centerX: e.cx; centerY: e.cy; radiusX: e.s(99); radiusY: e.s(99); startAngle: 270; sweepAngle: 360 * innerRing.p }
            }
        }

        // ---------- 듣는 중: 바깥으로 퍼지는 파동 ----------
        Repeater {
            model: 2
            Shape {
                id: rip
                required property int index
                anchors.fill: parent
                preferredRendererType: Shape.CurveRenderer
                visible: e.listenAmt > 0.01
                readonly property real p: (e.t * 0.6 + index * 0.5) % 1
                opacity: e.listenAmt * Math.sin(p * Math.PI) * 0.7
                ShapePath {
                    strokeColor: e.accent; strokeWidth: e.lw(1.6); fillColor: "transparent"
                    PathAngleArc {
                        centerX: e.cx; centerY: e.cy
                        radiusX: e.s(99 + 110 * rip.p); radiusY: e.s(99 + 110 * rip.p)
                        startAngle: 0; sweepAngle: 360
                    }
                }
            }
        }

        // ---------- 워드마크 J.A.R.V.I.S. ----------
        Text {
            id: wm
            readonly property real p: e.stage(0.55, 1.0)
            anchors.centerIn: parent
            anchors.verticalCenterOffset: -(e.voiceBars ? 7 : 0)
            text: "J.A.R.V.I.S."
            color: "#ffffff"
            font.family: "Bahnschrift"; font.weight: Font.DemiBold
            font.pixelSize: Math.max(9, e.s(30)); font.letterSpacing: e.s(3)
            opacity: p
            transform: Scale {
                origin.x: wm.width / 2; origin.y: wm.height / 2
                xScale: e.s(170) / Math.max(1, wm.width) * (0.94 + 0.06 * wm.p)
                yScale: 0.94 + 0.06 * wm.p
            }
        }
    }

    // 음성 파형 (전체 모드)
    Row {
        visible: e.voiceBars
        anchors.horizontalCenter: parent.horizontalCenter
        y: e.cy + e.s(30)
        height: 14
        spacing: 2.5
        opacity: e.stage(0.7, 1.0)
        Repeater {
            model: 13
            Rectangle {
                required property int index
                readonly property real prof: Math.exp(-Math.pow((index - 6) / 3.6, 2))
                readonly property real n: 0.5 + 0.5 * Math.sin(e.t * (6 + index % 5) + index * 1.7)
                readonly property real idle: 0.12 + 0.08 * Math.sin(e.t * 2.0 + index * 0.6)
                width: 2.5; radius: 1.25
                height: Math.max(2, 14 * Math.min(1, idle + e.amp * prof * (0.4 + 0.6 * n) * 1.5))
                anchors.verticalCenter: parent.verticalCenter
                color: index === 6 ? "#ffffff" : e.ringCol
                opacity: 0.5 + 0.5 * prof
            }
        }
    }
}
