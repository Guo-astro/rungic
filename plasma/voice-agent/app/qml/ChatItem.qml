// SPDX-License-Identifier: GPL-2.0-or-later
// One entry of the chat: speech bubbles, agent messages, commands, files, approvals.
import QtQuick
import QtQuick.Controls as QQC2
import QtQuick.Layouts
import org.kde.kirigami as Kirigami
import dev.moto.voiceassistant

Item {
    id: item
    required property int index
    required property string kind
    required property string role
    required property string text
    required property string itemId
    required property string command
    required property string output
    required property string status
    required property string exitCode
    width: ListView.view.width
    implicitHeight: loader.implicitHeight + Kirigami.Units.smallSpacing * 2

    readonly property bool mine: kind === "message" && role === "user" || kind === "live-user"

    Loader {
        id: loader
        x: item.mine ? item.width - width - Kirigami.Units.largeSpacing : Kirigami.Units.largeSpacing
        y: Kirigami.Units.smallSpacing
        width: Math.min(implicitWidth, item.width - Kirigami.Units.gridUnit * 3)
        sourceComponent: {
            switch (item.kind) {
            case "command": return commandCard
            case "files": return filesCard
            case "approval": return approvalCard
            case "marker": return marker
            case "error": return errorCard
            default: return bubble
            }
        }
    }

    Component {
        id: bubble
        Rectangle {
            implicitWidth: Math.min(label.implicitWidth, item.width * 0.8) + Kirigami.Units.largeSpacing * 2
            implicitHeight: label.implicitHeight + Kirigami.Units.largeSpacing * 1.5
            radius: Kirigami.Units.cornerRadius * 2
            color: item.mine ? Kirigami.Theme.highlightColor
                 : item.kind === "agent" ? Kirigami.Theme.alternateBackgroundColor
                 : Kirigami.ColorUtils.tintWithAlpha(Kirigami.Theme.backgroundColor, Kirigami.Theme.textColor, 0.08)
            opacity: item.kind.startsWith("live") ? 0.7 : 1
            QQC2.Label {
                id: label
                anchors.centerIn: parent
                width: Math.min(implicitWidth, item.width * 0.8)
                text: item.text
                wrapMode: Text.Wrap
                textFormat: item.kind === "agent" ? Text.MarkdownText : Text.PlainText
                color: item.mine ? Kirigami.Theme.highlightedTextColor : Kirigami.Theme.textColor
                font.pointSize: item.kind === "agent" ? Kirigami.Theme.smallFont.pointSize : Kirigami.Theme.defaultFont.pointSize
            }
        }
    }

    Component {
        id: marker
        QQC2.Label {
            width: item.width - Kirigami.Units.largeSpacing * 2
            horizontalAlignment: Text.AlignHCenter
            text: item.text
            opacity: 0.6
            font.pointSize: Kirigami.Theme.smallFont.pointSize
        }
    }

    Component {
        id: errorCard
        QQC2.Label {
            width: item.width * 0.8
            text: "⚠ " + item.text
            wrapMode: Text.Wrap
            color: Kirigami.Theme.negativeTextColor
        }
    }

    Component {
        id: commandCard
        Rectangle {
            property bool expanded: false
            implicitWidth: item.width * 0.85
            implicitHeight: column.implicitHeight + Kirigami.Units.largeSpacing
            radius: Kirigami.Units.cornerRadius
            color: Kirigami.Theme.alternateBackgroundColor
            border.color: Kirigami.ColorUtils.tintWithAlpha(Kirigami.Theme.backgroundColor, Kirigami.Theme.textColor, 0.15)
            ColumnLayout {
                id: column
                anchors { left: parent.left; right: parent.right; top: parent.top; margins: Kirigami.Units.smallSpacing * 2 }
                RowLayout {
                    QQC2.BusyIndicator { visible: item.status === "running"; running: visible; implicitWidth: Kirigami.Units.iconSizes.small; implicitHeight: implicitWidth }
                    Kirigami.Icon {
                        visible: item.status !== "running"
                        source: item.exitCode === "0" ? "emblem-success" : "emblem-error"
                        implicitWidth: Kirigami.Units.iconSizes.small; implicitHeight: implicitWidth
                    }
                    QQC2.Label {
                        Layout.fillWidth: true
                        text: item.command.replace(/^\/bin\/bash -lc '([\s\S]*)'$/, "$1")
                        font.family: "monospace"
                        font.pointSize: Kirigami.Theme.smallFont.pointSize
                        elide: Text.ElideRight
                        maximumLineCount: 2
                        wrapMode: Text.WrapAnywhere
                    }
                }
                QQC2.Label {
                    Layout.fillWidth: true
                    visible: parent.parent.expanded && item.output.length > 0
                    text: item.output
                    font.family: "monospace"
                    font.pointSize: Kirigami.Theme.smallFont.pointSize
                    wrapMode: Text.WrapAnywhere
                }
            }
            MouseArea { anchors.fill: parent; onClicked: parent.expanded = !parent.expanded }
        }
    }

    Component {
        id: filesCard
        Rectangle {
            implicitWidth: item.width * 0.85
            implicitHeight: filesLabel.implicitHeight + Kirigami.Units.largeSpacing
            radius: Kirigami.Units.cornerRadius
            color: Kirigami.Theme.alternateBackgroundColor
            QQC2.Label {
                id: filesLabel
                anchors { left: parent.left; right: parent.right; verticalCenter: parent.verticalCenter; margins: Kirigami.Units.smallSpacing * 2 }
                text: "📝 修改了文件\n" + item.text
                wrapMode: Text.WrapAnywhere
                font.pointSize: Kirigami.Theme.smallFont.pointSize
            }
        }
    }

    Component {
        id: approvalCard
        Rectangle {
            implicitWidth: item.width * 0.85
            implicitHeight: approvalColumn.implicitHeight + Kirigami.Units.largeSpacing * 2
            radius: Kirigami.Units.cornerRadius * 2
            color: Kirigami.ColorUtils.tintWithAlpha(Kirigami.Theme.backgroundColor, Kirigami.Theme.neutralTextColor, 0.15)
            border.color: Kirigami.Theme.neutralTextColor
            ColumnLayout {
                id: approvalColumn
                anchors { left: parent.left; right: parent.right; top: parent.top; margins: Kirigami.Units.largeSpacing }
                QQC2.Label { text: "需要你的批准"; font.bold: true }
                QQC2.Label {
                    Layout.fillWidth: true
                    text: item.command.length > 0 ? item.command : item.text
                    font.family: item.command.length > 0 ? "monospace" : Kirigami.Theme.defaultFont.family
                    wrapMode: Text.WrapAnywhere
                }
                QQC2.Label { Layout.fillWidth: true; visible: item.text.length > 0 && item.command.length > 0; text: item.text; wrapMode: Text.Wrap; opacity: 0.7 }
                RowLayout {
                    visible: item.status === "pending"
                    QQC2.Button { text: "允许"; icon.name: "dialog-ok"; onClicked: AgentClient.approve(item.itemId, "allow") }
                    QQC2.Button { text: "本次对话都允许"; onClicked: AgentClient.approve(item.itemId, "allow-session") }
                    QQC2.Button { text: "拒绝"; icon.name: "dialog-cancel"; onClicked: AgentClient.approve(item.itemId, "deny") }
                }
                QQC2.Label {
                    visible: item.status !== "pending"
                    text: item.status === "decline" ? "已拒绝" : item.status === "accept" ? "已允许" : "已过期"
                    opacity: 0.7
                }
            }
        }
    }
}
