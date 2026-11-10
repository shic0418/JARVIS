// J.A.R.V.I.S 홀로그램 HUD — 화면 오른쪽 구석에 떠 있는 투명 창
//   축소 모드: 엠블럼 이미지 + 상태 표시
//   전체 모드: 모서리를 깎은 청사진 판 하나에 코어 · 대화 · 진단 · 작업 로그 · 입력
import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import QtQuick.Shapes
import QtQuick.Effects

Window {
    id: win
    width: 420; height: 724
    visible: true
    color: "transparent"
    flags: Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool
    title: "J.A.R.V.I.S"

    readonly property string st: jarvis.state
    readonly property bool compact: jarvis.compact
    readonly property color cyan: "#3ee6ff"
    readonly property color amber: "#ffbe4d"
    readonly property color warm: "#ffc65a"
    readonly property color red: "#ff5470"
    property color accent: st === "thinking" ? amber : st === "offline" ? red : st === "listening" ? "#8af4ff" : cyan
    Behavior on accent { ColorAnimation { duration: 450 } }
    readonly property real level: Math.max(jarvis.micLevel, jarvis.voiceLevel)
    readonly property var stats: JSON.parse(jarvis.statsJson)
    readonly property var stateLabels: ({ boot: "INITIALIZING", standby: "STANDBY", listening: "LISTENING",
                                          thinking: "PROCESSING", speaking: "RESPONDING", offline: "MIC OFFLINE" })
    property var cpuHist: []
    onStatsChanged: { const h = cpuHist.slice(-59); h.push(stats.cpu || 0); cpuHist = h }

    // 전체 모드로 펼칠 때 구역이 위에서부터 차례로 떠오르는 연출
    property real enter: 0
    NumberAnimation { id: enterAnim; target: win; property: "enter"; from: 0; to: 1; duration: 1000 }
    Component.onCompleted: enterAnim.start()
    function ent(d) { const x = Math.max(0, Math.min(1, (enter - d) / 0.45)); return 1 - Math.pow(1 - x, 3) }

    function c(a) { return Qt.rgba(accent.r, accent.g, accent.b, a) }
    function rate(b) {
        if (b === undefined) return "-"
        if (b >= 1048576) return (b / 1048576).toFixed(1) + " MB/s"
        return Math.round(b / 1024) + " KB/s"
    }
    function pad(n) { return n < 10 ? "0" + n : "" + n }

    Item {
        id: root
        anchors.fill: parent
        opacity: (win.st === "standby" && !hover.hovered && !settings.open && confirm.cid === "") ? 0.84 : 1.0
        Behavior on opacity { NumberAnimation { duration: 500 } }
        HoverHandler { id: hover }

        // =====================================================================
        // 축소 모드 — 엠블럼
        // =====================================================================
        Item {
            id: compactView
            visible: win.compact
            anchors.fill: parent
            onVisibleChanged: if (visible) compactFade.restart()
            NumberAnimation on opacity { id: compactFade; from: 0; to: 1; duration: 450; easing.type: Easing.OutCubic }

            Emblem {
                id: emblem
                size: 214
                anchors.horizontalCenter: parent.horizontalCenter
                y: 0
                accent: win.accent
                level: win.level
                mode: win.st

                HoverHandler { cursorShape: Qt.PointingHandCursor }
                TapHandler { onTapped: jarvis.activate() }
                DragHandler { target: null; onActiveChanged: if (active) win.startSystemMove() }
            }

            Rectangle {   // 상태 글자 가독성용 알약
                anchors.centerIn: statusCol
                width: statusCol.width + 26; height: statusCol.height + 10
                radius: height / 2
                color: Qt.rgba(0.0, 0.03, 0.06, 0.72)
                border.color: win.c(0.35); border.width: 1
            }
            Column {
                id: statusCol
                anchors.horizontalCenter: parent.horizontalCenter
                y: emblem.y + emblem.height + 6
                spacing: 1
                Text {
                    anchors.horizontalCenter: parent.horizontalCenter
                    text: win.stateLabels[win.st] || ""
                    color: win.accent
                    font.family: "Bahnschrift"; font.pixelSize: 10; font.letterSpacing: 4; font.weight: Font.DemiBold
                }
                Text {
                    anchors.horizontalCenter: parent.horizontalCenter
                    width: Math.min(implicitWidth, 190)
                    horizontalAlignment: Text.AlignHCenter
                    elide: Text.ElideRight
                    text: jarvis.statusText
                    color: Qt.rgba(0.82, 0.96, 1, 0.78)
                    font.pixelSize: 11
                }
            }

            // 채팅 입력 — 음성 인식이 잘 안 될 때 글로 명령
            HoloPanel {
                id: miniBar
                x: 8; width: parent.width - 16; height: 30
                y: statusCol.y + statusCol.height + 12
                accent: win.accent
                fillAlpha: miniInput.activeFocus ? 0.9 : 0.72
                cut: 7

                Text {
                    id: miniCaret
                    anchors.verticalCenter: parent.verticalCenter
                    text: "›"
                    color: win.accent
                    font.family: "Bahnschrift"; font.pixelSize: 16; font.weight: Font.DemiBold
                }
                TextField {
                    id: miniInput
                    anchors.left: miniCaret.right; anchors.right: parent.right
                    anchors.verticalCenter: parent.verticalCenter
                    color: "#e9fcff"
                    font.pixelSize: 12
                    leftPadding: 5; rightPadding: 0; topPadding: 0; bottomPadding: 0
                    placeholderText: "명령 입력…  (Enter)"
                    placeholderTextColor: Qt.rgba(0.75, 0.93, 1, 0.42)
                    selectionColor: win.c(0.5)
                    background: Item {}
                    // 처리 중이라 받지 못한 명령은 지우지 않고 남겨 둔다
                    onAccepted: if (text.trim() !== "" && jarvis.submitText(text)) text = ""
                    Keys.onEscapePressed: { text = ""; jarvis.releaseFocus() }
                }
            }
            Rectangle {   // 마지막 대답 (글로 물었을 때 읽을 수 있게)
                visible: jarvis.replyText !== ""
                x: 8; width: parent.width - 16
                y: miniBar.y + miniBar.height + 5
                height: miniReply.height + 10
                radius: 4
                color: Qt.rgba(0.0, 0.03, 0.06, 0.74)
                border.color: win.c(0.25); border.width: 1
                Text {
                    id: miniReply
                    x: 8; y: 5
                    width: parent.width - 16
                    text: jarvis.replyText
                    wrapMode: Text.Wrap
                    maximumLineCount: 3
                    elide: Text.ElideRight
                    color: Qt.rgba(0.85, 0.97, 1, 0.92)
                    font.pixelSize: 11
                }
            }

            IconButton {
                visible: hover.hovered
                accent: win.accent
                glyph: ""; tip: "크게 보기"
                anchors.right: parent.right; anchors.top: parent.top
                onClicked: jarvis.setCompact(false)
            }
        }

        // =====================================================================
        // 전체 모드
        // =====================================================================
        Item {
            id: full
            visible: !win.compact
            anchors.fill: parent
            anchors.margins: 4
            onVisibleChanged: if (visible) enterAnim.restart()

            Chassis {
                anchors.fill: parent
                opacity: win.ent(0)
                accent: win.accent
                glowY: core.y + core3.y + core3.height / 2
            }

            // ------------------------- 헤더 -------------------------
            Item {
                id: header
                width: parent.width; height: 58
                opacity: win.ent(0.04)
                transform: Translate { y: (1 - win.ent(0.04)) * -10 }

                DragHandler { target: null; onActiveChanged: if (active) win.startSystemMove() }

                Column {
                    x: 28
                    anchors.verticalCenter: parent.verticalCenter
                    anchors.verticalCenterOffset: -2
                    spacing: 3
                    Text {
                        text: "J.A.R.V.I.S."
                        color: "#ecfdff"
                        font.family: "Bahnschrift"; font.pixelSize: 19; font.letterSpacing: 5; font.weight: Font.DemiBold
                        layer.enabled: true
                        layer.effect: MultiEffect {
                            shadowEnabled: true; shadowColor: win.accent; shadowBlur: 0.5; blurMax: 12
                            shadowHorizontalOffset: 0; shadowVerticalOffset: 0
                        }
                    }
                    Row {
                        spacing: 6
                        Rectangle {
                            width: 6; height: 6; radius: 3
                            anchors.verticalCenter: parent.verticalCenter
                            color: jarvis.hasApiKey ? "#53ffa8" : win.amber
                            SequentialAnimation on opacity {
                                loops: Animation.Infinite
                                NumberAnimation { to: 0.35; duration: 900 }
                                NumberAnimation { to: 1.0; duration: 900 }
                            }
                        }
                        Text {
                            text: jarvis.linkText
                            color: win.c(0.62)
                            font.family: "Bahnschrift"; font.pixelSize: 8; font.letterSpacing: 1.8
                        }
                    }
                }

                Column {
                    id: clock
                    anchors.right: buttons.left; anchors.rightMargin: 10
                    anchors.verticalCenter: parent.verticalCenter
                    anchors.verticalCenterOffset: -2
                    property string time: ""
                    property string date: ""
                    Timer {
                        interval: 500; running: true; repeat: true; triggeredOnStart: true
                        onTriggered: {
                            const d = new Date()
                            clock.time = win.pad(d.getHours()) + ":" + win.pad(d.getMinutes()) + ":" + win.pad(d.getSeconds())
                            clock.date = d.getFullYear() + "." + win.pad(d.getMonth() + 1) + "." + win.pad(d.getDate()) + "  "
                                         + ["SUN", "MON", "TUE", "WED", "THU", "FRI", "SAT"][d.getDay()]
                        }
                    }
                    Text { anchors.right: parent.right; text: clock.time; color: "#e6fbff"; font.family: "Bahnschrift"; font.pixelSize: 16; font.letterSpacing: 1.5 }
                    Text { anchors.right: parent.right; text: clock.date; color: win.c(0.6); font.family: "Bahnschrift"; font.pixelSize: 8; font.letterSpacing: 1.5 }
                }
                Row {
                    id: buttons
                    anchors.right: parent.right; anchors.rightMargin: 10
                    anchors.verticalCenter: parent.verticalCenter
                    anchors.verticalCenterOffset: -2
                    spacing: 0
                    IconButton { accent: win.accent; glyph: ""; tip: "작게 보기"; onClicked: jarvis.setCompact(true) }
                    IconButton { accent: win.accent; glyph: ""; tip: "설정"; onClicked: settings.show() }
                    IconButton { accent: win.accent; glyph: ""; tip: "트레이로 숨기기"; onClicked: jarvis.hideHud() }
                }

                // 눈금자 + 움직이는 스캐너
                Item {
                    id: ruler
                    x: 16; width: parent.width - 32
                    y: parent.height - 7; height: 7
                    Rectangle { width: parent.width; height: 1; color: win.c(0.28) }
                    Repeater {
                        model: Math.floor(ruler.width / 8) + 1
                        Rectangle {
                            required property int index
                            x: index * 8; y: 1
                            width: 1; height: index % 5 === 0 ? 5 : 2
                            color: win.c(index % 5 === 0 ? 0.5 : 0.22)
                        }
                    }
                    Rectangle {
                        width: 34; height: 2; y: -0.5
                        gradient: Gradient {
                            orientation: Gradient.Horizontal
                            GradientStop { position: 0.0; color: win.c(0.0) }
                            GradientStop { position: 0.5; color: win.accent }
                            GradientStop { position: 1.0; color: win.c(0.0) }
                        }
                        SequentialAnimation on x {
                            loops: Animation.Infinite
                            running: full.visible
                            NumberAnimation { from: -34; to: ruler.width; duration: 3600; easing.type: Easing.InOutSine }
                            PauseAnimation { duration: 1800 }
                        }
                    }
                }
            }

            // ------------------------- 코어 -------------------------
            Item {
                id: core
                y: 58
                width: parent.width; height: 270
                opacity: win.ent(0.1)
                transform: Translate { y: (1 - win.ent(0.1)) * 12 }

                Column {
                    x: 18; y: 10
                    spacing: 4
                    Text {
                        text: "VOICE CORE"
                        color: win.c(0.6); font.family: "Bahnschrift"; font.pixelSize: 8; font.letterSpacing: 2
                    }
                    Text {
                        text: "HOTKEY · " + jarvis.hotkeyText
                        color: win.c(0.42); font.family: "Bahnschrift"; font.pixelSize: 8; font.letterSpacing: 1.6
                    }
                }
                Column {
                    anchors.right: parent.right; anchors.rightMargin: 18; y: 10
                    spacing: 4
                    Text {
                        anchors.right: parent.right
                        text: "WAKE · " + (jarvis.wakeEnabled ? "ARMED" : "MANUAL")
                        color: jarvis.wakeEnabled ? win.c(0.7) : Qt.rgba(1, 0.42, 0.5, 0.75)
                        font.family: "Bahnschrift"; font.pixelSize: 8; font.letterSpacing: 2
                    }
                    Text {
                        anchors.right: parent.right
                        visible: jarvis.chatMode
                        text: "CHAT · LIVE"
                        color: win.warm
                        font.family: "Bahnschrift"; font.pixelSize: 8; font.letterSpacing: 2
                    }
                    Text {
                        anchors.right: parent.right
                        text: "AI · " + jarvis.modelName.replace("claude-", "").toUpperCase()
                        color: win.c(0.42); font.family: "Bahnschrift"; font.pixelSize: 8; font.letterSpacing: 1.6
                    }
                }

                ArcMeter {
                    anchors.centerIn: core3
                    radius: core3.size * 0.5 + 6
                    thickness: 5
                    startAngle: 130; span: 100
                    color: win.warm
                    level: jarvis.micLevel
                    label: "MIC"
                }
                ArcMeter {
                    anchors.centerIn: core3
                    radius: core3.size * 0.5 + 6
                    thickness: 5
                    startAngle: 50; span: -100
                    color: win.accent
                    level: jarvis.voiceLevel
                    label: "VOX"
                }

                Emblem {
                    id: core3
                    size: 212
                    anchors.horizontalCenter: parent.horizontalCenter
                    y: 14
                    accent: win.accent
                    level: win.level
                    mode: win.st
                    voiceBars: true

                    HoverHandler { cursorShape: Qt.PointingHandCursor }
                    TapHandler { onTapped: jarvis.activate() }
                }

                Column {
                    anchors.horizontalCenter: parent.horizontalCenter
                    y: core3.y + core3.height + 2
                    spacing: 2
                    Text {
                        anchors.horizontalCenter: parent.horizontalCenter
                        text: win.stateLabels[win.st] || ""
                        color: win.accent
                        font.family: "Bahnschrift"; font.pixelSize: 10; font.letterSpacing: 4; font.weight: Font.DemiBold
                    }
                    Text {
                        anchors.horizontalCenter: parent.horizontalCenter
                        width: Math.min(implicitWidth, 300)
                        horizontalAlignment: Text.AlignHCenter
                        elide: Text.ElideRight
                        text: jarvis.statusText
                        color: Qt.rgba(0.85, 0.97, 1, 0.82)
                        font.pixelSize: 12
                    }
                }
            }

            // ------------------------- 대화 -------------------------
            Item {
                id: talk
                x: 16; y: 334
                width: parent.width - 32; height: 112
                opacity: win.ent(0.2)
                transform: Translate { y: (1 - win.ent(0.2)) * 12 }

                property int shown: 0
                property string prev: ""
                Connections {
                    target: jarvis
                    // 대화 모드에서는 답이 조금씩 늘어나므로, 이어지는 글이면 처음부터 다시 타이핑하지 않는다
                    function onReplyTextChanged() {
                        const t = jarvis.replyText
                        if (talk.prev === "" || !t.startsWith(talk.prev)) talk.shown = 0
                        talk.prev = t
                        if (!typer.running) typer.start()
                    }
                }
                Timer {
                    id: typer
                    interval: 18; repeat: true
                    onTriggered: { talk.shown += 2; if (talk.shown >= jarvis.replyText.length) stop() }
                }

                SectionHead {
                    width: parent.width
                    accent: win.accent
                    title: "TRANSCRIPT"
                    tag: typer.running ? "RECEIVING" : ""
                }

                Column {
                    y: 22
                    width: parent.width
                    spacing: 8
                    Item {
                        width: parent.width; height: userTxt.height
                        visible: jarvis.userText !== ""
                        Text {
                            y: 2
                            text: "YOU"
                            color: win.c(0.55)
                            font.family: "Bahnschrift"; font.pixelSize: 8; font.letterSpacing: 1.6; font.weight: Font.DemiBold
                        }
                        Text {
                            id: userTxt
                            x: 50; width: parent.width - 50
                            text: jarvis.userText
                            color: "#9fd8ea"
                            font.pixelSize: 12
                            wrapMode: Text.WordWrap
                            maximumLineCount: 2
                            elide: Text.ElideRight
                        }
                    }
                    // 긴 답도 잘리지 않게: 칸을 넘으면 스크롤 (타이핑 중에는 마지막 줄을 따라감, 휠로 위로 올려 볼 수 있음)
                    Item {
                        width: parent.width
                        height: Math.max(30, talk.height - 22 - (jarvis.userText !== "" ? userTxt.height + 8 : 0))
                        Text {
                            y: 2
                            text: "JARVIS"
                            color: win.accent
                            font.family: "Bahnschrift"; font.pixelSize: 8; font.letterSpacing: 1.6; font.weight: Font.DemiBold
                        }
                        Rectangle { x: 42; width: 2; height: Math.min(parent.height, Math.max(replyTxt.height, 14)); color: win.c(0.45) }
                        Flickable {
                            id: replyFlick
                            x: 50; width: parent.width - 56; height: parent.height
                            clip: true
                            contentWidth: width; contentHeight: replyTxt.height
                            boundsBehavior: Flickable.StopAtBounds
                            interactive: contentHeight > height
                            Text {
                                id: replyTxt
                                width: replyFlick.width
                                text: jarvis.replyText !== "" ? jarvis.replyText.substring(0, talk.shown) + (typer.running ? "▌" : "")
                                                              : "말을 걸거나 아래 입력창에 명령을 입력하세요."
                                color: jarvis.replyText !== "" ? "#d7fbff" : Qt.rgba(0.8, 0.95, 1, 0.4)
                                font.pixelSize: 13
                                lineHeight: 1.15
                                wrapMode: Text.WordWrap
                                onHeightChanged: {
                                    if (talk.shown === 0) replyFlick.contentY = 0
                                    else if (typer.running) replyFlick.contentY = Math.max(0, height - replyFlick.height)
                                }
                            }
                        }
                        Rectangle {   // 스크롤 위치 표시
                            visible: replyFlick.contentHeight > replyFlick.height + 1
                            x: parent.width - 3; width: 2; radius: 1
                            height: Math.max(10, replyFlick.height * replyFlick.height / Math.max(1, replyFlick.contentHeight))
                            y: (replyFlick.height - height) * (replyFlick.contentY / Math.max(1, replyFlick.contentHeight - replyFlick.height))
                            color: win.c(0.6)
                        }
                    }
                }
            }

            // ------------------------- 시스템 진단 -------------------------
            Item {
                id: sys
                x: 16; y: 454
                width: parent.width - 32; height: 86
                opacity: win.ent(0.28)
                transform: Translate { y: (1 - win.ent(0.28)) * 12 }

                SectionHead {
                    width: parent.width
                    accent: win.accent
                    title: "SYSTEM DIAGNOSTICS"
                    tag: "NET  ↓ " + win.rate(win.stats.down) + "   ↑ " + win.rate(win.stats.up)
                    tagColor: Qt.rgba(0.88, 0.97, 1, 0.72)
                }

                Row {
                    y: 24
                    spacing: (parent.width - 4 * 86) / 3
                    StatBar { accent: win.accent; label: "CPU"; value: (win.stats.cpu || 0) / 100; valueText: Math.round(win.stats.cpu || 0) + "%" }
                    StatBar { accent: win.accent; label: "MEM"; value: (win.stats.ram || 0) / 100; valueText: Math.round(win.stats.ram || 0) + "%" }
                    StatBar { accent: win.accent; label: "DISK"; value: (win.stats.disk || 0) / 100; valueText: Math.round(win.stats.disk || 0) + "%" }
                    StatBar {
                        accent: win.accent
                        label: (win.stats.bat ?? -1) < 0 ? "POWER" : (win.stats.plugged ? "CHRG" : "BATT")
                        value: (win.stats.bat ?? -1) < 0 ? 1 : win.stats.bat / 100
                        valueText: (win.stats.bat ?? -1) < 0 ? "AC" : Math.round(win.stats.bat) + "%"
                        warn: (win.stats.bat ?? 100) >= 0 && (win.stats.bat ?? 100) < 20 && !win.stats.plugged
                    }
                }

                // CPU 사용률 흐름 (최근 60초)
                Item {
                    id: spark
                    y: 62
                    width: parent.width; height: 22
                    readonly property var pts: {
                        const h = win.cpuHist, n = h.length, w = spark.width, ht = spark.height
                        const step = w / 59
                        const out = []
                        for (let i = 0; i < n; i++)
                            out.push(Qt.point(w - (n - 1 - i) * step, ht - 1 - Math.min(100, h[i]) / 100 * (ht - 2)))
                        return out
                    }
                    Rectangle { width: parent.width; height: 1; y: parent.height - 1; color: win.c(0.18) }
                    Shape {
                        anchors.fill: parent
                        visible: spark.pts.length > 1
                        preferredRendererType: Shape.CurveRenderer
                        ShapePath {
                            strokeColor: "transparent"
                            fillGradient: LinearGradient {
                                x1: 0; y1: 0; x2: 0; y2: spark.height
                                GradientStop { position: 0.0; color: win.c(0.28) }
                                GradientStop { position: 1.0; color: win.c(0.0) }
                            }
                            PathPolyline {
                                path: spark.pts.length > 1
                                      ? [Qt.point(spark.pts[0].x, spark.height)].concat(spark.pts, [Qt.point(spark.width, spark.height)])
                                      : []
                            }
                        }
                        ShapePath {
                            strokeColor: win.accent; strokeWidth: 1.3; fillColor: "transparent"
                            joinStyle: ShapePath.RoundJoin
                            PathPolyline { path: spark.pts }
                        }
                    }
                    Text {
                        x: 2; y: 1
                        text: "CPU · 60s"
                        color: win.c(0.45)
                        font.family: "Bahnschrift"; font.pixelSize: 7; font.letterSpacing: 1.5
                    }
                }
            }

            // ------------------------- 작업 로그 -------------------------
            Item {
                id: log
                x: 16; y: 548
                width: parent.width - 32; height: 102
                opacity: win.ent(0.36)
                transform: Translate { y: (1 - win.ent(0.36)) * 12 }

                SectionHead {
                    width: parent.width
                    accent: win.accent
                    title: "ACTIVITY LOG"
                    tag: actions.count > 0 ? actions.count + " OPS" : ""
                }

                ListModel { id: actions }
                ListView {
                    id: list
                    y: 20
                    width: parent.width; height: parent.height - 20
                    clip: true
                    model: actions
                    boundsBehavior: Flickable.StopAtBounds
                    delegate: Item {
                        required property string label
                        required property string status
                        required property string time
                        required property string detail
                        readonly property color sc: status === "ok" ? win.cyan : status === "error" ? "#ff6b81" : win.amber
                        width: list.width; height: 20

                        Text {
                            width: 50
                            anchors.verticalCenter: parent.verticalCenter
                            text: time
                            color: win.c(0.5)
                            font.family: "Bahnschrift"; font.pixelSize: 9; font.letterSpacing: 1
                        }
                        Rectangle { x: 57; width: 1; height: parent.height; color: win.c(0.18) }
                        Rectangle {
                            x: 54; width: 7; height: 7
                            radius: status === "run" ? 0 : 3.5
                            rotation: status === "run" ? 45 : 0
                            anchors.verticalCenter: parent.verticalCenter
                            color: status === "ok" ? "transparent" : sc
                            border.color: sc; border.width: 1.4
                            SequentialAnimation on opacity {
                                running: status === "run"; loops: Animation.Infinite
                                NumberAnimation { to: 0.2; duration: 400 }
                                NumberAnimation { to: 1; duration: 400 }
                            }
                        }
                        Text {
                            x: 70; width: parent.width - 70
                            anchors.verticalCenter: parent.verticalCenter
                            text: label
                            elide: Text.ElideRight
                            color: status === "error" ? "#ffb3bf" : "#cdeff8"
                            font.pixelSize: 11
                            HoverHandler { id: lh }
                            ToolTip.visible: lh.hovered && detail !== ""
                            ToolTip.text: detail
                            ToolTip.delay: 400
                        }
                    }
                }
                Text {
                    visible: actions.count === 0
                    anchors.horizontalCenter: parent.horizontalCenter
                    y: 20 + (parent.height - 20) / 2 - height / 2
                    text: "실행한 작업이 여기에 표시됩니다"
                    color: Qt.rgba(0.8, 0.95, 1, 0.35)
                    font.pixelSize: 11
                }
            }

            // ------------------------- 입력 -------------------------
            HoloPanel {
                id: inputBar
                x: 16; y: 660
                width: parent.width - 32; height: 40
                opacity: win.ent(0.44)
                transform: Translate { y: (1 - win.ent(0.44)) * 12 }
                accent: win.accent
                fillAlpha: 0.55
                cut: 8

                RowLayout {
                    anchors.fill: parent
                    anchors.margins: -5
                    spacing: 2
                    Item {
                        Layout.preferredWidth: 28; Layout.preferredHeight: 28
                        IconButton {
                            anchors.fill: parent
                            accent: win.accent
                            glyph: ""
                            active: jarvis.wakeEnabled
                            tip: jarvis.wakeEnabled ? "호출어 대기 끄기 (“자비스”)" : "호출어 대기 켜기 (“자비스”)"
                            onClicked: jarvis.setWake(!jarvis.wakeEnabled)
                        }
                        Rectangle {
                            visible: !jarvis.wakeEnabled
                            anchors.centerIn: parent
                            width: 18; height: 1.6; rotation: -45
                            color: "#ff6b81"
                        }
                    }
                    IconButton {
                        Layout.preferredWidth: 28; Layout.preferredHeight: 28
                        accent: jarvis.chatMode ? win.warm : win.accent
                        glyph: ""
                        active: jarvis.chatMode
                        tip: jarvis.chatMode ? "자유 대화 모드 끝내기" : "자유 대화 모드 (호출어 없이 AI 와 대화)"
                        onClicked: jarvis.toggleChat()
                    }
                    Text {
                        Layout.leftMargin: 4
                        text: "›"
                        color: win.accent
                        font.family: "Bahnschrift"; font.pixelSize: 18; font.weight: Font.DemiBold
                    }
                    TextField {
                        id: input
                        Layout.fillWidth: true
                        color: "#e9fcff"
                        font.pixelSize: 13
                        leftPadding: 4
                        placeholderText: "명령 입력…  (" + jarvis.hotkeyText + " 으로 음성 호출)"
                        placeholderTextColor: Qt.rgba(0.75, 0.93, 1, 0.38)
                        selectionColor: win.c(0.5)
                        background: Item {}
                        onAccepted: { if (text.trim() !== "") { jarvis.submitText(text); text = "" } }
                    }
                    IconButton {
                        Layout.preferredWidth: 28; Layout.preferredHeight: 28
                        accent: win.accent
                        glyph: ""
                        tip: "보내기"
                        onClicked: input.accepted()
                    }
                }
            }

            // ------------------------- 스캔라인 -------------------------
            Item {
                anchors.fill: parent
                clip: true
                Rectangle {
                    width: parent.width; height: 70
                    gradient: Gradient {
                        GradientStop { position: 0.0; color: "transparent" }
                        GradientStop { position: 0.5; color: win.c(0.045) }
                        GradientStop { position: 1.0; color: "transparent" }
                    }
                    SequentialAnimation on y {
                        loops: Animation.Infinite
                        running: full.visible
                        NumberAnimation { from: -70; to: full.height; duration: 5200; easing.type: Easing.InOutSine }
                        PauseAnimation { duration: 2600 }
                    }
                }
            }
        }

        // ===================== 알림 =====================
        Rectangle {
            id: toast
            property string level: "info"
            function show(lv, msg) { level = lv; txt.text = msg; opacity = 1; hideT.restart() }
            anchors.horizontalCenter: parent.horizontalCenter
            y: win.compact ? 6 : 70
            width: Math.min(parent.width - 30, txt.implicitWidth + 28)
            height: txt.implicitHeight + 14
            radius: 3
            opacity: 0
            visible: opacity > 0
            Behavior on opacity { NumberAnimation { duration: 250 } }
            readonly property color tc: level === "error" ? "#ff6b81" : level === "warn" ? win.amber : win.cyan
            color: Qt.rgba(0.01, 0.06, 0.09, 0.94)
            border.color: tc
            Rectangle { width: 3; height: parent.height; color: toast.tc }
            Text {
                id: txt
                anchors.centerIn: parent
                width: Math.min(implicitWidth, toast.parent.width - 58)
                wrapMode: Text.WordWrap
                horizontalAlignment: Text.AlignHCenter
                color: "#eafcff"
                font.pixelSize: 12
            }
            Timer { id: hideT; interval: 4200; onTriggered: toast.opacity = 0 }
            TapHandler { onTapped: toast.opacity = 0 }
        }

        ConfirmCard {
            id: confirm
            anchors.fill: parent
            onAnswered: (id, ok) => jarvis.answerConfirm(id, ok)
        }

        SettingsPanel {
            id: settings
            objectName: "settings"
            anchors.fill: parent
            accent: win.cyan
        }
    }

    Connections {
        target: jarvis
        function onActionEvent(id, label, status, detail) {
            for (let i = 0; i < actions.count; i++) {
                if (actions.get(i).aid === id) {
                    actions.setProperty(i, "status", status)
                    actions.setProperty(i, "detail", detail)
                    return
                }
            }
            const d = new Date()
            actions.insert(0, { aid: id, label: label, status: status, detail: detail,
                                time: win.pad(d.getHours()) + ":" + win.pad(d.getMinutes()) + ":" + win.pad(d.getSeconds()) })
            while (actions.count > 40) actions.remove(actions.count - 1)
            list.positionViewAtBeginning()
        }
        function onConfirmRequest(id, title, detail) {
            if (win.compact) jarvis.setCompact(false)
            confirm.show(id, title, detail)
        }
        function onConfirmClosed(id) { confirm.close(id) }
        function onToast(level, text) { toast.show(level, text) }
    }
}
