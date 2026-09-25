// SPDX-License-Identifier: GPL-2.0-or-later
// An entry of the conversation in the overlay (docs/67): the chat's bubbles, lighter;
// an agent turn is one line saying what it is doing (the details are in the app).
import QtQuick
import QtQuick.Controls as QQC2
import org.kde.kirigami as Kirigami

Item {
    id: entry
    required property string kind
    required property string role
    required property string text
    required property string status
    required property real started
    required property real finished
    required property var steps
    property bool dark: true
    width: ListView.view.width
    implicitHeight: loader.implicitHeight + Kirigami.Units.smallSpacing

    readonly property bool mine: role === "user" && (kind === "message" || kind === "live-user")

    Loader {
        id: loader
        x: entry.mine ? entry.width - width : 0
        width: Math.min(implicitWidth, entry.width * (entry.kind === "work" ? 1 : 0.82))
        sourceComponent: entry.kind === "work" ? work
                       : entry.kind === "error" || entry.kind === "marker" || entry.kind === "approval" ? note
                       : entry.kind === "call" ? call : bubble
    }

    Component {
        id: bubble
        Rectangle {
            readonly property real pad: Kirigami.Units.largeSpacing
            implicitWidth: Math.min(measure.implicitWidth, entry.width * 0.82 - pad * 2) + pad * 2
            implicitHeight: label.implicitHeight + pad * 1.3
            radius: Math.min(height / 2, Kirigami.Units.gridUnit)
            color: entry.mine ? Kirigami.Theme.highlightColor
                 : entry.dark ? Qt.rgba(1, 1, 1, 0.10) : Qt.rgba(1, 1, 1, 0.62)
            opacity: entry.kind.startsWith("live") ? 0.72 : 1
            Text {
                id: measure
                visible: false
                text: entry.text
                font: label.font
            }
            QQC2.Label {
                id: label
                x: parent.pad
                anchors.verticalCenter: parent.verticalCenter
                width: parent.width - parent.pad * 2
                text: entry.text
                wrapMode: Text.Wrap
                color: entry.mine ? "white" : Kirigami.Theme.textColor
                font.pointSize: Kirigami.Theme.defaultFont.pointSize * 1.08
            }
        }
    }

    Component {
        id: work
        Rectangle {
            id: capsule
            property real now: Date.now() / 1000
            Timer {
                interval: 1000; repeat: true
                running: entry.status === "running" || entry.status === "live"
                onTriggered: capsule.now = Date.now() / 1000
            }
            readonly property bool running: entry.status === "running" || entry.status === "live"
            // The latest step, a command without the shell wrapper Codex adds.
            readonly property string step: entry.text.replace(/^\/bin\/(?:ba)?sh -lc '([\s\S]*)'$/, "$1").split("\n")[0]
            readonly property int seconds: Math.max(0, Math.round((running ? now : entry.finished) - entry.started))
            implicitWidth: entry.width
            implicitHeight: row.implicitHeight + Kirigami.Units.smallSpacing * 2
            radius: height / 2
            color: entry.dark ? Qt.rgba(1, 1, 1, 0.06) : Qt.rgba(0, 0, 0, 0.04)
            Row {
                id: row
                anchors.verticalCenter: parent.verticalCenter
                x: Kirigami.Units.largeSpacing
                width: parent.width - Kirigami.Units.largeSpacing * 2
                spacing: Kirigami.Units.smallSpacing
                QQC2.BusyIndicator {
                    visible: capsule.running
                    width: Kirigami.Units.iconSizes.small
                    height: width
                    running: visible
                }
                Kirigami.Icon {
                    visible: !capsule.running
                    width: Kirigami.Units.iconSizes.small
                    height: width
                    source: entry.status === "stopped" ? "media-playback-stop-symbolic" : "checkmark-symbolic"
                    opacity: 0.6
                }
                QQC2.Label {
                    width: row.width - Kirigami.Units.iconSizes.small - row.spacing
                    anchors.verticalCenter: parent.verticalCenter
                    elide: Text.ElideRight
                    opacity: 0.7
                    font.pointSize: Kirigami.Theme.smallFont.pointSize
                    text: entry.status === "stopped" ? "已停止"
                        : capsule.running ? "正在处理 · " + capsule.seconds + " 秒" + (capsule.step ? " · " + capsule.step : "")
                        : "已处理 · " + entry.steps.count + " 步 · 用时 " + capsule.seconds + " 秒"
                }
            }
        }
    }

    Component {
        id: call
        Item {
            implicitWidth: entry.width
            implicitHeight: callLabel.implicitHeight
            QQC2.Label {
                id: callLabel
                width: parent.width
                horizontalAlignment: Text.AlignHCenter
                opacity: 0.7
                font.pointSize: Kirigami.Theme.smallFont.pointSize
                text: "通话 · " + entry.role + (entry.text ? " · " + entry.text : "")
                elide: Text.ElideRight
            }
        }
    }

    Component {
        id: note
        Item {
            implicitWidth: entry.width
            implicitHeight: noteLabel.implicitHeight
            QQC2.Label {
                id: noteLabel
                width: parent.width
                horizontalAlignment: Text.AlignHCenter
                wrapMode: Text.Wrap
                font.pointSize: Kirigami.Theme.smallFont.pointSize
                color: entry.kind === "error" ? Kirigami.Theme.negativeTextColor : Kirigami.Theme.textColor
                opacity: entry.kind === "error" ? 1 : 0.6
                text: entry.text
            }
        }
    }
}
