// SPDX-License-Identifier: GPL-2.0-or-later
// An entry of the conversation in the overlay (docs/67), on its dark or light backdrop.
// The panel shows the latest turn: what the user said as a caption above the answer in
// large type. Pulled up, it shows the whole conversation: the user's words in a glass
// bubble, the assistant's as plain text. An agent turn is one line saying what it does.
import QtQuick
import QtQuick.Controls as QQC2
import org.kde.kirigami as Kirigami

Item {
    id: entry
    required property int index
    required property string kind
    required property string role
    required property string text
    required property string status
    required property real started
    required property real finished
    required property var steps
    property int from: 0              // entries before it are not shown
    property bool compact: true       // the latest turn only (not pulled up)
    readonly property bool shown: index >= from
    visible: shown
    width: ListView.view.width
    implicitHeight: shown ? loader.implicitHeight + Kirigami.Units.largeSpacing : 0

    readonly property bool mine: role === "user" && (kind === "message" || kind === "live-user")
    readonly property color ink: Style.ink

    Loader {
        id: loader
        active: entry.shown
        x: entry.mine && !entry.compact ? entry.width - width : 0
        width: entry.mine && !entry.compact ? Math.min(implicitWidth, entry.width * 0.8) : entry.width
        sourceComponent: entry.kind === "work" ? work
                       : entry.kind === "error" || entry.kind === "marker" || entry.kind === "approval" ? note
                       : entry.kind === "call" ? call
                       : entry.mine ? (entry.compact ? caption : bubble) : answer
    }

    Component {
        id: caption
        Text {
            text: entry.text
            wrapMode: Text.Wrap
            color: Style.dim
            font.pixelSize: 14
        }
    }

    Component {
        id: bubble
        Rectangle {
            readonly property real padX: 16
            implicitWidth: Math.min(measure.implicitWidth, entry.width * 0.8 - padX * 2) + padX * 2
            implicitHeight: label.implicitHeight + 20
            radius: 20
            color: Style.glass
            opacity: entry.kind.startsWith("live") ? 0.72 : 1
            Text {
                id: measure
                visible: false
                text: entry.text
                font: label.font
            }
            Text {
                id: label
                x: parent.padX
                anchors.verticalCenter: parent.verticalCenter
                width: parent.width - parent.padX * 2
                text: entry.text
                wrapMode: Text.Wrap
                color: entry.ink
                font.pixelSize: 16
                lineHeight: 1.1
            }
        }
    }

    Component {
        id: answer
        Text {
            text: entry.text
            wrapMode: Text.Wrap
            color: entry.ink
            opacity: entry.kind.startsWith("live") ? 0.8 : 1
            font.pixelSize: entry.compact ? 21 : 17
            font.weight: entry.compact ? Font.Medium : Font.Normal
            lineHeight: 1.15
        }
    }

    Component {
        id: work
        Item {
            id: capsule
            property real now: Date.now() / 1000
            Timer {
                interval: 1000; repeat: true
                running: capsule.running
                onTriggered: capsule.now = Date.now() / 1000
            }
            readonly property bool running: entry.status === "running" || entry.status === "live"
            // The latest step, a command without the shell wrapper Codex adds.
            readonly property string step: entry.text.replace(/^\/bin\/(?:ba)?sh -lc '([\s\S]*)'$/, "$1").split("\n")[0]
            readonly property int seconds: Math.max(0, Math.round((running ? now : entry.finished) - entry.started))
            implicitWidth: entry.width
            implicitHeight: 32
            Rectangle {
                width: Math.min(parent.width, row.implicitWidth + 28)
                height: parent.height
                radius: height / 2
                color: Style.glass
                Row {
                    id: row
                    x: 14
                    width: parent.width - 28
                    anchors.verticalCenter: parent.verticalCenter
                    spacing: 8
                    QQC2.BusyIndicator {
                        visible: capsule.running
                        width: 16
                        height: 16
                        running: visible
                    }
                    Kirigami.Icon {
                        visible: !capsule.running
                        width: 16
                        height: 16
                        anchors.verticalCenter: parent.verticalCenter
                        source: entry.status === "stopped" ? "media-playback-stop-symbolic" : "checkmark-symbolic"
                        color: Style.dim
                        isMask: true
                    }
                    Text {
                        width: Math.min(implicitWidth, capsule.width - 28 - 24)
                        anchors.verticalCenter: parent.verticalCenter
                        elide: Text.ElideRight
                        color: Style.dim
                        font.pixelSize: 13
                        text: entry.status === "stopped" ? "已停止"
                            : capsule.running ? "正在处理 · " + capsule.seconds + " 秒" + (capsule.step ? " · " + capsule.step : "")
                            : "已处理 · " + entry.steps.count + " 步 · 用时 " + capsule.seconds + " 秒"
                    }
                }
            }
        }
    }

    Component {
        id: call
        Text {
            horizontalAlignment: Text.AlignHCenter
            color: Style.dim
            font.pixelSize: 13
            text: "通话 · " + entry.role + (entry.text ? " · " + entry.text : "")
            elide: Text.ElideRight
        }
    }

    Component {
        id: note
        Text {
            horizontalAlignment: Text.AlignHCenter
            wrapMode: Text.Wrap
            font.pixelSize: 13
            color: entry.kind === "error" ? Style.error : Style.dim
            text: entry.text
        }
    }
}
