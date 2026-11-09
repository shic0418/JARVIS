// 액티브 모드 — 화면 전체에 펼쳐지는 헬멧 시야 HUD
//   켜질 때: 섬광 · 렌즈 플레어 · 충격파가 퍼지고, 조준경과 양쪽 눈 고리가 그려지며,
//            패널들이 헬멧 곡면을 따라 휘어진 채 가운데에서 날아가 자리를 잡는다. 글자는 암호가 풀리듯 나타난다.
//   꺼질 때: 같은 과정을 거꾸로 — 모든 것이 가운데로 빨려 들어가며 사라진다.
//   마우스 · 키보드 입력은 그대로 아래 창으로 통과한다 (켜 둔 채로 PC 를 쓸 수 있음).
import QtQuick
import QtQuick.Shapes
import QtQuick.Effects

Window {
    id: ov
    objectName: "activeMode"
    color: "transparent"
    flags: Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool
           | Qt.WindowTransparentForInput | Qt.WindowDoesNotAcceptFocus
    visible: false
    title: "J.A.R.V.I.S ACTIVE"

    readonly property bool on: jarvis.activeMode
    readonly property string st: jarvis.state
    readonly property color cyan: "#46d9ff"
    readonly property color hot: "#eafdff"
    readonly property color red: "#ff3b4f"
    property color accent: st === "thinking" ? "#ffb347" : st === "offline" ? "#ff4d61" : st === "listening" ? "#8af4ff" : cyan
    Behavior on accent { ColorAnimation { duration: 450 } }
    readonly property real level: Math.max(jarvis.micLevel, jarvis.voiceLevel)
    readonly property var stats: JSON.parse(jarvis.statsJson)
    readonly property var stateLabels: ({ boot: "INITIALIZING", standby: "STANDBY", listening: "LISTENING",
                                          thinking: "PROCESSING", speaking: "RESPONDING", offline: "MIC OFFLINE" })
    property var cpuHist: []
    onStatsChanged: { const h = cpuHist.slice(-47); h.push(stats.cpu || 0); cpuHist = h }

    // 화면 크기에 맞춘 단위 (1600×900 기준 1)
    readonly property real u: Math.max(0.55, Math.min(width / 1600, height / 900))
    readonly property real cx: width / 2
    readonly property real cy: height / 2
    readonly property real diag: Math.sqrt(width * width + height * height)

    // ---- 펼침 진행도 p: 0(꺼짐) → 1(완전히 펼쳐짐) ----
    property real p: 0
    readonly property bool live: visible && p > 0
    NumberAnimation { id: openAnim; target: ov; property: "p"; to: 1; duration: 2700 }
    SequentialAnimation {
        id: closeAnim
        NumberAnimation { target: ov; property: "p"; to: 0; duration: 950; easing.type: Easing.InQuad }
        ScriptAction { script: ov.visible = false }
    }
    onOnChanged: {
        if (on) { closeAnim.stop(); visible = true; openAnim.restart() }
        else if (visible) { openAnim.stop(); closeAnim.restart() }
    }
    Component.onCompleted: if (on) { visible = true; openAnim.restart() }

    function lin(a, b) { return Math.max(0, Math.min(1, (p - a) / (b - a))) }
    function seg(a, b) { const x = lin(a, b); return 1 - Math.pow(1 - x, 3) }
    function rnd(i) { const x = Math.sin(i * 12.9898 + 78.233) * 43758.5453; return x - Math.floor(x) }
    function c(a) { return Qt.rgba(accent.r, accent.g, accent.b, a) }
    function rc(a) { return Qt.rgba(red.r, red.g, red.b, a) }
    function pad(n) { return n < 10 ? "0" + n : "" + n }
    function rate(b) {
        if (b === undefined) return "-"
        if (b >= 1048576) return (b / 1048576).toFixed(1) + " MB/s"
        return Math.round(b / 1024) + " KB/s"
    }
    // 암호가 풀리듯: 앞에서부터 진짜 글자, 바로 뒤 몇 칸은 무작위 기호
    readonly property string glyphs: "ABCDEF0123456789#%&*/<>=+"
    function decode(s, t, seed) {
        s = s || ""
        if (t >= 1) return s
        if (t <= 0) return ""
        const n = Math.floor(s.length * t)
        let out = s.substring(0, n)
        for (let i = n; i < Math.min(s.length, n + 5); i++)
            out += s[i] === " " ? " " : glyphs[Math.floor(rnd(i * 7.3 + tick * 1.7 + seed) * glyphs.length)]
        return out
    }

    property date now: new Date()
    Timer { interval: 250; running: ov.visible; repeat: true; triggeredOnStart: true; onTriggered: ov.now = new Date() }
    property int tick: 0                       // 깜빡이는 숫자 · 암호 글자용
    Timer { interval: 70; running: ov.live; repeat: true; onTriggered: ov.tick++ }
    readonly property int slow: Math.floor(tick / 9)

    // 계속 돌아가는 값들 (보일 때만)
    property real spin: 0
    NumberAnimation on spin { from: 0; to: 360; duration: 26000; loops: Animation.Infinite; running: ov.live }
    property real sweep: 0
    NumberAnimation on sweep { from: 0; to: 360; duration: 3200; loops: Animation.Infinite; running: ov.live }
    property real heading: 0
    NumberAnimation on heading { from: 0; to: 360; duration: 90000; loops: Animation.Infinite; running: ov.live }
    property real scan: 0
    NumberAnimation on scan { from: 0; to: 1; duration: 6000; loops: Animation.Infinite; running: ov.live }
    property real pulse: 0
    SequentialAnimation on pulse {
        loops: Animation.Infinite; running: ov.live
        NumberAnimation { from: 0; to: 1; duration: 1100; easing.type: Easing.InOutSine }
        NumberAnimation { from: 1; to: 0; duration: 1100; easing.type: Easing.InOutSine }
    }
    property real roll: 0                      // 헬멧이 살짝 기우는 느낌
    SequentialAnimation on roll {
        loops: Animation.Infinite; running: ov.live
        NumberAnimation { from: -2.2; to: 2.2; duration: 4200; easing.type: Easing.InOutSine }
        NumberAnimation { from: 2.2; to: -2.2; duration: 4200; easing.type: Easing.InOutSine }
    }
    property real lvl: 0
    Behavior on lvl { NumberAnimation { duration: 90 } }
    onLevelChanged: lvl = Math.min(1, level)

    // 홀로그램이 가끔 지직거림
    property real flick: 1
    Timer {
        interval: 5000; running: ov.live && ov.p >= 1; repeat: true
        onTriggered: { interval = 3500 + Math.random() * 6500; flickAnim.restart() }
    }
    SequentialAnimation {
        id: flickAnim
        NumberAnimation { target: ov; property: "flick"; to: 0.45; duration: 35 }
        NumberAnimation { target: ov; property: "flick"; to: 1; duration: 45 }
        NumberAnimation { target: ov; property: "flick"; to: 0.7; duration: 30 }
        NumberAnimation { target: ov; property: "flick"; to: 1; duration: 90 }
    }

    // 최근 작업 기록
    ListModel { id: acts }
    Connections {
        target: jarvis
        function onActionEvent(id, label, status, detail) {
            for (let i = 0; i < acts.count; i++) {
                if (acts.get(i).aid === id) { acts.setProperty(i, "status", status); return }
            }
            const d = new Date()
            acts.insert(0, { aid: id, label: label, status: status, t: ov.pad(d.getHours()) + ":" + ov.pad(d.getMinutes()) })
            while (acts.count > 4) acts.remove(acts.count - 1)
        }
    }

    // 시스템 기록 (켜질 때는 부팅 순서, 그다음은 흘러가는 데이터)
    readonly property var bootLines: ["J.A.R.V.I.S  HUD  v4.2", "OPTICAL ARRAY ...... ONLINE", "VOICE CHANNEL ...... LINKED",
                                      "SENSOR GRID ........ CALIBRATED", "DIAGNOSTICS ........ NOMINAL", "ALL SYSTEMS ........ READY"]
    property int streamBase: 0
    Timer { interval: 420; running: ov.live && ov.p >= 1; repeat: true; onTriggered: ov.streamBase++ }
    function streamLine(k) {
        const tags = ["SYNC", "UPLINK", "THERMAL", "OPTIC", "AUDIO", "MEMBLK", "CACHE", "GRID", "VECTOR", "SENSOR"]
        const addr = "0x" + Math.floor(rnd(k * 1.7) * 65535).toString(16).toUpperCase().padStart(4, "0")
        if (k % 6 === 0) return addr + "  CPU       " + (stats.cpu || 0).toFixed(1) + " %"
        if (k % 6 === 3) return addr + "  MEMORY    " + (stats.ram || 0).toFixed(1) + " %"
        const tag = (tags[Math.floor(rnd(k * 3.1) * tags.length)] + "          ").substring(0, 10)
        return addr + "  " + tag + (rnd(k * 5.3) * 99.9).toFixed(2) + (rnd(k * 0.7) > 0.85 ? "  ▲" : "  OK")
    }

    // 표적 추적 박스 (화면 여기저기를 옮겨 다니며 '분석')
    property real tgx: cx + 120 * u
    property real tgy: cy - 80 * u
    property int tgn: 0
    Behavior on tgx { NumberAnimation { duration: 750; easing.type: Easing.InOutCubic } }
    Behavior on tgy { NumberAnimation { duration: 750; easing.type: Easing.InOutCubic } }
    Timer {
        interval: 3300; running: ov.live && ov.p >= 1; repeat: true
        onTriggered: {
            ov.tgn++
            ov.tgx = ov.width * (0.3 + 0.4 * Math.random())
            ov.tgy = ov.height * (0.28 + 0.42 * Math.random())
            lockAnim.restart()
        }
    }
    property real lock: 1
    SequentialAnimation {
        id: lockAnim
        NumberAnimation { target: ov; property: "lock"; to: 0; duration: 10 }
        PauseAnimation { duration: 650 }
        NumberAnimation { target: ov; property: "lock"; to: 1; duration: 450; easing.type: Easing.OutBack }
    }

    // ---------------------------------------------------------------- 공용 조각
    // 가운데에서 제자리로 날아오며 깜빡이며 켜지는 묶음. tilt: 헬멧 곡면처럼 바깥쪽이 다가오게 기울임
    component Fly: Item {
        id: fly
        property real d: 0.3
        property real tilt: 0
        readonly property real e: ov.seg(d, d + 0.32)
        visible: e > 0
        opacity: e >= 1 ? 1 : e * (0.35 + 0.65 * ov.rnd(Math.floor(ov.p * 70) + d * 977))
        transform: [
            Rotation { origin.x: fly.tilt > 0 ? fly.width : 0; origin.y: fly.height / 2; axis { x: 0; y: 1; z: 0 }
                       angle: fly.tilt * (0.4 + 0.6 * fly.e) },
            Scale { origin.x: fly.width / 2; origin.y: fly.height / 2; xScale: 0.5 + 0.5 * fly.e; yScale: 0.5 + 0.5 * fly.e },
            Translate { x: (ov.cx - (fly.x + fly.width / 2)) * (1 - fly.e); y: (ov.cy - (fly.y + fly.height / 2)) * (1 - fly.e) }
        ]
    }
    component Decode: Text {
        property string full: ""
        property real t: 1
        property int seed: 0
        text: ov.decode(full, t, seed)
        color: ov.c(0.85)
        font.family: "Bahnschrift"; font.pixelSize: 11 * ov.u; font.letterSpacing: 2 * ov.u
    }
    component Label: Text {
        color: ov.c(0.62)
        font.family: "Bahnschrift"; font.pixelSize: 9 * ov.u; font.letterSpacing: 2 * ov.u; font.weight: Font.DemiBold
    }
    // 원형 게이지 (CPU / RAM)
    component Gauge: Item {
        id: g
        property real v: 0
        property string label: ""
        property real e: 1
        property real shown: 0
        Behavior on shown { NumberAnimation { duration: 600; easing.type: Easing.OutCubic } }
        onVChanged: shown = v
        Component.onCompleted: shown = v
        width: 70 * ov.u; height: width + 16 * ov.u
        readonly property real r: width / 2 - 5 * ov.u
        Shape {
            width: g.width; height: g.width
            preferredRendererType: Shape.CurveRenderer
            ShapePath {
                strokeColor: ov.c(0.14); strokeWidth: 5 * ov.u; fillColor: "transparent"; capStyle: ShapePath.FlatCap
                PathAngleArc { centerX: g.width / 2; centerY: g.width / 2; radiusX: g.r; radiusY: g.r; startAngle: 135; sweepAngle: 270 * g.e }
            }
            ShapePath {
                strokeColor: g.v > 85 ? ov.red : ov.hot; strokeWidth: 5 * ov.u; fillColor: "transparent"; capStyle: ShapePath.FlatCap
                PathAngleArc { centerX: g.width / 2; centerY: g.width / 2; radiusX: g.r; radiusY: g.r; startAngle: 135
                               sweepAngle: 270 * Math.max(0.005, g.shown / 100) * g.e }
            }
            ShapePath {
                strokeColor: ov.c(0.4); strokeWidth: 1; fillColor: "transparent"
                strokeStyle: ShapePath.DashLine; dashPattern: [1, 3]
                PathAngleArc { centerX: g.width / 2; centerY: g.width / 2; radiusX: g.r - 9 * ov.u; radiusY: g.r - 9 * ov.u; startAngle: 0; sweepAngle: 360 * g.e }
            }
        }
        Text {
            x: 0; width: g.width; y: g.width / 2 - height / 2
            horizontalAlignment: Text.AlignHCenter
            text: Math.round(g.shown * g.e) + "%"
            color: ov.hot; font.family: "Bahnschrift"; font.pixelSize: 14 * ov.u
        }
        Label { anchors.horizontalCenter: parent.horizontalCenter; y: g.width - 4 * ov.u; text: g.label; font.pixelSize: 8 * ov.u }
    }
    // 양쪽 눈 위치의 조준 고리
    component EyeRing: Item {
        id: er
        property string tag: ""
        property bool mirror: false
        property real e: 1
        property real rr: 64 * ov.u
        readonly property int dir: mirror ? -1 : 1
        width: rr * 2; height: rr * 2
        Item {
            anchors.fill: parent
            rotation: ov.spin * 1.6 * er.dir
            Repeater {
                model: 48
                Rectangle {
                    visible: index < 48 * er.e
                    width: 1.5; height: index % 4 === 0 ? 9 * ov.u : 4 * ov.u
                    x: er.rr - width / 2; y: 0
                    color: ov.c(index % 4 === 0 ? 0.9 : 0.4)
                    transform: Rotation { origin.x: 0.75; origin.y: er.rr; angle: index * 7.5 }
                }
            }
        }
        Shape {
            anchors.fill: parent
            rotation: -ov.spin * 2.4 * er.dir
            preferredRendererType: Shape.CurveRenderer
            ShapePath {
                strokeColor: ov.hot; strokeWidth: 3 * ov.u; fillColor: "transparent"; capStyle: ShapePath.FlatCap
                PathAngleArc { centerX: er.rr; centerY: er.rr; radiusX: er.rr * 0.8; radiusY: er.rr * 0.8; startAngle: 200; sweepAngle: 120 * er.e }
            }
            ShapePath {
                strokeColor: ov.accent; strokeWidth: 7 * ov.u; fillColor: "transparent"; capStyle: ShapePath.FlatCap
                PathAngleArc { centerX: er.rr; centerY: er.rr; radiusX: er.rr * 0.8; radiusY: er.rr * 0.8; startAngle: 20; sweepAngle: 55 * er.e }
            }
            ShapePath {
                strokeColor: ov.c(0.6); strokeWidth: 1.5; fillColor: "transparent"
                strokeStyle: ShapePath.DashLine; dashPattern: [3, 3]
                PathAngleArc { centerX: er.rr; centerY: er.rr; radiusX: er.rr * 0.62; radiusY: er.rr * 0.62; startAngle: 90; sweepAngle: 360 * er.e }
            }
        }
        Rectangle {
            width: er.rr * 0.92; height: width; radius: width / 2; anchors.centerIn: parent
            color: ov.c(0.05 + 0.05 * ov.pulse); border.color: ov.c(0.3); border.width: 1
        }
        Rectangle { width: er.rr * 0.36; height: 1; anchors.centerIn: parent; color: ov.c(0.7) }
        Rectangle { width: 1; height: er.rr * 0.36; anchors.centerIn: parent; color: ov.c(0.7) }
        Rectangle { width: 5 * ov.u; height: width; radius: width / 2; anchors.centerIn: parent; color: ov.hot }
        Column {
            x: er.mirror ? -width - 10 * ov.u : er.width + 10 * ov.u
            y: er.rr * 0.15
            spacing: 2
            Decode { full: er.tag; t: er.e; seed: 11; font.pixelSize: 9 * ov.u; color: ov.c(0.9); anchors.right: er.mirror ? parent.right : undefined }
            Text {
                anchors.right: er.mirror ? parent.right : undefined
                text: (96 + 3.9 * ov.rnd(ov.slow + er.rr + (er.mirror ? 5 : 0))).toFixed(1) + " %"
                color: ov.hot; font.family: "Bahnschrift"; font.pixelSize: 15 * ov.u
            }
            Text {
                anchors.right: er.mirror ? parent.right : undefined
                text: "FOCUS " + (1.2 + ov.rnd(ov.slow * 2 + (er.mirror ? 3 : 0)) * 0.6).toFixed(2) + " m"
                color: ov.c(0.55); font.family: "Bahnschrift"; font.pixelSize: 8 * ov.u; font.letterSpacing: 1.5 * ov.u
            }
        }
    }

    // =====================================================================
    // 바탕: 헬멧 안쪽 (어두운 가장자리 + 청록 빛 + 미세한 주사선) — 빛 번짐 효과는 받지 않음
    Item {
        anchors.fill: parent
        opacity: ov.seg(0.1, 0.45) * ov.flick
        Shape {
            anchors.fill: parent
            ShapePath {
                strokeColor: "transparent"
                fillGradient: RadialGradient {
                    centerX: ov.cx; centerY: ov.cy; centerRadius: ov.diag * 0.56
                    focalX: ov.cx; focalY: ov.cy; focalRadius: 0
                    GradientStop { position: 0.0; color: "transparent" }
                    GradientStop { position: 0.55; color: Qt.rgba(0.0, 0.03, 0.06, 0.0) }
                    GradientStop { position: 0.82; color: Qt.rgba(0.0, 0.05, 0.09, 0.42) }
                    GradientStop { position: 1.0; color: Qt.rgba(0.0, 0.02, 0.05, 0.78) }
                }
                PathPolyline { path: [Qt.point(0, 0), Qt.point(ov.width, 0), Qt.point(ov.width, ov.height), Qt.point(0, ov.height), Qt.point(0, 0)] }
            }
        }
        Rectangle {
            width: parent.width * 0.14; height: parent.height
            gradient: Gradient { orientation: Gradient.Horizontal
                GradientStop { position: 0; color: ov.c(0.2) } GradientStop { position: 1; color: ov.c(0) } }
        }
        Rectangle {
            width: parent.width * 0.14; height: parent.height; anchors.right: parent.right
            gradient: Gradient { orientation: Gradient.Horizontal
                GradientStop { position: 0; color: ov.c(0) } GradientStop { position: 1; color: ov.c(0.2) } }
        }
        Canvas {   // 홀로그램 주사선 (한 번만 그림)
            anchors.fill: parent
            opacity: 0.5
            onWidthChanged: requestPaint()
            onHeightChanged: requestPaint()
            onPaint: {
                const g = getContext("2d")
                g.reset()
                g.fillStyle = "rgba(120, 230, 255, 0.07)"
                for (let y = 0; y < height; y += 3) g.fillRect(0, y, width, 1)
            }
        }
        Rectangle {   // 위에서 아래로 훑는 빛띠
            visible: ov.p >= 1
            width: parent.width; height: 120 * ov.u
            y: -height + (parent.height + height) * ov.scan
            gradient: Gradient {
                GradientStop { position: 0.0; color: ov.c(0) }
                GradientStop { position: 0.9; color: ov.c(0.05) }
                GradientStop { position: 1.0; color: ov.c(0.2) }
            }
        }
    }

    // HUD 본체 — 전체에 빛 번짐(글로우)
    Item {
        id: hud
        anchors.fill: parent
        opacity: (ov.p < 1 && ov.p > 0.12 ? (0.6 + 0.4 * ov.rnd(Math.floor(ov.p * 90))) : 1) * ov.flick
        layer.enabled: ov.visible
        layer.effect: MultiEffect {
            shadowEnabled: true
            shadowColor: ov.accent
            shadowBlur: 1.0
            blurMax: 36
            shadowOpacity: 1.0
            shadowScale: 1.0
            shadowHorizontalOffset: 0; shadowVerticalOffset: 0
            autoPaddingEnabled: false
        }

        // ---- 헬멧 바이저 곡선 + 모서리 꺾쇠 ----
        Shape {
            anchors.fill: parent
            opacity: ov.seg(0.18, 0.5)
            preferredRendererType: Shape.CurveRenderer
            ShapePath {
                strokeColor: ov.c(0.55); strokeWidth: 1.5; fillColor: "transparent"
                PathMove { x: 0; y: 0.16 * ov.height }
                PathQuad { x: ov.width; y: 0.16 * ov.height; controlX: ov.cx; controlY: -0.06 * ov.height }
                PathMove { x: 0; y: 0.86 * ov.height }
                PathQuad { x: ov.width; y: 0.86 * ov.height; controlX: ov.cx; controlY: 1.08 * ov.height }
            }
            ShapePath {
                strokeColor: ov.c(0.25); strokeWidth: 1; fillColor: "transparent"
                strokeStyle: ShapePath.DashLine; dashPattern: [6, 6]
                PathMove { x: 0; y: 0.185 * ov.height }
                PathQuad { x: ov.width; y: 0.185 * ov.height; controlX: ov.cx; controlY: -0.03 * ov.height }
                PathMove { x: 0; y: 0.835 * ov.height }
                PathQuad { x: ov.width; y: 0.835 * ov.height; controlX: ov.cx; controlY: 1.05 * ov.height }
            }
        }
        Repeater {
            model: 4
            Shape {
                id: corner
                readonly property bool onRight: index % 2 === 1
                readonly property bool onBottom: index >= 2
                readonly property real m: 20 * ov.u
                readonly property real len: 64 * ov.u * ov.seg(0.22, 0.55)
                width: len; height: len
                x: onRight ? ov.width - m - len : m
                y: onBottom ? ov.height - m - len : m
                opacity: ov.seg(0.22, 0.4)
                preferredRendererType: Shape.CurveRenderer
                ShapePath {
                    strokeColor: ov.hot; strokeWidth: 2.5; fillColor: "transparent"; capStyle: ShapePath.FlatCap
                    PathMove { x: corner.onRight ? 0 : corner.len; y: corner.onBottom ? corner.len : 0 }
                    PathLine { x: corner.onRight ? corner.len : 0; y: corner.onBottom ? corner.len : 0 }
                    PathLine { x: corner.onRight ? corner.len : 0; y: corner.onBottom ? 0 : corner.len }
                }
            }
        }

        // ---- 켜지는 순간: 충격파 고리 ----
        Repeater {
            model: 4
            Rectangle {
                readonly property real t: ov.lin(0.02 + index * 0.06, 0.42 + index * 0.06)
                visible: t > 0 && t < 1
                width: 30 + ov.diag * 1.05 * (1 - Math.pow(1 - t, 2.2)); height: width; radius: width / 2
                x: ov.cx - width / 2; y: ov.cy - height / 2
                color: "transparent"
                border.color: index === 0 ? ov.hot : ov.accent
                border.width: (index === 0 ? 5 : 2) * (1 - t) + 1
                opacity: (1 - t) * (index === 0 ? 0.95 : 0.55)
            }
        }
        // ---- 사방으로 뻗는 빛줄기 ----
        Repeater {
            model: 64
            Item {
                readonly property real jit: ov.rnd(index)
                readonly property real t: ov.lin(0.03 + jit * 0.14, 0.33 + jit * 0.14)
                visible: t > 0 && t < 1
                x: ov.cx; y: ov.cy
                rotation: index * (360 / 64) + jit * 5
                Rectangle {
                    readonly property real len: (60 + 180 * parent.jit) * ov.u
                    x: -width / 2
                    y: -(50 * ov.u + (ov.diag / 2) * parent.t) - len
                    width: 1 + 1.6 * parent.jit; height: len
                    opacity: Math.sin(parent.t * Math.PI) * 0.9
                    gradient: Gradient {
                        GradientStop { position: 0.0; color: "#ffffff" }
                        GradientStop { position: 1.0; color: ov.c(0) }
                    }
                }
            }
        }

        // ---- 표적 추적 박스 (빨강) ----
        Item {
            id: tg
            visible: ov.p >= 1
            readonly property real sz: (110 - 50 * ov.lock) * ov.u
            x: ov.tgx - sz / 2; y: ov.tgy - sz / 2
            width: sz; height: sz
            Repeater {
                model: 4
                Shape {
                    id: tc
                    readonly property bool onRight: index % 2 === 1
                    readonly property bool onBottom: index >= 2
                    readonly property real len: 12 * ov.u
                    width: len; height: len
                    x: onRight ? tg.width - len : 0
                    y: onBottom ? tg.height - len : 0
                    preferredRendererType: Shape.CurveRenderer
                    ShapePath {
                        strokeColor: ov.red; strokeWidth: 2; fillColor: "transparent"; capStyle: ShapePath.FlatCap
                        PathMove { x: tc.onRight ? 0 : tc.len; y: tc.onBottom ? tc.len : 0 }
                        PathLine { x: tc.onRight ? tc.len : 0; y: tc.onBottom ? tc.len : 0 }
                        PathLine { x: tc.onRight ? tc.len : 0; y: tc.onBottom ? 0 : tc.len }
                    }
                }
            }
            Rectangle {
                anchors.centerIn: parent
                width: 10 * ov.u; height: width; rotation: 45
                color: "transparent"; border.color: ov.red; border.width: 1.5
                opacity: ov.lock
            }
            Column {
                x: tg.width + 8 * ov.u; y: 0
                spacing: 1
                Text {
                    text: ov.lock >= 1 ? "LOCKED" : "ANALYZING" + ".".repeat(1 + ov.tick % 3)
                    color: ov.red; font.family: "Bahnschrift"; font.pixelSize: 10 * ov.u; font.letterSpacing: 2 * ov.u; font.weight: Font.DemiBold
                }
                Text {
                    text: "OBJ-" + ov.pad(ov.tgn % 100) + "  ·  " + (2 + ov.rnd(ov.tgn) * 40).toFixed(1) + " m"
                    color: ov.rc(0.75); font.family: "Bahnschrift"; font.pixelSize: 8 * ov.u; font.letterSpacing: 1.5 * ov.u
                }
            }
        }

        // ---- 가운데 조준경 ----
        Item {
            id: reticle
            readonly property real rr: 168 * ov.u
            readonly property real e: ov.seg(0.05, 0.45)
            readonly property real draw: ov.seg(0.2, 0.7)     // 고리가 그려지는 진행도
            width: rr * 2; height: rr * 2
            x: ov.cx - rr; y: ov.cy - rr
            visible: e > 0
            opacity: Math.min(1, e * 1.4)
            scale: 0.15 + 0.85 * e + Math.sin(e * Math.PI) * 0.14

            Rectangle { anchors.fill: parent; radius: width / 2; color: "transparent"; border.color: ov.c(0.25); border.width: 1 }
            // 바깥 눈금 고리
            Item {
                anchors.fill: parent
                rotation: -ov.spin * 0.25
                Repeater {
                    model: 120
                    Rectangle {
                        visible: index < 120 * reticle.draw
                        width: index % 10 === 0 ? 2 : 1
                        height: index % 10 === 0 ? 14 * ov.u : (index % 5 === 0 ? 8 * ov.u : 4 * ov.u)
                        x: reticle.rr - width / 2; y: 2
                        color: index % 10 === 0 ? ov.hot : ov.c(0.4)
                        transform: Rotation { origin.x: width / 2; origin.y: reticle.rr - 2; angle: index * 3 }
                    }
                }
                Repeater {
                    model: 4
                    Item {
                        x: reticle.rr; y: reticle.rr
                        rotation: index * 90
                        Text {
                            x: -width / 2; y: -reticle.rr - 18 * ov.u
                            text: ("00" + index * 90).slice(-3)
                            color: ov.c(0.7); font.family: "Bahnschrift"; font.pixelSize: 9 * ov.u
                        }
                    }
                }
            }
            // 소리 스펙트럼 고리 (목소리 · 마이크에 반응)
            Repeater {
                model: 72
                Rectangle {
                    readonly property real amp: (0.08 + ov.lvl * (0.35 + 0.65 * ov.rnd(index * 3.3 + ov.tick))) * (index < 72 * reticle.draw ? 1 : 0)
                    width: 2 * ov.u; height: 3 * ov.u + 26 * ov.u * amp
                    x: reticle.rr - width / 2
                    y: reticle.rr - reticle.rr * 0.74 - height
                    color: ov.c(0.35 + 0.6 * amp)
                    transform: Rotation { origin.x: width / 2; origin.y: reticle.rr * 0.74 + height; angle: index * 5 }
                }
            }
            // 분절 고리 (시계 방향)
            Shape {
                anchors.fill: parent
                rotation: ov.spin
                preferredRendererType: Shape.CurveRenderer
                ShapePath {
                    strokeColor: ov.hot; strokeWidth: 6 * ov.u; fillColor: "transparent"; capStyle: ShapePath.FlatCap
                    PathAngleArc { centerX: reticle.rr; centerY: reticle.rr; radiusX: reticle.rr * 0.88; radiusY: reticle.rr * 0.88; startAngle: 10; sweepAngle: 70 * reticle.draw }
                    PathAngleArc { centerX: reticle.rr; centerY: reticle.rr; radiusX: reticle.rr * 0.88; radiusY: reticle.rr * 0.88; startAngle: 130; sweepAngle: 40 * reticle.draw }
                    PathAngleArc { centerX: reticle.rr; centerY: reticle.rr; radiusX: reticle.rr * 0.88; radiusY: reticle.rr * 0.88; startAngle: 215; sweepAngle: 95 * reticle.draw }
                }
                ShapePath {
                    strokeColor: ov.c(0.35); strokeWidth: 1; fillColor: "transparent"
                    PathAngleArc { centerX: reticle.rr; centerY: reticle.rr; radiusX: reticle.rr * 0.94; radiusY: reticle.rr * 0.94; startAngle: 0; sweepAngle: 360 * reticle.draw }
                }
            }
            // 점선 고리 (반시계 방향)
            Shape {
                anchors.fill: parent
                rotation: -ov.spin * 2.2
                preferredRendererType: Shape.CurveRenderer
                ShapePath {
                    strokeColor: ov.c(0.5); strokeWidth: 2; fillColor: "transparent"
                    strokeStyle: ShapePath.DashLine; dashPattern: [2, 5]
                    PathAngleArc { centerX: reticle.rr; centerY: reticle.rr; radiusX: reticle.rr * 0.6; radiusY: reticle.rr * 0.6; startAngle: 0; sweepAngle: 300 * reticle.draw }
                }
                ShapePath {
                    strokeColor: ov.accent; strokeWidth: 4 * ov.u; fillColor: "transparent"; capStyle: ShapePath.FlatCap
                    PathAngleArc { centerX: reticle.rr; centerY: reticle.rr; radiusX: reticle.rr * 0.6; radiusY: reticle.rr * 0.6; startAngle: 310; sweepAngle: 40 * reticle.draw }
                }
            }
            // 목소리 크기에 따라 늘어나는 호 (좌우)
            Shape {
                anchors.fill: parent
                preferredRendererType: Shape.CurveRenderer
                ShapePath {
                    strokeColor: ov.hot; strokeWidth: 3 * ov.u; fillColor: "transparent"; capStyle: ShapePath.FlatCap
                    PathAngleArc { centerX: reticle.rr; centerY: reticle.rr; radiusX: reticle.rr * 0.5; radiusY: reticle.rr * 0.5
                                   startAngle: 180 - (8 + 62 * ov.lvl); sweepAngle: 2 * (8 + 62 * ov.lvl) }
                    PathAngleArc { centerX: reticle.rr; centerY: reticle.rr; radiusX: reticle.rr * 0.5; radiusY: reticle.rr * 0.5
                                   startAngle: -(8 + 62 * ov.lvl); sweepAngle: 2 * (8 + 62 * ov.lvl) }
                }
            }
            // 수평선 (헬멧 기울기)
            Item {
                anchors.fill: parent
                rotation: ov.roll
                Repeater {
                    model: 2
                    Item {
                        x: index === 0 ? -64 * ov.u : reticle.width + 8 * ov.u
                        y: reticle.rr
                        Rectangle { width: 56 * ov.u; height: 1.5; color: ov.c(0.85) }
                        Rectangle { x: index === 0 ? 56 * ov.u - 1.5 : 0; width: 1.5; height: 8 * ov.u; color: ov.c(0.85) }
                    }
                }
            }
            // 가운데 십자선
            Repeater {
                model: 4
                Rectangle {
                    readonly property bool hz: index < 2
                    readonly property real gap: 12 * ov.u
                    readonly property real len: 30 * ov.u
                    width: hz ? len : 1.5; height: hz ? 1.5 : len
                    x: hz ? (index === 0 ? reticle.rr - gap - len : reticle.rr + gap) : reticle.rr - 0.75
                    y: hz ? reticle.rr - 0.75 : (index === 2 ? reticle.rr - gap - len : reticle.rr + gap)
                    color: ov.c(0.85)
                }
            }
            Rectangle {
                width: 6 * ov.u; height: width; radius: width / 2
                x: reticle.rr - width / 2; y: reticle.rr - height / 2
                color: ov.hot
                opacity: 0.6 + 0.4 * ov.pulse
            }
            Repeater {
                model: 4
                Item {
                    x: reticle.rr; y: reticle.rr
                    rotation: index * 90 + 45
                    Rectangle {
                        width: 9 * ov.u; height: 9 * ov.u; rotation: 45
                        x: -width / 2; y: -reticle.rr - 12 * ov.u - 6 * ov.u * ov.pulse
                        color: "transparent"; border.color: ov.accent; border.width: 1.5
                    }
                }
            }
        }
        // 조준경 바깥 큰 괄호 호 (좌우)
        Shape {
            id: brk
            readonly property real e: ov.seg(0.3, 0.7)
            readonly property real r1: reticle.rr * 1.24
            x: ov.cx - r1; y: ov.cy - r1
            width: r1 * 2; height: r1 * 2
            opacity: e
            preferredRendererType: Shape.CurveRenderer
            ShapePath {
                strokeColor: ov.c(0.75); strokeWidth: 2; fillColor: "transparent"; capStyle: ShapePath.FlatCap
                PathAngleArc { centerX: brk.r1; centerY: brk.r1; radiusX: brk.r1; radiusY: brk.r1; startAngle: 180 - 32 * brk.e; sweepAngle: 64 * brk.e }
                PathAngleArc { centerX: brk.r1; centerY: brk.r1; radiusX: brk.r1; radiusY: brk.r1; startAngle: -32 * brk.e; sweepAngle: 64 * brk.e }
            }
            ShapePath {
                strokeColor: ov.c(0.35); strokeWidth: 5 * ov.u; fillColor: "transparent"; capStyle: ShapePath.FlatCap
                strokeStyle: ShapePath.DashLine; dashPattern: [0.6, 1.2]
                PathAngleArc { centerX: brk.r1; centerY: brk.r1; radiusX: brk.r1 - 8 * ov.u; radiusY: brk.r1 - 8 * ov.u; startAngle: 180 - 24 * brk.e; sweepAngle: 48 * brk.e }
                PathAngleArc { centerX: brk.r1; centerY: brk.r1; radiusX: brk.r1 - 8 * ov.u; radiusY: brk.r1 - 8 * ov.u; startAngle: -24 * brk.e; sweepAngle: 48 * brk.e }
            }
        }
        // 조준경 대각선 수치
        Repeater {
            model: [["ALT", (120 + ov.rnd(ov.slow) * 4).toFixed(1) + " m"], ["VEL", (ov.lvl * 40 + ov.rnd(ov.slow + 1) * 2).toFixed(1) + " m/s"],
                    ["PWR", (99 + ov.rnd(ov.slow + 2)).toFixed(1) + " %"], ["SYS", Math.round(ov.stats.cpu || 0) + " / " + Math.round(ov.stats.ram || 0)]]
            Column {
                readonly property bool onRight: index % 2 === 1
                readonly property bool onBottom: index >= 2
                readonly property real off: reticle.rr * 0.86
                x: onRight ? ov.cx + off : ov.cx - off - width
                y: onBottom ? ov.cy + off - height : ov.cy - off
                opacity: ov.seg(0.55, 0.85)
                spacing: 0
                Text { anchors.right: parent.onRight ? undefined : parent.right; text: modelData[0]
                       color: ov.c(0.6); font.family: "Bahnschrift"; font.pixelSize: 8 * ov.u; font.letterSpacing: 2 * ov.u; font.weight: Font.DemiBold }
                Text { anchors.right: parent.onRight ? undefined : parent.right; text: modelData[1]
                       color: ov.hot; font.family: "Bahnschrift"; font.pixelSize: 12 * ov.u }
            }
        }
        // 조준경 아래 상태 글
        Column {
            anchors.horizontalCenter: parent.horizontalCenter
            y: ov.cy + reticle.rr + 18 * ov.u
            spacing: 4 * ov.u
            opacity: ov.seg(0.45, 0.7)
            Decode {
                anchors.horizontalCenter: parent.horizontalCenter
                full: ov.p < 1 ? "ACTIVE MODE ENGAGED" : (ov.stateLabels[ov.st] || ov.st.toUpperCase())
                t: ov.lin(0.45, 0.8); seed: 3
                color: ov.hot
                font.pixelSize: 15 * ov.u; font.letterSpacing: 6 * ov.u; font.weight: Font.DemiBold
            }
            Decode {
                anchors.horizontalCenter: parent.horizontalCenter
                full: jarvis.statusText
                t: ov.lin(0.6, 0.92); seed: 5
                color: ov.c(0.65)
                font.pixelSize: 10 * ov.u
            }
        }

        // ---- 양쪽 눈 조준 고리 ----
        EyeRing {
            tag: "OPTIC · L"; mirror: true
            e: ov.seg(0.35, 0.75)
            visible: e > 0
            x: ov.cx - 300 * ov.u - rr; y: ov.cy - 40 * ov.u - rr
            opacity: e
        }
        EyeRing {
            tag: "OPTIC · R"
            e: ov.seg(0.38, 0.78)
            visible: e > 0
            x: ov.cx + 300 * ov.u - rr; y: ov.cy - 40 * ov.u - rr
            opacity: e
        }

        // ---- 위쪽: 방위 테이프 + 제목 ----
        Fly {
            d: 0.3
            width: ov.width * 0.36; height: 64 * ov.u
            x: ov.cx - width / 2; y: 20 * ov.u
            Item {
                id: hd
                width: parent.width; height: 30 * ov.u
                clip: true
                readonly property real k: width / 120    // 화면에 보이는 각도 120°
                Repeater {
                    model: 72 * 2
                    Item {
                        readonly property real deg: (index % 72) * 5 + (index >= 72 ? 360 : 0)
                        readonly property real xx: hd.width / 2 + (deg - ov.heading) * hd.k
                        readonly property real wrapped: xx < -20 ? xx + 360 * hd.k : xx
                        visible: wrapped > -10 && wrapped < hd.width + 10
                        x: wrapped
                        readonly property real fade: 1 - Math.min(1, Math.abs(wrapped - hd.width / 2) / (hd.width / 2))
                        Rectangle {
                            width: 1; height: (index % 72) % 3 === 0 ? 10 * ov.u : 5 * ov.u
                            y: hd.height - height
                            color: ov.c(0.2 + 0.7 * parent.fade)
                        }
                        Text {
                            readonly property int dd: (index % 72) * 5
                            visible: dd % 45 === 0
                            text: dd % 45 === 0 ? ["N", "NE", "E", "SE", "S", "SW", "W", "NW"][dd / 45] : ""
                            x: -width / 2; y: 0
                            color: dd === 0 ? ov.hot : ov.c(0.25 + 0.7 * parent.fade)
                            font.family: "Bahnschrift"; font.pixelSize: 11 * ov.u; font.weight: Font.DemiBold
                        }
                    }
                }
            }
            Rectangle { width: 1.5; height: 16 * ov.u; color: ov.hot; x: parent.width / 2; y: 26 * ov.u }
            Decode {
                anchors.horizontalCenter: parent.horizontalCenter
                y: 44 * ov.u
                full: "J.A.R.V.I.S   ·   ACTIVE MODE   ·   HDG " + ("00" + Math.floor(ov.heading)).slice(-3)
                t: ov.lin(0.4, 0.75); seed: 1
                font.letterSpacing: 4 * ov.u; font.weight: Font.DemiBold
            }
        }
        // CPU 기록 막대
        Fly {
            d: 0.55
            width: 240 * ov.u; height: 40 * ov.u
            x: ov.cx - width / 2; y: ov.height * 0.17 + 24 * ov.u
            Row {
                anchors.bottom: parent.bottom
                anchors.horizontalCenter: parent.horizontalCenter
                spacing: 1
                Repeater {
                    model: ov.cpuHist
                    Rectangle {
                        width: 4 * ov.u; height: Math.max(1, 32 * ov.u * modelData / 100)
                        anchors.bottom: parent.bottom
                        color: ov.c(0.25 + 0.6 * (index / Math.max(1, ov.cpuHist.length)))
                    }
                }
            }
            Label { text: "LOAD HISTORY · 48 s"; font.pixelSize: 8 * ov.u; anchors.horizontalCenter: parent.horizontalCenter; y: -6 * ov.u }
        }

        // ---- 왼쪽 가장자리: 빨간 화살표 기둥 ----
        Item {
            x: 22 * ov.u; y: ov.cy - 120 * ov.u
            width: 30 * ov.u; height: 240 * ov.u
            opacity: ov.seg(0.5, 0.75)
            Repeater {
                model: 6
                Text {
                    readonly property real ph: ((ov.scan * 6 + index) % 6) / 6
                    anchors.horizontalCenter: parent.horizontalCenter
                    y: parent.height * (1 - ph) - height
                    text: "︿"
                    color: ov.red
                    opacity: Math.sin(ph * Math.PI)
                    font.pixelSize: 26 * ov.u; font.weight: Font.Bold
                }
            }
            Text {
                anchors.horizontalCenter: parent.horizontalCenter
                y: parent.height + 6 * ov.u
                text: "LIFT"
                color: ov.red; font.family: "Bahnschrift"; font.pixelSize: 9 * ov.u; font.letterSpacing: 2 * ov.u; font.weight: Font.DemiBold
            }
        }

        // ---- 왼쪽 위: 시간 ----
        Fly {
            d: 0.34; tilt: 22
            x: 62 * ov.u; y: ov.height * 0.2
            width: 300 * ov.u; height: 132 * ov.u
            HoloPanel { anchors.fill: parent; accent: ov.accent; fillAlpha: 0.1; cut: 12; title: "SYSTEM TIME"; tag: "KST // UTC+9" }
            // 날짜 고리
            Item {
                id: dayRing
                x: 14 * ov.u; y: 32 * ov.u
                width: 88 * ov.u; height: width
                Shape {
                    anchors.fill: parent
                    preferredRendererType: Shape.CurveRenderer
                    ShapePath {
                        strokeColor: ov.c(0.18); strokeWidth: 4 * ov.u; fillColor: "transparent"
                        PathAngleArc { centerX: dayRing.width / 2; centerY: dayRing.width / 2; radiusX: 40 * ov.u; radiusY: 40 * ov.u; startAngle: 0; sweepAngle: 360 }
                    }
                    ShapePath {
                        strokeColor: ov.hot; strokeWidth: 4 * ov.u; fillColor: "transparent"; capStyle: ShapePath.FlatCap
                        PathAngleArc { centerX: dayRing.width / 2; centerY: dayRing.width / 2; radiusX: 40 * ov.u; radiusY: 40 * ov.u
                                       startAngle: -90; sweepAngle: Math.max(1, 6 * (ov.now.getSeconds() + ov.now.getMilliseconds() / 1000)) }
                    }
                    ShapePath {
                        strokeColor: ov.c(0.45); strokeWidth: 1; fillColor: "transparent"
                        strokeStyle: ShapePath.DashLine; dashPattern: [1, 4]
                        PathAngleArc { centerX: dayRing.width / 2; centerY: dayRing.width / 2; radiusX: 32 * ov.u; radiusY: 32 * ov.u; startAngle: 0; sweepAngle: 360 }
                    }
                }
                Text {
                    anchors.centerIn: parent
                    text: ov.now.getDate()
                    color: ov.hot; font.family: "Bahnschrift"; font.pixelSize: 30 * ov.u; font.weight: Font.Light
                }
            }
            Column {
                x: 112 * ov.u; y: 30 * ov.u
                spacing: 0
                Text {
                    text: ov.pad(ov.now.getHours()) + ":" + ov.pad(ov.now.getMinutes())
                    color: ov.hot; font.family: "Bahnschrift"; font.pixelSize: 44 * ov.u; font.weight: Font.Light
                }
                Decode {
                    full: ["SUNDAY", "MONDAY", "TUESDAY", "WEDNESDAY", "THURSDAY", "FRIDAY", "SATURDAY"][ov.now.getDay()]
                    t: ov.lin(0.5, 0.8); seed: 7
                    font.pixelSize: 12 * ov.u; font.letterSpacing: 3 * ov.u
                }
                Text {
                    text: ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"][ov.now.getMonth()] + " " + ov.now.getFullYear()
                          + "   ·   " + ov.pad(ov.now.getSeconds()) + " s"
                    color: ov.c(0.55); font.family: "Bahnschrift"; font.pixelSize: 9 * ov.u; font.letterSpacing: 2 * ov.u
                }
            }
        }

        // ---- 왼쪽 가운데: 시스템 기록 ----
        Fly {
            d: 0.4; tilt: 22
            x: 62 * ov.u; y: ov.height * 0.2 + 146 * ov.u
            width: 300 * ov.u; height: 150 * ov.u
            HoloPanel { anchors.fill: parent; accent: ov.accent; fillAlpha: 0.1; cut: 12; title: "SYSTEM LOG"; tag: "STREAM " + ov.pad(ov.streamBase % 100) }
            Column {
                x: 14 * ov.u; y: 30 * ov.u
                spacing: 3 * ov.u
                Repeater {
                    model: 7
                    Text {
                        readonly property bool boot: ov.p < 1 || ov.streamBase < 3
                        text: boot ? (index < ov.bootLines.length ? ov.decode(ov.bootLines[index], ov.lin(0.45 + index * 0.07, 0.6 + index * 0.07), index) : "")
                                   : ov.streamLine(ov.streamBase + index)
                        color: index === 6 || (boot && index === 5) ? ov.hot : ov.c(0.4 + 0.08 * index)
                        font.family: "Consolas"; font.pixelSize: 10 * ov.u
                    }
                }
            }
        }

        // ---- 왼쪽 아래: 레이더 ----
        Fly {
            d: 0.46; tilt: 22
            x: 62 * ov.u; width: 300 * ov.u; height: 214 * ov.u
            y: ov.height * 0.8 - height
            HoloPanel { anchors.fill: parent; accent: ov.accent; fillAlpha: 0.1; cut: 12; title: "PROXIMITY SCAN"; tag: "RANGE 2.4 KM" }
            Item {
                id: radar
                readonly property real sz: 166 * ov.u
                width: sz; height: sz
                x: 14 * ov.u; y: 34 * ov.u
                Repeater {
                    model: 3
                    Rectangle {
                        width: radar.sz * (index + 1) / 3; height: width; radius: width / 2
                        x: (radar.sz - width) / 2; y: (radar.sz - height) / 2
                        color: "transparent"; border.color: ov.c(index === 2 ? 0.5 : 0.22); border.width: 1
                    }
                }
                Rectangle { width: radar.sz; height: 1; y: radar.sz / 2; color: ov.c(0.2) }
                Rectangle { width: 1; height: radar.sz; x: radar.sz / 2; color: ov.c(0.2) }
                Shape {
                    anchors.fill: parent
                    rotation: ov.sweep
                    preferredRendererType: Shape.CurveRenderer
                    ShapePath {
                        strokeColor: "transparent"
                        fillGradient: ConicalGradient {
                            centerX: radar.sz / 2; centerY: radar.sz / 2; angle: 0
                            GradientStop { position: 0.0; color: ov.c(0.6) }
                            GradientStop { position: 0.22; color: ov.c(0.0) }
                            GradientStop { position: 1.0; color: ov.c(0.0) }
                        }
                        PathAngleArc { centerX: radar.sz / 2; centerY: radar.sz / 2; radiusX: radar.sz / 2; radiusY: radar.sz / 2; startAngle: 0; sweepAngle: 360 }
                    }
                    Rectangle { x: radar.sz / 2; y: radar.sz / 2 - 0.75; width: radar.sz / 2; height: 1.5; color: ov.hot }
                }
                Repeater {
                    model: 6
                    Rectangle {
                        readonly property real a: ov.rnd(index + 40) * 360
                        readonly property real dist: (0.25 + 0.7 * ov.rnd(index + 90)) * radar.sz / 2
                        readonly property real since: ((ov.sweep - a) % 360 + 360) % 360
                        width: 6 * ov.u; height: width; radius: width / 2
                        x: radar.sz / 2 + Math.cos(a * Math.PI / 180) * dist - width / 2
                        y: radar.sz / 2 + Math.sin(a * Math.PI / 180) * dist - height / 2
                        color: index === 0 ? ov.red : ov.hot
                        opacity: Math.max(0, 1 - since / 220)
                    }
                }
            }
            Column {
                x: 14 * ov.u + radar.sz + 14 * ov.u; y: 40 * ov.u
                spacing: 8 * ov.u
                Repeater {
                    model: [["CONTACTS", "06"], ["FLAGGED", "01"], ["SWEEP", "3.2 s"], ["SIGNAL", (95 + ov.rnd(ov.slow) * 4.9).toFixed(1) + "%"]]
                    Column {
                        spacing: 1
                        Label { text: modelData[0]; font.pixelSize: 8 * ov.u }
                        Text { text: modelData[1]; color: modelData[0] === "FLAGGED" ? ov.red : ov.hot
                               font.family: "Bahnschrift"; font.pixelSize: 14 * ov.u }
                    }
                }
            }
        }

        // ---- 오른쪽 위: 경고 감시 (빨강) ----
        Fly {
            id: alertBox
            d: 0.36; tilt: -22
            width: 300 * ov.u; height: 118 * ov.u
            x: ov.width - 62 * ov.u - width; y: ov.height * 0.2
            readonly property bool cpuHi: (ov.stats.cpu || 0) > 85
            readonly property bool ramHi: (ov.stats.ram || 0) > 88
            readonly property bool batLo: ov.stats.bat !== undefined && ov.stats.bat >= 0 && ov.stats.bat < 20 && !ov.stats.plugged
            readonly property bool alert: cpuHi || ramHi || batLo
            Rectangle {
                anchors.fill: parent
                color: ov.rc(alertBox.alert ? 0.14 + 0.08 * ov.pulse : 0.06)
                border.color: ov.rc(alertBox.alert ? 0.95 : 0.7); border.width: 1.5
            }
            Rectangle {
                width: parent.width; height: 20 * ov.u
                color: ov.rc(0.75)
                Row {
                    x: 10 * ov.u; anchors.verticalCenter: parent.verticalCenter
                    spacing: 8 * ov.u
                    Rectangle { width: 7 * ov.u; height: width; radius: width / 2; color: "#fff"; opacity: 0.4 + 0.6 * ov.pulse; anchors.verticalCenter: parent.verticalCenter }
                    Text { text: "ALERT MONITOR"; color: "#fff"; font.family: "Bahnschrift"; font.pixelSize: 10 * ov.u; font.letterSpacing: 3 * ov.u; font.weight: Font.DemiBold }
                }
                Text {
                    anchors.right: parent.right; anchors.rightMargin: 10 * ov.u; anchors.verticalCenter: parent.verticalCenter
                    text: alertBox.alert ? "WARNING" : "CLEAR"
                    color: "#fff"; font.family: "Bahnschrift"; font.pixelSize: 9 * ov.u; font.letterSpacing: 2 * ov.u
                }
            }
            Column {
                x: 12 * ov.u; y: 28 * ov.u
                width: parent.width - 24 * ov.u
                spacing: 4 * ov.u
                Repeater {
                    model: 4
                    Item {
                        readonly property var row: [
                            ["PROCESSOR LOAD", Math.round(ov.stats.cpu || 0) + "%", alertBox.cpuHi],
                            ["MEMORY PRESSURE", Math.round(ov.stats.ram || 0) + "%", alertBox.ramHi],
                            ["POWER CELL", (ov.stats.bat === undefined || ov.stats.bat < 0) ? "AC LINE" : Math.round(ov.stats.bat) + "%", alertBox.batLo],
                            ["NETWORK UPLINK", ov.rate(ov.stats.down), false]][index]
                        width: parent.width; height: 16 * ov.u
                        Text { text: ov.decode(row[0], ov.lin(0.5 + index * 0.05, 0.75 + index * 0.05), index + 20)
                               color: row[2] ? ov.red : ov.rc(0.9); font.family: "Bahnschrift"; font.pixelSize: 10 * ov.u; font.letterSpacing: 1.5 * ov.u }
                        Text { anchors.right: parent.right; text: row[1] + (row[2] ? "  ▲" : "")
                               color: row[2] ? ov.red : ov.hot; font.family: "Bahnschrift"; font.pixelSize: 11 * ov.u }
                    }
                }
            }
        }

        // ---- 오른쪽 가운데: 진단 게이지 ----
        Fly {
            d: 0.42; tilt: -22
            width: 300 * ov.u; height: 150 * ov.u
            x: ov.width - 62 * ov.u - width; y: ov.height * 0.2 + 132 * ov.u
            HoloPanel { anchors.fill: parent; accent: ov.accent; fillAlpha: 0.1; cut: 12; title: "DIAGNOSTICS"; tag: "SUBSYSTEMS" }
            Row {
                x: 16 * ov.u; y: 32 * ov.u
                spacing: 24 * ov.u
                Gauge { v: ov.stats.cpu || 0; label: "CPU"; e: ov.seg(0.5, 0.85) }
                Gauge { v: ov.stats.ram || 0; label: "MEMORY"; e: ov.seg(0.55, 0.9) }
                // 저장공간: 파이
                Item {
                    id: pie
                    width: 70 * ov.u; height: width + 16 * ov.u
                    readonly property real used: (ov.stats.disk || 0) / 100 * ov.seg(0.6, 0.95)
                    Shape {
                        width: pie.width; height: pie.width
                        preferredRendererType: Shape.CurveRenderer
                        ShapePath {
                            strokeColor: ov.c(0.5); strokeWidth: 1; fillColor: ov.c(0.08)
                            PathAngleArc { centerX: pie.width / 2; centerY: pie.width / 2; radiusX: pie.width / 2 - 3; radiusY: pie.width / 2 - 3; startAngle: 0; sweepAngle: 360 }
                        }
                        ShapePath {
                            strokeColor: "transparent"; fillColor: ov.c(0.75)
                            PathMove { x: pie.width / 2; y: pie.width / 2 }
                            PathAngleArc { moveToStart: false; centerX: pie.width / 2; centerY: pie.width / 2; radiusX: pie.width / 2 - 7; radiusY: pie.width / 2 - 7
                                           startAngle: -90; sweepAngle: 360 * Math.max(0.002, pie.used) }
                            PathLine { x: pie.width / 2; y: pie.width / 2 }
                        }
                    }
                    Text { anchors.horizontalCenter: parent.horizontalCenter; y: pie.width / 2 - height / 2
                           text: Math.round(pie.used * 100) + "%"; color: "#ffffff"; font.family: "Bahnschrift"; font.pixelSize: 12 * ov.u
                           style: Text.Outline; styleColor: Qt.rgba(0, 0.1, 0.15, 0.6) }
                    Label { anchors.horizontalCenter: parent.horizontalCenter; y: pie.width - 4 * ov.u; text: "STORAGE"; font.pixelSize: 8 * ov.u }
                }
            }
            Row {
                x: 16 * ov.u; y: 124 * ov.u
                spacing: 18 * ov.u
                Label { text: "▼ " + ov.rate(ov.stats.down); color: ov.hot; font.pixelSize: 9 * ov.u }
                Label { text: "▲ " + ov.rate(ov.stats.up); color: ov.hot; font.pixelSize: 9 * ov.u }
                Label { text: "SYNC " + (97 + ov.rnd(ov.slow) * 2.9).toFixed(1) + "%"; font.pixelSize: 9 * ov.u }
            }
        }

        // ---- 오른쪽 아래: 통신 기록 ----
        Fly {
            d: 0.5; tilt: -22
            width: 300 * ov.u; height: 214 * ov.u
            x: ov.width - 62 * ov.u - width; y: ov.height * 0.8 - height
            HoloPanel { anchors.fill: parent; accent: ov.accent; fillAlpha: 0.1; cut: 12; title: "COMMS LINK"; tag: jarvis.chatMode ? "CHAT MODE" : "SECURE" }
            Column {
                x: 14 * ov.u; y: 32 * ov.u
                width: parent.width - 28 * ov.u
                spacing: 5 * ov.u
                Label { text: "▸ OPERATOR"; font.pixelSize: 8 * ov.u }
                Text {
                    width: parent.width; text: jarvis.userText || "—"
                    color: ov.hot; font.pixelSize: 12 * ov.u; elide: Text.ElideRight; maximumLineCount: 2; wrapMode: Text.Wrap
                }
                Label { text: "▸ J.A.R.V.I.S"; font.pixelSize: 8 * ov.u }
                Text {
                    width: parent.width; text: jarvis.replyText || "—"
                    color: ov.c(0.95); font.pixelSize: 12 * ov.u; elide: Text.ElideRight; maximumLineCount: 2; wrapMode: Text.Wrap
                }
                Rectangle { width: parent.width; height: 1; color: ov.c(0.25) }
                Repeater {
                    model: acts
                    Row {
                        spacing: 6 * ov.u
                        Rectangle {
                            width: 5 * ov.u; height: width; rotation: 45
                            anchors.verticalCenter: parent.verticalCenter
                            color: status === "error" ? ov.red : status === "run" ? "#ffb347" : "#53ffa8"
                        }
                        Text { text: t; color: ov.c(0.55); font.family: "Bahnschrift"; font.pixelSize: 9 * ov.u }
                        Text { text: label; color: ov.c(0.85); font.pixelSize: 10 * ov.u; elide: Text.ElideRight; width: 220 * ov.u }
                    }
                }
            }
        }

        // ---- 아래 가운데: 음성 파형 ----
        Fly {
            d: 0.55
            width: 420 * ov.u; height: 70 * ov.u
            x: ov.cx - width / 2; y: ov.cy + reticle.rr + 70 * ov.u
            Row {
                anchors.horizontalCenter: parent.horizontalCenter
                height: 44 * ov.u
                spacing: 3 * ov.u
                Repeater {
                    model: 41
                    Rectangle {
                        readonly property real centerFade: 1 - Math.abs(index - 20) / 21
                        readonly property real wob: 0.5 + 0.5 * Math.sin(ov.sweep * Math.PI / 180 * 6 + index * 0.9)
                        width: 4 * ov.u
                        height: Math.max(2, 44 * ov.u * centerFade * (0.08 + ov.lvl * (0.5 + 0.5 * wob)))
                        anchors.verticalCenter: parent.verticalCenter
                        radius: 1
                        color: ov.c(0.35 + 0.6 * centerFade)
                    }
                }
            }
            Label {
                anchors.horizontalCenter: parent.horizontalCenter
                y: 50 * ov.u
                text: "VOICE CHANNEL  ·  " + (jarvis.wakeEnabled ? "WAKE WORD ARMED" : "HOTKEY " + jarvis.hotkeyText)
                font.pixelSize: 9 * ov.u
            }
        }
    }

    // ---- 켜지는 순간: 섬광 + 가로 렌즈 플레어 (글로우 위에 얹음) ----
    Rectangle {
        anchors.fill: parent
        readonly property real t: ov.lin(0.0, 0.16)
        visible: t > 0 && t < 1
        color: ov.hot
        opacity: Math.sin(t * Math.PI) * 0.22
    }
    Item {
        readonly property real t: ov.lin(0.0, 0.32)
        visible: t > 0 && t < 1
        anchors.fill: parent
        opacity: Math.sin(t * Math.PI)
        Rectangle {
            width: ov.width * (0.1 + 1.1 * parent.t); height: 3 * ov.u
            x: ov.cx - width / 2; y: ov.cy - height / 2
            gradient: Gradient { orientation: Gradient.Horizontal
                GradientStop { position: 0.0; color: ov.c(0) }
                GradientStop { position: 0.5; color: "#ffffff" }
                GradientStop { position: 1.0; color: ov.c(0) } }
        }
        Rectangle {
            width: ov.width * (0.05 + 0.6 * parent.t); height: 22 * ov.u
            x: ov.cx - width / 2; y: ov.cy - height / 2
            opacity: 0.35
            gradient: Gradient { orientation: Gradient.Horizontal
                GradientStop { position: 0.0; color: ov.c(0) }
                GradientStop { position: 0.5; color: ov.c(0.9) }
                GradientStop { position: 1.0; color: ov.c(0) } }
        }
        Rectangle {   // 가운데 빛무리
            width: 160 * ov.u * (0.5 + parent.t); height: width; radius: width / 2
            x: ov.cx - width / 2; y: ov.cy - height / 2
            gradient: Gradient {
                GradientStop { position: 0.0; color: ov.c(0) }
                GradientStop { position: 0.5; color: Qt.rgba(1, 1, 1, 0.55) }
                GradientStop { position: 1.0; color: ov.c(0) }
            }
        }
    }
}
