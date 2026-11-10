// 전체 모드 본체 — 모서리를 깎은 하나의 판 + 청사진 격자
import QtQuick
import QtQuick.Shapes

Item {
    id: ch
    property color accent: "#3ee6ff"
    property real cut: 20        // 왼쪽 위 · 오른쪽 아래 (크게 깎음)
    property real cut2: 6        // 나머지 두 모서리
    property real glowY: 190     // 코어 쪽을 살짝 밝게

    function c(a) { return Qt.rgba(ch.accent.r, ch.accent.g, ch.accent.b, a) }
    readonly property var pts: [
        Qt.point(cut, 0.5), Qt.point(width - cut2, 0.5), Qt.point(width - 0.5, cut2),
        Qt.point(width - 0.5, height - cut), Qt.point(width - cut, height - 0.5),
        Qt.point(cut2, height - 0.5), Qt.point(0.5, height - cut2), Qt.point(0.5, cut), Qt.point(cut, 0.5)
    ]

    onGlowYChanged: bg.requestPaint()

    // 바탕 + 격자 (색이 고정이라 크기가 바뀔 때만 다시 그림)
    Canvas {
        id: bg
        anchors.fill: parent
        onWidthChanged: requestPaint()
        onHeightChanged: requestPaint()
        onPaint: {
            const g = getContext("2d")
            const w = width, h = height
            g.reset()
            g.beginPath()
            const p = ch.pts
            g.moveTo(p[0].x, p[0].y)
            for (let i = 1; i < p.length; i++) g.lineTo(p[i].x, p[i].y)
            g.closePath()

            const lg = g.createLinearGradient(0, 0, 0, h)
            lg.addColorStop(0, "rgba(5, 20, 31, 0.93)")
            lg.addColorStop(0.5, "rgba(3, 13, 21, 0.93)")
            lg.addColorStop(1, "rgba(2, 9, 15, 0.95)")
            g.fillStyle = lg
            g.fill()

            g.save()
            g.clip()
            const rg = g.createRadialGradient(w / 2, ch.glowY, 0, w / 2, ch.glowY, w * 0.62)
            rg.addColorStop(0, "rgba(62, 230, 255, 0.10)")
            rg.addColorStop(1, "rgba(62, 230, 255, 0)")
            g.fillStyle = rg
            g.fillRect(0, 0, w, h)

            g.lineWidth = 1
            g.strokeStyle = "rgba(62, 230, 255, 0.035)"
            g.beginPath()
            for (let x = 12; x < w; x += 12) { g.moveTo(x + 0.5, 0); g.lineTo(x + 0.5, h) }
            for (let y = 12; y < h; y += 12) { g.moveTo(0, y + 0.5); g.lineTo(w, y + 0.5) }
            g.stroke()
            g.strokeStyle = "rgba(62, 230, 255, 0.06)"
            g.beginPath()
            for (let x = 48; x < w; x += 48) { g.moveTo(x + 0.5, 0); g.lineTo(x + 0.5, h) }
            for (let y = 48; y < h; y += 48) { g.moveTo(0, y + 0.5); g.lineTo(w, y + 0.5) }
            g.stroke()
            g.restore()
        }
    }

    Shape {
        anchors.fill: parent
        preferredRendererType: Shape.CurveRenderer
        // 테두리 (상태색)
        ShapePath {
            strokeColor: ch.c(0.4); strokeWidth: 1; fillColor: "transparent"
            PathPolyline { path: ch.pts }
        }
        // 깎인 모서리 강조
        ShapePath {
            strokeColor: ch.accent; strokeWidth: 2.4; fillColor: "transparent"
            capStyle: ShapePath.FlatCap; joinStyle: ShapePath.MiterJoin
            PathMove { x: 1; y: ch.cut + 34 }
            PathLine { x: 1; y: ch.cut }
            PathLine { x: ch.cut; y: 1 }
            PathLine { x: ch.cut + 52; y: 1 }
            PathMove { x: ch.width - 1; y: ch.height - ch.cut - 34 }
            PathLine { x: ch.width - 1; y: ch.height - ch.cut }
            PathLine { x: ch.width - ch.cut; y: ch.height - 1 }
            PathLine { x: ch.width - ch.cut - 52; y: ch.height - 1 }
        }
        // 옆면 눈금 (엠블럼의 측면 장식)
        ShapePath {
            strokeColor: ch.c(0.75); strokeWidth: 2; fillColor: "transparent"; capStyle: ShapePath.FlatCap
            PathMove { x: ch.width - 1; y: ch.glowY - 34 }
            PathLine { x: ch.width - 1; y: ch.glowY - 22 }
            PathMove { x: ch.width - 1; y: ch.glowY - 16 }
            PathLine { x: ch.width - 1; y: ch.glowY + 16 }
            PathMove { x: ch.width - 1; y: ch.glowY + 22 }
            PathLine { x: ch.width - 1; y: ch.glowY + 26 }
            PathMove { x: 1; y: ch.glowY - 8 }
            PathLine { x: 1; y: ch.glowY + 24 }
        }
    }
}
