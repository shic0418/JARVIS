// 구역 제목줄:  ◆ TITLE ────────────── TAG
import QtQuick

Item {
    id: s
    property color accent: "#3ee6ff"
    property string title: ""
    property string tag: ""
    property color tagColor: c(0.55)
    height: 14

    function c(a) { return Qt.rgba(s.accent.r, s.accent.g, s.accent.b, a) }

    Rectangle {
        id: dia
        x: 1
        width: 5; height: 5
        rotation: 45
        anchors.verticalCenter: parent.verticalCenter
        color: s.accent
    }
    Text {
        id: tt
        x: 13
        anchors.verticalCenter: parent.verticalCenter
        text: s.title
        color: s.c(0.9)
        font.family: "Bahnschrift"; font.pixelSize: 9; font.letterSpacing: 2.4; font.weight: Font.DemiBold
    }
    Text {
        id: tg
        anchors.right: parent.right
        anchors.verticalCenter: parent.verticalCenter
        text: s.tag
        color: s.tagColor
        font.family: "Bahnschrift"; font.pixelSize: 9; font.letterSpacing: 1.5
    }
    Rectangle {
        anchors.left: tt.right; anchors.leftMargin: 8
        anchors.right: tg.left; anchors.rightMargin: s.tag !== "" ? 8 : 0
        anchors.verticalCenter: parent.verticalCenter
        height: 1
        gradient: Gradient {
            orientation: Gradient.Horizontal
            GradientStop { position: 0.0; color: s.c(0.4) }
            GradientStop { position: 1.0; color: s.c(0.06) }
        }
    }
}
