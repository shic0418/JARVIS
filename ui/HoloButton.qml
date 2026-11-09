// 텍스트 버튼
import QtQuick

Item {
    id: b
    property color accent: "#3ee6ff"
    property string text: ""
    property bool primary: false
    signal clicked()
    implicitWidth: Math.max(84, label.implicitWidth + 28)
    implicitHeight: 32

    Rectangle {
        anchors.fill: parent
        radius: 3
        color: Qt.rgba(b.accent.r, b.accent.g, b.accent.b, b.primary ? (hover.hovered ? 0.42 : 0.28) : (hover.hovered ? 0.16 : 0.06))
        border.color: Qt.rgba(b.accent.r, b.accent.g, b.accent.b, b.primary ? 0.95 : 0.45)
        border.width: 1
    }
    Text {
        id: label
        anchors.centerIn: parent
        text: b.text
        color: b.primary ? "#ffffff" : Qt.rgba(b.accent.r, b.accent.g, b.accent.b, 0.95)
        font.family: "Bahnschrift"
        font.pixelSize: 12
        font.letterSpacing: 1.5
        font.weight: Font.DemiBold
    }
    HoverHandler { id: hover; cursorShape: Qt.PointingHandCursor }
    TapHandler { onTapped: b.clicked() }
}
