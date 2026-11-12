// J.A.R.V.I.S 엠블럼 — 원본 이미지를 구성 요소별로 분해해 벡터로 다시 그린 코어 (배경 없음)
//
//   바깥 프레임   r196 굵은 링 · 오른쪽 사다리 브래킷(r186~202) · 왼쪽 위 겹선 · 왼쪽 점 3개
//   눈금 링       r160~176, 6° 간격 60개 — 빛이 천천히 훑고 지나가고, 말할 때 바깥으로 늘어남
//   하늘색 띠     r124~151, 178°→35° 20칸 — 꼭대기가 가장 밝고 양끝으로 흐려짐
//   노란 점 5개   r118, 띠 안쪽 잔눈금 위
//   노란 선/캡슐  r117~129, 왼쪽
//   안쪽 링       r107 밝은 링 + 어두운 원판 + 희미한 회로 무늬
//   워드마크      J.A.R.V.I.S.
//
// 좌표는 원본 이미지(512px, 중심 256.5,252.5)의 픽셀 값을 그대로 쓰고 u 로 크기를 맞춘다.
// 모든 움직임은 매 프레임 지수 감쇠로 목표값을 따라가므로 상태가 바뀌어도 툭 끊기지 않는다.
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
    readonly property real speedTarget: mode === "thinking" ? 4.5 : mode === "listening" ? 1.6
                                      : mode === "speaking" ? 1.4 : mode === "offline" ? 0.3 : 1.0
    readonly property real energyTarget: mode === "thinking" ? 1.0 : mode === "listening" ? 0.85
                                       : mode === "speaking" ? 0.7 : mode === "boot" ? 0.5 : mode === "offline" ? 0.3 : 0.2
    readonly property real tintTarget: (mode === "thinking" || mode === "offline") ? 0.8 : 0.0

    // ---------------- 매 프레임 갱신되는 값 ----------------
    property real t: 0
    property real spd: 1
    property real energy: 0.2
    property real tint: 0
    property real amp: 0
    property real listenAmt: 0
    property real thinkAmt: 0
    property real aBand: 0
    property real aTicks: 0
    property real aGold: 0
    property real aCircuit: 0
    property real aOrbit: 0
    property real scanA: 0
    property real flowA: 0
    readonly property real breath: 0.5 + 0.5 * Math.sin(t * 1.15)
    readonly property real sway: 2.2 * Math.sin(t * 0.21) + 1.1 * Math.sin(t * 0.13 + 1.3)

    // 대기 중에는 1초에 20번만 갱신한다 — 움직임이 느려서 차이가 보이지 않고, 그 사이 프레임은 아무것도 바뀌지 않으므로
    // 화면을 다시 그리지 않는다 (예전에는 모니터 주사율대로 매 프레임 그림자 · 흐림 효과까지 다시 그려 CPU · GPU 를 계속 썼다).
    // 듣는 중 · 생각 중 · 말하는 중과 등장 연출 동안에는 매 프레임 갱신한다.
    property real acc: 0
    readonly property bool calm: (mode === "standby" || mode === "offline") && intro >= 1
                                 && listenAmt < 0.02 && thinkAmt < 0.02
    FrameAnimation {
        running: e.visible
        onTriggered: {
            e.acc += frameTime
            if (e.calm && e.acc < 0.05)
                return
            const dt = Math.min(e.acc, 0.1)
            e.acc = 0
            const f = k => 1 - Math.exp(-dt * k)
            e.t += dt
            e.spd += (e.speedTarget - e.spd) * f(1.6)
            e.energy += (e.energyTarget - e.energy) * f(2.4)
            e.tint += (e.tintTarget - e.tint) * f(3)
            e.listenAmt += ((e.mode === "listening" ? 1 : 0) - e.listenAmt) * f(3.5)
            e.thinkAmt += ((e.mode === "thinking" ? 1 : 0) - e.thinkAmt) * f(3.5)
            const target = Math.min(1, e.mode === "standby" ? e.level * 0.5 : e.level)
            e.amp += (target - e.amp) * f(target > e.amp ? 20 : 4.5)   // 빠르게 오르고 천천히 가라앉음
            // 띠와 노란 호: 평소엔 원본 구도 자리 주변을 천천히 오가고(말하면 폭이 커짐),
            // 생각 중엔 계속 돌다가 끝나면 앞쪽의 제자리로 감속하며 돌아온다
            const swing = 1 + 0.8 * e.energy + 1.2 * e.amp
            const hold = 1 - e.thinkAmt
            const bandHome = Math.ceil((e.aBand - 60) / 360) * 360 + 9 * swing * Math.sin(e.t * 0.42)
            e.aBand += dt * 150 * e.thinkAmt + (bandHome - e.aBand) * f(1.1) * hold
            const goldHome = Math.floor((e.aGold + 60) / 360) * 360 + 6 * swing * Math.sin(e.t * 0.31 + 2.0)
            e.aGold += -dt * 90 * e.thinkAmt + (goldHome - e.aGold) * f(1.1) * hold
            e.aTicks -= dt * 2 * e.spd
            e.aCircuit += dt * 6 * e.spd
            e.aOrbit += dt * (50 + 130 * e.thinkAmt)
            e.scanA += dt * (40 + 150 * e.listenAmt + 90 * e.thinkAmt)
            e.flowA += dt * 170
        }
    }

    // 등장 연출: 요소마다 시차를 두고 그려진다
    property real intro: 0
    NumberAnimation on intro { id: introAnim; from: 0; to: 1; duration: 1900 }
    onVisibleChanged: if (visible) introAnim.restart()
    function clamp01(x) { return Math.max(0, Math.min(1, x)) }
    function ease(x) { x = clamp01(x); return 1 - Math.pow(1 - x, 3) }
    function stage(a, b) { return ease((intro - a) / (b - a)) }

    // ---------------- 색 ----------------
    function rgba(c, a) { return Qt.rgba(c.r, c.g, c.b, a) }
    function tinted(base, k) { return Qt.tint(base, Qt.rgba(e.accent.r, e.accent.g, e.accent.b, k)) }
    readonly property color ringCol: tinted("#8eeaf8", tint)
    readonly property color ringHot: Qt.lighter(ringCol, 1.12 + 0.25 * amp)
    readonly property color bandCol: tinted("#6ac3ea", tint * 0.85)
    readonly property color gold: "#f2c84b"

    // ---------------- 도우미 ----------------
    function s(v) { return v * e.u }                    // 원본 픽셀 → 화면
    function lw(v) { return Math.max(1, v * e.u) }       // 선 굵기 (최소 1px)
    function px(deg, rad) { return e.cx + Math.cos(deg * Math.PI / 180) * rad }
    function py(deg, rad) { return e.cy + Math.sin(deg * Math.PI / 180) * rad }
    function bandProfile(a) {   // 띠 밝기: 꼭대기가 가장 밝고 양끝으로 흐려짐 (원본 측정값)
        if (a < 225) return 0.62 + 0.38 * (a - 178) / 47
        if (a <= 318) return 1.0
        return Math.max(0.42, 1.0 - 0.58 * (a - 318) / 77)
    }

    // =====================================================================
    // 0) 은은한 그림자 + 후광 (밝은 배경화면에서도 읽히도록)
    // =====================================================================
    Shape {
        anchors.fill: parent
        preferredRendererType: Shape.CurveRenderer
        opacity: e.stage(0.0, 0.5)
        ShapePath {
            strokeColor: "transparent"
            fillGradient: RadialGradient {
                centerX: e.cx; centerY: e.cy; centerRadius: e.size * 0.5
                focalX: e.cx; focalY: e.cy
                GradientStop { position: 0.0; color: Qt.rgba(0.0, 0.03, 0.06, 0.4) }
                GradientStop { position: 0.80; color: Qt.rgba(0.0, 0.03, 0.06, 0.2) }
                GradientStop { position: 1.0; color: Qt.rgba(0.0, 0.03, 0.06, 0.0) }
            }
            PathAngleArc { centerX: e.cx; centerY: e.cy; radiusX: e.size * 0.5; radiusY: e.size * 0.5; startAngle: 0; sweepAngle: 360 }
        }
    }
    Shape {
        anchors.fill: parent
        preferredRendererType: Shape.CurveRenderer
        opacity: e.stage(0.2, 0.9) * (0.35 + 0.35 * e.energy + 0.45 * e.amp + 0.12 * e.breath)
        ShapePath {
            strokeColor: "transparent"
            fillGradient: RadialGradient {
                centerX: e.cx; centerY: e.cy; centerRadius: e.size * 0.5
                focalX: e.cx; focalY: e.cy
                GradientStop { position: 0.0; color: e.rgba(e.accent, 0.0) }
                GradientStop { position: 0.62; color: e.rgba(e.accent, 0.10) }
                GradientStop { position: 0.89; color: e.rgba(e.accent, 0.22) }
                GradientStop { position: 1.0; color: e.rgba(e.accent, 0.0) }
            }
            PathAngleArc { centerX: e.cx; centerY: e.cy; radiusX: e.size * 0.5; radiusY: e.size * 0.5; startAngle: 0; sweepAngle: 360 }
        }
    }

    // =====================================================================
    // 1) 안쪽 어두운 원판 + 회로 무늬
    // =====================================================================
    Shape {
        anchors.fill: parent
        preferredRendererType: Shape.CurveRenderer
        opacity: e.stage(0.05, 0.5)
        ShapePath {
            strokeColor: "transparent"
            fillGradient: RadialGradient {
                centerX: e.cx; centerY: e.cy; centerRadius: e.s(105)
                focalX: e.cx; focalY: e.cy - e.s(20)
                GradientStop { position: 0.0; color: Qt.rgba(0.04, 0.12, 0.17, 0.95) }
                GradientStop { position: 0.85; color: Qt.rgba(0.01, 0.05, 0.08, 0.95) }
                GradientStop { position: 1.0; color: e.rgba(e.ringCol, 0.35) }
            }
            PathAngleArc { centerX: e.cx; centerY: e.cy; radiusX: e.s(105); radiusY: e.s(105); startAngle: 0; sweepAngle: 360 }
        }
    }
    Item {   // 회로 무늬 (희미하게, 천천히 회전)
        anchors.fill: parent
        opacity: e.stage(0.3, 0.9) * (0.75 + 0.25 * e.energy)
        Shape {
            anchors.fill: parent
            preferredRendererType: Shape.CurveRenderer
            rotation: e.aCircuit
            ShapePath {
                strokeColor: e.rgba(e.ringCol, 0.22); strokeWidth: e.lw(1.2); fillColor: "transparent"
                strokeStyle: ShapePath.DashLine; dashPattern: [3, 2.5]
                PathAngleArc { centerX: e.cx; centerY: e.cy; radiusX: e.s(92); radiusY: e.s(92); startAngle: 0; sweepAngle: 360 }
            }
            ShapePath {   // 톱니
                strokeColor: e.rgba(e.ringCol, 0.11); strokeWidth: e.s(7); fillColor: "transparent"; capStyle: ShapePath.FlatCap
                strokeStyle: ShapePath.DashLine; dashPattern: [0.3, 0.55]
                PathAngleArc { centerX: e.cx; centerY: e.cy; radiusX: e.s(80); radiusY: e.s(80); startAngle: 0; sweepAngle: 360 }
            }
        }
        Shape {
            anchors.fill: parent
            preferredRendererType: Shape.CurveRenderer
            rotation: -e.aCircuit * 0.6
            ShapePath {
                strokeColor: e.rgba(e.ringCol, 0.16); strokeWidth: e.lw(1); fillColor: "transparent"
                PathAngleArc { centerX: e.cx; centerY: e.cy; radiusX: e.s(66); radiusY: e.s(66); startAngle: 20; sweepAngle: 130 }
                PathAngleArc { centerX: e.cx; centerY: e.cy; radiusX: e.s(66); radiusY: e.s(66); startAngle: 200; sweepAngle: 130 }
            }
        }
        Shape {   // 가로 십자선
            anchors.fill: parent
            preferredRendererType: Shape.CurveRenderer
            ShapePath {
                strokeColor: e.rgba(e.ringCol, 0.09); strokeWidth: 1; fillColor: "transparent"
                PathMove { x: e.cx - e.s(100); y: e.cy + e.s(30) }
                PathLine { x: e.cx + e.s(100); y: e.cy + e.s(30) }
                PathMove { x: e.cx - e.s(92); y: e.cy - e.s(40) }
                PathLine { x: e.cx + e.s(92); y: e.cy - e.s(40) }
            }
        }
    }

    // =====================================================================
    // 2) 링 묶음 (발광)
    // =====================================================================
    Item {
        id: rings
        anchors.fill: parent
        layer.enabled: true
        layer.smooth: true
        layer.effect: MultiEffect {
            shadowEnabled: true
            shadowColor: e.accent
            shadowBlur: 0.6
            blurMax: 22
            shadowOpacity: Math.min(1, 0.72 + 0.2 * e.energy + 0.3 * e.amp + 0.1 * e.breath)
            shadowHorizontalOffset: 0
            shadowVerticalOffset: 0
        }

        // ---------- 바깥 프레임 (돌지 않고 천천히 흔들림) ----------
        Item {
            anchors.fill: parent
            rotation: e.sway
            Shape {
                id: frame
                anchors.fill: parent
                preferredRendererType: Shape.CurveRenderer
                readonly property real p: e.stage(0.0, 0.5)
                readonly property real q: e.stage(0.25, 0.65)
                ShapePath {   // 메인 링: 왼쪽에서 양쪽으로 그려짐
                    strokeColor: e.ringHot; strokeWidth: e.s(5.5); fillColor: "transparent"; capStyle: ShapePath.FlatCap
                    PathAngleArc { centerX: e.cx; centerY: e.cy; radiusX: e.s(196); radiusY: e.s(196); startAngle: 190 - 132 * frame.p; sweepAngle: 264 * frame.p }
                }
                ShapePath {   // 오른쪽 바깥 띠
                    strokeColor: e.ringCol; strokeWidth: e.s(3); fillColor: "transparent"; capStyle: ShapePath.FlatCap
                    PathAngleArc { centerX: e.cx; centerY: e.cy; radiusX: e.s(202); radiusY: e.s(202); startAngle: 328; sweepAngle: 84 * frame.q }
                }
                ShapePath {   // 꺾임 연결 · 안쪽 겹선
                    strokeColor: e.rgba(e.ringCol, 0.9 * frame.q); strokeWidth: e.lw(2); fillColor: "transparent"; capStyle: ShapePath.FlatCap
                    PathMove { x: e.px(322, e.s(196)); y: e.py(322, e.s(196)) }
                    PathLine { x: e.px(328, e.s(202)); y: e.py(328, e.s(202)) }
                    PathMove { x: e.px(52, e.s(202)); y: e.py(52, e.s(202)) }
                    PathLine { x: e.px(58, e.s(196)); y: e.py(58, e.s(196)) }
                    PathAngleArc { centerX: e.cx; centerY: e.cy; radiusX: e.s(186); radiusY: e.s(186); startAngle: 326; sweepAngle: 58 * frame.q }
                    PathAngleArc { centerX: e.cx; centerY: e.cy; radiusX: e.s(187); radiusY: e.s(187); startAngle: 212; sweepAngle: 40 * frame.q }
                    PathMove { x: e.px(252, e.s(187)); y: e.py(252, e.s(187)) }
                    PathLine { x: e.px(252, e.s(196)); y: e.py(252, e.s(196)) }
                }
                ShapePath {   // 사다리
                    strokeColor: e.rgba(e.ringCol, 0.85 * frame.q); strokeWidth: e.s(8); fillColor: "transparent"; capStyle: ShapePath.FlatCap
                    strokeStyle: ShapePath.DashLine
                    dashPattern: [0.2, 0.42]
                    PathAngleArc { centerX: e.cx; centerY: e.cy; radiusX: e.s(194); radiusY: e.s(194); startAngle: 338; sweepAngle: 32 * frame.q }
                }
                ShapePath {   // 오른쪽 아래 보조 호
                    strokeColor: e.rgba(e.ringCol, 0.45 * frame.q); strokeWidth: e.lw(1.5); fillColor: "transparent"
                    PathAngleArc { centerX: e.cx; centerY: e.cy; radiusX: e.s(157); radiusY: e.s(157); startAngle: 40; sweepAngle: 72 }
                    PathMove { x: e.px(112, e.s(157)); y: e.py(112, e.s(157)) }
                    PathLine { x: e.px(112, e.s(166)); y: e.py(112, e.s(166)) }
                }
            }
            Repeater {   // 왼쪽 점 3개
                model: 3
                Rectangle {
                    required property int index
                    readonly property real a: 188 + index * 4
                    width: e.s(4); height: width; radius: width / 2
                    color: e.ringCol
                    x: e.px(a, e.s(186)) - width / 2
                    y: e.py(a, e.s(186)) - height / 2
                    opacity: e.stage(0.45 + index * 0.05, 0.6 + index * 0.05) * (0.7 + 0.3 * Math.sin(e.t * 1.6 - index * 0.9))
                }
            }
        }

        // ---------- 눈금 링 (빛이 훑고 지나감 · 말하면 늘어남) ----------
        Item {
            anchors.fill: parent
            rotation: e.aTicks
            Repeater {
                model: 60
                Rectangle {
                    required property int index
                    readonly property real ang: index * 6
                    readonly property real inner: e.s(160)
                    readonly property real d: ((ang + e.aTicks - e.scanA) % 360 + 360) % 360
                    readonly property real wave: Math.pow(0.5 + 0.5 * Math.cos(d * Math.PI / 180), 10)
                    readonly property real n: 0.5 + 0.5 * Math.sin(e.t * (5 + index % 4) + index * 2.1)
                    width: e.lw(2); height: e.s(16) + e.amp * (0.35 + 0.65 * n) * e.s(16)
                    antialiasing: true
                    x: e.cx - width / 2
                    y: e.cy - inner - height
                    color: e.ringCol
                    opacity: e.stage(0.12 + index * 0.006, 0.3 + index * 0.006)
                             * Math.min(1, 0.6 + wave * (0.25 + 0.4 * e.energy) + 0.35 * e.amp)
                    transform: Rotation { origin.x: width / 2; origin.y: inner + height; angle: ang }
                }
            }
        }

        // ---------- 하늘색 띠 + 잔눈금 + 노란 점 ----------
        Item {
            anchors.fill: parent
            rotation: e.aBand
            Repeater {
                model: 20
                Shape {
                    id: seg
                    required property int index
                    anchors.fill: parent
                    preferredRendererType: Shape.CurveRenderer
                    readonly property real step: 217 / 20
                    readonly property real a0: 178 + index * step
                    readonly property real mid: a0 + step / 2
                    readonly property real d: ((mid - e.flowA) % 360 + 360) % 360
                    readonly property real flow: Math.pow(0.5 + 0.5 * Math.cos(d * Math.PI / 180), 14)
                    opacity: e.stage(0.22 + index * 0.018, 0.4 + index * 0.018)
                             * Math.min(1, e.bandProfile(mid) * 0.95 + flow * e.thinkAmt * 0.45 + e.amp * 0.12)
                    ShapePath {
                        strokeColor: e.bandCol; strokeWidth: e.s(27); fillColor: "transparent"; capStyle: ShapePath.FlatCap
                        PathAngleArc { centerX: e.cx; centerY: e.cy; radiusX: e.s(137.5); radiusY: e.s(137.5); startAngle: seg.a0 + 0.45; sweepAngle: seg.step - 0.9 }
                    }
                }
            }
            Shape {   // 띠 테두리 + 안쪽 잔눈금
                id: bandEdge
                anchors.fill: parent
                preferredRendererType: Shape.CurveRenderer
                readonly property real p: e.stage(0.22, 0.78)
                opacity: p
                ShapePath {
                    strokeColor: e.rgba(Qt.lighter(e.bandCol, 1.35), 0.75); strokeWidth: e.lw(1.3); fillColor: "transparent"
                    PathAngleArc { centerX: e.cx; centerY: e.cy; radiusX: e.s(124); radiusY: e.s(124); startAngle: 178; sweepAngle: 217 * bandEdge.p }
                    PathAngleArc { centerX: e.cx; centerY: e.cy; radiusX: e.s(151); radiusY: e.s(151); startAngle: 178; sweepAngle: 217 * bandEdge.p }
                }
                ShapePath {
                    strokeColor: e.rgba(e.ringCol, 0.6); strokeWidth: e.s(6); fillColor: "transparent"; capStyle: ShapePath.FlatCap
                    strokeStyle: ShapePath.DashLine
                    dashPattern: [0.18, 0.5]
                    PathAngleArc { centerX: e.cx; centerY: e.cy; radiusX: e.s(117.5); radiusY: e.s(117.5); startAngle: 140; sweepAngle: 160 * bandEdge.p }
                }
            }
            Repeater {   // 노란 점 (가운데는 고리)
                model: 5
                Rectangle {
                    required property int index
                    readonly property real a: [243, 256, 269, 280, 290][index]
                    readonly property real chase: Math.pow(Math.max(0, Math.cos(e.t * 5 - index * 0.9)), 4)
                    width: e.s(index === 2 ? 9 : 7); height: width; radius: width / 2
                    color: index === 2 ? "transparent" : e.gold
                    border.color: e.gold; border.width: index === 2 ? e.lw(1.6) : 0
                    x: e.px(a, e.s(118)) - width / 2
                    y: e.py(a, e.s(118)) - height / 2
                    opacity: e.stage(0.55 + index * 0.04, 0.7 + index * 0.04)
                             * (0.72 + 0.28 * Math.sin(e.t * 1.3 + index) * (1 - e.thinkAmt) + 0.28 * e.thinkAmt * (chase - 0.5))
                }
            }
        }

        // ---------- 노란 선 + 캡슐 (반대로 천천히 회전) ----------
        Shape {
            id: goldArc
            anchors.fill: parent
            preferredRendererType: Shape.CurveRenderer
            rotation: e.aGold
            readonly property real p: e.stage(0.4, 0.85)
            opacity: Math.min(1, p * 1.5)
            ShapePath {
                strokeColor: e.gold; strokeWidth: e.lw(2.4); fillColor: "transparent"; capStyle: ShapePath.FlatCap
                PathAngleArc { centerX: e.cx; centerY: e.cy; radiusX: e.s(121); radiusY: e.s(121); startAngle: 176; sweepAngle: 47 * goldArc.p }
            }
            ShapePath {
                strokeColor: e.gold; strokeWidth: e.lw(2); fillColor: Qt.rgba(0.95, 0.78, 0.29, 0.10)
                joinStyle: ShapePath.RoundJoin
                PathAngleArc { centerX: e.cx; centerY: e.cy; radiusX: e.s(129); radiusY: e.s(129); startAngle: 147; sweepAngle: 29 }
                PathArc { x: e.px(176, e.s(117)); y: e.py(176, e.s(117)); radiusX: e.s(6); radiusY: e.s(6); direction: PathArc.Clockwise }
                PathAngleArc { centerX: e.cx; centerY: e.cy; radiusX: e.s(117); radiusY: e.s(117); startAngle: 176; sweepAngle: -29; moveToStart: false }
                PathArc { x: e.px(147, e.s(129)); y: e.py(147, e.s(129)); radiusX: e.s(6); radiusY: e.s(6); direction: PathArc.Clockwise }
            }
        }

        // ---------- 안쪽 밝은 링 ----------
        Shape {
            id: innerRing
            anchors.fill: parent
            preferredRendererType: Shape.CurveRenderer
            readonly property real p: e.stage(0.08, 0.55)
            ShapePath {
                strokeColor: e.ringHot; strokeWidth: e.s(5.5) * (1 + 0.25 * e.amp); fillColor: "transparent"; capStyle: ShapePath.FlatCap
                PathAngleArc { centerX: e.cx; centerY: e.cy; radiusX: e.s(107); radiusY: e.s(107); startAngle: 270; sweepAngle: 360 * innerRing.p }
            }
            ShapePath {
                strokeColor: e.rgba(e.ringCol, 0.5 * innerRing.p); strokeWidth: e.lw(1.3); fillColor: "transparent"
                PathAngleArc { centerX: e.cx; centerY: e.cy; radiusX: e.s(113); radiusY: e.s(113); startAngle: 60; sweepAngle: 140 }
            }
        }

        // ---------- 생각 중: 띠 위를 도는 빛 ----------
        Item {
            anchors.fill: parent
            visible: e.thinkAmt > 0.01
            opacity: e.thinkAmt
            rotation: e.aOrbit
            Repeater {
                model: 3
                Rectangle {
                    required property int index
                    width: e.s(9); height: width; radius: width / 2
                    color: "#fff3d6"
                    x: e.cx + Math.cos(index * 2.0944) * e.s(137.5) - width / 2
                    y: e.cy + Math.sin(index * 2.0944) * e.s(137.5) - height / 2
                }
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
                        radiusX: e.s(107 + 108 * rip.p); radiusY: e.s(107 + 108 * rip.p)
                        startAngle: 0; sweepAngle: 360
                    }
                }
            }
        }
    }

    // =====================================================================
    // 3) 워드마크 J.A.R.V.I.S. (금속 질감 + 발광)
    // =====================================================================
    Item {
        id: wm
        readonly property real p: e.stage(0.55, 1.0)
        anchors.centerIn: parent
        anchors.verticalCenterOffset: e.s(-3) - (e.voiceBars ? 7 : 0)
        width: wmText.implicitWidth; height: wmText.implicitHeight
        opacity: p
        transform: Scale {
            origin.x: wm.width / 2; origin.y: wm.height / 2
            xScale: e.s(184) / Math.max(1, wm.width) * (0.94 + 0.06 * wm.p)
            yScale: 0.94 + 0.06 * wm.p
        }
        layer.enabled: true
        layer.effect: MultiEffect {
            shadowEnabled: true; shadowColor: e.accent
            shadowBlur: 0.6; blurMax: 14
            shadowOpacity: Math.min(1, 0.45 + 0.35 * e.amp + 0.12 * e.breath)
            shadowHorizontalOffset: 0; shadowVerticalOffset: 0
        }
        Text {
            id: wmText
            text: "J.A.R.V.I.S."
            font.family: "Bahnschrift"; font.weight: Font.Bold; font.pixelSize: Math.max(9, e.s(27))
            color: "#ffffff"
        }
        Item {   // 글자 아래쪽 절반은 살짝 푸른 은색 — 금속 반사 느낌
            readonly property real split: wmText.baselineOffset - wmText.font.pixelSize * 0.34
            y: split
            width: wmText.width; height: wmText.height - split
            clip: true
            Text {
                y: -parent.split
                text: wmText.text
                font: wmText.font
                color: "#c4e2ec"
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
