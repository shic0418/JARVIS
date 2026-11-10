// 반투명 홀로그램 패널 — 모서리를 깎은 판 + 상단 라벨 (설정 · 승인 카드 · 입력창)
import QtQuick
import QtQuick.Shapes

Item {
    id: p
    property color accent: "#3ee6ff"
    property string title: ""
    property string tag: ""
    property real fillAlpha: 0.66
    property real cut: 10
    default property alias content: inner.data

    function c(a) { return Qt.rgba(p.accent.r, p.accent.g, p.accent.b, a) }
    readonly property var pts: [
        Qt.point(p.cut, 0.5), Qt.point(p.width - 0.5, 0.5), Qt.point(p.width - 0.5, p.height - p.cut),
        Qt.point(p.width - p.cut, p.height - 0.5), Qt.point(0.5, p.height - 0.5), Qt.point(0.5, p.cut), Qt.point(p.cut, 0.5)
    ]

    Shape {
        anchors.fill: parent
        preferredRendererType: Shape.CurveRenderer
        ShapePath {
            strokeColor: "transparent"
            fillColor: Qt.rgba(0.012, 0.055, 0.085, p.fillAlpha)
            PathPolyline { path: p.pts }
        }
        ShapePath {
            strokeColor: p.c(0.3); strokeWidth: 1
            fillGradient: LinearGradient {
                x1: 0; y1: 0; x2: 0; y2: p.height
                GradientStop { position: 0.0; color: p.c(0.10) }
                GradientStop { position: 0.35; color: p.c(0.0) }
                GradientStop { position: 1.0; color: p.c(0.04) }
            }
            PathPolyline { path: p.pts }
        }
        ShapePath {   // 깎인 모서리 강조
            strokeColor: p.accent; strokeWidth: 2; fillColor: "transparent"
            capStyle: ShapePath.FlatCap; joinStyle: ShapePath.MiterJoin
            PathMove { x: 1; y: p.cut + 14 }
            PathLine { x: 1; y: p.cut }
            PathLine { x: p.cut; y: 1 }
            PathLine { x: p.cut + 22; y: 1 }
            PathMove { x: p.width - 1; y: p.height - p.cut - 14 }
            PathLine { x: p.width - 1; y: p.height - p.cut }
            PathLine { x: p.width - p.cut; y: p.height - 1 }
            PathLine { x: p.width - p.cut - 22; y: p.height - 1 }
        }
    }

    // 상단 라벨
    Row {
        visible: p.title !== ""
        x: 12; y: 8
        spacing: 7
        Rectangle { width: 5; height: 5; rotation: 45; color: p.accent; anchors.verticalCenter: parent.verticalCenter }
        Text {
            text: p.title
            color: p.c(0.9)
            font.family: "Bahnschrift"
            font.pixelSize: 9
            font.letterSpacing: 2.4
            font.weight: Font.DemiBold
        }
    }
    Text {
        visible: p.tag !== ""
        text: p.tag
        anchors.right: parent.right; anchors.rightMargin: 12
        y: 8
        color: p.c(0.5)
        font.family: "Bahnschrift"
        font.pixelSize: 9
        font.letterSpacing: 1.5
    }

    Item {
        id: inner
        anchors.fill: parent
        anchors.margins: 10
        anchors.topMargin: p.title !== "" ? 24 : 10
    }
}
