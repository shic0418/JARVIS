// 액티브 모드 — 수트를 입고 헬멧 안에서 앞을 보는 화면 (MCU 아이언맨 HUD 의 느낌을 새로 그림)
//   테두리: 검은 그늘 대신 헬멧 안쪽 장갑 — 레드 이마판 · 골드 뺨판 · 레드 턱판, 골드 테두리에 HUD 빛이 비쳐 주황으로 빛난다.
//           장갑 안쪽은 따뜻한 어둠이 깔려 그 위의 위젯은 뒤 화면이 흰 창이어도 또렷하다.
//   홀로그램: 금색 · 주황 · 흰빛, 굵은 선과 채운 도형. 모든 선과 글자 둘레에 어두운 테를 둘러(헤일로) 흰 화면 위에서도 읽힌다.
//   시선 고리: 웹캠으로 추정한 시선(없으면 마우스 커서)을 큰 홀로그램 고리가 따라가고, 한곳을 오래 보면 잠근다(LOCK).
//   켜질 때: 장갑 판이 위아래에서 닫혀 눈높이 틈만 남기고 봉인(덜컹) → 열리며 섬광 · 충격파 · 휜 보정 격자,
//            위젯들이 곡면을 따라 날아가 자리를 잡고, SYSLOG 에 실제 점검 결과가 한 줄씩 찍힌다(→ ALL SYSTEMS ONLINE).
//   꺼질 때: 위젯이 바깥쪽부터 꺼지고 → 조준경이 풀리고 → 화면이 가로 한 줄로 접혀 점이 된다
//            → 장갑 판이 덮었다가(덜컹) 위아래로 열리며 원래 화면이 드러난다.
//   마우스 · 키보드 입력은 그대로 아래 창으로 통과한다 (켜 둔 채로 PC 를 쓸 수 있음).
//   단, 아래 가운데의 채팅 입력 바만은 따로 뜬 창이라 눌러서 글로 명령할 수 있다.
import QtQuick
import QtQuick.Controls.Basic as QC
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
    // ---- 색: 금색 홀로그램 + 흰빛, 경고는 빨강, 생각 중은 얼음빛 ----
    readonly property color gold: "#ffb02e"
    readonly property color hot: "#fff4dc"
    readonly property color ember: "#ff7a1c"
    readonly property color red: "#ff3b30"
    readonly property color amber: "#ffc04a"
    readonly property color ice: "#66e3ff"
    readonly property color green: "#7dffb0"
    readonly property color ink: "#1a0c00"                            // 금색 판 위 글자
    readonly property color shade: Qt.rgba(0.06, 0.025, 0.0, 0.95)   // 글자 테두리
    readonly property color outline: Qt.rgba(0.05, 0.02, 0.0, 0.88)  // 선 밑에 깔리는 어두운 테 (흰 화면 위에서도 선이 보이게)
    property color accent: st === "thinking" ? ice : st === "offline" ? red : st === "listening" ? amber : gold
    Behavior on accent { ColorAnimation { duration: 450 } }
    readonly property real level: Math.max(jarvis.micLevel, jarvis.voiceLevel)
    readonly property var stats: JSON.parse(jarvis.statsJson)
    readonly property var stateLabels: ({ boot: "INITIALIZING", standby: "STANDBY", listening: "LISTENING",
                                          thinking: "PROCESSING", speaking: "RESPONDING", offline: "MIC OFFLINE" })
    property var cpuHist: []
    readonly property var timers: JSON.parse(jarvis.timersJson)     // 돌고 있는 타이머 (가까운 순)
    readonly property var weather: JSON.parse(jarvis.weatherJson)
    readonly property var target: JSON.parse(jarvis.targetJson)     // 추적 박스: 지금 창 / 짚은 위치
    readonly property var gaze: JSON.parse(jarvis.gazeJson)         // 시선: {x, y, src: eye | cursor, conf}
    onStatsChanged: { const h = cpuHist.slice(-29); h.push(stats.cpu || 0); cpuHist = h }

    // 화면 크기에 맞춘 단위 (1600×900 기준 1)
    readonly property real u: Math.max(0.55, Math.min(width / 1600, height / 900))
    readonly property real cx: width / 2
    readonly property real cy: height / 2
    readonly property real diag: Math.sqrt(width * width + height * height)

    // ---- 펼침 진행도 p: 0(꺼짐) → 1(완전히 펼쳐짐) / 종료 진행도 down: 0 → 1 ----
    property real p: 0
    property real down: 0
    readonly property bool live: visible && p > 0
    // Windows 설정 '애니메이션 효과' 꺼짐 또는 hud_motion: off → 회전 · 스캔 · 깜빡임 연출을 멈춤 (app.py 가 reduceMotion 을 넘겨줌)
    readonly property bool calm: typeof reduceMotion !== "undefined" && reduceMotion === true
    readonly property bool moving: live && !calm
    // ---- 수트 착용: 장갑 판이 위아래에서 닫히며 봉인(seal 0→1) → 덜컹 → 다시 열리며(1→2) HUD 가 켜진다 ----
    property real seal: 2
    property real engagedAt: Date.now()   // 이번에 켠 시각 (세션 시간)
    property bool skipSeal: true         // 접히던 중에 다시 켜면(또는 움직임 줄이기) 봉인 연출은 건너뜀
    property real jolt: 0                 // 봉인되는 순간의 덜컹임 (1 → 0)
    readonly property real joltX: jolt * 7 * u * Math.sin(jolt * 37)
    readonly property real joltY: jolt * 5 * u * Math.cos(jolt * 29)
    NumberAnimation { id: joltAnim; target: ov; property: "jolt"; from: 1; to: 0; duration: 420; easing.type: Easing.OutQuad }
    SequentialAnimation {
        id: openAnim
        NumberAnimation { target: ov; property: "seal"; from: 0; to: 1; duration: ov.skipSeal ? 0 : 340; easing.type: Easing.InCubic }
        ScriptAction { script: if (!ov.skipSeal) joltAnim.restart() }
        PauseAnimation { duration: ov.skipSeal ? 0 : 150 }
        ParallelAnimation {
            NumberAnimation { target: ov; property: "p"; to: 1; duration: ov.calm ? 500 : 2700 }
            NumberAnimation { target: ov; property: "seal"; to: 2; duration: ov.skipSeal ? 0 : 560; easing.type: Easing.OutCubic }
        }
    }
    // 종료: 위젯 차례로 꺼짐 → 조준경 풀림 → 가로 한 줄로 접힘 → 점 → 장갑 판이 덮임(덜컹) → 위아래로 열림
    SequentialAnimation {
        id: closeAnim
        ScriptAction { script: if (ov.booted) ov.log("SYSTEM", "POWERING DOWN", "warn") }
        NumberAnimation { target: ov; property: "down"; from: 0; to: 0.56; duration: ov.calm ? 150 : 1060 }
        ScriptAction { script: if (!ov.calm) joltAnim.restart() }
        NumberAnimation { target: ov; property: "down"; to: 1; duration: ov.calm ? 150 : 840 }
        ScriptAction { script: { ov.visible = false; ov.p = 0; ov.down = 0; ov.seal = 2 } }
    }
    function engage() {
        closeAnim.stop()
        bootTimer.stop()
        down = 0
        skipSeal = calm || p > 0.05
        seal = skipSeal ? 2 : 0
        if (!skipSeal) {                      // 처음부터 켤 때만 로그를 새로 시작 (열리던 중 다시 켜면 이어서)
            syslog.clear()
            bootStep = 0
        }
        engagedAt = Date.now()
        visible = true
        openAnim.restart()
        if (skipSeal && !booted && p > 0.5) bootTimer.start()   // 접히던 중 다시 켬: p 가 이미 커서 onPChanged 가 안 올 수 있음
        if (skipSeal && !calm && p > 0.5) flickAnim.restart()     // 되살아나는 순간 한 번 지직
    }
    onOnChanged: {
        if (on) engage()
        else if (visible) {
            openAnim.stop(); bootTimer.stop(); seal = 2
            if (p < 0.001) visible = false   // 아직 봉인 단계였으면 보여 줄 것이 없으므로 바로 닫는다
            else if (!closeAnim.running) closeAnim.restart()
        }
    }
    Component.onCompleted: if (on) engage()

    function lin(a, b) { return Math.max(0, Math.min(1, (p - a) / (b - a))) }
    function seg(a, b) { const x = lin(a, b); return 1 - Math.pow(1 - x, 3) }
    function dlin(a, b) { return Math.max(0, Math.min(1, (down - a) / (b - a))) }
    function din(a, b) { const x = dlin(a, b); return x * x * x }
    function rnd(i) { const x = Math.sin(i * 12.9898 + 78.233) * 43758.5453; return x - Math.floor(x) }
    function c(a) { return Qt.rgba(accent.r, accent.g, accent.b, a) }
    function gd(a) { return Qt.rgba(gold.r, gold.g, gold.b, a) }
    function hc(a) { return Qt.rgba(hot.r, hot.g, hot.b, a) }
    function rc(a) { return Qt.rgba(red.r, red.g, red.b, a) }
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
    // 대기 중에는 1초에 한 번 (초 단위 표시뿐이라 차이가 없다)
    Timer { interval: ov.idle ? 1000 : 250; running: ov.visible; repeat: true; triggeredOnStart: true; onTriggered: ov.now = new Date() }

    // ---- 하나의 시계로 모든 연출을 돌린다 ----
    // 시간 t 하나만 흐르고 회전 · 스캔 · 맥박 · 시선 고리 따라가기는 모두 t 와 함께 계산한다.
    // 대기 중(조용하고, 켜짐 · 꺼짐 연출 · 잠금 · 지직거림이 끝난 상태)에는 1초에 15번만 갱신한다.
    // 듣기 · 생각 · 말하기 · 연출 중에는 매 프레임 갱신.
    property real t: 0
    readonly property bool idle: p >= 1 && seal >= 2 && down <= 0 && (st === "standby" || st === "offline" || st === "boot")
                                 && lock >= 1 && flick >= 1 && jolt <= 0
    // 시선 고리: 화면 좌표 (부드럽게 따라감) + 한곳을 오래 보면 잠금
    readonly property bool gazeOn: gaze.x !== undefined
    property real gx: -1
    property real gy: -1
    property real dwell: 0
    property real anchorX: 0
    property real anchorY: 0
    readonly property bool gazeLock: dwell > 1.2
    function advance(dt) {
        dt = Math.min(dt, 0.1)
        t += dt
        lvl += (Math.min(1, level) - lvl) * (1 - Math.exp(-dt * 22))   // 소리 크기를 부드럽게 따라감
        if (gazeOn) {
            if (gx < 0) { gx = gaze.x; gy = gaze.y }
            const k = 1 - Math.exp(-dt * 9)
            gx += (gaze.x - gx) * k
            gy += (gaze.y - gy) * k
            if (Math.abs(gaze.x - anchorX) > 70 * u || Math.abs(gaze.y - anchorY) > 70 * u) {
                anchorX = gaze.x; anchorY = gaze.y; dwell = 0
            } else dwell += dt
        }
    }
    onGazeChanged: if (!moving && gazeOn) { gx = gaze.x; gy = gaze.y }   // 움직임 줄이기: 시계가 멈춰 있으므로 바로 반영
    FrameAnimation {                       // 연출 중: 매 프레임
        running: ov.moving && !ov.idle
        onTriggered: ov.advance(frameTime)
    }
    Timer {                                // 대기 중: 1초에 15번. 그 사이에는 애니메이션 구동기도 쉬어 화면을 아예 다시 그리지 않는다
        interval: 66; repeat: true
        running: ov.moving && ov.idle
        property real last: 0
        onRunningChanged: last = Date.now()
        onTriggered: { const n = Date.now(); ov.advance((n - last) / 1000); last = n }
    }
    readonly property int tick: Math.floor(t / 0.07)          // 깜빡이는 숫자 · 암호 글자용
    readonly property real spin: t * 360 / 26 % 360
    readonly property real sweep: t * 360 / 3.2 % 360
    readonly property real heading: t * 4 % 360
    readonly property real scan: t / 6 % 1
    readonly property real pulse: 0.5 - 0.5 * Math.cos(t * Math.PI / 1.1)
    readonly property real roll: -2.2 * Math.cos(t * Math.PI / 4.2)   // 헬멧이 살짝 기우는 느낌
    readonly property real pitch: 7 * Math.sin(t * 0.35)               // 수평 사다리가 아주 천천히 오르내림
    property real lvl: 0
    onLevelChanged: if (!moving) lvl = Math.min(1, level)   // 움직임 줄이기: 시계가 멈춰 있으므로 바로 반영

    // 홀로그램이 가끔 지직거림
    property real flick: 1
    Timer {
        interval: 5000; running: ov.moving && ov.p >= 1 && ov.down <= 0; repeat: true
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
            while (acts.count > 3) acts.remove(acts.count - 1)
        }
    }

    // ---- 시스템 로그: 착용 직후 실제 점검 결과를 한 줄씩 찍고, 그 뒤에는 상태 · 추적 · 작업 결과를 이어서 기록 ----
    // lv: ok | warn | err | info | lock
    ListModel { id: syslog }
    readonly property int logMax: 9
    function log(tag, val, lv) {
        const d = new Date()
        syslog.append({ tag: String(tag), val: String(val), lv: lv,
                        ts: pad(d.getHours()) + ":" + pad(d.getMinutes()) + ":" + pad(d.getSeconds()) })
        while (syslog.count > logMax) syslog.remove(0)
    }
    property int bootStep: 0
    readonly property int bootCount: 10          // bootChecks() 줄 수
    readonly property bool booted: bootStep >= bootCount
    function bootChecks() {
        const w = weather, s = stats
        return [
            ["VISOR SEAL", "OK", "ok"],
            ["J.A.R.V.I.S CORE", "ONLINE", "ok"],
            ["AUDIO INPUT", st === "offline" ? "OFFLINE" : "OK", st === "offline" ? "err" : "ok"],
            ["VOICE CHANNEL", jarvis.wakeEnabled ? "WAKE WORD" : "HOTKEY " + jarvis.hotkeyText, "ok"],
            ["AI LINK", jarvis.hasApiKey ? "ONLINE" : "LOCAL ONLY", jarvis.hasApiKey ? "ok" : "warn"],
            ["EYE TRACKING", gaze.src === "eye" ? "OPTICAL" : gazeOn ? "CURSOR" : "OFF", gaze.src === "eye" ? "ok" : "info"],
            ["TELEMETRY", "CPU " + Math.round(s.cpu || 0) + "% · RAM " + Math.round(s.ram || 0) + "%",
             (s.cpu || 0) > 90 || (s.ram || 0) > 90 ? "warn" : "ok"],
            ["POWER", s.bat === undefined || s.bat < 0 ? "AC" : s.bat + "%" + (s.plugged ? " CHG" : ""),
             s.bat >= 0 && s.bat < 15 && !s.plugged ? "warn" : "ok"],
            ["ATMOSPHERICS", w.temp !== undefined ? "LINKED" : w.error ? "OFFLINE" : "SYNCING",
             w.temp !== undefined ? "ok" : w.error ? "warn" : "info"],
            ["HUD CALIBRATION", "COMPLETE", "ok"],
        ]
    }
    property int bootWarn: 0
    // SYSLOG 위젯이 날아와 자리 잡을 즈음부터 한 줄씩 찍는다
    onPChanged: if (on && p > 0.5 && !booted && !bootTimer.running && openAnim.running) bootTimer.start()
    Timer {
        id: bootTimer
        interval: ov.calm ? 40 : 230; repeat: true
        onTriggered: {
            const list = ov.bootChecks()
            if (ov.bootStep === 0) ov.bootWarn = 0
            if (ov.bootStep < list.length) {
                const r = list[ov.bootStep]
                if (r[2] === "warn" || r[2] === "err") ov.bootWarn++
                ov.log(r[0], r[1], r[2])
                ov.bootStep++
                if (ov.bootStep < list.length) return
            }
            ov.log(ov.bootWarn ? "SYSTEMS ONLINE" : "ALL SYSTEMS ONLINE",
                   ov.bootWarn ? ov.bootWarn + " CHECK" : "READY", ov.bootWarn ? "warn" : "ok")
            stop()
        }
    }
    onStChanged: if (on && booted && st !== "boot" && st !== "listening") log("STATE", stateLabels[st] || st.toUpperCase(),
                                                        st === "offline" ? "err" : "info")
    Connections {
        target: jarvis
        function onActionEvent(id, label, status, detail) {
            if (ov.on && ov.booted && status !== "run")
                ov.log(label, status === "error" ? "FAIL" : "DONE", status === "error" ? "err" : "ok")
        }
    }

    // 추적 박스: 대상이 바뀔 때마다 넓게 벌어졌다가 조여 들며 '잠금'
    property string lastTarget: ""
    property string lastApp: ""
    onTargetChanged: {
        const id = target.id === undefined ? "" : String(target.id)
        if (id !== "" && id !== lastTarget) {
            lockAnim.restart()
            if (on && booted) {
                if (target.kind === "point") log("TARGET", "LOCK · " + (target.title || "POINT"), "lock")
                else if ((target.app || "") !== lastApp) log("TRACK", target.app || "WINDOW", "info")
            }
            lastApp = target.kind === "point" ? "" : (target.app || "")
        }
        lastTarget = id
    }
    property real lock: 1
    SequentialAnimation {
        id: lockAnim
        NumberAnimation { target: ov; property: "lock"; to: 0; duration: 10 }
        PauseAnimation { duration: 380 }
        NumberAnimation { target: ov; property: "lock"; to: 1; duration: 480; easing.type: Easing.OutBack }
    }

    // ---------------------------------------------------------------- 헬멧 안쪽 장갑의 윤곽 (안쪽 가장자리, 화면 비율로)
    function fp(x, y) { return Qt.point(x * width, y * height) }
    readonly property var browEdge: [fp(0, 0.205), fp(0.05, 0.125), fp(0.17, 0.072), fp(0.33, 0.046), fp(0.44, 0.04), fp(0.475, 0.052),
                                     fp(0.5, 0.07), fp(0.525, 0.052), fp(0.56, 0.04), fp(0.67, 0.046), fp(0.83, 0.072), fp(0.95, 0.125), fp(1, 0.205)]
    readonly property var chinEdge: [fp(0, 0.83), fp(0.035, 0.895), fp(0.16, 0.94), fp(0.36, 0.958), fp(0.46, 0.962), fp(0.5, 0.952),
                                     fp(0.54, 0.962), fp(0.64, 0.958), fp(0.84, 0.94), fp(0.965, 0.895), fp(1, 0.83)]
    readonly property var cheekL: [fp(0, 0.205), fp(0.014, 0.3), fp(0.02, 0.5), fp(0.014, 0.7), fp(0, 0.83)]
    readonly property var cheekR: [fp(1, 0.205), fp(0.986, 0.3), fp(0.98, 0.5), fp(0.986, 0.7), fp(1, 0.83)]

    // ---------------------------------------------------------------- 배치: 헬멧 곡면을 따라 휘는 양쪽 열
    readonly property real colW: 300 * u
    readonly property real colTop: height * 0.165
    readonly property real gapY: 22 * u
    // 세로 가운데에서 멀수록 안쪽으로 조금 들어오고(곡면), 열 모양 '(' ')' 을 따라 살짝 기운다
    function colX(side, y, h) {
        const k = (y + h / 2 - cy) / (height * 0.5)
        const m = (58 + 26 * k * k) * u
        return side < 0 ? m : width - m - colW
    }
    function colRot(side, y, h) { return side * 5 * (y + h / 2 - cy) / (height * 0.5) }

    // ---------------------------------------------------------------- 공용 조각
    // 가운데에서 제자리로 날아오며 깜빡이며 켜지는 묶음. tilt: 헬멧 곡면처럼 바깥쪽이 다가오게 기울임
    // 끌 때는 d 순서대로(바깥 위젯이 먼저) 지직거리며 꺼진다.
    component Fly: Item {
        id: fly
        property real d: 0.3
        property real tilt: 0
        property real zrot: 0
        readonly property real e: ov.seg(d, d + 0.32)
        readonly property real off: ov.down <= 0 ? 0 : ov.dlin(0.02 + (d - 0.3) * 0.7, 0.16 + (d - 0.3) * 0.7)
        visible: e > 0 && off < 1
        opacity: (e >= 1 ? 1 : e * (0.35 + 0.65 * ov.rnd(Math.floor(ov.p * 70) + d * 977)))
                 * (off <= 0 ? 1 : (1 - off) * (0.3 + 0.7 * ov.rnd(Math.floor(ov.down * 90) + d * 331)))
        transform: [
            Rotation { origin.x: fly.tilt > 0 ? fly.width : 0; origin.y: fly.height / 2; axis { x: 0; y: 1; z: 0 }
                       angle: fly.tilt * (0.4 + 0.6 * fly.e) },
            Rotation { origin.x: fly.width / 2; origin.y: fly.height / 2; angle: fly.zrot * fly.e },
            Scale { origin.x: fly.width / 2; origin.y: fly.height / 2
                    xScale: (0.5 + 0.5 * fly.e) * (1 + 0.15 * fly.off); yScale: (0.5 + 0.5 * fly.e) * (1 - 0.6 * fly.off) },
            Translate { x: (ov.cx - (fly.x + fly.width / 2)) * (1 - fly.e); y: (ov.cy - (fly.y + fly.height / 2)) * (1 - fly.e) }
        ]
    }
    // 모든 글자: 어두운 테두리 (뒤 화면이 밝거나 복잡해도 읽히게) + 기본은 굵게
    component HText: Text {
        property bool plate: false            // true: 글자 뒤에 어두운 이름표 판 (흰 화면 위에서도 읽히게)
        style: Text.Outline; styleColor: ov.shade
        font.family: "Bahnschrift"; font.weight: Font.DemiBold
        Rectangle {
            visible: parent.plate && parent.text !== ""
            z: -1
            x: -4 * ov.u; y: -1 * ov.u
            width: parent.implicitWidth + 8 * ov.u; height: parent.implicitHeight + 2 * ov.u
            color: Qt.rgba(0.07, 0.03, 0.0, 0.74)
        }
    }
    component Decode: HText {
        property string full: ""
        property real t: 1
        property int seed: 0
        text: ov.decode(full, t, seed)
        color: ov.gd(0.95)
        font.pixelSize: 12 * ov.u; font.letterSpacing: 2 * ov.u
    }
    component Label: HText {
        color: ov.gd(0.9)
        font.pixelSize: 10 * ov.u; font.letterSpacing: 2 * ov.u; font.weight: Font.Bold
    }
    // 홀로그램 위젯: 깎은 모서리 판 + 금색 머리 탭 + 바깥쪽 굵은 눈금 막대. 내용은 inner (안쪽 여백 12u) 에 들어간다.
    component Wid: Fly {
        id: w
        property string title: ""
        property string tag: ""
        property int side: -1                     // -1 왼쪽 열, 1 오른쪽 열 (막대는 바깥쪽)
        readonly property real hh: 24 * ov.u      // 머리 탭 높이
        readonly property real cut: 16 * ov.u
        readonly property real iw: width - 24 * ov.u   // 내용 폭
        default property alias content: inner.data
        width: ov.colW
        x: ov.colX(side, y, height)
        tilt: side < 0 ? 14 : -14
        zrot: ov.colRot(side, y, height)
        readonly property var outline: side < 0
            ? [Qt.point(0, hh), Qt.point(width - cut, hh), Qt.point(width, hh + cut), Qt.point(width, height),
               Qt.point(cut, height), Qt.point(0, height - cut), Qt.point(0, hh)]
            : [Qt.point(0, hh + cut), Qt.point(cut, hh), Qt.point(width, hh), Qt.point(width, height - cut),
               Qt.point(width - cut, height), Qt.point(0, height), Qt.point(0, hh + cut)]
        Shape {
            anchors.fill: parent
            ShapePath {   // 판: 어두운 유리 + 금색 테
                strokeColor: ov.gd(0.6); strokeWidth: 2 * ov.u; joinStyle: ShapePath.MiterJoin
                fillGradient: LinearGradient {
                    x1: 0; y1: w.hh; x2: 0; y2: w.height
                    GradientStop { position: 0.0; color: Qt.rgba(0.20, 0.10, 0.0, 0.62) }
                    GradientStop { position: 0.25; color: Qt.rgba(0.07, 0.03, 0.0, 0.66) }
                    GradientStop { position: 1.0; color: Qt.rgba(0.05, 0.02, 0.0, 0.72) }
                }
                PathPolyline { path: w.outline }
            }
            ShapePath {   // 머리 탭 (금색으로 채움)
                strokeColor: "transparent"; fillColor: ov.accent
                PathPolyline { path: w.side < 0
                    ? [Qt.point(0, 0), Qt.point(titleT.implicitWidth + 30 * ov.u, 0), Qt.point(titleT.implicitWidth + 30 * ov.u + w.hh, w.hh),
                       Qt.point(0, w.hh), Qt.point(0, 0)]
                    : [Qt.point(w.width, 0), Qt.point(w.width - titleT.implicitWidth - 30 * ov.u, 0),
                       Qt.point(w.width - titleT.implicitWidth - 30 * ov.u - w.hh, w.hh), Qt.point(w.width, w.hh), Qt.point(w.width, 0)] }
            }
            ShapePath {   // 굵은 꺾쇠: 바깥쪽 아래 · 안쪽 위
                strokeColor: ov.hot; strokeWidth: 4 * ov.u; fillColor: "transparent"; capStyle: ShapePath.FlatCap
                joinStyle: ShapePath.MiterJoin
                PathMove { x: w.side < 0 ? 0 : w.width; y: w.height - w.cut - 26 * ov.u }
                PathLine { x: w.side < 0 ? 0 : w.width; y: w.height - w.cut }
                PathLine { x: w.side < 0 ? w.cut : w.width - w.cut; y: w.height }
                PathLine { x: w.side < 0 ? w.cut + 30 * ov.u : w.width - w.cut - 30 * ov.u; y: w.height }
                PathMove { x: w.side < 0 ? w.width - w.cut - 30 * ov.u : w.cut + 30 * ov.u; y: w.hh }
                PathLine { x: w.side < 0 ? w.width - w.cut : w.cut; y: w.hh }
                PathLine { x: w.side < 0 ? w.width : 0; y: w.hh + w.cut }
                PathLine { x: w.side < 0 ? w.width : 0; y: w.hh + w.cut + 22 * ov.u }
            }
        }
        HText {
            id: titleT
            x: w.side < 0 ? 12 * ov.u : w.width - 12 * ov.u - width
            y: (w.hh - height) / 2
            text: w.title
            color: ov.ink; style: Text.Normal
            font.pixelSize: 12 * ov.u; font.letterSpacing: 3 * ov.u; font.weight: Font.Bold
        }
        HText {
            x: w.side < 0 ? w.width - width - 4 * ov.u : 4 * ov.u
            y: (w.hh - height) / 2
            text: w.tag; color: ov.gd(0.95)
            font.pixelSize: 10 * ov.u; font.letterSpacing: 1.5 * ov.u; font.weight: Font.Bold
        }
        // 바깥쪽 눈금 막대: 굵은 칸 여섯 개
        Column {
            x: w.side < 0 ? -14 * ov.u : w.width + 8 * ov.u
            y: w.hh + 4 * ov.u
            spacing: 4 * ov.u
            Repeater {
                model: 6
                Rectangle {
                    width: 6 * ov.u; height: (w.height - w.hh - 8 * ov.u - 20 * ov.u) / 6
                    color: index === 0 ? ov.hot : ov.c(index % 2 ? 0.85 : 0.4)
                }
            }
        }
        Item {
            id: inner
            x: 12 * ov.u; y: w.hh + 8 * ov.u
            width: w.iw; height: w.height - y - 8 * ov.u
        }
    }
    // 원형 게이지 (CPU / RAM): 굵은 칸 막대 고리
    component Gauge: Item {
        id: g
        property real v: 0
        property string label: ""
        property real e: 1
        property real shown: 0
        Behavior on shown { NumberAnimation { duration: 600; easing.type: Easing.OutCubic } }
        onVChanged: shown = v
        Component.onCompleted: shown = v
        width: 76 * ov.u; height: width + 16 * ov.u
        readonly property real r: width / 2 - 6 * ov.u
        Shape {
            width: g.width; height: g.width
            preferredRendererType: Shape.CurveRenderer
            ShapePath {
                strokeColor: ov.c(0.22); strokeWidth: 8 * ov.u; fillColor: "transparent"; capStyle: ShapePath.FlatCap
                strokeStyle: ShapePath.DashLine; dashPattern: [1.1, 0.35]
                PathAngleArc { centerX: g.width / 2; centerY: g.width / 2; radiusX: g.r; radiusY: g.r; startAngle: 135; sweepAngle: 270 * g.e }
            }
            ShapePath {
                strokeColor: g.v > 85 ? ov.red : ov.accent; strokeWidth: 8 * ov.u; fillColor: "transparent"; capStyle: ShapePath.FlatCap
                strokeStyle: ShapePath.DashLine; dashPattern: [1.1, 0.35]
                PathAngleArc { centerX: g.width / 2; centerY: g.width / 2; radiusX: g.r; radiusY: g.r; startAngle: 135
                               sweepAngle: 270 * Math.max(0.005, g.shown / 100) * g.e }
            }
            ShapePath {
                strokeColor: ov.hc(0.7); strokeWidth: 2 * ov.u; fillColor: "transparent"
                PathAngleArc { centerX: g.width / 2; centerY: g.width / 2; radiusX: g.r - 10 * ov.u; radiusY: g.r - 10 * ov.u; startAngle: 135; sweepAngle: 270 * g.e }
            }
        }
        HText {
            x: 0; width: g.width; y: g.width / 2 - height / 2
            horizontalAlignment: Text.AlignHCenter
            text: Math.round(g.shown * g.e) + "%"
            color: ov.hot; font.pixelSize: 17 * ov.u; font.weight: Font.Bold
        }
        Label { anchors.horizontalCenter: parent.horizontalCenter; y: g.width - 4 * ov.u; text: g.label; font.pixelSize: 9 * ov.u }
    }

    // =====================================================================
    // 바탕: 장갑 안쪽의 따뜻한 어둠 — 가운데는 맑고, 위젯이 놓이는 양쪽은 진하다 (흰 창 위에서도 위젯이 읽히게)
    Item {
        id: bg
        anchors.fill: parent
        opacity: ov.seg(0.1, 0.45) * ov.flick * (ov.calm ? 1 - ov.down : 1 - ov.dlin(0.3, 0.55))
        transform: Translate { x: ov.joltX; y: ov.joltY }
        Rectangle {   // 바이저 색: 아주 옅은 호박빛 (뒤 화면은 그대로 보임)
            anchors.fill: parent
            color: Qt.rgba(0.06, 0.03, 0.0, 0.12)
        }
        // 가장자리로 갈수록 어두워지는 타원
        Item {
            width: ov.width; height: ov.width
            y: ov.cy - height / 2
            transform: Scale { origin.x: ov.width / 2; origin.y: ov.width / 2; yScale: ov.height / ov.width * 1.15 }
            Shape {
                anchors.fill: parent
                ShapePath {
                    strokeColor: "transparent"
                    fillGradient: RadialGradient {
                        centerX: ov.width / 2; centerY: ov.width / 2; centerRadius: ov.width * 0.6
                        focalX: ov.width / 2; focalY: ov.width / 2; focalRadius: 0
                        GradientStop { position: 0.0; color: "transparent" }
                        GradientStop { position: 0.58; color: "transparent" }
                        GradientStop { position: 0.78; color: Qt.rgba(0.04, 0.015, 0.0, 0.55) }
                        GradientStop { position: 1.0; color: Qt.rgba(0.02, 0.008, 0.0, 0.92) }
                    }
                    PathPolyline { path: [Qt.point(0, 0), Qt.point(ov.width, 0), Qt.point(ov.width, ov.width), Qt.point(0, ov.width), Qt.point(0, 0)] }
                }
            }
        }
        // 양쪽 열 뒤: 위젯 폭만큼은 진하게, 그 안쪽으로 부드럽게 옅어짐
        Repeater {
            model: 2
            Rectangle {
                readonly property real reach: ov.colX(-1, 0, 0) + ov.colW + 110 * ov.u
                width: reach; height: parent.height
                x: index === 0 ? 0 : ov.width - reach
                gradient: Gradient { orientation: Gradient.Horizontal
                    GradientStop { position: index === 0 ? 0.0 : 1.0; color: Qt.rgba(0.035, 0.014, 0.0, 0.88) }
                    GradientStop { position: index === 0 ? 0.62 : 0.38; color: Qt.rgba(0.035, 0.014, 0.0, 0.8) }
                    GradientStop { position: index === 0 ? 1.0 : 0.0; color: Qt.rgba(0.035, 0.014, 0.0, 0) } }
            }
        }
        // 위 방위 테이프 뒤: 가장자리가 부드러운 타원 그늘
        Repeater {
            model: [[ov.cx, ov.height * 0.11, 340 * ov.u, 64 * ov.u, 0.4]]
            Item {
                readonly property real rx: modelData[2]
                x: modelData[0] - rx; y: modelData[1] - rx
                width: rx * 2; height: rx * 2
                transform: Scale { origin.x: modelData[2]; origin.y: modelData[2]; yScale: modelData[3] / modelData[2] }
                Shape {
                    anchors.fill: parent
                    ShapePath {
                        strokeColor: "transparent"
                        fillGradient: RadialGradient {
                            centerX: modelData[2]; centerY: modelData[2]; centerRadius: modelData[2]
                            focalX: modelData[2]; focalY: modelData[2]; focalRadius: 0
                            GradientStop { position: 0.0; color: Qt.rgba(0.04, 0.015, 0, modelData[4]) }
                            GradientStop { position: 0.6; color: Qt.rgba(0.04, 0.015, 0, modelData[4] * 0.7) }
                            GradientStop { position: 1.0; color: Qt.rgba(0.04, 0.015, 0, 0) }
                        }
                        PathAngleArc { centerX: modelData[2]; centerY: modelData[2]; radiusX: modelData[2]; radiusY: modelData[2]; startAngle: 0; sweepAngle: 360 }
                    }
                }
            }
        }
        Canvas {   // 홀로그램 주사선 (한 번만 그림)
            anchors.fill: parent
            opacity: 0.3
            onWidthChanged: requestPaint()
            onHeightChanged: requestPaint()
            onPaint: {
                const g = getContext("2d")
                g.reset()
                g.fillStyle = "rgba(255, 190, 110, 0.07)"
                for (let y = 0; y < height; y += 3) g.fillRect(0, y, width, 1)
            }
        }
        Rectangle {   // 위에서 아래로 훑는 빛띠
            visible: ov.p >= 1
            width: parent.width; height: 120 * ov.u
            y: -height + (parent.height + height) * ov.scan
            gradient: Gradient {
                GradientStop { position: 0.0; color: ov.gd(0) }
                GradientStop { position: 0.9; color: ov.gd(0.03) }
                GradientStop { position: 1.0; color: ov.gd(0.1) }
            }
        }
    }

    // =====================================================================
    // 헬멧 안쪽 장갑 — 레드 이마판 · 골드 뺨판 · 레드 턱판(가운데 골드), 골드 테두리에 HUD 빛이 비친다.
    // 눈에서 너무 가까워 초점이 맞지 않는 느낌으로 살짝 흐리게. 움직이지 않으므로 한 번 그린 그림을 계속 쓴다.
    Item {
        id: armor
        anchors.fill: parent
        opacity: ov.calm ? (ov.down > 0 ? 1 - ov.down : ov.seg(0, 0.3))
               : ov.down > 0 ? (ov.down < 0.56 ? 1 : 0)
               : ov.skipSeal ? ov.seg(0, 0.3) : (ov.seal >= 1 ? 1 : 0)
        visible: opacity > 0
        transform: Translate { x: ov.joltX; y: ov.joltY }
        layer.enabled: ov.visible
        layer.effect: MultiEffect { blurEnabled: true; blur: 0.18; blurMax: 12; autoPaddingEnabled: false }
        Shape {
            anchors.fill: parent
            // 이마판 (레드)
            ShapePath {
                strokeColor: "transparent"
                fillGradient: LinearGradient {
                    x1: 0; y1: 0; x2: 0; y2: ov.height * 0.2
                    GradientStop { position: 0.0; color: "#190303" }
                    GradientStop { position: 0.45; color: "#4a0a0a" }
                    GradientStop { position: 1.0; color: "#8a1616" }
                }
                PathPolyline { path: [Qt.point(-4, -4), Qt.point(ov.width + 4, -4)].concat(ov.browEdge.slice().reverse()).concat([Qt.point(-4, ov.height * 0.205), Qt.point(-4, -4)]) }
            }
            // 턱판 (레드)
            ShapePath {
                strokeColor: "transparent"
                fillGradient: LinearGradient {
                    x1: 0; y1: ov.height * 0.83; x2: 0; y2: ov.height
                    GradientStop { position: 0.0; color: "#7a1313" }
                    GradientStop { position: 0.6; color: "#3d0808" }
                    GradientStop { position: 1.0; color: "#150202" }
                }
                PathPolyline { path: ov.chinEdge.concat([Qt.point(ov.width + 4, ov.height * 0.83), Qt.point(ov.width + 4, ov.height + 4),
                                                         Qt.point(-4, ov.height + 4), Qt.point(-4, ov.height * 0.83), ov.chinEdge[0]]) }
            }
            // 뺨판 (골드) — 왼쪽 · 오른쪽
            ShapePath {
                strokeColor: "transparent"
                fillGradient: LinearGradient {
                    x1: 0; y1: 0; x2: ov.width * 0.022; y2: 0
                    GradientStop { position: 0.0; color: "#2a1a04" }
                    GradientStop { position: 1.0; color: "#7a5816" }
                }
                PathPolyline { path: [Qt.point(-4, ov.height * 0.205)].concat(ov.cheekL).concat([Qt.point(-4, ov.height * 0.83), Qt.point(-4, ov.height * 0.205)]) }
            }
            ShapePath {
                strokeColor: "transparent"
                fillGradient: LinearGradient {
                    x1: ov.width; y1: 0; x2: ov.width * 0.978; y2: 0
                    GradientStop { position: 0.0; color: "#2a1a04" }
                    GradientStop { position: 1.0; color: "#7a5816" }
                }
                PathPolyline { path: [Qt.point(ov.width + 4, ov.height * 0.205)].concat(ov.cheekR).concat([Qt.point(ov.width + 4, ov.height * 0.83), Qt.point(ov.width + 4, ov.height * 0.205)]) }
            }
            // 턱 가운데 골드 판
            ShapePath {
                strokeColor: "#2a1a04"; strokeWidth: 2 * ov.u
                fillGradient: LinearGradient {
                    x1: 0; y1: ov.height * 0.955; x2: 0; y2: ov.height
                    GradientStop { position: 0.0; color: "#9a7222" }
                    GradientStop { position: 1.0; color: "#3a2806" }
                }
                PathPolyline { path: [ov.fp(0.4, 1.01), ov.fp(0.44, 0.972), ov.fp(0.5, 0.964), ov.fp(0.56, 0.972), ov.fp(0.6, 1.01), ov.fp(0.4, 1.01)] }
            }
            // 이마 가운데 능선 + 판 이음새 (어두운 홈 + 밝은 모서리)
            ShapePath {
                strokeColor: "#120202"; strokeWidth: 4 * ov.u; fillColor: "transparent"
                PathMove { x: ov.width * 0.5; y: 0 }
                PathLine { x: ov.width * 0.5; y: ov.height * 0.07 }
                PathMove { x: ov.width * 0.12; y: 0 }
                PathLine { x: ov.width * 0.17; y: ov.height * 0.072 }
                PathMove { x: ov.width * 0.88; y: 0 }
                PathLine { x: ov.width * 0.83; y: ov.height * 0.072 }
                PathMove { x: ov.width * 0.31; y: 0 }
                PathLine { x: ov.width * 0.33; y: ov.height * 0.046 }
                PathMove { x: ov.width * 0.69; y: 0 }
                PathLine { x: ov.width * 0.67; y: ov.height * 0.046 }
                PathMove { x: ov.width * 0.12; y: ov.height }
                PathLine { x: ov.width * 0.16; y: ov.height * 0.94 }
                PathMove { x: ov.width * 0.88; y: ov.height }
                PathLine { x: ov.width * 0.84; y: ov.height * 0.94 }
                PathMove { x: 0; y: ov.height * 0.42 }
                PathLine { x: ov.width * 0.019; y: ov.height * 0.42 }
                PathMove { x: ov.width; y: ov.height * 0.42 }
                PathLine { x: ov.width * 0.981; y: ov.height * 0.42 }
                PathMove { x: 0; y: ov.height * 0.62 }
                PathLine { x: ov.width * 0.018; y: ov.height * 0.62 }
                PathMove { x: ov.width; y: ov.height * 0.62 }
                PathLine { x: ov.width * 0.982; y: ov.height * 0.62 }
            }
            ShapePath {
                strokeColor: Qt.rgba(1, 0.55, 0.4, 0.28); strokeWidth: 1.5 * ov.u; fillColor: "transparent"
                PathMove { x: ov.width * 0.5 + 3 * ov.u; y: 0 }
                PathLine { x: ov.width * 0.5 + 3 * ov.u; y: ov.height * 0.066 }
                PathMove { x: ov.width * 0.12 + 3 * ov.u; y: 0 }
                PathLine { x: ov.width * 0.17 + 3 * ov.u; y: ov.height * 0.07 }
                PathMove { x: ov.width * 0.88 + 3 * ov.u; y: 0 }
                PathLine { x: ov.width * 0.83 + 3 * ov.u; y: ov.height * 0.07 }
                PathMove { x: ov.width * 0.31 + 3 * ov.u; y: 0 }
                PathLine { x: ov.width * 0.33 + 3 * ov.u; y: ov.height * 0.044 }
                PathMove { x: ov.width * 0.69 + 3 * ov.u; y: 0 }
                PathLine { x: ov.width * 0.67 + 3 * ov.u; y: ov.height * 0.044 }
            }
            // 이마 양쪽 통풍 홈
            ShapePath {
                strokeColor: "#0c0101"; strokeWidth: 3.5 * ov.u; fillColor: "transparent"; capStyle: ShapePath.RoundCap
                PathMove { x: ov.width * 0.205; y: ov.height * 0.018 }
                PathLine { x: ov.width * 0.225; y: ov.height * 0.046 }
                PathMove { x: ov.width * 0.222; y: ov.height * 0.016 }
                PathLine { x: ov.width * 0.242; y: ov.height * 0.043 }
                PathMove { x: ov.width * 0.239; y: ov.height * 0.014 }
                PathLine { x: ov.width * 0.259; y: ov.height * 0.04 }
                PathMove { x: ov.width * 0.795; y: ov.height * 0.018 }
                PathLine { x: ov.width * 0.775; y: ov.height * 0.046 }
                PathMove { x: ov.width * 0.778; y: ov.height * 0.016 }
                PathLine { x: ov.width * 0.758; y: ov.height * 0.043 }
                PathMove { x: ov.width * 0.761; y: ov.height * 0.014 }
                PathLine { x: ov.width * 0.741; y: ov.height * 0.04 }
            }
            // 안쪽 가장자리 골드 테: 어두운 바깥 → 골드 → 밝은 모서리 (세 겹으로 깎은 느낌)
            ShapePath {
                strokeColor: "#4a3008"; strokeWidth: 11 * ov.u; fillColor: "transparent"; joinStyle: ShapePath.RoundJoin
                PathPolyline { path: ov.browEdge }
                PathPolyline { path: ov.chinEdge }
                PathPolyline { path: ov.cheekL }
                PathPolyline { path: ov.cheekR }
            }
            ShapePath {
                strokeColor: "#c9962f"; strokeWidth: 6 * ov.u; fillColor: "transparent"; joinStyle: ShapePath.RoundJoin
                PathPolyline { path: ov.browEdge }
                PathPolyline { path: ov.chinEdge }
                PathPolyline { path: ov.cheekL }
                PathPolyline { path: ov.cheekR }
            }
            ShapePath {
                strokeColor: "#ffe3a0"; strokeWidth: 1.8 * ov.u; fillColor: "transparent"; joinStyle: ShapePath.RoundJoin
                PathPolyline { path: ov.browEdge }
                PathPolyline { path: ov.chinEdge }
                PathPolyline { path: ov.cheekL }
                PathPolyline { path: ov.cheekR }
            }
            // HUD 빛이 테두리에 비친 번짐
            ShapePath {
                strokeColor: Qt.rgba(1, 0.6, 0.15, 0.16); strokeWidth: 30 * ov.u; fillColor: "transparent"; joinStyle: ShapePath.RoundJoin
                PathPolyline { path: ov.browEdge }
                PathPolyline { path: ov.chinEdge }
            }
        }
        // 이마 가운데 표시등 (주황)
        Row {
            x: ov.cx - width / 2; y: ov.height * 0.018
            spacing: 6 * ov.u
            Repeater {
                model: 5
                Rectangle {
                    width: (index === 2 ? 18 : 8) * ov.u; height: 4 * ov.u; radius: 1
                    color: index === 2 ? "#ffd27a" : "#ff8a2a"
                    opacity: index === 2 ? 1 : 0.75
                }
            }
        }
    }

    // =====================================================================
    // HUD 본체 — 모든 선 · 글자 둘레에 어두운 테(헤일로)를 둘러 흰 화면 위에서도 또렷하게.
    // 끌 때는 가로 한 줄로 접혔다가 점이 된다.
    Item {
        id: hud
        anchors.fill: parent
        opacity: (ov.p < 1 && ov.p > 0.12 ? (0.6 + 0.4 * ov.rnd(Math.floor(ov.p * 90))) : 1) * ov.flick
                 * (ov.calm ? 1 - ov.down : 1 - ov.dlin(0.6, 0.66))
        visible: opacity > 0.001
        transform: [
            Scale {
                origin.x: ov.cx; origin.y: ov.cy
                yScale: ov.calm ? 1 : 1 - 0.996 * ov.din(0.34, 0.48)
                xScale: ov.calm ? 1 : 1 - 0.98 * ov.din(0.48, 0.6)
            },
            Translate { x: ov.joltX; y: ov.joltY }
        ]
        layer.enabled: ov.visible
        layer.effect: MultiEffect {
            shadowEnabled: true
            shadowColor: Qt.rgba(0.04, 0.015, 0.0, 1)
            shadowBlur: 0.4                  // 선마다 어두운 테를 깔고, 그 둘레를 한 번 더 부드럽게 어둡게
            blurMax: 12
            shadowOpacity: 1.0
            shadowScale: 1.0
            shadowHorizontalOffset: 0; shadowVerticalOffset: 0
            autoPaddingEnabled: false
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
                border.color: index === 0 ? ov.hot : ov.gold
                border.width: (index === 0 ? 7 : 3) * (1 - t) + 1.5
                opacity: (1 - t) * (index === 0 ? 0.95 : 0.6)
            }
        }
        // ---- 사방으로 뻗는 빛줄기 ----
        Repeater {
            model: 48
            Item {
                readonly property real jit: ov.rnd(index)
                readonly property real t: ov.lin(0.03 + jit * 0.14, 0.33 + jit * 0.14)
                visible: t > 0 && t < 1
                x: ov.cx; y: ov.cy
                rotation: index * (360 / 48) + jit * 5
                Rectangle {
                    readonly property real len: (70 + 180 * parent.jit) * ov.u
                    x: -width / 2
                    y: -(50 * ov.u + (ov.diag / 2) * parent.t) - len
                    width: 2 + 2.5 * parent.jit; height: len
                    opacity: Math.sin(parent.t * Math.PI) * 0.9
                    gradient: Gradient {
                        GradientStop { position: 0.0; color: "#fff8e8" }
                        GradientStop { position: 1.0; color: ov.gd(0) }
                    }
                }
            }
        }

        // ---- 시야 보정 격자 ----
        Item {
            id: calib
            readonly property real e: ov.lin(0.1, 0.62)
            visible: e > 0 && e < 1
            anchors.fill: parent
            opacity: Math.sin(e * Math.PI) * 0.85
            Repeater {   // 가로줄: 가운데에서 멀수록 바깥쪽으로 불룩
                model: 11
                Shape {
                    readonly property real k: (index - 5) / 5
                    readonly property real show: Math.max(0, Math.min(1, calib.e * 3.2 - Math.abs(k) * 1.4))
                    readonly property real yy: ov.cy + k * ov.height * 0.4
                    visible: show > 0
                    anchors.fill: parent
                    ShapePath {
                        strokeColor: ov.gd(index === 5 ? 0.9 : 0.5); strokeWidth: (index === 5 ? 3 : 2) * ov.u; fillColor: "transparent"
                        PathMove { x: ov.cx - ov.width * 0.48 * show; y: yy }
                        PathQuad { x: ov.cx + ov.width * 0.48 * show; y: yy; controlX: ov.cx; controlY: yy + k * ov.height * 0.1 * show }
                    }
                }
            }
            Repeater {   // 세로줄
                model: 15
                Shape {
                    readonly property real k: (index - 7) / 7
                    readonly property real show: Math.max(0, Math.min(1, calib.e * 3.2 - Math.abs(k) * 1.4))
                    readonly property real xx: ov.cx + k * ov.width * 0.45
                    visible: show > 0
                    anchors.fill: parent
                    ShapePath {
                        strokeColor: ov.gd(index === 7 ? 0.9 : 0.5); strokeWidth: (index === 7 ? 3 : 2) * ov.u; fillColor: "transparent"
                        PathMove { x: xx; y: ov.cy - ov.height * 0.42 * show }
                        PathQuad { x: xx; y: ov.cy + ov.height * 0.42 * show; controlX: xx + k * ov.width * 0.07 * show; controlY: ov.cy }
                    }
                }
            }
            HText { plate: true;
                anchors.horizontalCenter: parent.horizontalCenter
                y: ov.cy - 186 * ov.u
                text: ov.decode("CALIBRATING VIRTUAL HORIZON  ·  " + Math.round(calib.e * 100) + "%", Math.min(1, calib.e * 3), 21)
                color: ov.hot
                font.pixelSize: 14 * ov.u; font.letterSpacing: 4 * ov.u; font.weight: Font.Bold
            }
        }

        // ---- 추적 박스: 지금 쓰고 있는 창을 따라다니고, 자비스가 짚은 곳에는 빨갛게 잠금 ----
        Item {
            id: tg
            readonly property bool has: ov.target.kind !== undefined && ov.p >= 1 && ov.down <= 0
            readonly property bool pt: ov.target.kind === "point"
            readonly property color col: pt ? ov.red : ov.gold
            readonly property real mg: 6 * ov.u
            readonly property real pad: (1 - ov.lock) * 36 * ov.u
            readonly property real x0: has ? Math.max(mg, ov.target.x) : ov.cx - 40
            readonly property real y0: has ? Math.max(mg, ov.target.y) : ov.cy - 40
            readonly property real x1: has ? Math.min(ov.width - mg, ov.target.x + ov.target.w) : ov.cx + 40
            readonly property real y1: has ? Math.min(ov.height - mg, ov.target.y + ov.target.h) : ov.cy + 40
            x: x0 - pad; y: y0 - pad
            width: Math.max(20, x1 - x0) + 2 * pad; height: Math.max(20, y1 - y0) + 2 * pad
            Behavior on x { NumberAnimation { duration: 420; easing.type: Easing.OutCubic } }
            Behavior on y { NumberAnimation { duration: 420; easing.type: Easing.OutCubic } }
            Behavior on width { NumberAnimation { duration: 420; easing.type: Easing.OutCubic } }
            Behavior on height { NumberAnimation { duration: 420; easing.type: Easing.OutCubic } }
            opacity: has ? (pt ? 1 : 0.85) : 0
            Behavior on opacity { NumberAnimation { duration: 300 } }
            visible: opacity > 0.01

            Repeater {
                model: 4
                Shape {
                    id: tc
                    readonly property bool onRight: index % 2 === 1
                    readonly property bool onBottom: index >= 2
                    readonly property real len: Math.min((tg.pt ? 20 : 28) * ov.u, tg.width / 3, tg.height / 3)
                    width: len; height: len
                    x: onRight ? tg.width - len : 0
                    y: onBottom ? tg.height - len : 0
                    ShapePath {
                        strokeColor: tg.col; strokeWidth: (tg.pt ? 4.5 : 3.5) * ov.u; fillColor: "transparent"; capStyle: ShapePath.FlatCap
                        joinStyle: ShapePath.MiterJoin
                        PathMove { x: tc.onRight ? 0 : tc.len; y: tc.onBottom ? tc.len : 0 }
                        PathLine { x: tc.onRight ? tc.len : 0; y: tc.onBottom ? tc.len : 0 }
                        PathLine { x: tc.onRight ? tc.len : 0; y: tc.onBottom ? 0 : tc.len }
                    }
                }
            }
            // 짚은 위치: 가운데 고리가 맥박치듯
            Rectangle {
                visible: tg.pt
                anchors.centerIn: parent
                width: 22 * ov.u + 16 * ov.u * ov.pulse; height: width; radius: width / 2
                color: "transparent"; border.color: ov.red; border.width: 3 * ov.u
                opacity: 0.4 + 0.6 * ov.lock
            }
            Rectangle {
                visible: tg.pt
                anchors.centerIn: parent
                width: 10 * ov.u; height: width; rotation: 45
                color: ov.red
            }
            // 이름표: 어두운 받침 위 (흰 창 위에서도 읽히게). 박스 위에 자리가 없으면 안쪽 위
            Item {
                id: tgLabel
                readonly property bool inside: tg.y < 56 * ov.u
                readonly property real gx: tg.x + x
                x: Math.min(inside ? 30 * ov.u : 0, Math.max(0, ov.width - tg.x - width - 10))
                y: inside ? 30 * ov.u : -height - 8 * ov.u
                width: tgCol.width + 16 * ov.u; height: tgCol.height + 10 * ov.u
                // 양쪽 위젯 열 위에 걸치면 흐리게 (위젯 글자와 겹쳐 읽기 어려움)
                opacity: gx < ov.colX(-1, 0, 0) + ov.colW + 20 * ov.u || gx + width > ov.width - ov.colX(-1, 0, 0) - ov.colW - 20 * ov.u ? 0.45 : 1
                Rectangle { anchors.fill: parent; color: Qt.rgba(0.06, 0.025, 0, 0.78) }
                Rectangle { width: 4 * ov.u; height: parent.height; color: tg.col }
                Column {
                    id: tgCol
                    x: 12 * ov.u; y: 5 * ov.u
                    spacing: 1
                    HText {
                        text: tg.pt ? (ov.lock >= 1 ? "LOCKED" : "ANALYZING" + ".".repeat(1 + ov.tick % 3))
                                    : "TRACKING  ·  " + (ov.target.app || "WINDOW").toUpperCase()
                        color: tg.col; font.pixelSize: 11 * ov.u; font.letterSpacing: 2 * ov.u; font.weight: Font.Bold
                    }
                    HText {
                        width: Math.min(implicitWidth, 380 * ov.u); elide: Text.ElideRight
                        text: ov.target.title || ""
                        color: ov.hot; font.pixelSize: (tg.pt ? 15 : 12) * ov.u
                    }
                    HText {
                        visible: !tg.pt && ov.target.cpu !== undefined && ov.target.cpu >= 0
                        text: "CPU " + ov.target.cpu + "%   ·   MEM " + ov.mb(ov.target.mem || 0)
                        color: ov.gd(0.9); font.pixelSize: 10 * ov.u; font.letterSpacing: 1.5 * ov.u
                    }
                }
            }
        }

        // ---- 가운데 조준경: 굵은 금색 고리 ----
        Item {
            id: reticle
            readonly property real rr: 120 * ov.u
            readonly property real e: ov.seg(0.05, 0.45)
            readonly property real draw: ov.seg(0.2, 0.7) * (1 - ov.dlin(0.12, 0.34))     // 고리가 그려지는 / 풀리는 진행도
            width: rr * 2; height: rr * 2
            x: ov.cx - rr; y: ov.cy - rr
            visible: e > 0
            opacity: Math.min(1, e * 1.4)
            scale: 0.15 + 0.85 * e + Math.sin(e * Math.PI) * 0.14

            // 바깥 눈금: 네 토막 (천천히 돎)
            Item {
                anchors.fill: parent
                rotation: -ov.spin * 0.25
                Repeater {
                    model: 72
                    Rectangle {
                        readonly property real a: index * 5
                        readonly property bool inArc: (a % 90) >= 15 && (a % 90) <= 75
                        visible: inArc && index < 72 * reticle.draw
                        width: (index % 6 === 0 ? 3.5 : 2) * ov.u
                        height: index % 6 === 0 ? 14 * ov.u : 6 * ov.u
                        x: reticle.rr - width / 2; y: 0
                        color: index % 6 === 0 ? ov.hot : ov.c(0.75)
                        border.color: ov.outline; border.width: index % 6 === 0 ? 1 * ov.u : 0
                        transform: Rotation { origin.x: width / 2; origin.y: reticle.rr; angle: a }
                    }
                }
                Repeater {
                    model: 4
                    Item {
                        x: reticle.rr; y: reticle.rr
                        rotation: index * 90
                        HText { plate: true;
                            x: -width / 2; y: -reticle.rr - 20 * ov.u
                            text: ("00" + index * 90).slice(-3)
                            opacity: reticle.draw
                            color: ov.gd(0.95); font.pixelSize: 11 * ov.u; font.weight: Font.Bold
                        }
                    }
                }
            }
            // 소리 스펙트럼 고리 (목소리 · 마이크에 반응)
            Repeater {
                model: 48
                Rectangle {
                    readonly property real amp: (0.08 + ov.lvl * (0.35 + 0.65 * ov.rnd(index * 3.3 + ov.tick))) * (index < 48 * reticle.draw ? 1 : 0)
                    width: 3.5 * ov.u; height: 3 * ov.u + 24 * ov.u * amp
                    x: reticle.rr - width / 2
                    y: reticle.rr - reticle.rr * 0.68 - height
                    color: amp > 0.4 ? ov.hot : ov.c(0.55 + 0.45 * amp)
                    border.color: ov.outline; border.width: 1 * ov.u
                    transform: Rotation { origin.x: width / 2; origin.y: reticle.rr * 0.68 + height; angle: index * 7.5 }
                }
            }
            // 분절 호 (시계 방향) + 아래 번짐
            Shape {
                anchors.fill: parent
                rotation: ov.spin
                preferredRendererType: Shape.CurveRenderer
                ShapePath {
                    strokeColor: ov.c(0.2); strokeWidth: 16 * ov.u; fillColor: "transparent"; capStyle: ShapePath.FlatCap
                    PathAngleArc { centerX: reticle.rr; centerY: reticle.rr; radiusX: reticle.rr * 0.87; radiusY: reticle.rr * 0.87; startAngle: 10; sweepAngle: 60 * reticle.draw }
                    PathAngleArc { centerX: reticle.rr; centerY: reticle.rr; radiusX: reticle.rr * 0.87; radiusY: reticle.rr * 0.87; startAngle: 215; sweepAngle: 85 * reticle.draw }
                }
                ShapePath {
                    strokeColor: ov.outline; strokeWidth: (6 * ov.u) + 4 * ov.u; fillColor: "transparent"; capStyle: ShapePath.FlatCap
                    PathAngleArc { centerX: reticle.rr; centerY: reticle.rr; radiusX: reticle.rr * 0.87; radiusY: reticle.rr * 0.87; startAngle: 10; sweepAngle: 60 * reticle.draw }
                    PathAngleArc { centerX: reticle.rr; centerY: reticle.rr; radiusX: reticle.rr * 0.87; radiusY: reticle.rr * 0.87; startAngle: 215; sweepAngle: 85 * reticle.draw }
                }
                ShapePath {
                    strokeColor: ov.accent; strokeWidth: 6 * ov.u; fillColor: "transparent"; capStyle: ShapePath.FlatCap
                    PathAngleArc { centerX: reticle.rr; centerY: reticle.rr; radiusX: reticle.rr * 0.87; radiusY: reticle.rr * 0.87; startAngle: 10; sweepAngle: 60 * reticle.draw }
                    PathAngleArc { centerX: reticle.rr; centerY: reticle.rr; radiusX: reticle.rr * 0.87; radiusY: reticle.rr * 0.87; startAngle: 215; sweepAngle: 85 * reticle.draw }
                }
                ShapePath {
                    strokeColor: ov.outline; strokeWidth: (6 * ov.u) + 4 * ov.u; fillColor: "transparent"; capStyle: ShapePath.FlatCap
                    PathAngleArc { centerX: reticle.rr; centerY: reticle.rr; radiusX: reticle.rr * 0.87; radiusY: reticle.rr * 0.87; startAngle: 130; sweepAngle: 30 * reticle.draw }
                }
                ShapePath {
                    strokeColor: ov.hot; strokeWidth: 6 * ov.u; fillColor: "transparent"; capStyle: ShapePath.FlatCap
                    PathAngleArc { centerX: reticle.rr; centerY: reticle.rr; radiusX: reticle.rr * 0.87; radiusY: reticle.rr * 0.87; startAngle: 130; sweepAngle: 30 * reticle.draw }
                }
            }
            // 점선 고리 (반시계 방향)
            Shape {
                anchors.fill: parent
                rotation: -ov.spin * 2.2
                preferredRendererType: Shape.CurveRenderer
                ShapePath {
                    strokeColor: ov.outline; strokeWidth: (3 * ov.u) + 4 * ov.u; fillColor: "transparent"; capStyle: ShapePath.FlatCap
                    PathAngleArc { centerX: reticle.rr; centerY: reticle.rr; radiusX: reticle.rr * 0.52; radiusY: reticle.rr * 0.52; startAngle: 0; sweepAngle: 300 * reticle.draw }
                }
                ShapePath {
                    strokeColor: ov.c(0.75); strokeWidth: 3 * ov.u; fillColor: "transparent"; capStyle: ShapePath.FlatCap
                    strokeStyle: ShapePath.DashLine; dashPattern: [2, 2.5]
                    PathAngleArc { centerX: reticle.rr; centerY: reticle.rr; radiusX: reticle.rr * 0.52; radiusY: reticle.rr * 0.52; startAngle: 0; sweepAngle: 300 * reticle.draw }
                }
                ShapePath {
                    strokeColor: ov.outline; strokeWidth: (6 * ov.u) + 4 * ov.u; fillColor: "transparent"; capStyle: ShapePath.FlatCap
                    PathAngleArc { centerX: reticle.rr; centerY: reticle.rr; radiusX: reticle.rr * 0.52; radiusY: reticle.rr * 0.52; startAngle: 310; sweepAngle: 40 * reticle.draw }
                }
                ShapePath {
                    strokeColor: ov.hot; strokeWidth: 6 * ov.u; fillColor: "transparent"; capStyle: ShapePath.FlatCap
                    PathAngleArc { centerX: reticle.rr; centerY: reticle.rr; radiusX: reticle.rr * 0.52; radiusY: reticle.rr * 0.52; startAngle: 310; sweepAngle: 40 * reticle.draw }
                }
            }
            // 목소리 크기에 따라 늘어나는 호 (좌우)
            Shape {
                anchors.fill: parent
                preferredRendererType: Shape.CurveRenderer
                ShapePath {
                    strokeColor: ov.outline; strokeWidth: (4 * ov.u) + 4 * ov.u; fillColor: "transparent"; capStyle: ShapePath.FlatCap
                    PathAngleArc { centerX: reticle.rr; centerY: reticle.rr; radiusX: reticle.rr * 0.4; radiusY: reticle.rr * 0.4
                                   startAngle: 180 - (8 + 58 * ov.lvl) * reticle.draw; sweepAngle: 2 * (8 + 58 * ov.lvl) * reticle.draw }
                    PathAngleArc { centerX: reticle.rr; centerY: reticle.rr; radiusX: reticle.rr * 0.4; radiusY: reticle.rr * 0.4
                                   startAngle: -(8 + 58 * ov.lvl) * reticle.draw; sweepAngle: 2 * (8 + 58 * ov.lvl) * reticle.draw }
                }
                ShapePath {
                    strokeColor: ov.hot; strokeWidth: 4 * ov.u; fillColor: "transparent"; capStyle: ShapePath.FlatCap
                    PathAngleArc { centerX: reticle.rr; centerY: reticle.rr; radiusX: reticle.rr * 0.4; radiusY: reticle.rr * 0.4
                                   startAngle: 180 - (8 + 58 * ov.lvl) * reticle.draw; sweepAngle: 2 * (8 + 58 * ov.lvl) * reticle.draw }
                    PathAngleArc { centerX: reticle.rr; centerY: reticle.rr; radiusX: reticle.rr * 0.4; radiusY: reticle.rr * 0.4
                                   startAngle: -(8 + 58 * ov.lvl) * reticle.draw; sweepAngle: 2 * (8 + 58 * ov.lvl) * reticle.draw }
                }
            }
            // 가장 가까운 타이머: 줄어드는 고리 + 남은 시간
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
                        strokeColor: ov.outline; strokeWidth: (5 * ov.u) + 4 * ov.u; fillColor: "transparent"
                        PathAngleArc { centerX: reticle.rr; centerY: reticle.rr; radiusX: reticle.rr * 0.3; radiusY: reticle.rr * 0.3; startAngle: 0; sweepAngle: 360 }
                    }
                    ShapePath {
                        strokeColor: ov.c(0.25); strokeWidth: 5 * ov.u; fillColor: "transparent"
                        PathAngleArc { centerX: reticle.rr; centerY: reticle.rr; radiusX: reticle.rr * 0.3; radiusY: reticle.rr * 0.3; startAngle: 0; sweepAngle: 360 }
                    }
                    ShapePath {
                        strokeColor: ov.outline; strokeWidth: (5 * ov.u) + 4 * ov.u; fillColor: "transparent"; capStyle: ShapePath.FlatCap
                        PathAngleArc { centerX: reticle.rr; centerY: reticle.rr; radiusX: reticle.rr * 0.3; radiusY: reticle.rr * 0.3
                                       startAngle: -90; sweepAngle: 360 * Math.max(0.002, tmr.frac) }
                    }
                    ShapePath {
                        strokeColor: tmr.frac < 0.1 ? ov.red : ov.hot; strokeWidth: 5 * ov.u; fillColor: "transparent"; capStyle: ShapePath.FlatCap
                        PathAngleArc { centerX: reticle.rr; centerY: reticle.rr; radiusX: reticle.rr * 0.3; radiusY: reticle.rr * 0.3
                                       startAngle: -90; sweepAngle: 360 * Math.max(0.002, tmr.frac) }
                    }
                }
                HText { plate: true;
                    anchors.horizontalCenter: parent.horizontalCenter
                    y: reticle.rr + 14 * ov.u
                    text: tmr.t0 ? ov.hms(ov.left(tmr.t0)) : ""
                    color: tmr.frac < 0.1 ? ov.red : ov.hot
                    font.pixelSize: 15 * ov.u; font.weight: Font.Bold
                }
            }
            // 가운데: 비행 경로 표시 (원 + 양 날개 + 꼬리)
            Item {
                x: reticle.rr; y: reticle.rr
                opacity: reticle.draw
                Rectangle {
                    width: 18 * ov.u; height: width; radius: width / 2; x: -width / 2; y: -height / 2
                    color: "transparent"; border.color: ov.hot; border.width: 3 * ov.u
                    Rectangle { anchors.fill: parent; anchors.margins: -2 * ov.u; radius: width / 2; color: "transparent"; border.color: ov.outline; border.width: 2 * ov.u }
                }
                Rectangle { x: -9 * ov.u - 24 * ov.u; y: -3.5 * ov.u; width: 26 * ov.u; height: 7 * ov.u; color: ov.outline }
                Rectangle { x: 7 * ov.u; y: -3.5 * ov.u; width: 26 * ov.u; height: 7 * ov.u; color: ov.outline }
                Rectangle { x: -3.5 * ov.u; y: -9 * ov.u - 14 * ov.u; width: 7 * ov.u; height: 14 * ov.u; color: ov.outline }
                Rectangle { x: -9 * ov.u - 22 * ov.u; y: -1.5 * ov.u; width: 22 * ov.u; height: 3 * ov.u; color: ov.hot }
                Rectangle { x: 9 * ov.u; y: -1.5 * ov.u; width: 22 * ov.u; height: 3 * ov.u; color: ov.hot }
                Rectangle { x: -1.5 * ov.u; y: -9 * ov.u - 12 * ov.u; width: 3 * ov.u; height: 12 * ov.u; color: ov.hot }
                Rectangle {
                    width: 5 * ov.u; height: width; radius: width / 2; x: -width / 2; y: -height / 2
                    color: ov.gold; opacity: 0.5 + 0.5 * ov.pulse
                }
            }
            Repeater {
                model: 4
                Item {
                    x: reticle.rr; y: reticle.rr
                    rotation: index * 90 + 45
                    Rectangle {
                        width: 10 * ov.u; height: 10 * ov.u; rotation: 45
                        x: -width / 2; y: -reticle.rr - 12 * ov.u - 6 * ov.u * ov.pulse
                        opacity: reticle.draw
                        color: ov.accent
                    }
                }
            }
        }

        // ---- 수평 사다리 (헬멧 기울기 · 오르내림): 조준경 바깥 양쪽 ----
        Item {
            id: ladder
            x: ov.cx; y: ov.cy
            rotation: ov.roll * 1.6
            opacity: ov.seg(0.45, 0.8) * (1 - ov.dlin(0.1, 0.3))
            visible: opacity > 0
            readonly property real gap: reticle.rr + 20 * ov.u
            Repeater {
                model: [-2, -1, 0, 1, 2]
                Item {
                    id: rung
                    readonly property int k: modelData
                    readonly property real len: (k === 0 ? 70 : 40) * ov.u
                    y: -k * 44 * ov.u + ov.pitch * ov.u
                    Repeater {
                        model: 2
                        Item {
                            readonly property int sd: index === 0 ? -1 : 1
                            Shape {
                                ShapePath {
                                    strokeColor: ov.outline; strokeWidth: ((rung.k === 0 ? 4 : 3) * ov.u) + 4 * ov.u
                                    fillColor: "transparent"; capStyle: ShapePath.FlatCap; joinStyle: ShapePath.MiterJoin
                                    PathMove { x: sd * ladder.gap; y: 0 }
                                    PathLine { x: sd * (ladder.gap + rung.len); y: 0 }
                                    PathLine { x: sd * (ladder.gap + rung.len); y: rung.k === 0 ? 0 : (rung.k > 0 ? 8 : -8) * ov.u }
                                }
                                ShapePath {
                                    strokeColor: rung.k === 0 ? ov.hot : ov.gd(0.9); strokeWidth: (rung.k === 0 ? 4 : 3) * ov.u
                                    fillColor: "transparent"; capStyle: ShapePath.FlatCap; joinStyle: ShapePath.MiterJoin
                                    strokeStyle: rung.k < 0 ? ShapePath.DashLine : ShapePath.SolidLine; dashPattern: [3, 2]
                                    PathMove { x: sd * ladder.gap; y: 0 }
                                    PathLine { x: sd * (ladder.gap + rung.len); y: 0 }
                                    PathLine { x: sd * (ladder.gap + rung.len); y: rung.k === 0 ? 0 : (rung.k > 0 ? 8 : -8) * ov.u }
                                }
                            }
                            HText { plate: true;
                                visible: rung.k !== 0
                                x: sd < 0 ? -(ladder.gap + rung.len) - width - 6 * ov.u : ladder.gap + rung.len + 6 * ov.u
                                y: -height / 2
                                text: Math.abs(rung.k) * 10
                                color: ov.gd(0.95); font.pixelSize: 11 * ov.u; font.weight: Font.Bold
                            }
                        }
                    }
                }
            }
        }
        // 조준경 대각선 수치 — 모두 실제 값: 전원(배터리 · 충전) / 목소리 · 마이크 크기 / 내려받는 속도 / CPU · RAM
        Repeater {
            model: [["PWR", ov.stats.bat === undefined || ov.stats.bat < 0 ? "AC LINE" : ov.stats.bat + " %" + (ov.stats.plugged ? " CHG" : "")],
                    ["VOX", Math.round(ov.lvl * 100) + " %"],
                    ["NET", "▼ " + ov.rate(ov.stats.down)], ["SYS", Math.round(ov.stats.cpu || 0) + " / " + Math.round(ov.stats.ram || 0)]]
            Column {
                readonly property bool onRight: index % 2 === 1
                readonly property bool onBottom: index >= 2
                readonly property real off: reticle.rr * 1.02
                x: onRight ? ov.cx + off : ov.cx - off - width
                y: onBottom ? ov.cy + off - height : ov.cy - off
                opacity: ov.seg(0.55, 0.85) * (1 - ov.dlin(0.1, 0.28))
                spacing: 0
                HText { plate: true; anchors.right: parent.onRight ? undefined : parent.right; text: modelData[0]
                       color: ov.gd(0.95); font.pixelSize: 10 * ov.u; font.letterSpacing: 2 * ov.u; font.weight: Font.Bold }
                HText { plate: true; anchors.right: parent.onRight ? undefined : parent.right; text: modelData[1]
                       color: ov.hot; font.pixelSize: 16 * ov.u; font.weight: Font.Bold }
            }
        }

        // ---- 조준경 아래: 상태 글 + 턱선을 따라 휜 음성 파형 ----
        Column {
            anchors.horizontalCenter: parent.horizontalCenter
            y: ov.cy + reticle.rr + 24 * ov.u
            spacing: 4 * ov.u
            opacity: ov.seg(0.45, 0.7) * (1 - ov.dlin(0.06, 0.24))
            Decode { plate: true;
                anchors.horizontalCenter: parent.horizontalCenter
                full: ov.down > 0 ? "DISENGAGING" : ov.p < 1 ? "ACTIVE MODE ENGAGED" : (ov.stateLabels[ov.st] || ov.st.toUpperCase())
                t: ov.lin(0.45, 0.8); seed: 3
                color: ov.down > 0 ? ov.ember : ov.hot
                font.pixelSize: 20 * ov.u; font.letterSpacing: 9 * ov.u; font.weight: Font.Bold
            }
            Decode { plate: true;
                anchors.horizontalCenter: parent.horizontalCenter
                full: jarvis.statusText
                t: ov.lin(0.6, 0.92); seed: 5
                color: ov.gd(0.95)
                font.pixelSize: 12 * ov.u; font.letterSpacing: 1 * ov.u
            }
        }
        Item {
            id: wave
            readonly property real e: ov.seg(0.55, 0.85)
            readonly property real r: reticle.rr + 118 * ov.u
            x: ov.cx; y: ov.cy
            opacity: e * (1 - ov.dlin(0.04, 0.22))
            visible: opacity > 0
            Repeater {
                model: 33
                Item {
                    readonly property real centerFade: 1 - Math.abs(index - 16) / 17
                    readonly property real wob: 0.5 + 0.5 * Math.sin(ov.sweep * Math.PI / 180 * 6 + index * 0.9)
                    rotation: (index - 16) * 1.6 * wave.e
                    Rectangle {
                        x: -width / 2
                        y: wave.r
                        width: 5 * ov.u
                        height: Math.max(3 * ov.u, 40 * ov.u * parent.centerFade * (0.1 + ov.lvl * (0.5 + 0.5 * parent.wob)))
                        color: parent.centerFade > 0.75 ? ov.hot : ov.c(0.5 + 0.5 * parent.centerFade)
                        border.color: ov.outline; border.width: 1 * ov.u
                    }
                }
            }
            Repeater {   // 파형 양 끝의 굵은 괄호
                model: 2
                Item {
                    rotation: (index === 0 ? -1 : 1) * 30 * wave.e
                    Rectangle { x: -2 * ov.u; y: wave.r - 6 * ov.u; width: 4 * ov.u; height: 26 * ov.u; color: ov.gold }
                }
            }
        }

        // ---- 위쪽: 이마판 아래를 따라 휜 방위 테이프 + 제목 ----
        Fly {
            d: 0.3
            width: ov.width * 0.36; height: 78 * ov.u
            x: ov.cx - width / 2; y: ov.height * 0.085
            Item {
                id: hd
                width: parent.width; height: 46 * ov.u
                clip: true
                readonly property real k: width / 120    // 화면에 보이는 각도 120°
                // 보이는 120° 안의 눈금 자리만 만든다
                readonly property int base: Math.floor(ov.heading / 5) - 13
                Repeater {
                    model: 27
                    Item {
                        readonly property int dd: (((hd.base + index) * 5) % 360 + 360) % 360
                        readonly property real xx: hd.width / 2 + ((hd.base + index) * 5 - ov.heading) * hd.k
                        readonly property real q: (xx - hd.width / 2) / (hd.width / 2)
                        readonly property real bend: 12 * ov.u * q * q      // 헬멧 윗선을 따라 양 끝이 내려감
                        visible: xx > -10 && xx < hd.width + 10
                        x: xx
                        readonly property real fade: 1 - Math.min(1, Math.abs(q))
                        Rectangle {
                            width: ((dd / 5) % 3 === 0 ? 3 : 2) * ov.u; height: (dd / 5) % 3 === 0 ? 14 * ov.u : 7 * ov.u
                            x: -width / 2
                            y: 30 * ov.u - height + parent.bend
                            color: ov.gd(0.35 + 0.65 * parent.fade)
                        }
                        HText { plate: true;
                            visible: dd % 45 === 0
                            text: dd % 45 === 0 ? ["N", "NE", "E", "SE", "S", "SW", "W", "NW"][dd / 45] : ""
                            x: -width / 2; y: parent.bend
                            color: dd === 0 ? ov.hot : ov.gd(0.4 + 0.6 * parent.fade)
                            font.pixelSize: 13 * ov.u; font.weight: Font.Bold
                        }
                    }
                }
            }
            Shape {   // 가운데 방위 표시 (위를 가리키는 삼각형)
                x: parent.width / 2; y: 32 * ov.u
                ShapePath {
                    strokeColor: "transparent"; fillColor: ov.hot
                    PathMove { x: -7 * ov.u; y: 10 * ov.u }
                    PathLine { x: 7 * ov.u; y: 10 * ov.u }
                    PathLine { x: 0; y: 0 }
                    PathLine { x: -7 * ov.u; y: 10 * ov.u }
                }
            }
            Decode { plate: true;
                anchors.horizontalCenter: parent.horizontalCenter
                y: 50 * ov.u
                full: "J.A.R.V.I.S   ·   ACTIVE   ·   HDG " + ("00" + Math.floor(ov.heading)).slice(-3)
                t: ov.lin(0.4, 0.75); seed: 1
                color: ov.hot
                font.pixelSize: 13 * ov.u; font.letterSpacing: 5 * ov.u; font.weight: Font.Bold
            }
        }

        // ================================================================ 왼쪽 열
        // ---- 시간 (+ 가장 가까운 타이머) ----
        Wid {
            id: wTime
            side: -1; d: 0.34
            title: "SYSTEM TIME"; tag: "KST // UTC+9"
            y: ov.colTop; height: 118 * ov.u
            Item {
                id: dayRing
                y: -2 * ov.u
                width: 76 * ov.u; height: width
                Shape {
                    anchors.fill: parent
                    preferredRendererType: Shape.CurveRenderer
                    ShapePath {
                        strokeColor: ov.c(0.25); strokeWidth: 6 * ov.u; fillColor: "transparent"
                        PathAngleArc { centerX: dayRing.width / 2; centerY: dayRing.width / 2; radiusX: 33 * ov.u; radiusY: 33 * ov.u; startAngle: 0; sweepAngle: 360 }
                    }
                    ShapePath {
                        strokeColor: ov.hot; strokeWidth: 6 * ov.u; fillColor: "transparent"; capStyle: ShapePath.FlatCap
                        PathAngleArc { centerX: dayRing.width / 2; centerY: dayRing.width / 2; radiusX: 33 * ov.u; radiusY: 33 * ov.u
                                       startAngle: -90; sweepAngle: Math.max(1, 6 * (ov.now.getSeconds() + (ov.idle ? 0 : ov.now.getMilliseconds() / 1000))) }
                    }
                }
                HText {
                    anchors.centerIn: parent
                    text: ov.now.getDate()
                    color: ov.hot; font.pixelSize: 26 * ov.u; font.weight: Font.Bold
                }
            }
            Column {
                x: 90 * ov.u; y: -6 * ov.u
                width: wTime.iw - x
                spacing: 0
                HText {
                    text: ov.pad(ov.now.getHours()) + ":" + ov.pad(ov.now.getMinutes())
                    color: ov.hot; font.pixelSize: 46 * ov.u; font.weight: Font.DemiBold
                }
                Decode {
                    full: ["SUNDAY", "MONDAY", "TUESDAY", "WEDNESDAY", "THURSDAY", "FRIDAY", "SATURDAY"][ov.now.getDay()]
                          + "  ·  " + ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"][ov.now.getMonth()]
                          + " " + ov.now.getFullYear()
                    t: ov.lin(0.5, 0.8); seed: 7
                    font.pixelSize: 11 * ov.u; font.letterSpacing: 2 * ov.u; font.weight: Font.Bold
                }
                HText {   // 타이머가 돌면 가장 가까운 것, 아니면 세션 시간
                    width: parent.width; elide: Text.ElideRight
                    readonly property var t0: ov.timers.length ? ov.timers[0] : null
                    text: t0 ? "⏱ " + t0.label + "  " + ov.hms(ov.left(t0)) + (ov.timers.length > 1 ? "  +" + (ov.timers.length - 1) : "")
                             : "SESSION " + ov.hms(Math.max(0, (ov.now.getTime() - ov.engagedAt) / 1000))
                    color: t0 ? (ov.left(t0) / Math.max(1, t0.total) < 0.1 ? ov.red : ov.hot) : ov.gd(0.85)
                    font.pixelSize: (t0 ? 12 : 10) * ov.u; font.letterSpacing: 1.5 * ov.u
                }
            }
        }

        // ---- VITALS: 사람 모양 도식, 부위마다 실제 하위 시스템 상태 ----
        Wid {
            id: integ
            side: -1; d: 0.42
            y: wTime.y + wTime.height + ov.gapY; height: 236 * ov.u
            title: "VITALS"
            tag: integ.errs ? integ.errs + " FAULT" : integ.warns ? integ.warns + " CAUTION" : "NOMINAL"
            readonly property var s: ov.stats
            readonly property real cpu: s.cpu || 0
            readonly property real ram: s.ram || 0
            readonly property real dsk: s.disk || 0
            readonly property real bat: s.bat === undefined ? -1 : s.bat
            // 0 정상 · 1 주의 · 2 이상 · 3 동작 중
            readonly property var lvl: ({
                ai: !jarvis.hasApiKey ? 1 : ov.st === "thinking" ? 3 : 0,
                aud: ov.st === "offline" ? 2 : ov.st === "listening" ? 3 : 0,
                vox: ov.st === "speaking" ? 3 : 0,
                cpu: cpu > 90 ? 2 : cpu > 75 ? 1 : 0,
                mem: ram > 90 ? 2 : ram > 80 ? 1 : 0,
                dsk: dsk > 95 ? 2 : dsk > 88 ? 1 : 0,
                net: (s.down || 0) > 512 * 1024 ? 3 : 0,
                pwr: bat < 0 || s.plugged ? 0 : bat < 15 ? 2 : bat < 30 ? 1 : 0
            })
            readonly property var val: ({
                ai: !jarvis.hasApiKey ? "LOCAL" : ov.st === "thinking" ? "BUSY" : "ONLINE",
                aud: ov.st === "offline" ? "OFFLINE" : ov.st === "listening" ? "LIVE" : "OK",
                vox: ov.st === "speaking" ? "TX" : "IDLE",
                cpu: Math.round(cpu) + "%", mem: Math.round(ram) + "%", dsk: Math.round(dsk) + "%",
                net: ov.rate(s.down), pwr: bat < 0 ? "AC" : bat + "%"
            })
            readonly property int warns: ["ai", "aud", "cpu", "mem", "dsk", "pwr"].filter(k => lvl[k] === 1).length
            readonly property int errs: ["ai", "aud", "cpu", "mem", "dsk", "pwr"].filter(k => lvl[k] === 2).length
            readonly property int score: Math.max(0, 100 - 8 * warns - 22 * errs)
            function col(n, a) {
                return n === 2 ? ov.rc(a) : n === 1 ? Qt.rgba(1, 0.75, 0.29, a) : n === 3 ? ov.hc(a) : ov.gd(a)
            }
            readonly property real fs: 1.04 * ov.u               // 도식 축척 (76 × 150 단위)
            readonly property real fx: (iw - 76 * fs) / 2
            readonly property real fy: 0
            readonly property real reveal: ov.seg(0.55, 0.95)
            // 부위: [키, 다각형]
            Repeater {
                model: [
                    ["ai",  [[28, 4], [48, 4], [52, 14], [50, 26], [38, 30], [26, 26], [24, 14]]],
                    ["cpu", [[22, 34], [54, 34], [58, 46], [54, 70], [38, 74], [22, 70], [18, 46]]],
                    ["mem", [[26, 77], [50, 77], [52, 90], [38, 97], [24, 90]]],
                    ["aud", [[17, 36], [8, 40], [3, 68], [1, 95], [8, 97], [11, 70], [16, 50]]],
                    ["vox", [[59, 36], [68, 40], [73, 68], [75, 95], [68, 97], [65, 70], [60, 50]]],
                    ["dsk", [[24, 99], [37, 102], [35, 124], [34, 147], [23, 147], [24, 124], [21, 103]]],
                    ["net", [[52, 99], [39, 102], [41, 124], [42, 147], [53, 147], [52, 124], [55, 103]]]
                ]
                Shape {
                    readonly property int n: integ.lvl[modelData[0]]
                    visible: integ.reveal > 0 && index < 7 * integ.reveal + 0.5
                    x: integ.fx; y: integ.fy
                    width: 76 * integ.fs; height: 150 * integ.fs
                    preferredRendererType: Shape.CurveRenderer
                    ShapePath {
                        strokeColor: integ.col(n, 1); strokeWidth: 2.2 * ov.u
                        fillColor: integ.col(n, n === 0 ? 0.22 : n === 3 ? 0.45 + 0.3 * ov.pulse : 0.55)
                        joinStyle: ShapePath.MiterJoin
                        PathPolyline { path: modelData[1].concat([modelData[1][0]]).map(q => Qt.point(q[0] * integ.fs, q[1] * integ.fs)) }
                    }
                }
            }
            // 가슴의 동력원: 전원 상태 · 목소리에 맞춰 빛남
            Rectangle {
                readonly property real r: (7 + 3 * ov.lvl) * integ.fs
                x: integ.fx + 38 * integ.fs - r; y: integ.fy + 48 * integ.fs - r
                width: r * 2; height: width; radius: r
                visible: integ.reveal > 0.3
                color: integ.lvl.pwr === 0 ? Qt.rgba(0.75, 0.95, 1, 0.55 + 0.4 * ov.pulse) : integ.col(integ.lvl.pwr, 0.7)
                border.color: integ.lvl.pwr === 0 ? "#e8fbff" : integ.col(integ.lvl.pwr, 1); border.width: 2.5 * ov.u
            }
            // 위에서 아래로 훑는 검사선
            Rectangle {
                visible: ov.p >= 1
                x: integ.fx - 8 * ov.u; width: 76 * integ.fs + 16 * ov.u; height: 2.5 * ov.u
                y: integ.fy + 150 * integ.fs * ov.scan
                color: ov.hot; opacity: 0.8
            }
            // 이름표 + 지시선: [키, 이름, 왼쪽?, 줄 y, 닿는 점 x, y] (도식 단위)
            Repeater {
                model: [["ai", "AI CORE", true, 2, 25, 14], ["cpu", "CPU", true, 38, 19, 50], ["aud", "AUDIO IN", true, 74, 4, 70],
                        ["dsk", "STORAGE", true, 112, 23, 128], ["pwr", "POWER", false, 2, 44, 48], ["vox", "VOICE OUT", false, 38, 72, 66],
                        ["mem", "MEMORY", false, 74, 51, 86], ["net", "NETWORK", false, 112, 53, 128]]
                Item {
                    readonly property bool lf: modelData[2]
                    readonly property int n: integ.lvl[modelData[0]]
                    readonly property real ly: integ.fy + (modelData[3] + 8) * integ.fs
                    visible: integ.reveal > 0.2 + (index % 4) * 0.18
                    Shape {
                        ShapePath {
                            strokeColor: integ.col(n, 0.8); strokeWidth: 1.6 * ov.u; fillColor: "transparent"
                            PathPolyline { path: [
                                Qt.point(lf ? integ.fx - 12 * ov.u : integ.fx + 76 * integ.fs + 12 * ov.u, ly),
                                Qt.point(lf ? integ.fx - 6 * ov.u : integ.fx + 76 * integ.fs + 6 * ov.u, ly),
                                Qt.point(integ.fx + modelData[4] * integ.fs, integ.fy + modelData[5] * integ.fs)
                            ] }
                        }
                    }
                    Rectangle {
                        width: 5 * ov.u; height: width; radius: width / 2; color: integ.col(n, 1)
                        x: integ.fx + modelData[4] * integ.fs - width / 2; y: integ.fy + modelData[5] * integ.fs - width / 2
                    }
                    Column {
                        x: lf ? integ.fx - 14 * ov.u - width : integ.fx + 76 * integ.fs + 14 * ov.u
                        y: integ.fy + modelData[3] * integ.fs
                        HText {
                            anchors.right: lf ? parent.right : undefined
                            text: modelData[1]; color: ov.gd(0.9)
                            font.pixelSize: 9 * ov.u; font.letterSpacing: 1 * ov.u; font.weight: Font.Bold
                        }
                        HText {
                            anchors.right: lf ? parent.right : undefined
                            text: integ.val[modelData[0]]
                            color: n === 0 ? ov.hot : integ.col(n, 1)
                            font.pixelSize: 14 * ov.u; font.weight: Font.Bold
                        }
                    }
                }
            }
            // 아래: 무결성 점수 막대
            Item {
                y: integ.height - integ.hh - 8 * ov.u - 26 * ov.u
                width: integ.iw; height: 12 * ov.u
                HText {
                    anchors.verticalCenter: parent.verticalCenter
                    text: "INTEGRITY " + Math.round(integ.score * integ.reveal) + "%"
                    color: integ.errs ? ov.red : ov.hot
                    font.pixelSize: 10 * ov.u; font.letterSpacing: 1.5 * ov.u; font.weight: Font.Bold
                }
                Row {
                    anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter
                    spacing: 2 * ov.u
                    Repeater {
                        model: 20
                        Rectangle {
                            width: 4 * ov.u; height: 10 * ov.u
                            color: index < Math.round(integ.score * integ.reveal / 5)
                                   ? (integ.errs ? ov.red : integ.warns ? ov.amber : ov.gold) : ov.gd(0.18)
                        }
                    }
                }
            }
        }

        // ---- SYSLOG: 착용 점검 → 이후 상태 · 추적 · 작업 기록 ----
        Wid {
            id: wLog
            side: -1; d: 0.5
            y: integ.y + integ.height + ov.gapY; height: 196 * ov.u
            title: "SYSLOG"
            tag: ov.down > 0 ? "SHUTDOWN" : ov.booted ? "LIVE" : "SUIT-UP " + Math.round(100 * ov.bootStep / ov.bootCount) + "%"
            Column {
                width: wLog.iw
                Repeater {
                    model: syslog
                    Item {
                        id: row
                        width: parent.width; height: 16 * ov.u
                        property real tp: 0
                        NumberAnimation on tp { from: 0; to: 1; duration: ov.calm ? 0 : 420 }
                        readonly property color lc: lv === "err" || lv === "lock" ? ov.red : lv === "warn" ? ov.amber
                                                  : lv === "ok" ? ov.green : ov.hot
                        HText {
                            anchors.verticalCenter: parent.verticalCenter
                            text: ts; color: ov.gd(0.7)
                            font.pixelSize: 9 * ov.u; font.weight: Font.DemiBold
                        }
                        HText {
                            x: 54 * ov.u; anchors.verticalCenter: parent.verticalCenter
                            width: Math.max(0, row.width - x - rowVal.implicitWidth - 8 * ov.u); elide: Text.ElideRight
                            text: ov.decode(tag, row.tp, index * 3 + 1)
                            color: lv === "lock" ? ov.red : ov.hot
                            font.pixelSize: 10 * ov.u; font.letterSpacing: 1 * ov.u
                        }
                        HText {
                            id: rowVal
                            anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter
                            text: ov.decode(val, Math.max(0, row.tp * 1.6 - 0.6), index * 5 + 2)
                            color: row.lc
                            font.pixelSize: 10 * ov.u; font.weight: Font.Bold
                        }
                    }
                }
            }
            Rectangle {   // 끝에서 깜빡이는 커서
                anchors.right: parent.right
                y: parent.height - 12 * ov.u
                width: 8 * ov.u; height: 11 * ov.u
                color: ov.hot
                visible: ov.tick % 14 < 7 || !ov.booted
            }
        }

        // ================================================================ 오른쪽 열
        // ---- 진단: CPU · 메모리 · 저장공간 + 부하 기록 + 통신량 ----
        Wid {
            id: wDiag
            side: 1; d: 0.38
            title: "DIAGNOSTICS"; tag: "SUBSYSTEMS"
            y: ov.colTop; height: 156 * ov.u
            Row {
                spacing: 18 * ov.u
                Gauge { v: ov.stats.cpu || 0; label: "CPU"; e: ov.seg(0.5, 0.85) }
                Gauge { v: ov.stats.ram || 0; label: "MEMORY"; e: ov.seg(0.55, 0.9) }
                // 저장공간: 파이
                Item {
                    id: pie
                    width: 76 * ov.u; height: width + 16 * ov.u
                    readonly property real used: (ov.stats.disk || 0) / 100 * ov.seg(0.6, 0.95)
                    Shape {
                        width: pie.width; height: pie.width
                        preferredRendererType: Shape.CurveRenderer
                        ShapePath {
                            strokeColor: ov.c(0.85); strokeWidth: 3 * ov.u; fillColor: "transparent"
                            PathAngleArc { centerX: pie.width / 2; centerY: pie.width / 2; radiusX: pie.width / 2 - 4 * ov.u; radiusY: pie.width / 2 - 4 * ov.u; startAngle: 0; sweepAngle: 360 }
                        }
                        ShapePath {
                            strokeColor: "transparent"; fillColor: ov.c(0.75)
                            PathMove { x: pie.width / 2; y: pie.width / 2 }
                            PathAngleArc { moveToStart: false; centerX: pie.width / 2; centerY: pie.width / 2; radiusX: pie.width / 2 - 10 * ov.u; radiusY: pie.width / 2 - 10 * ov.u
                                           startAngle: -90; sweepAngle: 360 * Math.max(0.002, pie.used) }
                            PathLine { x: pie.width / 2; y: pie.width / 2 }
                        }
                    }
                    HText { anchors.horizontalCenter: parent.horizontalCenter; y: pie.width / 2 - height / 2
                           text: Math.round(pie.used * 100) + "%"; color: "#ffffff"; font.pixelSize: 15 * ov.u; font.weight: Font.Bold }
                    Label { anchors.horizontalCenter: parent.horizontalCenter; y: pie.width - 4 * ov.u; text: "STORAGE"; font.pixelSize: 9 * ov.u }
                }
            }
            // 부하 기록 (30초)
            Row {
                y: parent.height - 16 * ov.u
                height: 16 * ov.u
                spacing: 1.5 * ov.u
                Repeater {
                    model: ov.cpuHist
                    Rectangle {
                        width: 3 * ov.u; height: Math.max(2, 16 * ov.u * modelData / 100)
                        anchors.bottom: parent.bottom
                        color: ov.c(0.4 + 0.6 * (index / 30))
                    }
                }
            }
            Label {
                anchors.right: parent.right; y: parent.height - height
                text: "▼ " + ov.rate(ov.stats.down) + "   ▲ " + ov.rate(ov.stats.up)
                color: ov.hot; font.pixelSize: 10 * ov.u; font.letterSpacing: 1 * ov.u
            }
        }

        // ---- 날씨 ----
        Wid {
            id: wx
            side: 1; d: 0.46
            y: wDiag.y + wDiag.height + ov.gapY; height: 196 * ov.u
            readonly property bool ready: ov.weather.temp !== undefined
            title: "ATMOSPHERICS"; tag: wx.ready ? String(ov.weather.loc).toUpperCase() : ""
            HText {
                visible: !wx.ready
                anchors.centerIn: parent
                text: ov.weather.error ? "WEATHER LINK OFFLINE" : "SCANNING ATMOSPHERE" + ".".repeat(1 + ov.tick % 3)
                color: ov.weather.error ? ov.red : ov.gd(0.95)
                font.pixelSize: 12 * ov.u; font.letterSpacing: 2 * ov.u; font.weight: Font.Bold
            }
            // 기온 + 강수 확률 고리
            Item {
                id: wring
                visible: wx.ready
                width: 90 * ov.u; height: width
                Shape {
                    anchors.fill: parent
                    preferredRendererType: Shape.CurveRenderer
                    ShapePath {
                        strokeColor: ov.c(0.25); strokeWidth: 7 * ov.u; fillColor: "transparent"
                        PathAngleArc { centerX: wring.width / 2; centerY: wring.width / 2; radiusX: 40 * ov.u; radiusY: 40 * ov.u; startAngle: 135; sweepAngle: 270 }
                    }
                    ShapePath {
                        strokeColor: ov.ice; strokeWidth: 7 * ov.u; fillColor: "transparent"; capStyle: ShapePath.FlatCap
                        PathAngleArc { centerX: wring.width / 2; centerY: wring.width / 2; radiusX: 40 * ov.u; radiusY: 40 * ov.u
                                       startAngle: 135; sweepAngle: 270 * Math.max(0.005, (ov.weather.rain || 0) / 100) * wx.e }
                    }
                }
                HText {
                    anchors.centerIn: parent; anchors.verticalCenterOffset: -4 * ov.u
                    text: (ov.weather.temp !== undefined ? ov.weather.temp : "-") + "°"
                    color: ov.hot; font.pixelSize: 32 * ov.u; font.weight: Font.Bold
                }
                HText {
                    anchors.horizontalCenter: parent.horizontalCenter
                    y: parent.height - 18 * ov.u
                    text: "RAIN " + (ov.weather.rain || 0) + "%"
                    color: ov.gd(0.95); font.pixelSize: 9 * ov.u; font.letterSpacing: 1.5 * ov.u; font.weight: Font.Bold
                }
            }
            Column {
                visible: wx.ready
                x: 104 * ov.u; y: 2 * ov.u
                width: wx.iw - x
                spacing: 4 * ov.u
                HText { width: parent.width; elide: Text.ElideRight; text: ov.weather.desc || ""; color: ov.hot; font.pixelSize: 17 * ov.u; font.weight: Font.Bold }
                HText { text: "체감 " + ov.weather.feels + "°  ·  습도 " + ov.weather.humidity + "%"; color: ov.gd(0.95); font.pixelSize: 11 * ov.u }
                HText { text: "바람 " + ov.weather.wind + " km/h"; color: ov.gd(0.95); font.pixelSize: 11 * ov.u }
                HText { text: "최고 " + ov.weather.max + "°  /  최저 " + ov.weather.min + "°"; color: ov.hot; font.pixelSize: 12 * ov.u }
            }
            // 오늘 3시간 간격 기온
            Row {
                id: hourly
                visible: wx.ready
                y: wx.height - wx.hh - 16 * ov.u - 52 * ov.u
                spacing: 8 * ov.u
                readonly property var hs: ov.weather.hourly || []
                readonly property real lo: Math.min.apply(null, hs.map(h => h.t).concat([99])) - 1
                readonly property real hi: Math.max.apply(null, hs.map(h => h.t).concat([-99])) + 1
                readonly property int nowSlot: Math.floor(ov.now.getHours() / 3)
                Repeater {
                    model: hourly.hs
                    Column {
                        spacing: 2 * ov.u
                        width: 26 * ov.u
                        readonly property bool cur: index === hourly.nowSlot
                        HText { anchors.horizontalCenter: parent.horizontalCenter; text: modelData.t + "°"
                               color: parent.cur ? ov.hot : ov.gd(0.9); font.pixelSize: 9 * ov.u }
                        Item {
                            width: parent.width; height: 20 * ov.u
                            Rectangle {
                                anchors.bottom: parent.bottom; anchors.horizontalCenter: parent.horizontalCenter
                                width: 8 * ov.u
                                height: Math.max(3, parent.height * (modelData.t - hourly.lo) / Math.max(1, hourly.hi - hourly.lo) * wx.e)
                                color: parent.parent.cur ? ov.hot : ov.gd(0.5 + 0.45 * modelData.rain / 100)
                            }
                        }
                        HText { anchors.horizontalCenter: parent.horizontalCenter; text: ov.pad(modelData.h)
                               color: parent.cur ? ov.hot : ov.gd(0.75); font.pixelSize: 9 * ov.u }
                    }
                }
            }
        }

        // ---- 통신 기록 ----
        Wid {
            id: wComms
            side: 1; d: 0.54
            y: wx.y + wx.height + ov.gapY; height: 196 * ov.u
            title: "COMMS LINK"; tag: jarvis.chatMode ? "CHAT MODE" : "SECURE"
            Column {
                width: wComms.iw
                spacing: 3 * ov.u
                Label { text: "▸ OPERATOR"; font.pixelSize: 9 * ov.u }
                HText {
                    width: parent.width; text: jarvis.userText || "—"
                    color: ov.hot; font.pixelSize: 13 * ov.u; elide: Text.ElideRight; maximumLineCount: 2; wrapMode: Text.Wrap
                }
                Label { text: "▸ J.A.R.V.I.S"; font.pixelSize: 9 * ov.u }
                HText {
                    width: parent.width; text: jarvis.replyText || "—"
                    color: ov.hc(0.95); font.pixelSize: 13 * ov.u; elide: Text.ElideRight; maximumLineCount: 2; wrapMode: Text.Wrap
                }
                Rectangle { width: parent.width; height: 2 * ov.u; color: ov.gd(0.4) }
                Repeater {
                    model: acts
                    Row {
                        spacing: 6 * ov.u
                        Rectangle {
                            width: 7 * ov.u; height: width; rotation: 45
                            anchors.verticalCenter: parent.verticalCenter
                            color: status === "error" ? ov.red : status === "run" ? ov.amber : ov.green
                        }
                        HText { text: t; color: ov.gd(0.8); font.pixelSize: 10 * ov.u }
                        HText { text: label; color: ov.hot; font.pixelSize: 11 * ov.u; elide: Text.ElideRight; width: 210 * ov.u }
                    }
                }
            }
        }

        // ---- 시선 고리: 눈이 가는 곳을 따라가는 홀로그램 (웹캠 시선, 없으면 마우스 커서) ----
        Item {
            id: gz
            readonly property real r: 68 * ov.u
            readonly property bool has: ov.gazeOn && ov.p >= 1 && ov.down <= 0 && ov.gx >= 0
            readonly property real dist: Math.sqrt((ov.gx - ov.cx) * (ov.gx - ov.cx) + (ov.gy - ov.cy) * (ov.gy - ov.cy))
            readonly property bool locked: ov.gazeLock
            readonly property bool eye: ov.gaze.src === "eye"
            property real shown: has ? 1 : 0
            Behavior on shown { NumberAnimation { duration: 350 } }
            visible: shown > 0.01
            // 조준경과 겹치면 옅게 (가운데를 볼 때 화면이 어지럽지 않게)
            opacity: shown * Math.max(0.25, Math.min(1, (dist - reticle.rr * 0.5) / (reticle.rr * 0.8)))
            anchors.fill: parent
            // 조준경에서 시선까지 이어지는 점선
            Shape {
                anchors.fill: parent
                visible: gz.dist > reticle.rr + gz.r
                ShapePath {
                    strokeColor: ov.outline; strokeWidth: (2 * ov.u) + 4 * ov.u; fillColor: "transparent"
                    PathMove { x: ov.cx + (ov.gx - ov.cx) / Math.max(1, gz.dist) * reticle.rr; y: ov.cy + (ov.gy - ov.cy) / Math.max(1, gz.dist) * reticle.rr }
                    PathLine { x: ov.gx - (ov.gx - ov.cx) / Math.max(1, gz.dist) * gz.r; y: ov.gy - (ov.gy - ov.cy) / Math.max(1, gz.dist) * gz.r }
                }
                ShapePath {
                    strokeColor: ov.gd(0.55); strokeWidth: 2 * ov.u; fillColor: "transparent"
                    strokeStyle: ShapePath.DashLine; dashPattern: [3, 4]
                    PathMove { x: ov.cx + (ov.gx - ov.cx) / Math.max(1, gz.dist) * reticle.rr; y: ov.cy + (ov.gy - ov.cy) / Math.max(1, gz.dist) * reticle.rr }
                    PathLine { x: ov.gx - (ov.gx - ov.cx) / Math.max(1, gz.dist) * gz.r; y: ov.gy - (ov.gy - ov.cy) / Math.max(1, gz.dist) * gz.r }
                }
            }
            Item {
                id: ring
                x: ov.gx - gz.r; y: ov.gy - gz.r
                width: gz.r * 2; height: width
                scale: gz.locked ? 0.82 : 1
                Behavior on scale { NumberAnimation { duration: 260; easing.type: Easing.OutBack } }
                // 번짐 + 바깥 분절 고리 (돎)
                Shape {
                    anchors.fill: parent
                    rotation: ov.spin * 1.6
                    preferredRendererType: Shape.CurveRenderer
                    ShapePath {
                        strokeColor: ov.gd(0.18); strokeWidth: 18 * ov.u; fillColor: "transparent"
                        PathAngleArc { centerX: gz.r; centerY: gz.r; radiusX: gz.r * 0.88; radiusY: gz.r * 0.88; startAngle: 0; sweepAngle: 360 }
                    }
                    ShapePath {
                        strokeColor: ov.outline; strokeWidth: (7 * ov.u) + 4 * ov.u; fillColor: "transparent"; capStyle: ShapePath.FlatCap
                        PathAngleArc { centerX: gz.r; centerY: gz.r; radiusX: gz.r * 0.88; radiusY: gz.r * 0.88; startAngle: 0; sweepAngle: 46 }
                        PathAngleArc { centerX: gz.r; centerY: gz.r; radiusX: gz.r * 0.88; radiusY: gz.r * 0.88; startAngle: 62; sweepAngle: 46 }
                        PathAngleArc { centerX: gz.r; centerY: gz.r; radiusX: gz.r * 0.88; radiusY: gz.r * 0.88; startAngle: 124; sweepAngle: 46 }
                        PathAngleArc { centerX: gz.r; centerY: gz.r; radiusX: gz.r * 0.88; radiusY: gz.r * 0.88; startAngle: 186; sweepAngle: 46 }
                        PathAngleArc { centerX: gz.r; centerY: gz.r; radiusX: gz.r * 0.88; radiusY: gz.r * 0.88; startAngle: 248; sweepAngle: 46 }
                        PathAngleArc { centerX: gz.r; centerY: gz.r; radiusX: gz.r * 0.88; radiusY: gz.r * 0.88; startAngle: 310; sweepAngle: 32 }
                    }
                    ShapePath {
                        strokeColor: gz.locked ? ov.hot : ov.gold; strokeWidth: 7 * ov.u; fillColor: "transparent"; capStyle: ShapePath.FlatCap
                        PathAngleArc { centerX: gz.r; centerY: gz.r; radiusX: gz.r * 0.88; radiusY: gz.r * 0.88; startAngle: 0; sweepAngle: 46 }
                        PathAngleArc { centerX: gz.r; centerY: gz.r; radiusX: gz.r * 0.88; radiusY: gz.r * 0.88; startAngle: 62; sweepAngle: 46 }
                        PathAngleArc { centerX: gz.r; centerY: gz.r; radiusX: gz.r * 0.88; radiusY: gz.r * 0.88; startAngle: 124; sweepAngle: 46 }
                        PathAngleArc { centerX: gz.r; centerY: gz.r; radiusX: gz.r * 0.88; radiusY: gz.r * 0.88; startAngle: 186; sweepAngle: 46 }
                        PathAngleArc { centerX: gz.r; centerY: gz.r; radiusX: gz.r * 0.88; radiusY: gz.r * 0.88; startAngle: 248; sweepAngle: 46 }
                        PathAngleArc { centerX: gz.r; centerY: gz.r; radiusX: gz.r * 0.88; radiusY: gz.r * 0.88; startAngle: 310; sweepAngle: 32 }
                    }
                }
                // 안쪽 점선 고리 (반대로 돎) + 굵은 호
                Shape {
                    anchors.fill: parent
                    rotation: -ov.spin * 3
                    preferredRendererType: Shape.CurveRenderer
                    ShapePath {
                        strokeColor: ov.outline; strokeWidth: (3 * ov.u) + 4 * ov.u; fillColor: "transparent"
                        PathAngleArc { centerX: gz.r; centerY: gz.r; radiusX: gz.r * 0.64; radiusY: gz.r * 0.64; startAngle: 0; sweepAngle: 360 }
                    }
                    ShapePath {
                        strokeColor: ov.amber; strokeWidth: 3 * ov.u; fillColor: "transparent"
                        strokeStyle: ShapePath.DashLine; dashPattern: [2, 2]
                        PathAngleArc { centerX: gz.r; centerY: gz.r; radiusX: gz.r * 0.64; radiusY: gz.r * 0.64; startAngle: 0; sweepAngle: 360 }
                    }
                    ShapePath {
                        strokeColor: ov.outline; strokeWidth: (6 * ov.u) + 4 * ov.u; fillColor: "transparent"; capStyle: ShapePath.FlatCap
                        PathAngleArc { centerX: gz.r; centerY: gz.r; radiusX: gz.r * 0.64; radiusY: gz.r * 0.64; startAngle: 200; sweepAngle: 70 }
                    }
                    ShapePath {
                        strokeColor: ov.ember; strokeWidth: 6 * ov.u; fillColor: "transparent"; capStyle: ShapePath.FlatCap
                        PathAngleArc { centerX: gz.r; centerY: gz.r; radiusX: gz.r * 0.64; radiusY: gz.r * 0.64; startAngle: 200; sweepAngle: 70 }
                    }
                }
                // 십자 (가운데는 비움) + 가운데 점
                Repeater {
                    model: 4
                    Item {
                        x: gz.r; y: gz.r
                        rotation: index * 90
                        Rectangle { x: -3.75 * ov.u; y: -gz.r * 0.5 - 2 * ov.u; width: 7.5 * ov.u; height: gz.r * 0.22 + 4 * ov.u; color: ov.outline }
                        Rectangle { x: -1.75 * ov.u; y: -gz.r * 0.5; width: 3.5 * ov.u; height: gz.r * 0.22; color: ov.hot }
                    }
                }
                Rectangle {
                    width: 8 * ov.u; height: width; radius: width / 2
                    x: gz.r - width / 2; y: gz.r - height / 2
                    color: gz.locked ? ov.red : ov.hot
                }
                // 잠금: 고리 둘레에 네모 꺾쇠가 조여 든다
                Repeater {
                    model: 4
                    Shape {
                        id: lk
                        readonly property bool onRight: index % 2 === 1
                        readonly property bool onBottom: index >= 2
                        readonly property real len: 18 * ov.u
                        readonly property real o: gz.locked ? -6 * ov.u : -26 * ov.u
                        visible: gz.locked
                        x: onRight ? gz.r * 2 - len - o : o
                        y: onBottom ? gz.r * 2 - len - o : o
                        width: len; height: len
                        ShapePath {
                            strokeColor: ov.outline; strokeWidth: (4 * ov.u) + 4 * ov.u; fillColor: "transparent"; capStyle: ShapePath.FlatCap
                            joinStyle: ShapePath.MiterJoin
                            PathMove { x: lk.onRight ? 0 : lk.len; y: lk.onBottom ? lk.len : 0 }
                            PathLine { x: lk.onRight ? lk.len : 0; y: lk.onBottom ? lk.len : 0 }
                            PathLine { x: lk.onRight ? lk.len : 0; y: lk.onBottom ? 0 : lk.len }
                        }
                        ShapePath {
                            strokeColor: ov.hot; strokeWidth: 4 * ov.u; fillColor: "transparent"; capStyle: ShapePath.FlatCap
                            joinStyle: ShapePath.MiterJoin
                            PathMove { x: lk.onRight ? 0 : lk.len; y: lk.onBottom ? lk.len : 0 }
                            PathLine { x: lk.onRight ? lk.len : 0; y: lk.onBottom ? lk.len : 0 }
                            PathLine { x: lk.onRight ? lk.len : 0; y: lk.onBottom ? 0 : lk.len }
                        }
                    }
                }
            }
            // 이름표: 고리 오른쪽 (화면 오른쪽 끝이면 왼쪽)
            Column {
                readonly property bool flip: ov.gx + gz.r + 170 * ov.u > ov.width
                x: flip ? ov.gx - gz.r - 14 * ov.u - width : ov.gx + gz.r + 14 * ov.u
                y: ov.gy - height / 2
                spacing: 1
                HText { plate: true;
                    anchors.right: parent.flip ? parent.right : undefined
                    text: "GAZE  ·  " + (gz.eye ? "OPTICAL" : "CURSOR")
                    color: ov.gold; font.pixelSize: 10 * ov.u; font.letterSpacing: 2 * ov.u; font.weight: Font.Bold
                }
                HText { plate: true;
                    anchors.right: parent.flip ? parent.right : undefined
                    text: gz.locked ? "LOCK" : "TRACKING"
                    color: gz.locked ? ov.hot : ov.gd(0.95); font.pixelSize: 16 * ov.u; font.letterSpacing: 3 * ov.u; font.weight: Font.Bold
                }
                HText { plate: true;
                    anchors.right: parent.flip ? parent.right : undefined
                    text: "X " + ov.pad4(ov.gx) + "   Y " + ov.pad4(ov.gy)
                    color: ov.gd(0.9); font.pixelSize: 10 * ov.u; font.letterSpacing: 1 * ov.u
                }
            }
        }
    }

    // ---- 켜지는 순간: 섬광 + 가로 렌즈 플레어 ----
    Rectangle {
        anchors.fill: parent
        readonly property real t: ov.lin(0.0, 0.16)
        visible: t > 0 && t < 1 && ov.down <= 0
        color: "#fff2d6"
        opacity: Math.sin(t * Math.PI) * 0.25
    }
    Item {
        readonly property real t: ov.lin(0.0, 0.32)
        visible: t > 0 && t < 1 && ov.down <= 0
        anchors.fill: parent
        opacity: Math.sin(t * Math.PI)
        Rectangle {
            width: ov.width * (0.1 + 1.1 * parent.t); height: 4 * ov.u
            x: ov.cx - width / 2; y: ov.cy - height / 2
            gradient: Gradient { orientation: Gradient.Horizontal
                GradientStop { position: 0.0; color: ov.gd(0) }
                GradientStop { position: 0.5; color: "#ffffff" }
                GradientStop { position: 1.0; color: ov.gd(0) } }
        }
        Rectangle {
            width: ov.width * (0.05 + 0.6 * parent.t); height: 26 * ov.u
            x: ov.cx - width / 2; y: ov.cy - height / 2
            opacity: 0.4
            gradient: Gradient { orientation: Gradient.Horizontal
                GradientStop { position: 0.0; color: ov.gd(0) }
                GradientStop { position: 0.5; color: ov.gd(0.9) }
                GradientStop { position: 1.0; color: ov.gd(0) } }
        }
        Rectangle {   // 가운데 빛무리
            width: 170 * ov.u * (0.5 + parent.t); height: width; radius: width / 2
            x: ov.cx - width / 2; y: ov.cy - height / 2
            gradient: Gradient {
                GradientStop { position: 0.0; color: ov.gd(0) }
                GradientStop { position: 0.5; color: Qt.rgba(1, 0.97, 0.9, 0.6) }
                GradientStop { position: 1.0; color: ov.gd(0) }
            }
        }
    }

    // ---- 꺼지는 순간: 가로 한 줄 → 점 (옛 모니터 전원을 끄듯) ----
    Item {
        anchors.fill: parent
        visible: !ov.calm && ov.down > 0.32 && ov.down < 0.76
        Rectangle {
            readonly property real squeeze: ov.din(0.48, 0.6)
            width: Math.max(4 * ov.u, ov.width * (1 - 0.99 * squeeze)); height: (2 + 4 * (1 - ov.dlin(0.34, 0.48))) * ov.u
            x: ov.cx - width / 2; y: ov.cy - height / 2
            opacity: ov.dlin(0.32, 0.4) * (1 - ov.dlin(0.6, 0.64))
            gradient: Gradient { orientation: Gradient.Horizontal
                GradientStop { position: 0.0; color: ov.gd(0) }
                GradientStop { position: 0.15; color: ov.gd(0.95) }
                GradientStop { position: 0.5; color: "#ffffff" }
                GradientStop { position: 0.85; color: ov.gd(0.95) }
                GradientStop { position: 1.0; color: ov.gd(0) } }
        }
        Rectangle {   // 마지막 점
            width: (12 + 36 * (1 - ov.dlin(0.6, 0.74))) * ov.u; height: width; radius: width / 2
            x: ov.cx - width / 2; y: ov.cy - height / 2
            opacity: ov.dlin(0.54, 0.6) * (1 - ov.dlin(0.62, 0.74))
            gradient: Gradient {
                GradientStop { position: 0.0; color: ov.gd(0) }
                GradientStop { position: 0.5; color: Qt.rgba(1, 0.98, 0.92, 0.95) }
                GradientStop { position: 1.0; color: ov.gd(0) }
            }
        }
    }

    // ---- 장갑 판 (페이스플레이트) ----
    //   켤 때: 위아래 판이 닫혀 눈높이의 좁은 틈만 남기고, 봉인되면 덜컹한 뒤 다시 열린다.
    //   끌 때: 화면이 한 줄로 접히는 동안 판이 닫혀 덮고(덜컹), 위아래로 열리며 원래 화면이 드러난다.
    Item {
        id: plates
        anchors.fill: parent
        readonly property real closeCover: ov.down < 0.44 ? 0 : ov.down < 0.56 ? Math.pow((ov.down - 0.44) / 0.12, 2)
                                         : ov.down < 0.74 ? 1 : 1 - (1 - Math.pow(1 - (ov.down - 0.74) / 0.26, 3))
        readonly property real cover: ov.down > 0 ? closeCover : ov.seal <= 1 ? ov.seal : 2 - ov.seal
        readonly property real slit: 34 * ov.u                     // 다 닫혔을 때 남는 눈높이 틈
        readonly property real dip: 22 * ov.u * cover               // 콧등: 가운데가 내려와 틈이 양쪽 눈 모양이 됨
        readonly property real hTop: (ov.cy - slit / 2) * cover
        readonly property real hBot: (ov.height - ov.cy - slit / 2) * cover
        readonly property var topEdge: [Qt.point(ov.width + 4, hTop), Qt.point(ov.cx + 330 * ov.u, hTop), Qt.point(ov.cx + 110 * ov.u, hTop + dip),
                                         Qt.point(ov.cx - 110 * ov.u, hTop + dip), Qt.point(ov.cx - 330 * ov.u, hTop), Qt.point(-4, hTop)]
        readonly property var botEdge: [Qt.point(-4, ov.height - hBot), Qt.point(ov.cx - 420 * ov.u, ov.height - hBot),
                                         Qt.point(ov.cx - 380 * ov.u, ov.height - hBot - 8 * ov.u * cover),
                                         Qt.point(ov.cx + 380 * ov.u, ov.height - hBot - 8 * ov.u * cover),
                                         Qt.point(ov.cx + 420 * ov.u, ov.height - hBot), Qt.point(ov.width + 4, ov.height - hBot)]
        visible: cover > 0.002 && (ov.down > 0 ? !ov.calm : !ov.skipSeal)
        transform: Translate { x: ov.joltX; y: ov.joltY }
        Shape {
            anchors.fill: parent
            ShapePath {   // 윗판 (레드)
                strokeColor: "transparent"
                fillGradient: LinearGradient {
                    x1: 0; y1: 0; x2: 0; y2: Math.max(1, plates.hTop)
                    GradientStop { position: 0.0; color: "#160303" }
                    GradientStop { position: 0.6; color: "#4a0a0a" }
                    GradientStop { position: 1.0; color: "#8e1818" }
                }
                PathPolyline { path: [Qt.point(-4, -4), Qt.point(ov.width + 4, -4)].concat(plates.topEdge).concat([Qt.point(-4, -4)]) }
            }
            ShapePath {   // 아랫판 (레드)
                strokeColor: "transparent"
                fillGradient: LinearGradient {
                    x1: 0; y1: ov.height - plates.hBot; x2: 0; y2: ov.height
                    GradientStop { position: 0.0; color: "#8e1818" }
                    GradientStop { position: 0.4; color: "#4a0a0a" }
                    GradientStop { position: 1.0; color: "#160303" }
                }
                PathPolyline { path: plates.botEdge.concat([Qt.point(ov.width + 4, ov.height + 4), Qt.point(-4, ov.height + 4), plates.botEdge[0]]) }
            }
            ShapePath {   // 판 이음새 (어두운 홈)
                strokeColor: "#120202"; strokeWidth: 4 * ov.u; fillColor: "transparent"
                PathMove { x: ov.cx - ov.width * 0.2; y: 0 }
                PathLine { x: ov.cx - ov.width * 0.2; y: plates.hTop - 16 * ov.u }
                PathMove { x: ov.cx + ov.width * 0.2; y: 0 }
                PathLine { x: ov.cx + ov.width * 0.2; y: plates.hTop - 16 * ov.u }
                PathMove { x: ov.cx; y: 0 }
                PathLine { x: ov.cx; y: plates.hTop + plates.dip - 14 * ov.u }
                PathMove { x: 0; y: plates.hTop * 0.55 }
                PathLine { x: ov.width; y: plates.hTop * 0.55 }
                PathMove { x: ov.cx - ov.width * 0.2; y: ov.height }
                PathLine { x: ov.cx - ov.width * 0.2; y: ov.height - plates.hBot + 18 * ov.u }
                PathMove { x: ov.cx + ov.width * 0.2; y: ov.height }
                PathLine { x: ov.cx + ov.width * 0.2; y: ov.height - plates.hBot + 18 * ov.u }
                PathMove { x: 0; y: ov.height - plates.hBot * 0.55 }
                PathLine { x: ov.width; y: ov.height - plates.hBot * 0.55 }
            }
            ShapePath {   // 판 끝: 골드 테 (어두운 바깥 · 골드 · 밝은 모서리)
                strokeColor: "#4a3008"; strokeWidth: 12 * ov.u; fillColor: "transparent"; joinStyle: ShapePath.MiterJoin
                PathPolyline { path: plates.topEdge }
                PathPolyline { path: plates.botEdge }
            }
            ShapePath {
                strokeColor: "#c9962f"; strokeWidth: 7 * ov.u; fillColor: "transparent"; joinStyle: ShapePath.MiterJoin
                PathPolyline { path: plates.topEdge }
                PathPolyline { path: plates.botEdge }
            }
            ShapePath {
                strokeColor: "#ffe3a0"; strokeWidth: 2 * ov.u; fillColor: "transparent"; joinStyle: ShapePath.MiterJoin
                PathPolyline { path: plates.topEdge }
                PathPolyline { path: plates.botEdge }
            }
        }
        // 봉인되는 순간 틈 사이로 번지는 빛줄기 (켤 때)
        Rectangle {
            readonly property real t: ov.down > 0 ? 0 : ov.seal < 0.85 ? 0 : ov.seal <= 1 ? (ov.seal - 0.85) / 0.15 : Math.max(0, 1 - (ov.seal - 1) * 3)
            visible: t > 0
            width: ov.width * (0.2 + 0.8 * t); height: 3 * ov.u
            x: ov.cx - width / 2; y: ov.cy - height / 2
            opacity: t
            gradient: Gradient { orientation: Gradient.Horizontal
                GradientStop { position: 0.0; color: ov.gd(0) }
                GradientStop { position: 0.5; color: "#ffffff" }
                GradientStop { position: 1.0; color: ov.gd(0) } }
        }
        HText {
            anchors.horizontalCenter: parent.horizontalCenter
            y: plates.hTop - height - 22 * ov.u
            visible: plates.cover > 0.5
            opacity: (plates.cover - 0.5) * 2
            text: ov.down > 0 ? "J.A.R.V.I.S  ·  STANDING BY" : ov.seal < 1 ? "FACEPLATE  ·  SEALING" : "FACEPLATE  ·  SEALED"
            color: ov.down > 0 || ov.seal >= 1 ? "#ffe3a0" : ov.gd(0.85)
            font.pixelSize: 13 * ov.u; font.letterSpacing: 5 * ov.u; font.weight: Font.Bold
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
        visible: ov.visible && e > 0 && (ov.calm ? ov.down <= 0 : ov.down < 0.16)
        width: Math.max(340, 440 * ov.u); height: Math.max(36, 40 * ov.u)
        x: ov.x + ov.cx - width / 2
        y: ov.y + Math.min(ov.height * 0.93 - height, ov.cy + reticle.rr + 182 * ov.u)

        Item {
            anchors.fill: parent
            opacity: chatBar.e * ov.flick * (1 - ov.dlin(0, 0.15)) * (ov.down > 0 ? 0.4 + 0.6 * ov.rnd(Math.floor(ov.down * 90) + 7) : 1)
            Shape {
                anchors.fill: parent
                ShapePath {
                    strokeColor: ov.gold; strokeWidth: 2.5
                    fillColor: Qt.rgba(0.08, 0.035, 0.0, chatBar.active ? 0.94 : 0.82)
                    joinStyle: ShapePath.MiterJoin
                    PathPolyline { path: [Qt.point(12, 1), Qt.point(chatBar.width - 1, 1), Qt.point(chatBar.width - 1, chatBar.height - 12),
                                          Qt.point(chatBar.width - 12, chatBar.height - 1), Qt.point(1, chatBar.height - 1), Qt.point(1, 12), Qt.point(12, 1)] }
                }
            }
            Rectangle { x: 1; y: 12; width: 5; height: parent.height - 13; color: ov.gold }
            HText {
                id: chatCaret
                x: 16; anchors.verticalCenter: parent.verticalCenter
                text: "›"
                color: ov.gold
                font.pixelSize: Math.max(19, 19 * ov.u); font.weight: Font.Bold
            }
            QC.TextField {
                id: chatInput
                anchors.left: chatCaret.right; anchors.right: chatHint.left
                anchors.rightMargin: 8
                anchors.verticalCenter: parent.verticalCenter
                color: ov.hot
                font.pixelSize: Math.max(14, 14 * ov.u)
                leftPadding: 8; rightPadding: 0; topPadding: 0; bottomPadding: 0
                placeholderText: chatBar.active ? "명령 입력…" : "여기를 눌러 글로 명령…"
                placeholderTextColor: Qt.rgba(1, 0.85, 0.6, 0.55)
                selectionColor: ov.gd(0.5)
                background: Item {}
                // 처리 중이라 받지 못한 명령은 지우지 않고 남겨 둔다
                onAccepted: if (text.trim() !== "" && jarvis.submitText(text)) text = ""
                Keys.onEscapePressed: { text = ""; jarvis.releaseFocus() }
            }
            Label {
                id: chatHint
                anchors.right: parent.right; anchors.rightMargin: 14
                anchors.verticalCenter: parent.verticalCenter
                text: ov.st === "thinking" ? "PROCESSING" : chatBar.active ? "ENTER · ESC" : "CHAT"
                font.pixelSize: Math.max(10, 10 * ov.u)
            }
        }
    }
}
