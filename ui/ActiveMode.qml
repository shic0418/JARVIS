// 액티브 모드 — 바탕화면 위에 투명하게 떠 있는 홀로그램 HUD
//   · 화면 전체를 어둡게 덮지 않는다: 바탕화면 · 아이콘 · 작업 표시줄이 그대로 보이고,
//     패널마다 옅은 유리판만 깔며, 선 · 눈금 · 숫자로 존재감을 만든다.
//   · 켜질 때: 충격파 고리가 퍼지고 고리 · 눈금이 그려지며 패널이 가운데에서 날아가 자리를 잡는다.
//     꺼질 때: 같은 과정을 거꾸로.
//   · 마우스 · 키보드 입력은 그대로 아래 창으로 통과한다 (켜 둔 채로 PC 를 쓸 수 있음).
//     단, 아래 가운데의 채팅 입력 바만은 따로 뜬 창이라 눌러서 글로 명령할 수 있다.
//   · 모든 숫자는 실제 데이터(jarvis.*)에서 온다. 장식용 가짜 수치는 쓰지 않는다.
//   · Windows '애니메이션 효과' 를 꺼 두었으면(reduceMotion) 회전 · 스캔 연출을 멈춘다.
import QtQuick
import QtQuick.Window
import QtQuick.Controls.Basic as QC
import QtQuick.Shapes

Window {
    id: ov
    objectName: "activeMode"
    color: "transparent"
    flags: Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool
           | Qt.WindowTransparentForInput | Qt.WindowDoesNotAcceptFocus
    visible: false
    title: "J.A.R.V.I.S ACTIVE"

    // =====================================================================
    // 디자인 토큰 — 색 · 글꼴 · 투명도는 모두 여기서만 정한다
    QtObject {
        id: tk
        readonly property color cyan: "#59EAF5"      // 주 색
        readonly property color cyan2: "#35C9D5"     // 보조 색
        readonly property color ice: "#B8F5FF"       // 강조 수치 · 핵심 선
        readonly property color teal: "#0B252C"      // 패널 바탕 기준 색
        readonly property color red: "#FF4058"       // 경고 전용
        readonly property color amber: "#FFC46B"     // 처리 중
        readonly property color green: "#6CF2B4"     // 완료
        readonly property color shade: Qt.rgba(0.0, 0.07, 0.09, 0.82)   // 글자 테두리 (밝은 화면 위 가독성)
        readonly property real panelAlpha: 0.28      // rgba(7, 35, 43, 0.28)
        readonly property string sans: "Bahnschrift"
        readonly property string mono: "Consolas"
    }
    function c(a) { return Qt.rgba(tk.cyan.r, tk.cyan.g, tk.cyan.b, a) }
    function c2(a) { return Qt.rgba(tk.cyan2.r, tk.cyan2.g, tk.cyan2.b, a) }
    function ic(a) { return Qt.rgba(tk.ice.r, tk.ice.g, tk.ice.b, a) }
    function rc(a) { return Qt.rgba(tk.red.r, tk.red.g, tk.red.b, a) }
    function sc(a) { return Qt.rgba(sCol.r, sCol.g, sCol.b, a) }
    function pc(a) { return Qt.rgba(7 / 255, 35 / 255, 43 / 255, a) }

    // =====================================================================
    // 데이터 (백엔드 연결은 그대로)
    readonly property bool on: jarvis.activeMode
    readonly property string st: jarvis.state
    readonly property var stats: JSON.parse(jarvis.statsJson)
    readonly property var timers: JSON.parse(jarvis.timersJson)     // 돌고 있는 타이머 (가까운 순)
    readonly property var procs: JSON.parse(jarvis.procsJson)       // 무거운 프로그램 상위 5개
    readonly property var weather: JSON.parse(jarvis.weatherJson)
    readonly property var target: JSON.parse(jarvis.targetJson)     // 추적 박스: 지금 창 / 짚은 위치
    readonly property var stateLabels: ({ boot: "INITIALIZING", standby: "STANDBY", listening: "LISTENING",
                                          thinking: "PROCESSING", speaking: "RESPONDING", offline: "MIC OFFLINE" })
    property var cpuHist: []
    onStatsChanged: { const h = cpuHist.slice(-47); h.push(stats.cpu || 0); cpuHist = h }

    // 상태 색: 중앙 HUD 의 상태 고리 · 표시등에만 쓴다 (패널은 늘 청록)
    property color sCol: st === "thinking" ? tk.amber : st === "offline" ? tk.red : st === "listening" ? tk.ice : tk.cyan
    Behavior on sCol { ColorAnimation { duration: 450 } }

    // 소리 크기 (실제 마이크 입력 · 자비스 목소리)
    property real inL: Math.min(1, jarvis.micLevel)
    property real outL: Math.min(1, jarvis.voiceLevel)
    Behavior on inL { NumberAnimation { duration: 110 } }
    Behavior on outL { NumberAnimation { duration: 110 } }
    readonly property real lvl: Math.max(inL, outL)

    readonly property bool cpuHi: (stats.cpu || 0) > 85
    readonly property bool ramHi: (stats.ram || 0) > 88
    readonly property bool batLo: stats.bat !== undefined && stats.bat >= 0 && stats.bat < 20 && !stats.plugged
    readonly property bool alert: cpuHi || ramHi || batLo

    // Windows 설정 '애니메이션 효과' 꺼짐 → 움직임 줄이기 (app.py 가 reduceMotion 을 넘겨줌)
    readonly property bool calm: typeof reduceMotion !== "undefined" && reduceMotion === true

    // =====================================================================
    // 배치 — 화면 크기 · 작업 표시줄에 맞춰 계산 (1600×900 기준 u = 1)
    readonly property real u: Math.max(0.55, Math.min(width / 1600, height / 900))
    function px(n) { return n * u }
    function fs(n) { return Math.max(n * 0.8, n * u) }     // 글자는 너무 작아지지 않게
    // 작업 표시줄 높이 (아래쪽). 그 위로만 그린다 — 작업 표시줄은 가리지 않는다
    readonly property real taskbar: Math.max(0, Math.min(height * 0.1, Screen.height - Screen.desktopAvailableHeight))
    readonly property real safeB: height - taskbar - px(12)
    // 바탕화면 아이콘 첫 줄(왼쪽)을 비워 두도록 패널을 안쪽으로
    readonly property real sideX: Math.max(96, Math.min(width * 0.065, 132))
    readonly property real panelW: px(296)
    readonly property real rightX: width - sideX - panelW
    readonly property real gap: px(14)
    readonly property real topH: px(86)
    readonly property real botStack: px(190)     // 상태 글 + 파형 + 채팅 입력
    readonly property real cx: width / 2
    readonly property real cy: topH + (safeB - botStack - topH) / 2
    readonly property real rr: Math.max(px(80), Math.min(px(170), (safeB - botStack - topH) / 2 - px(26),
                                                     (cx - sideX - panelW - px(80)) / 1.2))
    readonly property real colTop: px(104)
    readonly property real colH: px(166) + px(170) + px(212) + 2 * gap     // 더 긴 오른쪽 열 기준
    readonly property real colY: colTop + Math.max(0, (safeB - px(6) - colTop - colH) * 0.4)
    readonly property real chatH: Math.max(34, 36 * u)

    // ---- 펼침 진행도 p: 0(꺼짐) → 1(완전히 펼쳐짐) ----
    property real p: 0
    readonly property bool live: visible && p > 0
    readonly property bool moving: live && !calm
    NumberAnimation { id: openAnim; target: ov; property: "p"; to: 1; duration: ov.calm ? 500 : 2400 }
    SequentialAnimation {
        id: closeAnim
        NumberAnimation { target: ov; property: "p"; to: 0; duration: ov.calm ? 300 : 900; easing.type: Easing.InQuad }
        ScriptAction { script: ov.visible = false }
    }
    onOnChanged: {
        if (on) { closeAnim.stop(); visible = true; logReset(); openAnim.restart() }
        else if (visible) { openAnim.stop(); closeAnim.restart() }
    }
    Component.onCompleted: if (on) { visible = true; logReset(); openAnim.restart() }

    function lin(a, b) { return Math.max(0, Math.min(1, (p - a) / (b - a))) }
    function seg(a, b) { const x = lin(a, b); return 1 - Math.pow(1 - x, 3) }
    function rnd(i) { const x = Math.sin(i * 12.9898 + 78.233) * 43758.5453; return x - Math.floor(x) }
    function pad(n) { return n < 10 ? "0" + n : "" + n }
    function pad4(n) { n = Math.max(0, Math.round(n)); return ("000" + n).slice(-4) }
    function left(t) { return Math.max(0, (t.end - now.getTime()) / 1000) }
    function hms(sec) {
        sec = Math.ceil(sec)
        const h = Math.floor(sec / 3600), m = Math.floor(sec % 3600 / 60), x = sec % 60
        return (h ? h + ":" + pad(m) : pad(m)) + ":" + pad(x)
    }
    function mb(v) { return v >= 1024 ? (v / 1024).toFixed(1) + " GB" : Math.round(v) + " MB" }
    function rate(b) {
        if (b === undefined) return "—"
        if (b >= 1048576) return (b / 1048576).toFixed(1) + " MB/s"
        return Math.round(b / 1024) + " KB/s"
    }
    // 암호가 풀리듯: 앞에서부터 진짜 글자, 바로 뒤 몇 칸은 기호 (켜질 때만)
    readonly property string glyphs: "ABCDEF0123456789#%&*/<>=+"
    function decode(s, t, seed) {
        s = s || ""
        if (t >= 1) return s
        if (t <= 0) return ""
        const n = Math.floor(s.length * t)
        let out = s.substring(0, n)
        for (let i = n; i < Math.min(s.length, n + 4); i++)
            out += s[i] === " " ? " " : glyphs[Math.floor(rnd(i * 7.3 + tick * 1.7 + seed) * glyphs.length)]
        return out
    }

    property date now: new Date()
    Timer { interval: 250; running: ov.visible; repeat: true; triggeredOnStart: true; onTriggered: ov.now = new Date() }
    property int tick: 0                       // 스펙트럼 · 암호 글자용
    Timer { interval: 80; running: ov.live; repeat: true; onTriggered: ov.tick++ }

    readonly property string tzTag: {
        const off = -now.getTimezoneOffset() / 60
        return (off === 9 ? "KST" : "LOCAL") + " // UTC" + (off >= 0 ? "+" : "") + off
    }
    readonly property int dayOfYear: Math.floor((now - new Date(now.getFullYear(), 0, 0)) / 86400000)
    readonly property int isoWeek: {
        const d = new Date(Date.UTC(now.getFullYear(), now.getMonth(), now.getDate()))
        const k = d.getUTCDay() || 7
        d.setUTCDate(d.getUTCDate() + 4 - k)
        return Math.ceil(((d - Date.UTC(d.getUTCFullYear(), 0, 1)) / 86400000 + 1) / 7)
    }

    // 계속 돌아가는 값들 — 느리게, 보일 때만, 움직임 줄이기 설정이면 멈춤
    property real spin: 0
    NumberAnimation on spin { from: 0; to: 360; duration: 64000; loops: Animation.Infinite; running: ov.moving }
    property real sweepA: 0
    NumberAnimation on sweepA { from: 0; to: 360; duration: 7000; loops: Animation.Infinite; running: ov.moving }
    property real wave: 0
    NumberAnimation on wave { from: 0; to: 360; duration: 3200; loops: Animation.Infinite; running: ov.live }
    property real heading: 0
    NumberAnimation on heading { from: 0; to: 360; duration: 120000; loops: Animation.Infinite; running: ov.moving }
    property real pulse: 0.6
    SequentialAnimation on pulse {
        loops: Animation.Infinite; running: ov.moving
        NumberAnimation { from: 0.2; to: 1; duration: 1300; easing.type: Easing.InOutSine }
        NumberAnimation { from: 1; to: 0.2; duration: 1300; easing.type: Easing.InOutSine }
    }

    // ---- 최근 작업 기록 (COMMS LINK) ----
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

    // ---- 시스템 기록 (SYSTEM LOG): 실제로 일어난 일만 남긴다 ----
    ListModel { id: syslog }
    function logEv(tag, msg, lv) {
        const d = new Date()
        syslog.insert(0, { t: pad(d.getHours()) + ":" + pad(d.getMinutes()) + ":" + pad(d.getSeconds()),
                           tag: tag, msg: msg, lv: lv || "info" })
        while (syslog.count > 5) syslog.remove(syslog.count - 1)
    }
    function logReset() {
        syslog.clear()
        logEv("SYS", "ACTIVE MODE ENGAGED", "ok")
        if (weather.temp !== undefined) logEv("ATMOS", "LINK  " + String(weather.loc).toUpperCase(), "ok")
    }
    onStChanged: if (visible) logEv("VOICE", stateLabels[st] || st.toUpperCase(),
                                    st === "offline" ? "err" : st === "thinking" ? "run" : "info")
    onWeatherChanged: {
        if (!visible) return
        if (weather.temp !== undefined) logEv("ATMOS", "LINK  " + String(weather.loc).toUpperCase(), "ok")
        else if (weather.error) logEv("ATMOS", "LINK OFFLINE", "err")
    }
    onCpuHiChanged: if (visible && cpuHi) logEv("CPU", "LOAD HIGH  " + Math.round(stats.cpu) + "%", "err")
    onRamHiChanged: if (visible && ramHi) logEv("MEMORY", "USAGE HIGH  " + Math.round(stats.ram) + "%", "err")
    property int timerCount: 0
    onTimersChanged: {
        if (visible && timers.length > timerCount && timers.length) logEv("TIMER", "SET  " + timers[timers.length - 1].label, "ok")
        timerCount = timers.length
    }
    property string lastApp: ""

    // 추적 박스: 대상이 바뀔 때마다 넓게 벌어졌다가 조여 들며 '잠금'
    property string lastTarget: ""
    onTargetChanged: {
        const id = target.id === undefined ? "" : String(target.id)
        if (id !== "" && id !== lastTarget) lockAnim.restart()
        lastTarget = id
        if (visible && target.kind === "window" && target.app && target.app !== lastApp) logEv("OPTIC", "TRACK  " + target.app, "info")
        if (visible && target.kind === "point") logEv("OPTIC", "LOCK  " + (target.title || "TARGET"), "run")
        lastApp = target.kind === "window" ? (target.app || "") : lastApp
    }
    property real lock: 1
    SequentialAnimation {
        id: lockAnim
        NumberAnimation { target: ov; property: "lock"; to: 0; duration: 10 }
        PauseAnimation { duration: 340 }
        NumberAnimation { target: ov; property: "lock"; to: 1; duration: 460; easing.type: Easing.OutBack }
    }

    // =====================================================================
    // 공용 조각
    // 가운데에서 제자리로 날아오며 켜지는 묶음. tilt: 바깥쪽이 살짝 다가오는 홀로그램 곡면
    component Fly: Item {
        id: fly
        property real d: 0.3
        property real tilt: 0
        readonly property real e: ov.seg(d, d + 0.3)
        visible: e > 0
        opacity: e
        transform: [
            Rotation { origin.x: fly.tilt > 0 ? fly.width : 0; origin.y: fly.height / 2; axis { x: 0; y: 1; z: 0 }
                       angle: fly.tilt * (0.5 + 0.5 * fly.e) },
            Scale { origin.x: fly.width / 2; origin.y: fly.height / 2; xScale: 0.6 + 0.4 * fly.e; yScale: 0.6 + 0.4 * fly.e },
            Translate { x: (ov.cx - (fly.x + fly.width / 2)) * (1 - fly.e); y: (ov.cy - (fly.y + fly.height / 2)) * (1 - fly.e) }
        ]
    }
    // 모든 글자: 얇은 어두운 테두리 (뒤 화면이 밝거나 복잡해도 읽히게) — 화면 전체를 어둡게 하는 대신
    component HText: Text { style: Text.Outline; styleColor: tk.shade; font.family: tk.sans }
    component Decode: HText {
        property string full: ""
        property real t: 1
        property int seed: 0
        text: ov.decode(full, t, seed)
        color: ov.c(0.85)
        font.pixelSize: ov.fs(11); font.letterSpacing: ov.px(2)
    }
    component Label: HText {
        color: ov.c(0.74)
        font.pixelSize: ov.fs(8.5); font.letterSpacing: ov.px(1.8); font.weight: Font.DemiBold
    }
    component Num: HText { color: tk.ice; font.pixelSize: ov.fs(11); font.letterSpacing: ov.px(0.5) }
    // 작은 상태 표시등
    component Led: Item {
        id: led
        property color col: tk.cyan
        property bool blink: false
        width: ov.px(6); height: width
        Rectangle {
            anchors.centerIn: parent; width: parent.width * 2.2; height: width; radius: width / 2
            color: Qt.rgba(led.col.r, led.col.g, led.col.b, 0.16)
            opacity: led.blink ? ov.pulse : 0.7
        }
        Rectangle {
            anchors.fill: parent; radius: width / 2; color: led.col
            opacity: led.blink ? 0.45 + 0.55 * ov.pulse : 1
        }
    }
    // 홀로그램 패널: 옅은 유리판 + 머리카락 테두리 + 깎은 모서리 강조 + 머리글
    component HudPanel: Item {
        id: hp
        property string title: ""
        property string tag: ""
        property bool alert: false
        property real fill: tk.panelAlpha
        property real cut: ov.px(11)
        readonly property real hh: title !== "" ? ov.px(24) : 0
        readonly property color line: alert ? tk.red : tk.cyan
        function lc(a) { return Qt.rgba(line.r, line.g, line.b, a) }
        readonly property var pts: [
            Qt.point(hp.cut, 0.5), Qt.point(hp.width - 0.5, 0.5), Qt.point(hp.width - 0.5, hp.height - hp.cut),
            Qt.point(hp.width - hp.cut, hp.height - 0.5), Qt.point(0.5, hp.height - 0.5), Qt.point(0.5, hp.cut), Qt.point(hp.cut, 0.5)
        ]
        Shape {
            anchors.fill: parent
            preferredRendererType: Shape.CurveRenderer
            ShapePath {       // 유리판
                strokeColor: hp.lc(0.22); strokeWidth: 1
                fillGradient: LinearGradient {
                    x1: 0; y1: 0; x2: 0; y2: hp.height
                    GradientStop { position: 0.0; color: ov.pc(hp.fill + 0.07) }
                    GradientStop { position: 0.45; color: ov.pc(hp.fill) }
                    GradientStop { position: 1.0; color: ov.pc(Math.max(0, hp.fill - 0.05)) }
                }
                PathPolyline { path: hp.pts }
            }
            ShapePath {       // 깎인 모서리 강조
                strokeColor: hp.lc(0.9); strokeWidth: 1.5; fillColor: "transparent"
                capStyle: ShapePath.FlatCap; joinStyle: ShapePath.MiterJoin
                PathMove { x: 0.75; y: hp.cut + ov.px(16) }
                PathLine { x: 0.75; y: hp.cut }
                PathLine { x: hp.cut; y: 0.75 }
                PathLine { x: hp.cut + ov.px(26); y: 0.75 }
                PathMove { x: hp.width - 0.75; y: hp.height - hp.cut - ov.px(16) }
                PathLine { x: hp.width - 0.75; y: hp.height - hp.cut }
                PathLine { x: hp.width - hp.cut; y: hp.height - 0.75 }
                PathLine { x: hp.width - hp.cut - ov.px(26); y: hp.height - 0.75 }
            }
            ShapePath {       // 오른쪽 위 · 왼쪽 아래 작은 눈금
                strokeColor: hp.lc(0.45); strokeWidth: 1; fillColor: "transparent"
                PathMove { x: hp.width - ov.px(8); y: 0 }  PathLine { x: hp.width - ov.px(8); y: ov.px(4) }
                PathMove { x: hp.width - ov.px(12); y: 0 } PathLine { x: hp.width - ov.px(12); y: ov.px(4) }
                PathMove { x: hp.width - ov.px(16); y: 0 } PathLine { x: hp.width - ov.px(16); y: ov.px(4) }
                PathMove { x: ov.px(8); y: hp.height }      PathLine { x: ov.px(8); y: hp.height - ov.px(4) }
                PathMove { x: ov.px(12); y: hp.height }     PathLine { x: ov.px(12); y: hp.height - ov.px(4) }
            }
            ShapePath {       // 머리글 밑줄
                strokeColor: hp.title !== "" ? hp.lc(0.18) : "transparent"; strokeWidth: 1; fillColor: "transparent"
                PathMove { x: ov.px(10); y: hp.hh } PathLine { x: hp.width - ov.px(10); y: hp.hh }
            }
            ShapePath {
                strokeColor: hp.title !== "" ? hp.lc(0.8) : "transparent"; strokeWidth: 1.5; fillColor: "transparent"
                capStyle: ShapePath.FlatCap
                PathMove { x: ov.px(10); y: hp.hh } PathLine { x: ov.px(40); y: hp.hh }
            }
        }
        Row {
            id: hpTitle
            visible: hp.title !== ""
            x: ov.px(12); y: ov.px(7)
            spacing: ov.px(7)
            Rectangle { width: ov.px(5); height: width; rotation: 45; color: hp.line; anchors.verticalCenter: parent.verticalCenter }
            HText {
                text: hp.title
                color: hp.alert ? tk.red : ov.ic(0.92)
                font.pixelSize: ov.fs(9.5); font.letterSpacing: ov.px(2.6); font.weight: Font.DemiBold
            }
        }
        HText {
            visible: hp.tag !== ""
            text: hp.tag
            anchors.right: parent.right; anchors.rightMargin: ov.px(20)
            width: Math.max(0, hp.width - hpTitle.x - hpTitle.width - ov.px(32))
            horizontalAlignment: Text.AlignRight; elide: Text.ElideLeft
            y: ov.px(8)
            color: hp.alert ? tk.red : ov.c(0.55)
            font.pixelSize: ov.fs(8.5); font.letterSpacing: ov.px(1.5)
        }
    }
    // 다층 원형 게이지 (CPU / MEMORY / STORAGE) — 실제 사용량, 부드럽게 따라감
    component Gauge: Item {
        id: g
        property real v: 0
        property string label: ""
        property string sub: ""
        property real warn: 85
        property real e: 1
        property real shown: 0
        Behavior on shown { NumberAnimation { duration: ov.calm ? 0 : 800; easing.type: Easing.OutCubic } }
        onVChanged: shown = v
        Component.onCompleted: shown = v
        width: ov.px(78); height: width + ov.px(26)
        readonly property real m: width / 2
        readonly property real r: m - ov.px(9)
        readonly property bool hi: v >= warn
        readonly property color col: hi ? tk.red : tk.ice
        function gcol(a) { return Qt.rgba(col.r, col.g, col.b, a) }
        Shape {
            width: g.width; height: g.width
            preferredRendererType: Shape.CurveRenderer
            ShapePath {   // 바깥 머리카락 고리
                strokeColor: ov.c(0.2); strokeWidth: 1; fillColor: "transparent"
                PathAngleArc { centerX: g.m; centerY: g.m; radiusX: g.m - 1; radiusY: g.m - 1; startAngle: 135; sweepAngle: 270 * g.e }
            }
            ShapePath {   // 눈금 띠
                strokeColor: ov.c(0.42); strokeWidth: ov.px(3); fillColor: "transparent"
                strokeStyle: ShapePath.DashLine; dashPattern: [0.3, 2.6]
                PathAngleArc { centerX: g.m; centerY: g.m; radiusX: g.m - ov.px(4); radiusY: g.m - ov.px(4); startAngle: 135; sweepAngle: 270 * g.e }
            }
            ShapePath {   // 바탕 트랙
                strokeColor: ov.c(0.12); strokeWidth: ov.px(4); fillColor: "transparent"; capStyle: ShapePath.FlatCap
                PathAngleArc { centerX: g.m; centerY: g.m; radiusX: g.r; radiusY: g.r; startAngle: 135; sweepAngle: 270 * g.e }
            }
            ShapePath {   // 값 (아래 옅은 번짐 — 핵심 선에만 제한적으로)
                strokeColor: g.gcol(0.14); strokeWidth: ov.px(9); fillColor: "transparent"; capStyle: ShapePath.FlatCap
                PathAngleArc { centerX: g.m; centerY: g.m; radiusX: g.r; radiusY: g.r; startAngle: 135
                               sweepAngle: 270 * Math.max(0.004, g.shown / 100) * g.e }
            }
            ShapePath {
                strokeColor: g.col; strokeWidth: ov.px(3.5); fillColor: "transparent"; capStyle: ShapePath.FlatCap
                PathAngleArc { centerX: g.m; centerY: g.m; radiusX: g.r; radiusY: g.r; startAngle: 135
                               sweepAngle: 270 * Math.max(0.004, g.shown / 100) * g.e }
            }
            ShapePath {   // 경고 문턱
                strokeColor: ov.rc(0.8); strokeWidth: ov.px(5); fillColor: "transparent"; capStyle: ShapePath.FlatCap
                PathAngleArc { centerX: g.m; centerY: g.m; radiusX: g.r; radiusY: g.r; startAngle: 135 + 270 * g.warn / 100; sweepAngle: 1.5 * g.e }
            }
            ShapePath {   // 안쪽 점선 고리
                strokeColor: ov.c(0.3); strokeWidth: 1; fillColor: "transparent"
                strokeStyle: ShapePath.DashLine; dashPattern: [1, 3]
                PathAngleArc { centerX: g.m; centerY: g.m; radiusX: g.r - ov.px(8); radiusY: g.r - ov.px(8); startAngle: 0; sweepAngle: 360 * g.e }
            }
        }
        Row {
            anchors.horizontalCenter: parent.horizontalCenter
            y: g.m - height / 2
            HText { text: Math.round(g.shown * g.e); color: g.hi ? tk.red : tk.ice; font.pixelSize: ov.fs(17); font.weight: Font.Light }
            HText { text: "%"; color: ov.c(0.65); font.pixelSize: ov.fs(9); anchors.baseline: parent.children[0].baseline }
        }
        Column {
            anchors.horizontalCenter: parent.horizontalCenter
            y: g.width + ov.px(1)
            spacing: 0
            Label { anchors.horizontalCenter: parent.horizontalCenter; text: g.label; color: ov.ic(0.75) }
            HText { anchors.horizontalCenter: parent.horizontalCenter; text: g.sub; color: ov.c(0.45); font.pixelSize: ov.fs(7.5); font.letterSpacing: ov.px(1) }
        }
    }

    // =====================================================================
    // 켜지는 순간: 얇은 충격파 고리 + 가로 섬광 선 (화면 전체를 밝히지 않음)
    Repeater {
        model: 2
        Rectangle {
            readonly property real t: ov.calm ? 1 : ov.lin(0.02 + index * 0.08, 0.4 + index * 0.08)
            visible: t > 0 && t < 1
            width: 30 + ov.diag * 0.9 * (1 - Math.pow(1 - t, 2.2)); height: width; radius: width / 2
            x: ov.cx - width / 2; y: ov.cy - height / 2
            color: "transparent"
            border.color: index === 0 ? tk.ice : tk.cyan
            border.width: (index === 0 ? 2 : 1) * (1 - t) + 1
            opacity: (1 - t) * (index === 0 ? 0.6 : 0.35)
        }
    }
    readonly property real diag: Math.sqrt(width * width + height * height)
    Rectangle {
        readonly property real t: ov.calm ? 1 : ov.lin(0.0, 0.3)
        visible: t > 0 && t < 1
        opacity: Math.sin(t * Math.PI) * 0.8
        width: ov.width * (0.1 + 0.8 * t); height: 1.5
        x: ov.cx - width / 2; y: ov.cy
        gradient: Gradient { orientation: Gradient.Horizontal
            GradientStop { position: 0.0; color: ov.ic(0) }
            GradientStop { position: 0.5; color: tk.ice }
            GradientStop { position: 1.0; color: ov.ic(0) } }
    }

    // =====================================================================
    // HUD 본체 — 전체 글로우 · 화면 어둡게 하기 없음
    Item {
        id: hud
        anchors.fill: parent

        // ---- 안전 영역 모서리 꺾쇠 (작업 표시줄 위에서 끝남) ----
        Repeater {
            model: 4
            Shape {
                id: corner
                readonly property bool onRight: index % 2 === 1
                readonly property bool onBottom: index >= 2
                readonly property real m: ov.px(16)
                readonly property real len: ov.px(30) * ov.seg(0.2, 0.5)
                width: len; height: len
                x: onRight ? ov.width - m - len : m
                y: onBottom ? ov.safeB - len : m
                opacity: 0.7 * ov.seg(0.2, 0.4)
                preferredRendererType: Shape.CurveRenderer
                ShapePath {
                    strokeColor: tk.ice; strokeWidth: 1.5; fillColor: "transparent"; capStyle: ShapePath.FlatCap
                    PathMove { x: corner.onRight ? 0 : corner.len; y: corner.onBottom ? corner.len : 0 }
                    PathLine { x: corner.onRight ? corner.len : 0; y: corner.onBottom ? corner.len : 0 }
                    PathLine { x: corner.onRight ? corner.len : 0; y: corner.onBottom ? 0 : corner.len }
                }
            }
        }

        // ---- 추적 박스: 지금 쓰고 있는 창을 따라다니고, 자비스가 짚은 곳에는 빨갛게 잠금 ----
        Item {
            id: tg
            readonly property bool has: ov.target.kind !== undefined && ov.p >= 1
            readonly property bool pt: ov.target.kind === "point"
            readonly property color col: pt ? tk.red : tk.cyan
            readonly property real mg: 6 * ov.u
            readonly property real pad: (1 - ov.lock) * 36 * ov.u
            readonly property real x0: has ? Math.max(mg, ov.target.x) : ov.cx - 40
            readonly property real y0: has ? Math.max(mg, ov.target.y) : ov.cy - 40
            readonly property real x1: has ? Math.min(ov.width - mg, ov.target.x + ov.target.w) : ov.cx + 40
            readonly property real y1: has ? Math.min(ov.safeB, ov.target.y + ov.target.h) : ov.cy + 40
            x: x0 - pad; y: y0 - pad
            width: Math.max(20, x1 - x0) + 2 * pad; height: Math.max(20, y1 - y0) + 2 * pad
            Behavior on x { NumberAnimation { duration: 420; easing.type: Easing.OutCubic } }
            Behavior on y { NumberAnimation { duration: 420; easing.type: Easing.OutCubic } }
            Behavior on width { NumberAnimation { duration: 420; easing.type: Easing.OutCubic } }
            Behavior on height { NumberAnimation { duration: 420; easing.type: Easing.OutCubic } }
            opacity: has ? (pt ? 1 : 0.75) : 0
            Behavior on opacity { NumberAnimation { duration: 300 } }
            visible: opacity > 0.01

            Repeater {
                model: 4
                Shape {
                    id: tc
                    readonly property bool onRight: index % 2 === 1
                    readonly property bool onBottom: index >= 2
                    readonly property real len: Math.min((tg.pt ? 16 : 22) * ov.u, tg.width / 3, tg.height / 3)
                    width: len; height: len
                    x: onRight ? tg.width - len : 0
                    y: onBottom ? tg.height - len : 0
                    preferredRendererType: Shape.CurveRenderer
                    ShapePath {
                        strokeColor: tg.col; strokeWidth: tg.pt ? 2 : 1.5; fillColor: "transparent"; capStyle: ShapePath.FlatCap
                        PathMove { x: tc.onRight ? 0 : tc.len; y: tc.onBottom ? tc.len : 0 }
                        PathLine { x: tc.onRight ? tc.len : 0; y: tc.onBottom ? tc.len : 0 }
                        PathLine { x: tc.onRight ? tc.len : 0; y: tc.onBottom ? 0 : tc.len }
                    }
                }
            }
            // 가장자리 가운데 작은 눈금
            Repeater {
                model: 4
                Rectangle {
                    readonly property bool hz: index < 2
                    width: hz ? ov.px(8) : 1; height: hz ? 1 : ov.px(8)
                    x: hz ? tg.width / 2 - width / 2 : (index === 2 ? 0 : tg.width - 1)
                    y: hz ? (index === 0 ? 0 : tg.height - 1) : tg.height / 2 - height / 2
                    color: Qt.rgba(tg.col.r, tg.col.g, tg.col.b, 0.6)
                }
            }
            // 짚은 위치: 가운데 고리가 맥박치듯
            Rectangle {
                visible: tg.pt
                anchors.centerIn: parent
                width: 18 * ov.u + 12 * ov.u * ov.pulse; height: width; radius: width / 2
                color: "transparent"; border.color: tk.red; border.width: 1.5
                opacity: 0.4 + 0.6 * ov.lock
            }
            Rectangle {
                visible: tg.pt
                anchors.centerIn: parent
                width: 7 * ov.u; height: width; rotation: 45
                color: tk.red
            }
            // 이름표: 박스 위에 자리가 없으면 안쪽 위
            Rectangle {
                x: tgLabel.x - 8 * ov.u; y: tgLabel.y - 4 * ov.u
                width: tgLabel.width + 16 * ov.u; height: tgLabel.height + 8 * ov.u
                color: ov.pc(0.5)
                border.color: Qt.rgba(tg.col.r, tg.col.g, tg.col.b, 0.35); border.width: 1
                Rectangle { width: 2; height: parent.height; color: tg.col }
            }
            Column {
                id: tgLabel
                readonly property bool inside: tg.y < 52 * ov.u
                x: Math.min(inside ? 26 * ov.u : 8 * ov.u, Math.max(0, ov.width - tg.x - width - 10))
                y: inside ? 24 * ov.u : -height - 8 * ov.u
                spacing: 1
                HText {
                    text: tg.pt ? (ov.lock >= 1 ? "LOCKED" : "ANALYZING" + ".".repeat(1 + ov.tick % 3))
                                : "TRACKING  ·  " + (ov.target.app || "WINDOW").toUpperCase()
                    color: tg.col; font.pixelSize: ov.fs(9.5); font.letterSpacing: 2 * ov.u; font.weight: Font.DemiBold
                }
                HText {
                    width: Math.min(implicitWidth, 380 * ov.u); elide: Text.ElideRight
                    text: ov.target.title || ""
                    color: tk.ice; font.family: "Segoe UI"; font.pixelSize: ov.fs(tg.pt ? 14 : 11)
                }
                HText {
                    text: "X " + ov.pad4(ov.target.x || 0) + "  Y " + ov.pad4(ov.target.y || 0) + "   "
                          + Math.round(ov.target.w || 0) + " × " + Math.round(ov.target.h || 0)
                          + (!tg.pt && ov.target.cpu !== undefined && ov.target.cpu >= 0
                             ? "   ·   CPU " + ov.target.cpu + "%   MEM " + ov.mb(ov.target.mem || 0) : "")
                    color: ov.c(0.7); font.family: tk.mono; font.pixelSize: ov.fs(9)
                }
            }
        }

        // =================================================================
        // 중앙 원형 HUD — 가운데는 비워 두어 바탕화면이 그대로 보인다
        Item {
            id: reticle
            readonly property real rr: ov.rr
            readonly property real e: ov.seg(0.05, 0.42)
            readonly property real draw: ov.seg(0.18, 0.7)     // 고리가 그려지는 진행도
            width: rr * 2; height: rr * 2
            x: ov.cx - rr; y: ov.cy - rr
            visible: e > 0
            opacity: Math.min(1, e * 1.4)
            scale: 0.3 + 0.7 * e

            // 1) 고정된 바깥 측정 고리: 5° 눈금, 30° 마다 굵은 눈금 + 방위각
            Shape {
                anchors.fill: parent
                preferredRendererType: Shape.CurveRenderer
                ShapePath {
                    strokeColor: ov.c(0.34); strokeWidth: 1; fillColor: "transparent"
                    PathAngleArc { centerX: reticle.rr; centerY: reticle.rr; radiusX: reticle.rr - 0.5; radiusY: reticle.rr - 0.5; startAngle: -90; sweepAngle: 360 * reticle.draw }
                }
                ShapePath {
                    strokeColor: ov.c(0.14); strokeWidth: 1; fillColor: "transparent"
                    PathAngleArc { centerX: reticle.rr; centerY: reticle.rr; radiusX: reticle.rr * 0.955; radiusY: reticle.rr * 0.955; startAngle: 90; sweepAngle: 360 * reticle.draw }
                }
            }
            Repeater {
                model: 72
                Rectangle {
                    readonly property bool major: index % 6 === 0
                    visible: index < 72 * reticle.draw
                    width: major ? 1.5 : 1
                    height: major ? ov.px(10) : (index % 2 === 0 ? ov.px(5) : ov.px(3))
                    x: reticle.rr - width / 2; y: 1
                    color: major ? ov.ic(0.85) : ov.c(0.4)
                    transform: Rotation { origin.x: width / 2; origin.y: reticle.rr - 1; angle: index * 5 }
                }
            }
            Repeater {
                model: 12
                HText {
                    readonly property real a: (index * 30 - 90) * Math.PI / 180
                    readonly property real r2: reticle.rr + ov.px(12)
                    x: reticle.rr + Math.cos(a) * r2 - width / 2
                    y: reticle.rr + Math.sin(a) * r2 - height / 2
                    opacity: reticle.draw
                    text: ("00" + index * 30).slice(-3)
                    color: ov.c(index % 3 === 0 ? 0.8 : 0.42)
                    font.pixelSize: ov.fs(7.5); font.letterSpacing: ov.px(0.5)
                }
            }

            // 2) 레이더 스캔: 끝이 흐려지는 부채꼴 (안쪽 0.3R 은 비움)
            Item {
                anchors.fill: parent
                visible: !ov.calm && ov.p >= 0.7
                rotation: ov.sweepA
                Shape {
                    anchors.fill: parent
                    preferredRendererType: Shape.CurveRenderer
                    ShapePath {
                        strokeColor: "transparent"; fillColor: ov.ic(0.075)
                        PathAngleArc { centerX: reticle.rr; centerY: reticle.rr; radiusX: reticle.rr * 0.95; radiusY: reticle.rr * 0.95; startAngle: -6; sweepAngle: 6 }
                        PathAngleArc { moveToStart: false; centerX: reticle.rr; centerY: reticle.rr; radiusX: reticle.rr * 0.3; radiusY: reticle.rr * 0.3; startAngle: 0; sweepAngle: -6 }
                    }
                    ShapePath {
                        strokeColor: "transparent"; fillColor: ov.ic(0.045)
                        PathAngleArc { centerX: reticle.rr; centerY: reticle.rr; radiusX: reticle.rr * 0.95; radiusY: reticle.rr * 0.95; startAngle: -14; sweepAngle: 8 }
                        PathAngleArc { moveToStart: false; centerX: reticle.rr; centerY: reticle.rr; radiusX: reticle.rr * 0.3; radiusY: reticle.rr * 0.3; startAngle: -6; sweepAngle: -8 }
                    }
                    ShapePath {
                        strokeColor: "transparent"; fillColor: ov.ic(0.022)
                        PathAngleArc { centerX: reticle.rr; centerY: reticle.rr; radiusX: reticle.rr * 0.95; radiusY: reticle.rr * 0.95; startAngle: -26; sweepAngle: 12 }
                        PathAngleArc { moveToStart: false; centerX: reticle.rr; centerY: reticle.rr; radiusX: reticle.rr * 0.3; radiusY: reticle.rr * 0.3; startAngle: -14; sweepAngle: -12 }
                    }
                    ShapePath {
                        strokeColor: ov.ic(0.55); strokeWidth: 1; fillColor: "transparent"
                        PathMove { x: reticle.rr + reticle.rr * 0.3; y: reticle.rr }
                        PathLine { x: reticle.rr + reticle.rr * 0.95; y: reticle.rr }
                    }
                }
            }

            // 3) 분절 발광 호 (아주 느리게 시계 방향)
            Shape {
                anchors.fill: parent
                rotation: ov.spin
                preferredRendererType: Shape.CurveRenderer
                ShapePath {   // 옅은 번짐 (핵심 선에만)
                    strokeColor: ov.ic(0.07); strokeWidth: ov.px(11); fillColor: "transparent"; capStyle: ShapePath.FlatCap
                    PathAngleArc { centerX: reticle.rr; centerY: reticle.rr; radiusX: reticle.rr * 0.9; radiusY: reticle.rr * 0.9; startAngle: 8; sweepAngle: 62 * reticle.draw }
                    PathAngleArc { centerX: reticle.rr; centerY: reticle.rr; radiusX: reticle.rr * 0.9; radiusY: reticle.rr * 0.9; startAngle: 214; sweepAngle: 88 * reticle.draw }
                }
                ShapePath {
                    strokeColor: ov.ic(0.9); strokeWidth: ov.px(3.5); fillColor: "transparent"; capStyle: ShapePath.FlatCap
                    PathAngleArc { centerX: reticle.rr; centerY: reticle.rr; radiusX: reticle.rr * 0.9; radiusY: reticle.rr * 0.9; startAngle: 8; sweepAngle: 62 * reticle.draw }
                    PathAngleArc { centerX: reticle.rr; centerY: reticle.rr; radiusX: reticle.rr * 0.9; radiusY: reticle.rr * 0.9; startAngle: 82; sweepAngle: 9 * reticle.draw }
                    PathAngleArc { centerX: reticle.rr; centerY: reticle.rr; radiusX: reticle.rr * 0.9; radiusY: reticle.rr * 0.9; startAngle: 128; sweepAngle: 36 * reticle.draw }
                    PathAngleArc { centerX: reticle.rr; centerY: reticle.rr; radiusX: reticle.rr * 0.9; radiusY: reticle.rr * 0.9; startAngle: 176; sweepAngle: 5 * reticle.draw }
                    PathAngleArc { centerX: reticle.rr; centerY: reticle.rr; radiusX: reticle.rr * 0.9; radiusY: reticle.rr * 0.9; startAngle: 214; sweepAngle: 88 * reticle.draw }
                    PathAngleArc { centerX: reticle.rr; centerY: reticle.rr; radiusX: reticle.rr * 0.9; radiusY: reticle.rr * 0.9; startAngle: 318; sweepAngle: 18 * reticle.draw }
                }
                ShapePath {   // 짝을 이루는 안쪽 머리카락 선
                    strokeColor: ov.c(0.32); strokeWidth: 1; fillColor: "transparent"
                    PathAngleArc { centerX: reticle.rr; centerY: reticle.rr; radiusX: reticle.rr * 0.87; radiusY: reticle.rr * 0.87; startAngle: 0; sweepAngle: 150 * reticle.draw }
                    PathAngleArc { centerX: reticle.rr; centerY: reticle.rr; radiusX: reticle.rr * 0.87; radiusY: reticle.rr * 0.87; startAngle: 200; sweepAngle: 128 * reticle.draw }
                }
            }

            // 4) 촘촘한 눈금 띠 (아주 느리게 반시계 방향)
            Shape {
                anchors.fill: parent
                rotation: -ov.spin * 0.6
                preferredRendererType: Shape.CurveRenderer
                ShapePath {
                    strokeColor: ov.c(0.3); strokeWidth: ov.px(5); fillColor: "transparent"
                    strokeStyle: ShapePath.DashLine; dashPattern: [0.2, 1.1]
                    PathAngleArc { centerX: reticle.rr; centerY: reticle.rr; radiusX: reticle.rr * 0.81; radiusY: reticle.rr * 0.81; startAngle: 20; sweepAngle: 140 * reticle.draw }
                    PathAngleArc { centerX: reticle.rr; centerY: reticle.rr; radiusX: reticle.rr * 0.81; radiusY: reticle.rr * 0.81; startAngle: 200; sweepAngle: 140 * reticle.draw }
                }
                ShapePath {
                    strokeColor: ov.c(0.75); strokeWidth: ov.px(5); fillColor: "transparent"; capStyle: ShapePath.FlatCap
                    PathAngleArc { centerX: reticle.rr; centerY: reticle.rr; radiusX: reticle.rr * 0.81; radiusY: reticle.rr * 0.81; startAngle: 166; sweepAngle: 2 * reticle.draw }
                    PathAngleArc { centerX: reticle.rr; centerY: reticle.rr; radiusX: reticle.rr * 0.81; radiusY: reticle.rr * 0.81; startAngle: 346; sweepAngle: 2 * reticle.draw }
                }
            }

            // 5) 소리 스펙트럼 고리 — 실제 마이크 · 목소리 크기에 반응 (소리가 없으면 거의 납작)
            Repeater {
                model: 90
                Rectangle {
                    readonly property real amp: (0.05 + ov.lvl * (0.3 + 0.7 * ov.rnd(index * 3.3 + ov.tick))) * (index < 90 * reticle.draw ? 1 : 0)
                    width: ov.px(1.6); height: ov.px(2) + ov.px(20) * amp
                    x: reticle.rr - width / 2
                    y: reticle.rr - reticle.rr * 0.69 - height
                    color: ov.sc(0.3 + 0.65 * amp)
                    transform: Rotation { origin.x: width / 2; origin.y: reticle.rr * 0.69 + height; angle: index * 4 }
                }
            }

            // 6) 점선 고리 + 상태색 짧은 호 (반시계)
            Shape {
                anchors.fill: parent
                rotation: -ov.spin * 1.8
                preferredRendererType: Shape.CurveRenderer
                ShapePath {
                    strokeColor: ov.c(0.42); strokeWidth: 1.2; fillColor: "transparent"
                    strokeStyle: ShapePath.DashLine; dashPattern: [2, 5]
                    PathAngleArc { centerX: reticle.rr; centerY: reticle.rr; radiusX: reticle.rr * 0.6; radiusY: reticle.rr * 0.6; startAngle: 0; sweepAngle: 296 * reticle.draw }
                }
                ShapePath {
                    strokeColor: ov.sCol; strokeWidth: ov.px(3); fillColor: "transparent"; capStyle: ShapePath.FlatCap
                    PathAngleArc { centerX: reticle.rr; centerY: reticle.rr; radiusX: reticle.rr * 0.6; radiusY: reticle.rr * 0.6; startAngle: 306; sweepAngle: 40 * reticle.draw }
                }
            }

            // 7) 상태 고리: 소리 크기만큼 좌우로 늘어나는 호 / 처리 중이면 도는 호
            Shape {
                anchors.fill: parent
                preferredRendererType: Shape.CurveRenderer
                ShapePath {
                    strokeColor: ov.sc(0.22); strokeWidth: 1; fillColor: "transparent"
                    PathAngleArc { centerX: reticle.rr; centerY: reticle.rr; radiusX: reticle.rr * 0.5; radiusY: reticle.rr * 0.5; startAngle: 0; sweepAngle: 360 * reticle.draw }
                }
                ShapePath {
                    strokeColor: ov.sCol; strokeWidth: ov.px(2.5); fillColor: "transparent"; capStyle: ShapePath.FlatCap
                    PathAngleArc { centerX: reticle.rr; centerY: reticle.rr; radiusX: reticle.rr * 0.5; radiusY: reticle.rr * 0.5
                                   startAngle: 180 - (4 + 60 * ov.lvl); sweepAngle: 2 * (4 + 60 * ov.lvl) }
                    PathAngleArc { centerX: reticle.rr; centerY: reticle.rr; radiusX: reticle.rr * 0.5; radiusY: reticle.rr * 0.5
                                   startAngle: -(4 + 60 * ov.lvl); sweepAngle: 2 * (4 + 60 * ov.lvl) }
                }
            }
            Shape {
                anchors.fill: parent
                visible: ov.st === "thinking"
                rotation: ov.sweepA * 1.5
                preferredRendererType: Shape.CurveRenderer
                ShapePath {
                    strokeColor: tk.amber; strokeWidth: ov.px(2); fillColor: "transparent"; capStyle: ShapePath.FlatCap
                    PathAngleArc { centerX: reticle.rr; centerY: reticle.rr; radiusX: reticle.rr * 0.45; radiusY: reticle.rr * 0.45; startAngle: 0; sweepAngle: 28 }
                    PathAngleArc { centerX: reticle.rr; centerY: reticle.rr; radiusX: reticle.rr * 0.45; radiusY: reticle.rr * 0.45; startAngle: 120; sweepAngle: 28 }
                    PathAngleArc { centerX: reticle.rr; centerY: reticle.rr; radiusX: reticle.rr * 0.45; radiusY: reticle.rr * 0.45; startAngle: 240; sweepAngle: 28 }
                }
            }

            // 8) 가장 가까운 타이머: 줄어드는 고리 + 남은 시간
            Item {
                id: tmr
                readonly property var t0: ov.timers.length ? ov.timers[0] : null
                readonly property real frac: t0 ? ov.left(t0) / Math.max(1, t0.total) : 0
                visible: t0 !== null
                anchors.fill: parent
                Shape {
                    anchors.fill: parent
                    preferredRendererType: Shape.CurveRenderer
                    ShapePath {
                        strokeColor: ov.c(0.14); strokeWidth: ov.px(3); fillColor: "transparent"
                        PathAngleArc { centerX: reticle.rr; centerY: reticle.rr; radiusX: reticle.rr * 0.38; radiusY: reticle.rr * 0.38; startAngle: 0; sweepAngle: 360 }
                    }
                    ShapePath {
                        strokeColor: tmr.frac < 0.1 ? tk.red : tk.ice; strokeWidth: ov.px(3); fillColor: "transparent"; capStyle: ShapePath.FlatCap
                        PathAngleArc { centerX: reticle.rr; centerY: reticle.rr; radiusX: reticle.rr * 0.38; radiusY: reticle.rr * 0.38
                                       startAngle: -90; sweepAngle: 360 * Math.max(0.002, tmr.frac) }
                    }
                }
                HText {
                    anchors.horizontalCenter: parent.horizontalCenter
                    y: reticle.rr + ov.px(14)
                    text: tmr.t0 ? ov.hms(ov.left(tmr.t0)) : ""
                    color: tmr.frac < 0.1 ? tk.red : tk.ice
                    font.pixelSize: ov.fs(17); font.weight: Font.DemiBold
                }
            }

            // 9) 가운데: 머리카락 고리 · 십자선 · 중심점 · 화면 좌표
            Shape {
                anchors.fill: parent
                preferredRendererType: Shape.CurveRenderer
                ShapePath {
                    strokeColor: ov.c(0.4); strokeWidth: 1; fillColor: "transparent"
                    PathAngleArc { centerX: reticle.rr; centerY: reticle.rr; radiusX: reticle.rr * 0.26; radiusY: reticle.rr * 0.26; startAngle: 8; sweepAngle: 74 * reticle.draw }
                    PathAngleArc { centerX: reticle.rr; centerY: reticle.rr; radiusX: reticle.rr * 0.26; radiusY: reticle.rr * 0.26; startAngle: 98; sweepAngle: 74 * reticle.draw }
                    PathAngleArc { centerX: reticle.rr; centerY: reticle.rr; radiusX: reticle.rr * 0.26; radiusY: reticle.rr * 0.26; startAngle: 188; sweepAngle: 74 * reticle.draw }
                    PathAngleArc { centerX: reticle.rr; centerY: reticle.rr; radiusX: reticle.rr * 0.26; radiusY: reticle.rr * 0.26; startAngle: 278; sweepAngle: 74 * reticle.draw }
                }
            }
            Repeater {
                model: 4
                Rectangle {
                    readonly property bool hz: index < 2
                    readonly property real gap: reticle.rr * 0.07
                    readonly property real len: reticle.rr * 0.15
                    width: hz ? len : 1; height: hz ? 1 : len
                    x: hz ? (index === 0 ? reticle.rr - gap - len : reticle.rr + gap) : reticle.rr - 0.5
                    y: hz ? reticle.rr - 0.5 : (index === 2 ? reticle.rr - gap - len : reticle.rr + gap)
                    color: ov.ic(0.75)
                }
            }
            Rectangle {
                width: ov.px(4); height: width; radius: width / 2
                x: reticle.rr - width / 2; y: reticle.rr - height / 2
                color: ov.sCol
                opacity: 0.55 + 0.45 * ov.pulse
            }
            HText {
                visible: tmr.t0 === null
                x: reticle.rr + reticle.rr * 0.08; y: reticle.rr + reticle.rr * 0.06
                opacity: ov.seg(0.6, 0.9)
                text: "X " + ov.pad4(ov.cx) + "\nY " + ov.pad4(ov.cy)
                color: ov.c(0.5); font.family: tk.mono; font.pixelSize: ov.fs(7.5); lineHeight: 0.95
            }
        }

        // ---- 좌우 괄호 호: 왼쪽 = 마이크 입력, 오른쪽 = 자비스 목소리 (실제 크기) ----
        Shape {
            id: brk
            readonly property real e: ov.seg(0.3, 0.7)
            readonly property real r1: ov.rr * 1.2
            x: ov.cx - r1; y: ov.cy - r1
            width: r1 * 2; height: r1 * 2
            opacity: e
            preferredRendererType: Shape.CurveRenderer
            ShapePath {   // 바깥 머리카락 괄호
                strokeColor: ov.c(0.55); strokeWidth: 1.2; fillColor: "transparent"; capStyle: ShapePath.FlatCap
                PathAngleArc { centerX: brk.r1; centerY: brk.r1; radiusX: brk.r1; radiusY: brk.r1; startAngle: 180 - 34 * brk.e; sweepAngle: 68 * brk.e }
                PathAngleArc { centerX: brk.r1; centerY: brk.r1; radiusX: brk.r1; radiusY: brk.r1; startAngle: -34 * brk.e; sweepAngle: 68 * brk.e }
            }
            ShapePath {   // 눈금 트랙
                strokeColor: ov.c(0.24); strokeWidth: ov.px(5); fillColor: "transparent"
                strokeStyle: ShapePath.DashLine; dashPattern: [0.5, 0.9]
                PathAngleArc { centerX: brk.r1; centerY: brk.r1; radiusX: brk.r1 - ov.px(8); radiusY: brk.r1 - ov.px(8); startAngle: 150; sweepAngle: 60 * brk.e }
                PathAngleArc { centerX: brk.r1; centerY: brk.r1; radiusX: brk.r1 - ov.px(8); radiusY: brk.r1 - ov.px(8); startAngle: 30; sweepAngle: -60 * brk.e }
            }
            ShapePath {   // 실제 소리 크기 (아래에서 위로)
                strokeColor: ov.ic(0.9); strokeWidth: ov.px(5); fillColor: "transparent"
                strokeStyle: ShapePath.DashLine; dashPattern: [0.5, 0.9]
                PathAngleArc { centerX: brk.r1; centerY: brk.r1; radiusX: brk.r1 - ov.px(8); radiusY: brk.r1 - ov.px(8); startAngle: 150; sweepAngle: Math.max(0.5, 60 * ov.inL) * brk.e }
                PathAngleArc { centerX: brk.r1; centerY: brk.r1; radiusX: brk.r1 - ov.px(8); radiusY: brk.r1 - ov.px(8); startAngle: 30; sweepAngle: -Math.max(0.5, 60 * ov.outL) * brk.e }
            }
        }
        Repeater {
            model: [[-1, "VOICE IN", ov.inL], [1, "VOICE OUT", ov.outL]]
            Column {
                readonly property int sgn: modelData[0]
                readonly property real r1: ov.rr * 1.2
                x: sgn < 0 ? ov.cx - r1 - width - ov.px(12) : ov.cx + r1 + ov.px(12)
                y: ov.cy - height / 2
                opacity: brk.e
                spacing: 0
                Label { anchors.right: parent.sgn < 0 ? parent.right : undefined; text: modelData[1]; font.pixelSize: ov.fs(7.5) }
                Num { anchors.right: parent.sgn < 0 ? parent.right : undefined; text: Math.round(modelData[2] * 100) + " %"; font.pixelSize: ov.fs(10) }
            }
        }

        // ---- 대각선 주석: 지시선 + 실제 측정값 ----
        Item {
            id: notes
            anchors.fill: parent
            opacity: ov.seg(0.55, 0.85)
            readonly property var rows: [
                [-1, -1, "CORE LOAD", (ov.stats.cpu || 0).toFixed(1) + " %", ov.cpuHi],
                [1, -1, "MEMORY", (ov.stats.ram || 0).toFixed(1) + " %", ov.ramHi],
                [-1, 1, "DOWNLINK", ov.rate(ov.stats.down), false],
                [1, 1, "UPLINK", ov.rate(ov.stats.up), false]
            ]
            readonly property real k: 0.7071
            readonly property real r0: ov.rr * 1.03
            readonly property real dl: ov.px(22)
            readonly property real hl: ov.px(70)
            Shape {
                anchors.fill: parent
                preferredRendererType: Shape.CurveRenderer
                ShapePath {
                    strokeColor: ov.c(0.45); strokeWidth: 1; fillColor: "transparent"
                    PathMove { x: ov.cx - notes.r0 * notes.k; y: ov.cy - notes.r0 * notes.k }
                    PathLine { x: ov.cx - (notes.r0 + notes.dl) * notes.k; y: ov.cy - (notes.r0 + notes.dl) * notes.k }
                    PathLine { x: ov.cx - (notes.r0 + notes.dl) * notes.k - notes.hl; y: ov.cy - (notes.r0 + notes.dl) * notes.k }
                    PathMove { x: ov.cx + notes.r0 * notes.k; y: ov.cy - notes.r0 * notes.k }
                    PathLine { x: ov.cx + (notes.r0 + notes.dl) * notes.k; y: ov.cy - (notes.r0 + notes.dl) * notes.k }
                    PathLine { x: ov.cx + (notes.r0 + notes.dl) * notes.k + notes.hl; y: ov.cy - (notes.r0 + notes.dl) * notes.k }
                    PathMove { x: ov.cx - notes.r0 * notes.k; y: ov.cy + notes.r0 * notes.k }
                    PathLine { x: ov.cx - (notes.r0 + notes.dl) * notes.k; y: ov.cy + (notes.r0 + notes.dl) * notes.k }
                    PathLine { x: ov.cx - (notes.r0 + notes.dl) * notes.k - notes.hl; y: ov.cy + (notes.r0 + notes.dl) * notes.k }
                    PathMove { x: ov.cx + notes.r0 * notes.k; y: ov.cy + notes.r0 * notes.k }
                    PathLine { x: ov.cx + (notes.r0 + notes.dl) * notes.k; y: ov.cy + (notes.r0 + notes.dl) * notes.k }
                    PathLine { x: ov.cx + (notes.r0 + notes.dl) * notes.k + notes.hl; y: ov.cy + (notes.r0 + notes.dl) * notes.k }
                }
            }
            Repeater {
                model: notes.rows
                Item {
                    readonly property real ex: ov.cx + modelData[0] * ((notes.r0 + notes.dl) * notes.k + notes.hl)
                    readonly property real ey: ov.cy + modelData[1] * (notes.r0 + notes.dl) * notes.k
                    Rectangle {   // 고리 쪽 끝점
                        width: ov.px(4); height: width; rotation: 45
                        x: ov.cx + modelData[0] * notes.r0 * notes.k - width / 2
                        y: ov.cy + modelData[1] * notes.r0 * notes.k - height / 2
                        color: modelData[4] ? tk.red : tk.ice
                    }
                    Column {
                        x: modelData[0] < 0 ? parent.ex : parent.ex - width
                        y: parent.ey - height - ov.px(2)
                        spacing: -ov.px(1)
                        Label { anchors.right: modelData[0] > 0 ? parent.right : undefined; text: modelData[2]; font.pixelSize: ov.fs(7.5) }
                        Num { anchors.right: modelData[0] > 0 ? parent.right : undefined; text: modelData[3]
                              color: modelData[4] ? tk.red : tk.ice; font.pixelSize: ov.fs(12) }
                    }
                }
            }
        }

        // ---- 조준경 아래 상태 글 ----
        Column {
            anchors.horizontalCenter: parent.horizontalCenter
            y: ov.cy + ov.rr + ov.px(26)
            spacing: ov.px(3)
            opacity: ov.seg(0.45, 0.7)
            Decode {
                anchors.horizontalCenter: parent.horizontalCenter
                full: ov.p < 1 ? "ACTIVE MODE ENGAGED" : (ov.stateLabels[ov.st] || ov.st.toUpperCase())
                t: ov.calm ? 1 : ov.lin(0.45, 0.8); seed: 3
                color: tk.ice
                font.pixelSize: ov.fs(14); font.letterSpacing: ov.px(6); font.weight: Font.DemiBold
            }
            HText {
                anchors.horizontalCenter: parent.horizontalCenter
                width: Math.min(implicitWidth, ov.px(480)); elide: Text.ElideRight
                horizontalAlignment: Text.AlignHCenter
                text: jarvis.statusText
                color: ov.c(0.7)
                font.pixelSize: ov.fs(10.5); font.letterSpacing: ov.px(1)
            }
            HText {
                anchors.horizontalCenter: parent.horizontalCenter
                visible: ov.timers.length > 0
                text: ov.timers.length ? "⏱  " + ov.timers[0].label + (ov.timers.length > 1 ? "   +" + (ov.timers.length - 1) : "") : ""
                color: tk.ice; font.pixelSize: ov.fs(11)
            }
        }

        // =================================================================
        // 위쪽 HUD: 방위 테이프 · 제목 · 시스템 모드 / 상태 · 부하 기록
        Shape {   // 위 가장자리 머리카락 선 (가운데 테이프 자리는 비움)
            anchors.fill: parent
            opacity: 0.8 * ov.seg(0.2, 0.5)
            preferredRendererType: Shape.CurveRenderer
            readonly property real yy: ov.px(16)
            readonly property real g0: ov.cx - tape.width / 2 - ov.px(18)
            readonly property real g1: ov.cx + tape.width / 2 + ov.px(18)
            ShapePath {
                strokeColor: ov.c(0.28); strokeWidth: 1; fillColor: "transparent"
                PathMove { x: ov.sideX; y: ov.px(16) } PathLine { x: ov.cx - tape.width / 2 - ov.px(18); y: ov.px(16) }
                PathMove { x: ov.cx + tape.width / 2 + ov.px(18); y: ov.px(16) } PathLine { x: ov.width - ov.sideX; y: ov.px(16) }
            }
            ShapePath {
                strokeColor: ov.ic(0.7); strokeWidth: 1.5; fillColor: "transparent"; capStyle: ShapePath.FlatCap
                PathMove { x: ov.sideX; y: ov.px(12) } PathLine { x: ov.sideX; y: ov.px(20) }
                PathMove { x: ov.width - ov.sideX; y: ov.px(12) } PathLine { x: ov.width - ov.sideX; y: ov.px(20) }
                PathMove { x: ov.cx - tape.width / 2 - ov.px(18); y: ov.px(16) } PathLine { x: ov.cx - tape.width / 2 - ov.px(30); y: ov.px(16) }
                PathMove { x: ov.cx + tape.width / 2 + ov.px(18); y: ov.px(16) } PathLine { x: ov.cx + tape.width / 2 + ov.px(30); y: ov.px(16) }
            }
        }
        Fly {
            id: tape
            d: 0.3
            width: Math.min(ov.width * 0.3, ov.px(520)); height: ov.px(64)
            x: ov.cx - width / 2; y: ov.px(10)
            Item {
                id: hd
                width: parent.width; height: ov.px(28)
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
                            width: 1; height: (index % 72) % 3 === 0 ? ov.px(8) : ov.px(4)
                            y: hd.height - height
                            color: ov.c(0.15 + 0.6 * parent.fade)
                        }
                        HText {
                            readonly property int dd: (index % 72) * 5
                            visible: dd % 45 === 0
                            text: dd % 45 === 0 ? ["N", "NE", "E", "SE", "S", "SW", "W", "NW"][dd / 45] : ""
                            x: -width / 2; y: 0
                            color: dd === 0 ? tk.ice : ov.c(0.2 + 0.65 * parent.fade)
                            font.pixelSize: ov.fs(10); font.weight: Font.DemiBold
                        }
                    }
                }
            }
            Rectangle { width: parent.width; height: 1; y: ov.px(28); color: ov.c(0.25) }
            Rectangle { width: ov.px(7); height: width; rotation: 45; color: "transparent"; border.color: tk.ice; border.width: 1
                        x: parent.width / 2 - width / 2; y: ov.px(28) - height / 2 }
            Decode {
                anchors.horizontalCenter: parent.horizontalCenter
                y: ov.px(38)
                full: "J.A.R.V.I.S   ·   ACTIVE MODE   ·   HDG " + ("00" + Math.floor(ov.heading)).slice(-3)
                t: ov.calm ? 1 : ov.lin(0.4, 0.75); seed: 1
                color: ov.ic(0.9)
                font.pixelSize: ov.fs(10.5); font.letterSpacing: ov.px(4); font.weight: Font.DemiBold
            }
        }
        // 왼쪽 위: 시스템 모드 · 상태
        Fly {
            d: 0.32
            x: ov.sideX + ov.px(2); y: ov.px(28)
            width: ov.px(300); height: ov.px(52)
            Row {
                spacing: ov.px(26)
                Column {
                    spacing: ov.px(2)
                    Label { text: "SYSTEM MODE"; font.pixelSize: ov.fs(7.5) }
                    HText { text: "ACTIVE" + (jarvis.chatMode ? "  ·  CHAT" : ""); color: tk.ice
                            font.pixelSize: ov.fs(12); font.letterSpacing: ov.px(2); font.weight: Font.DemiBold }
                }
                Column {
                    spacing: ov.px(2)
                    Label { text: "SYSTEM STATUS"; font.pixelSize: ov.fs(7.5) }
                    Row {
                        spacing: ov.px(7)
                        Led { anchors.verticalCenter: parent.verticalCenter; col: ov.alert ? tk.red : tk.green; blink: ov.alert }
                        HText {
                            text: ov.cpuHi ? "CPU " + Math.round(ov.stats.cpu) + "%" : ov.ramHi ? "MEM " + Math.round(ov.stats.ram) + "%"
                                  : ov.batLo ? "BATTERY LOW" : "NOMINAL"
                            color: ov.alert ? tk.red : tk.ice
                            font.pixelSize: ov.fs(12); font.letterSpacing: ov.px(2); font.weight: Font.DemiBold
                        }
                    }
                }
            }
        }
        // 오른쪽 위: 부하 기록 (실제 CPU 48 초) + 화면 정보
        Fly {
            d: 0.36
            width: ov.px(220); height: ov.px(52)
            x: ov.width - ov.sideX - width - ov.px(2); y: ov.px(28)
            Item {
                id: spark
                width: parent.width; height: ov.px(26)
                Rectangle { width: parent.width; height: 1; y: parent.height; color: ov.c(0.25) }
                Rectangle { width: parent.width; height: 1; y: parent.height * 0.15; color: ov.rc(0.25) }   // 85 % 경고선
                Row {
                    anchors.bottom: parent.bottom; anchors.right: parent.right
                    spacing: 1
                    Repeater {
                        model: ov.cpuHist
                        Rectangle {
                            width: Math.max(1, spark.width / 48 - 1); height: Math.max(1, spark.height * modelData / 100)
                            anchors.bottom: parent.bottom
                            color: modelData > 85 ? tk.red : ov.c(0.2 + 0.65 * (index / Math.max(1, ov.cpuHist.length)))
                        }
                    }
                }
            }
            Row {
                y: ov.px(31)
                width: parent.width
                Label { text: "LOAD HISTORY · 48 s"; font.pixelSize: ov.fs(7.5); width: parent.width * 0.55; elide: Text.ElideRight }
                Label { text: "DISPLAY " + Math.round(ov.width) + "×" + Math.round(ov.height); font.pixelSize: ov.fs(7.5)
                        width: parent.width * 0.45; horizontalAlignment: Text.AlignRight; elide: Text.ElideLeft }
            }
        }

        // =================================================================
        // 왼쪽 열
        // ---- SYSTEM TIME ----
        Fly {
            d: 0.34; tilt: 12
            x: ov.sideX; y: ov.colY
            width: ov.panelW; height: ov.px(124)
            HudPanel { anchors.fill: parent; title: "SYSTEM TIME"; tag: ov.tzTag }
            // 초침 고리 (60 눈금)
            Item {
                id: dayRing
                x: ov.px(14); y: ov.px(32)
                width: ov.px(82); height: width
                readonly property real m: width / 2
                readonly property real sec: ov.now.getSeconds() + ov.now.getMilliseconds() / 1000
                Shape {
                    anchors.fill: parent
                    preferredRendererType: Shape.CurveRenderer
                    ShapePath {
                        strokeColor: ov.c(0.45); strokeWidth: ov.px(3); fillColor: "transparent"
                        strokeStyle: ShapePath.DashLine; dashPattern: [0.25, 2.3]
                        PathAngleArc { centerX: dayRing.m; centerY: dayRing.m; radiusX: dayRing.m - ov.px(2); radiusY: dayRing.m - ov.px(2); startAngle: -90; sweepAngle: 360 }
                    }
                    ShapePath {
                        strokeColor: ov.c(0.14); strokeWidth: ov.px(2.5); fillColor: "transparent"
                        PathAngleArc { centerX: dayRing.m; centerY: dayRing.m; radiusX: dayRing.m - ov.px(9); radiusY: dayRing.m - ov.px(9); startAngle: 0; sweepAngle: 360 }
                    }
                    ShapePath {
                        strokeColor: tk.ice; strokeWidth: ov.px(2.5); fillColor: "transparent"; capStyle: ShapePath.FlatCap
                        PathAngleArc { centerX: dayRing.m; centerY: dayRing.m; radiusX: dayRing.m - ov.px(9); radiusY: dayRing.m - ov.px(9)
                                       startAngle: -90; sweepAngle: Math.max(1, 6 * dayRing.sec) }
                    }
                    ShapePath {   // 분 위치 표식
                        strokeColor: ov.c(0.35); strokeWidth: 1; fillColor: "transparent"
                        PathAngleArc { centerX: dayRing.m; centerY: dayRing.m; radiusX: dayRing.m - ov.px(15); radiusY: dayRing.m - ov.px(15); startAngle: 0; sweepAngle: 360 }
                    }
                }
                Rectangle {   // 분침 끝 점
                    readonly property real a: (ov.now.getMinutes() * 6 - 90) * Math.PI / 180
                    width: ov.px(4); height: width; radius: width / 2; color: tk.cyan
                    x: dayRing.m + Math.cos(a) * (dayRing.m - ov.px(15)) - width / 2
                    y: dayRing.m + Math.sin(a) * (dayRing.m - ov.px(15)) - height / 2
                }
                Column {
                    anchors.centerIn: parent
                    spacing: -ov.px(2)
                    HText { anchors.horizontalCenter: parent.horizontalCenter; text: ov.now.getDate()
                            color: tk.ice; font.pixelSize: ov.fs(24); font.weight: Font.Light }
                    Label { anchors.horizontalCenter: parent.horizontalCenter; font.pixelSize: ov.fs(7)
                            text: ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"][ov.now.getMonth()] }
                }
            }
            Column {
                x: ov.px(110); y: ov.px(28)
                spacing: 0
                Row {
                    HText {
                        id: clockTxt
                        text: ov.pad(ov.now.getHours()) + ":" + ov.pad(ov.now.getMinutes())
                        color: tk.ice; font.pixelSize: ov.fs(42); font.weight: Font.Light
                    }
                    HText {
                        anchors.baseline: clockTxt.baseline
                        text: "  " + ov.pad(ov.now.getSeconds())
                        color: ov.c(0.7); font.pixelSize: ov.fs(14)
                    }
                }
                Decode {
                    full: ["SUNDAY", "MONDAY", "TUESDAY", "WEDNESDAY", "THURSDAY", "FRIDAY", "SATURDAY"][ov.now.getDay()]
                    t: ov.calm ? 1 : ov.lin(0.5, 0.8); seed: 7
                    color: ov.ic(0.85)
                    font.pixelSize: ov.fs(11); font.letterSpacing: ov.px(3.5)
                }
                HText {
                    text: ov.now.getFullYear() + "." + ov.pad(ov.now.getMonth() + 1) + "." + ov.pad(ov.now.getDate())
                          + "   ·   WK " + ov.pad(ov.isoWeek) + "   ·   D " + ("00" + ov.dayOfYear).slice(-3)
                    color: ov.c(0.55); font.pixelSize: ov.fs(8.5); font.letterSpacing: ov.px(1.2)
                }
            }
        }

        // ---- SYSTEM LOG: 실제 상태 + 실제로 일어난 일 (타이머가 있으면 타이머) ----
        Fly {
            d: 0.4; tilt: 12
            x: ov.sideX; y: ov.colY + ov.px(124) + ov.gap
            width: ov.panelW; height: ov.px(176)
            HudPanel {
                anchors.fill: parent
                title: ov.timers.length ? "TIMERS" : "SYSTEM LOG"
                tag: ov.timers.length ? ov.timers.length + " ACTIVE" : "EVENTS " + ov.pad(syslog.count)
            }
            // 상태 표 (2 × 2)
            Grid {
                x: ov.px(14); y: ov.px(32)
                columns: 2; columnSpacing: ov.px(14); rowSpacing: ov.px(5)
                Repeater {
                    model: [
                        ["CPU", (ov.stats.cpu || 0).toFixed(1) + "%", ov.cpuHi ? tk.red : tk.green],
                        ["MEMORY", (ov.stats.ram || 0).toFixed(1) + "%", ov.ramHi ? tk.red : tk.green],
                        ["OPTIC", ov.target.kind === "point" ? "LOCKED" : ov.target.kind ? "TRACKING" : "IDLE",
                                  ov.target.kind ? tk.cyan : ov.c(0.4)],
                        ["VOICE", ov.stateLabels[ov.st] || ov.st.toUpperCase(), ov.st === "offline" ? tk.red : ov.sCol]
                    ]
                    Item {
                        width: (ov.panelW - ov.px(42)) / 2; height: ov.px(15)
                        Led { anchors.verticalCenter: parent.verticalCenter; col: modelData[2]; width: ov.px(5)
                              blink: modelData[2] === tk.red }
                        Label { x: ov.px(11); anchors.verticalCenter: parent.verticalCenter; text: modelData[0]; font.pixelSize: ov.fs(8) }
                        HText { anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter
                                text: modelData[1]; color: modelData[2] === tk.red ? tk.red : tk.ice
                                font.family: tk.mono; font.pixelSize: ov.fs(10) }
                    }
                }
            }
            Rectangle { x: ov.px(14); y: ov.px(73); width: parent.width - ov.px(28); height: 1; color: ov.c(0.16) }
            // 사건 기록
            Column {
                visible: ov.timers.length === 0
                x: ov.px(14); y: ov.px(80)
                width: parent.width - ov.px(28); height: parent.height - y - ov.px(8); clip: true
                spacing: ov.px(2)
                Repeater {
                    model: syslog
                    Row {
                        spacing: ov.px(8)
                        opacity: 1 - index * 0.13
                        HText { text: t; color: ov.c(0.5); font.family: tk.mono; font.pixelSize: ov.fs(9.5) }
                        Rectangle { width: ov.px(4); height: width; rotation: 45; anchors.verticalCenter: parent.verticalCenter
                                    color: lv === "err" ? tk.red : lv === "run" ? tk.amber : lv === "ok" ? tk.green : tk.cyan }
                        HText { text: (tag + "      ").substring(0, 6); color: ov.c(0.75); font.family: tk.mono; font.pixelSize: ov.fs(9.5) }
                        HText { text: msg; color: lv === "err" ? tk.red : ov.ic(0.9); font.family: tk.mono; font.pixelSize: ov.fs(9.5)
                                width: ov.panelW - ov.px(170); elide: Text.ElideRight }
                    }
                }
            }
            // 타이머
            Column {
                visible: ov.timers.length > 0
                x: ov.px(14); y: ov.px(82)
                width: parent.width - ov.px(28)
                spacing: ov.px(6)
                Repeater {
                    model: ov.timers.slice(0, 3)
                    Column {
                        readonly property real rem: ov.left(modelData)
                        readonly property real frac: rem / Math.max(1, modelData.total)
                        width: parent.width
                        spacing: ov.px(3)
                        Item {
                            width: parent.width; height: ov.px(15)
                            HText { text: modelData.label; color: tk.ice; font.family: "Segoe UI"; font.pixelSize: ov.fs(11.5)
                                    width: parent.width - ov.px(80); elide: Text.ElideRight; anchors.verticalCenter: parent.verticalCenter }
                            HText { anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter
                                    text: ov.hms(parent.parent.rem); color: parent.parent.frac < 0.1 ? tk.red : tk.ice
                                    font.pixelSize: ov.fs(13) }
                        }
                        Rectangle {
                            width: parent.width; height: ov.px(2); color: ov.c(0.14)
                            Rectangle { width: parent.width * parent.parent.frac; height: parent.height
                                        color: parent.parent.frac < 0.1 ? tk.red : tk.cyan }
                        }
                    }
                }
            }
        }

        // ---- ATMOSPHERICS (날씨 연결 그대로) ----
        Fly {
            id: wx
            d: 0.46; tilt: 12
            x: ov.sideX; y: ov.colY + ov.px(124) + ov.px(176) + 2 * ov.gap
            width: ov.panelW; height: ov.px(212)
            readonly property bool ready: ov.weather.temp !== undefined
            HudPanel {
                anchors.fill: parent
                title: "ATMOSPHERICS"; tag: wx.ready ? String(ov.weather.loc).toUpperCase() : ""
                alert: ov.weather.error !== undefined && !wx.ready
            }
            HText {
                visible: !wx.ready
                anchors.centerIn: parent
                text: ov.weather.error ? "WEATHER LINK OFFLINE" : "SCANNING ATMOSPHERE" + ".".repeat(1 + ov.tick % 3)
                color: ov.weather.error ? tk.red : ov.c(0.75)
                font.pixelSize: ov.fs(10.5); font.letterSpacing: ov.px(2)
            }
            // 기온 + 강수 확률 고리
            Item {
                id: wring
                visible: wx.ready
                x: ov.px(14); y: ov.px(32)
                width: ov.px(88); height: width
                readonly property real m: width / 2
                Shape {
                    anchors.fill: parent
                    preferredRendererType: Shape.CurveRenderer
                    ShapePath {
                        strokeColor: ov.c(0.2); strokeWidth: 1; fillColor: "transparent"
                        PathAngleArc { centerX: wring.m; centerY: wring.m; radiusX: wring.m - 1; radiusY: wring.m - 1; startAngle: 135; sweepAngle: 270 }
                    }
                    ShapePath {
                        strokeColor: ov.c(0.14); strokeWidth: ov.px(3.5); fillColor: "transparent"
                        PathAngleArc { centerX: wring.m; centerY: wring.m; radiusX: wring.m - ov.px(7); radiusY: wring.m - ov.px(7); startAngle: 135; sweepAngle: 270 }
                    }
                    ShapePath {
                        strokeColor: tk.cyan; strokeWidth: ov.px(3.5); fillColor: "transparent"; capStyle: ShapePath.FlatCap
                        PathAngleArc { centerX: wring.m; centerY: wring.m; radiusX: wring.m - ov.px(7); radiusY: wring.m - ov.px(7)
                                       startAngle: 135; sweepAngle: 270 * Math.max(0.005, (ov.weather.rain || 0) / 100) * wx.e }
                    }
                    ShapePath {
                        strokeColor: ov.c(0.3); strokeWidth: 1; fillColor: "transparent"
                        strokeStyle: ShapePath.DashLine; dashPattern: [1, 3]
                        PathAngleArc { centerX: wring.m; centerY: wring.m; radiusX: wring.m - ov.px(14); radiusY: wring.m - ov.px(14); startAngle: 0; sweepAngle: 360 }
                    }
                }
                HText {
                    anchors.centerIn: parent; anchors.verticalCenterOffset: -ov.px(3)
                    text: (ov.weather.temp !== undefined ? ov.weather.temp : "-") + "°"
                    color: tk.ice; font.pixelSize: ov.fs(28); font.weight: Font.Light
                }
                HText {
                    anchors.horizontalCenter: parent.horizontalCenter
                    y: parent.height - ov.px(14)
                    text: "RAIN " + (ov.weather.rain || 0) + "%"
                    color: ov.c(0.75); font.pixelSize: ov.fs(7.5); font.letterSpacing: ov.px(1.5)
                }
            }
            Column {
                visible: wx.ready
                x: ov.px(116); y: ov.px(34)
                width: parent.width - ov.px(130)
                spacing: ov.px(4)
                HText { width: parent.width; elide: Text.ElideRight; text: ov.weather.desc || ""
                        color: tk.ice; font.family: "Segoe UI"; font.pixelSize: ov.fs(14) }
                Grid {
                    columns: 2; columnSpacing: ov.px(10); rowSpacing: ov.px(3)
                    Repeater {
                        model: [["체감", ov.weather.feels + "°"], ["습도", ov.weather.humidity + "%"],
                                ["바람", ov.weather.wind + " km/h"], ["최고 / 최저", ov.weather.max + "° / " + ov.weather.min + "°"]]
                        Column {
                            width: (wx.width - ov.px(140)) / 2
                            HText { text: modelData[0]; color: ov.c(0.75); font.family: "Segoe UI"; font.pixelSize: ov.fs(9.5) }
                            HText { text: modelData[1]; color: tk.ice; font.pixelSize: ov.fs(11.5) }
                        }
                    }
                }
            }
            // 오늘 3시간 간격 기온 — 선 그래프
            Item {
                id: hourly
                visible: wx.ready && hs.length > 1
                x: ov.px(18); y: ov.px(136)
                width: parent.width - ov.px(36); height: ov.px(62)
                readonly property var hs: ov.weather.hourly || []
                readonly property real lo: Math.min.apply(null, hs.map(h => h.t).concat([99])) - 1
                readonly property real hi: Math.max.apply(null, hs.map(h => h.t).concat([-99])) + 1
                readonly property int nowSlot: Math.floor(ov.now.getHours() / 3)
                readonly property real gy0: ov.px(14)
                readonly property real gh: ov.px(28)
                function px_(i) { return hs.length > 1 ? i * width / (hs.length - 1) : 0 }
                function py_(t) { return gy0 + gh * (1 - (t - lo) / Math.max(1, hi - lo) * wx.e) }
                readonly property var pts: hs.map((h, i) => Qt.point(px_(i), py_(h.t)))
                Rectangle { y: hourly.gy0 + hourly.gh; width: parent.width; height: 1; color: ov.c(0.18) }
                Shape {
                    anchors.fill: parent
                    preferredRendererType: Shape.CurveRenderer
                    ShapePath {
                        strokeColor: ov.c(0.75); strokeWidth: 1.5; fillColor: "transparent"
                        PathPolyline { path: hourly.pts }
                    }
                }
                Repeater {
                    model: hourly.hs
                    Item {
                        readonly property bool cur: index === hourly.nowSlot
                        x: hourly.px_(index); y: 0
                        Rectangle {   // 강수 확률 막대 (아래)
                            x: -ov.px(2); width: ov.px(4)
                            height: Math.max(1, ov.px(8) * modelData.rain / 100)
                            y: hourly.gy0 + hourly.gh - height
                            color: ov.c(0.35)
                        }
                        Rectangle {
                            width: parent.cur ? ov.px(6) : ov.px(4); height: width; radius: width / 2
                            x: -width / 2; y: hourly.py_(modelData.t) - height / 2
                            color: parent.cur ? tk.ice : tk.teal
                            border.color: parent.cur ? tk.ice : tk.cyan; border.width: 1
                        }
                        HText { x: -width / 2; y: hourly.py_(modelData.t) - height - ov.px(3); text: modelData.t + "°"
                                color: parent.cur ? tk.ice : ov.c(0.7); font.pixelSize: ov.fs(8) }
                        HText { x: -width / 2; y: hourly.gy0 + hourly.gh + ov.px(3); text: ov.pad(modelData.h)
                                color: parent.cur ? tk.ice : ov.c(0.5); font.pixelSize: ov.fs(8) }
                    }
                }
            }
        }

        // =================================================================
        // 오른쪽 열
        // ---- PROCESS MONITOR — "1번 꺼줘" 로 종료. 빨강은 무거울 때만 ----
        Fly {
            id: alertBox
            d: 0.36; tilt: -12
            x: ov.rightX; y: ov.colY
            width: ov.panelW; height: ov.px(166)
            HudPanel {
                anchors.fill: parent
                title: "PROCESS MONITOR"; alert: ov.alert
                tag: ov.cpuHi ? "CPU " + Math.round(ov.stats.cpu) + "%" : ov.ramHi ? "MEM " + Math.round(ov.stats.ram) + "%"
                     : ov.batLo ? "BATTERY LOW" : "CPU " + Math.round(ov.stats.cpu || 0) + "%  ·  MEM " + Math.round(ov.stats.ram || 0) + "%"
            }
            Led { x: parent.width - ov.px(14); y: ov.px(10); col: ov.alert ? tk.red : tk.green; blink: true; width: ov.px(5) }
            HText {
                visible: ov.procs.length === 0
                anchors.centerIn: parent
                text: "SCANNING PROCESSES" + ".".repeat(1 + ov.tick % 3)
                color: ov.c(0.75); font.pixelSize: ov.fs(10); font.letterSpacing: ov.px(2)
            }
            Column {
                x: ov.px(12); y: ov.px(31)
                width: parent.width - ov.px(24)
                spacing: ov.px(1)
                Repeater {
                    model: ov.procs
                    Item {
                        readonly property bool heavy: modelData.cpu >= 50 || modelData.mem >= 2048
                        readonly property color fg: heavy ? tk.red : tk.ice
                        width: parent.width; height: ov.px(19)
                        Rectangle {
                            width: ov.px(15); height: ov.px(13); anchors.verticalCenter: parent.verticalCenter
                            color: parent.heavy ? ov.rc(0.25) : "transparent"
                            border.color: parent.heavy ? tk.red : ov.c(0.5); border.width: 1
                            HText { anchors.centerIn: parent; text: index + 1; color: parent.parent.fg; font.pixelSize: ov.fs(8.5); font.weight: Font.DemiBold }
                        }
                        HText {
                            id: pmMem
                            anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter
                            width: ov.fs(48); horizontalAlignment: Text.AlignRight
                            text: ov.mb(modelData.mem)
                            color: modelData.mem >= 2048 ? tk.red : ov.ic(0.9); font.family: tk.mono; font.pixelSize: ov.fs(9.5)
                        }
                        HText {
                            id: pmCpu
                            anchors.right: pmMem.left; anchors.verticalCenter: parent.verticalCenter
                            width: ov.fs(42); horizontalAlignment: Text.AlignRight
                            text: modelData.cpu.toFixed(1) + "%"
                            color: modelData.cpu >= 50 ? tk.red : ov.ic(0.9); font.family: tk.mono; font.pixelSize: ov.fs(9.5)
                        }
                        Rectangle {   // CPU 막대
                            id: pmBar
                            anchors.right: pmCpu.left; anchors.rightMargin: ov.px(6); anchors.verticalCenter: parent.verticalCenter
                            width: ov.px(46); height: ov.px(3); color: ov.c(0.12)
                            Rectangle {
                                width: parent.width * Math.min(1, modelData.cpu / 100); height: parent.height
                                color: modelData.cpu >= 50 ? tk.red : tk.cyan
                                Behavior on width { NumberAnimation { duration: ov.calm ? 0 : 500; easing.type: Easing.OutCubic } }
                            }
                        }
                        HText {
                            x: ov.px(22); anchors.verticalCenter: parent.verticalCenter
                            width: Math.max(0, pmBar.x - x - ov.px(6)); elide: Text.ElideRight
                            text: modelData.name + (modelData.count > 1 ? "  ×" + modelData.count : "")
                            color: parent.fg; font.family: "Segoe UI"; font.pixelSize: ov.fs(10.5)
                        }
                    }
                }
            }
            HText {
                anchors.bottom: parent.bottom; anchors.bottomMargin: ov.px(6)
                anchors.horizontalCenter: parent.horizontalCenter
                text: "“1번 꺼줘” 라고 말하면 종료 (확인 후)"
                color: ov.c(0.6); font.family: "Segoe UI"; font.pixelSize: ov.fs(8.5)
            }
        }

        // ---- DIAGNOSTICS: 실제 CPU · 메모리 · 저장공간 ----
        Fly {
            d: 0.42; tilt: -12
            x: ov.rightX; y: ov.colY + ov.px(166) + ov.gap
            width: ov.panelW; height: ov.px(170)
            HudPanel { anchors.fill: parent; title: "DIAGNOSTICS"; tag: "SUBSYSTEMS" }
            Row {
                anchors.horizontalCenter: parent.horizontalCenter
                y: ov.px(30)
                spacing: ov.px(16)
                Gauge { v: ov.stats.cpu || 0; label: "CPU"; sub: "CORE LOAD"; warn: 85; e: ov.seg(0.5, 0.85) }
                Gauge { v: ov.stats.ram || 0; label: "MEMORY"; sub: "PHYSICAL"; warn: 88; e: ov.seg(0.55, 0.9) }
                Gauge { v: ov.stats.disk || 0; label: "STORAGE"; sub: "SYSTEM DRIVE"; warn: 90; e: ov.seg(0.6, 0.95) }
            }
            Rectangle { x: ov.px(14); y: parent.height - ov.px(24); width: parent.width - ov.px(28); height: 1; color: ov.c(0.14) }
            Row {
                x: ov.px(14); y: parent.height - ov.px(19)
                spacing: ov.px(16)
                Label { text: "▼ " + ov.rate(ov.stats.down); color: ov.ic(0.85); font.pixelSize: ov.fs(8.5) }
                Label { text: "▲ " + ov.rate(ov.stats.up); color: ov.ic(0.85); font.pixelSize: ov.fs(8.5) }
                Label {
                    text: ov.stats.bat !== undefined && ov.stats.bat >= 0
                          ? "BAT " + Math.round(ov.stats.bat) + "%" + (ov.stats.plugged ? " · AC" : "") : "POWER · AC"
                    color: ov.batLo ? tk.red : ov.c(0.6); font.pixelSize: ov.fs(8.5)
                }
            }
        }

        // ---- COMMS LINK: 명령 · 대답 · 작업 기록 ----
        Fly {
            d: 0.5; tilt: -12
            x: ov.rightX; y: ov.colY + ov.px(166) + ov.px(170) + 2 * ov.gap
            width: ov.panelW; height: ov.px(212)
            HudPanel { anchors.fill: parent; title: "COMMS LINK"; tag: jarvis.chatMode ? "CHAT MODE" : "SECURE" }
            Column {
                x: ov.px(14); y: ov.px(31)
                width: parent.width - ov.px(28); height: parent.height - y - ov.px(8); clip: true
                spacing: ov.px(3)
                Row {
                    spacing: ov.px(6)
                    Led { anchors.verticalCenter: parent.verticalCenter; col: tk.cyan; width: ov.px(4) }
                    Label { text: "OPERATOR"; font.pixelSize: ov.fs(7.5) }
                }
                HText {
                    width: parent.width; text: jarvis.userText || "—"
                    color: tk.ice; font.family: "Segoe UI"; font.pixelSize: ov.fs(11.5)
                    elide: Text.ElideRight; maximumLineCount: 2; wrapMode: Text.Wrap
                }
                Item { width: 1; height: ov.px(2) }
                Row {
                    spacing: ov.px(6)
                    Led { anchors.verticalCenter: parent.verticalCenter; col: ov.sCol; width: ov.px(4); blink: ov.st === "speaking" || ov.st === "thinking" }
                    Label { text: "J.A.R.V.I.S"; font.pixelSize: ov.fs(7.5) }
                    Label { text: "·  " + (ov.stateLabels[ov.st] || ov.st.toUpperCase()); color: ov.c(0.45); font.pixelSize: ov.fs(7.5) }
                }
                HText {
                    width: parent.width; text: jarvis.replyText || "—"
                    color: ov.c(0.95); font.family: "Segoe UI"; font.pixelSize: ov.fs(11.5)
                    elide: Text.ElideRight; maximumLineCount: 2; wrapMode: Text.Wrap
                }
                Item { width: 1; height: ov.px(2) }
                Rectangle { width: parent.width; height: 1; color: ov.c(0.16) }
                Repeater {
                    model: acts
                    Row {
                        spacing: ov.px(7)
                        Rectangle {
                            width: ov.px(4.5); height: width; rotation: 45
                            anchors.verticalCenter: parent.verticalCenter
                            color: status === "error" ? tk.red : status === "run" ? tk.amber : tk.green
                        }
                        HText { text: t; color: ov.c(0.5); font.family: tk.mono; font.pixelSize: ov.fs(9) }
                        HText { text: label; color: status === "error" ? tk.red : ov.ic(0.85); font.family: "Segoe UI"; font.pixelSize: ov.fs(9.5)
                                elide: Text.ElideRight; width: ov.panelW - ov.px(90) }
                    }
                }
            }
        }

        // =================================================================
        // 아래 가운데: 음성 채널 — 파형은 실제 마이크 · 목소리 크기로 움직인다
        Fly {
            id: voice
            d: 0.55
            width: ov.px(460); height: ov.px(64)
            x: ov.cx - width / 2; y: ov.safeB - ov.chatH - ov.px(10) - height
            readonly property real bh: ov.px(34)
            Rectangle { y: voice.bh / 2; x: ov.px(70); width: parent.width - ov.px(140); height: 1; color: ov.c(0.18) }
            Row {
                anchors.horizontalCenter: parent.horizontalCenter
                height: voice.bh
                spacing: ov.px(3)
                Repeater {
                    model: 45
                    Rectangle {
                        readonly property real centerFade: 1 - Math.abs(index - 22) / 23
                        readonly property real wob: 0.5 + 0.5 * Math.sin(ov.wave * Math.PI / 180 * 6 + index * 0.9)
                        width: ov.px(2.5)
                        height: Math.max(1.5, voice.bh * centerFade * (0.04 + ov.lvl * (0.5 + 0.5 * wob)))
                        anchors.verticalCenter: parent.verticalCenter
                        color: ov.sc(0.3 + 0.65 * centerFade)
                    }
                }
            }
            // 왼쪽: 지금 상태, 오른쪽: 입력 / 출력
            Row {
                x: 0; y: voice.bh / 2 - height / 2
                spacing: ov.px(6)
                Led { anchors.verticalCenter: parent.verticalCenter; col: ov.sCol; blink: ov.st === "listening" }
                Label { text: ov.st === "listening" ? "LISTENING" : ov.st === "speaking" ? "SPEAKING" : "IDLE"
                        color: ov.st === "listening" || ov.st === "speaking" ? tk.ice : ov.c(0.5); font.pixelSize: ov.fs(7.5) }
            }
            Label {
                anchors.right: parent.right; y: voice.bh / 2 - height / 2
                text: (ov.outL > ov.inL ? "OUT " : "IN ") + Math.round(ov.lvl * 100) + "%"
                font.family: tk.mono; font.pixelSize: ov.fs(8)
            }
            Row {
                anchors.horizontalCenter: parent.horizontalCenter
                y: voice.bh + ov.px(8)
                spacing: ov.px(8)
                Label { text: "VOICE CHANNEL"; font.pixelSize: ov.fs(8) }
                Label { text: "·"; font.pixelSize: ov.fs(8) }
                Led { anchors.verticalCenter: parent.verticalCenter; width: ov.px(4); col: jarvis.wakeEnabled ? tk.green : ov.c(0.5) }
                Label { text: jarvis.wakeEnabled ? "WAKE WORD ARMED" : "HOTKEY " + jarvis.hotkeyText
                        color: ov.ic(0.75); font.pixelSize: ov.fs(8) }
            }
        }
    }

    // ---- 채팅 입력 바 ----
    // 전체 화면 HUD 는 마우스 · 키보드를 아래 창으로 통과시키므로 그 안에서는 글을 칠 수 없다.
    // 그래서 누를 수 있는 작은 창을 음성 파형 아래에 따로 띄운다 (음성 인식이 잘 안 될 때 글로 명령).
    Window {
        id: chatBar
        objectName: "activeChat"
        title: "J.A.R.V.I.S CHAT"
        color: "transparent"
        flags: Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool
        readonly property real e: ov.seg(0.62, 0.94)
        visible: ov.visible && e > 0
        width: Math.max(340, 420 * ov.u); height: ov.chatH
        x: ov.x + ov.cx - width / 2
        y: ov.y + ov.safeB - height

        Item {
            anchors.fill: parent
            opacity: chatBar.e
            HudPanel { anchors.fill: parent; fill: chatBar.active ? 0.62 : 0.4; cut: 9 }
            Rectangle {   // 입력 중이면 아래 밑줄이 밝아진다
                x: 9; width: parent.width - 18; height: 1; y: parent.height - 1
                color: chatBar.active ? tk.ice : ov.c(0.25)
            }
            HText {
                id: chatCaret
                x: 14; anchors.verticalCenter: parent.verticalCenter
                text: "›"
                color: tk.cyan
                font.pixelSize: Math.max(17, 17 * ov.u); font.weight: Font.DemiBold
            }
            QC.TextField {
                id: chatInput
                anchors.left: chatCaret.right; anchors.right: chatHint.left
                anchors.rightMargin: 8
                anchors.verticalCenter: parent.verticalCenter
                color: tk.ice
                font.family: "Segoe UI"
                font.pixelSize: Math.max(13, 13 * ov.u)
                leftPadding: 8; rightPadding: 0; topPadding: 0; bottomPadding: 0
                placeholderText: chatBar.active ? "명령 입력…" : "여기를 눌러 글로 명령…"
                placeholderTextColor: Qt.rgba(0.72, 0.96, 1, 0.5)
                selectionColor: ov.c(0.45)
                background: Item {}
                // 처리 중이라 받지 못한 명령은 지우지 않고 남겨 둔다
                onAccepted: if (text.trim() !== "" && jarvis.submitText(text)) text = ""
                Keys.onEscapePressed: { text = ""; jarvis.releaseFocus() }
            }
            Row {
                id: chatHint
                anchors.right: parent.right; anchors.rightMargin: 14
                anchors.verticalCenter: parent.verticalCenter
                spacing: 6
                Led { anchors.verticalCenter: parent.verticalCenter; width: 5
                      col: ov.st === "thinking" ? tk.amber : chatBar.active ? tk.ice : ov.c(0.5); blink: ov.st === "thinking" }
                Label {
                    text: ov.st === "thinking" ? "PROCESSING" : chatBar.active ? "ENTER · ESC" : "CHAT"
                    font.pixelSize: Math.max(9, 9 * ov.u)
                }
            }
        }
    }
}
