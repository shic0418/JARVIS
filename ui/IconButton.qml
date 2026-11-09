// 아이콘 버튼 (Segoe MDL2 Assets 글리프)
import QtQuick
import QtQuick.Controls.Basic

Item {
    id: b
    property color accent: "#3ee6ff"
    property string glyph: ""
    property string tip: ""
    property bool active: false
    property real glyphSize: 13
    signal clicked()
    width: 28; height: 28

    Rectangle {
        anchors.fill: parent
        radius: width / 2
        color: Qt.rgba(b.accent.r, b.accent.g, b.accent.b, hover.hovered ? 0.18 : b.active ? 0.12 : 0.0)
        border.color: Qt.rgba(b.accent.r, b.accent.g, b.accent.b, hover.hovered || b.active ? 0.6 : 0.0)
        border.width: 1
        Behavior on color { ColorAnimation { duration: 150 } }
    }
    Text {
        anchors.centerIn: parent
        text: b.glyph
        font.family: "Segoe MDL2 Assets"
        font.pixelSize: b.glyphSize
        color: hover.hovered || b.active ? "#ffffff" : Qt.rgba(b.accent.r, b.accent.g, b.accent.b, 0.85)
    }
    HoverHandler { id: hover; cursorShape: Qt.PointingHandCursor }
    TapHandler { onTapped: b.clicked() }
    ToolTip.visible: hover.hovered && b.tip !== ""
    ToolTip.text: b.tip
    ToolTip.delay: 500
}
