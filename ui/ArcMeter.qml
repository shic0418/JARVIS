// 원호 레벨 미터 — 코어 양옆을 감싸는 분절 호 (MIC / VOX)
// 이 Item 의 중심을 코어 중심에 맞춰 배치한다.
import QtQuick
import QtQuick.Shapes

Item {
    id: m
    property color color: "#3ee6ff"
    property real level: 0           // 0..1
    property real radius: 110
    property real startAngle: 130    // 아래쪽 끝 (도, 3시 방향에서 시계 방향)
    property real span: 100          // + 시계 방향 / - 반시계 방향으로 위쪽 끝까지
    property int count: 16
    property real thickness: 6
    property string label: ""
    width: 2 * (radius + thickness + 24); height: width

    readonly property real cx: width / 2
    readonly property real cy: height / 2
    readonly property real period: 2 * Math.PI * radius * (Math.abs(span) / count) / 360 / thickness
    property real shown: 0
    Behavior on shown { NumberAnimation { duration: 90 } }
    onLevelChanged: shown = Math.max(0, Math.min(1, level))
    readonly property int lit: Math.round(shown * count)

    function rgba(a) { return Qt.rgba(m.color.r, m.color.g, m.color.b, a) }

    Shape {
        anchors.fill: parent
        preferredRendererType: Shape.CurveRenderer
        ShapePath {   // 바깥 안내선
            strokeColor: m.rgba(0.28); strokeWidth: 1; fillColor: "transparent"
            PathAngleArc {
                centerX: m.cx; centerY: m.cy
                radiusX: m.radius + m.thickness / 2 + 4; radiusY: m.radius + m.thickness / 2 + 4
                startAngle: m.startAngle - Math.sign(m.span) * 4; sweepAngle: m.span + Math.sign(m.span) * 8
            }
        }
        ShapePath {   // 꺼진 칸
            strokeColor: m.rgba(0.14); strokeWidth: m.thickness; fillColor: "transparent"; capStyle: ShapePath.FlatCap
            strokeStyle: ShapePath.DashLine
            dashPattern: [m.period * 0.7, m.period * 0.3]
            PathAngleArc { centerX: m.cx; centerY: m.cy; radiusX: m.radius; radiusY: m.radius; startAngle: m.startAngle; sweepAngle: m.span }
        }
        ShapePath {   // 켜진 칸
            strokeColor: m.color; strokeWidth: m.thickness; fillColor: "transparent"; capStyle: ShapePath.FlatCap
            strokeStyle: ShapePath.DashLine
            dashPattern: [m.period * 0.7, m.period * 0.3]
            PathAngleArc { centerX: m.cx; centerY: m.cy; radiusX: m.radius; radiusY: m.radius; startAngle: m.startAngle; sweepAngle: m.span * m.lit / m.count }
        }
    }

    Text {
        readonly property real a: (m.startAngle + m.span + Math.sign(m.span) * 11) * Math.PI / 180
        x: m.cx + Math.cos(a) * (m.radius + 4) - width / 2
        y: m.cy + Math.sin(a) * (m.radius + 4) - height / 2
        text: m.label
        color: m.rgba(0.8)
        font.family: "Bahnschrift"; font.pixelSize: 8; font.letterSpacing: 1.6; font.weight: Font.DemiBold
    }
}
