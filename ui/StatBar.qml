// 진단 수치 한 칸 — 라벨 · 값 + 분절 막대 (CPU / MEM / DISK / BATT)
import QtQuick

Item {
    id: sb
    property color accent: "#3ee6ff"
    property string label: ""
    property real value: 0            // 0..1
    property string valueText: ""
    property bool warn: value > 0.85
    property int count: 10
    width: 86; height: 32

    readonly property color col: warn ? "#ff6b81" : accent
    property real shown: value
    Behavior on shown { NumberAnimation { duration: 600; easing.type: Easing.OutCubic } }

    Text {
        anchors.left: parent.left
        anchors.baseline: val.baseline
        text: sb.label
        color: Qt.rgba(sb.accent.r, sb.accent.g, sb.accent.b, 0.7)
        font.family: "Bahnschrift"; font.pixelSize: 9; font.letterSpacing: 1.8
    }
    Text {
        id: val
        anchors.right: parent.right
        y: -3
        text: sb.valueText
        color: sb.warn ? "#ffb3bf" : "#e9fcff"
        font.family: "Bahnschrift"; font.pixelSize: 15; font.weight: Font.DemiBold
    }
    Row {
        y: 22
        spacing: 2
        Repeater {
            model: sb.count
            Rectangle {
                required property int index
                readonly property real lit: Math.max(0, Math.min(1, sb.shown * sb.count - index))
                width: (sb.width - (sb.count - 1) * 2) / sb.count
                height: 6
                color: sb.col
                opacity: 0.14 + 0.86 * lit
            }
        }
    }
}
