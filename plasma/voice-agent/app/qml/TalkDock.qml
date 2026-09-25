// SPDX-License-Identifier: GPL-2.0-or-later
// The bottom of the app's pages (docs/59): the light capsule is the talk control, as in
// the Home button's overlay (docs/67). What is going on is written above it; stop on
// its right while something runs. Hold to talk; a tap listens hands-free; lifting the
// finger far from the capsule drops what was said.
import QtQuick

Item {
    id: dock
    property string label
    property string hint                     // a second, quieter line
    property bool glowing: false
    property string mode: "idle"             // idle | work | speak; listen hides the capsule (the light is up)
    property real time: 0
    property bool canTalk: true
    property bool showStop: false
    signal talkPressed()
    signal talkReleased(bool inside)
    signal stopClicked()
    implicitHeight: column.implicitHeight + 40

    // Lets the list fade out above the control; gone while the light is up, not to cover it.
    Rectangle {
        anchors.fill: parent
        anchors.topMargin: -24
        opacity: dock.mode === "listen" ? 0 : 1
        Behavior on opacity { NumberAnimation { duration: 200 } }
        gradient: Gradient {
            GradientStop { position: 0.0; color: Qt.rgba(0.03, 0.035, 0.05, 0) }
            GradientStop { position: 0.35; color: Qt.rgba(0.03, 0.035, 0.05, 0.85) }
        }
    }

    Column {
        id: column
        anchors { left: parent.left; right: parent.right; top: parent.top; topMargin: 12 }
        spacing: 12
        Column {
            anchors.horizontalCenter: parent.horizontalCenter
            spacing: 4
            GlowLabel {
                anchors.horizontalCenter: parent.horizontalCenter
                text: dock.label
                time: dock.time
                glowing: dock.glowing
                font.pixelSize: dock.glowing && dock.mode === "listen" ? 15 : 13
                font.weight: dock.glowing ? Font.Medium : Font.Normal
            }
            Text {
                anchors.horizontalCenter: parent.horizontalCenter
                visible: text !== ""
                text: dock.hint
                color: Qt.rgba(1, 1, 1, 0.72)
                font.pixelSize: 13
            }
        }
        Item {
            width: Math.min(parent.width - 48, 420)
            height: 56
            anchors.horizontalCenter: parent.horizontalCenter

            LightPill {
                id: pill
                anchors.centerIn: parent
                time: dock.time
                mode: dock.mode === "listen" ? "idle" : dock.mode
                opacity: !dock.canTalk ? 0.35 : dock.mode === "listen" ? 0 : 1
                Behavior on opacity { NumberAnimation { duration: 200 } }
                // Kept (only faded) while listening: the finger holding it keeps its press.
                MouseArea {
                    anchors.fill: parent
                    anchors.margins: -10
                    enabled: dock.canTalk
                    Accessible.role: Accessible.Button
                    Accessible.name: "按住说话"
                    onPressed: dock.talkPressed()
                    onReleased: mouse => {
                        const far = 64
                        dock.talkReleased(mouse.x > -far && mouse.x < width + far && mouse.y > -far && mouse.y < height + far)
                    }
                    onCanceled: dock.talkReleased(true)
                }
            }

            GlassButton {
                anchors { right: parent.right; verticalCenter: parent.verticalCenter }
                visible: dock.showStop
                iconName: "media-playback-stop-symbolic"
                label: "停止"
                onClicked: dock.stopClicked()
            }
        }
    }
}
