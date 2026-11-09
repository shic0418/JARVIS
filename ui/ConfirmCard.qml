// 위험 명령 승인 카드
import QtQuick

Item {
    id: cc
    property string cid: ""
    property string title: ""
    property string detail: ""
    readonly property color amber: "#ffbe4d"
    signal answered(string cid, bool approved)
    visible: opacity > 0
    opacity: cid !== "" ? 1 : 0
    Behavior on opacity { NumberAnimation { duration: 220 } }

    function show(id, t, d) { cid = id; title = t; detail = d; countdown.restart() }
    function close(id) { if (id === cid) cid = "" }

    Rectangle { anchors.fill: parent; color: Qt.rgba(0, 0.02, 0.04, 0.55); radius: 6 }
    MouseArea { anchors.fill: parent }   // 뒤쪽 클릭 차단

    HoloPanel {
        id: card
        accent: cc.amber
        title: "AUTHORIZATION REQUIRED"
        tag: "45s"
        width: parent.width - 36
        height: col.implicitHeight + 50
        anchors.centerIn: parent
        fillAlpha: 0.9
        scale: cc.cid !== "" ? 1 : 0.92
        Behavior on scale { NumberAnimation { duration: 220; easing.type: Easing.OutBack } }

        Column {
            id: col
            width: parent.width
            spacing: 10
            Text {
                text: "⚠  " + cc.title
                color: "#fff1d6"
                font.family: "Bahnschrift"; font.pixelSize: 16; font.weight: Font.DemiBold
            }
            Rectangle {
                width: parent.width
                height: Math.min(det.implicitHeight + 16, 150)
                color: Qt.rgba(0, 0, 0, 0.35)
                border.color: Qt.rgba(1, 0.75, 0.3, 0.25)
                radius: 3
                clip: true
                Text {
                    id: det
                    x: 8; y: 8
                    width: parent.width - 16
                    text: cc.detail
                    wrapMode: Text.WrapAnywhere
                    color: "#ffe2b0"
                    font.family: "Consolas"; font.pixelSize: 11
                }
            }
            Text {
                text: "버튼을 누르거나 “승인” / “취소” 라고 말씀하세요"
                color: Qt.rgba(1, 0.85, 0.6, 0.7)
                font.pixelSize: 11
            }
            Rectangle {
                width: parent.width; height: 2
                color: Qt.rgba(1, 0.75, 0.3, 0.15)
                Rectangle {
                    id: bar
                    height: parent.height
                    color: cc.amber
                    width: parent.width
                    NumberAnimation on width { id: countdown; from: card.width - 20; to: 0; duration: 45000; running: false }
                }
            }
            Row {
                spacing: 10
                anchors.right: parent.right
                HoloButton { text: "거부"; accent: "#ff6b81"; onClicked: cc.answered(cc.cid, false) }
                HoloButton { text: "승인"; accent: cc.amber; primary: true; onClicked: cc.answered(cc.cid, true) }
            }
        }
    }
}
