// SPDX-License-Identifier: GPL-2.0-or-later
// One entry of the chat: speech bubbles, agent messages, commands, files, approvals.
import QtQuick
import QtQuick.Controls as QQC2
import QtQuick.Layouts
import org.kde.kirigami as Kirigami
import dev.moto.voiceassistant

Item {
    id: entry
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
        x: entry.mine ? entry.width - width - Kirigami.Units.largeSpacing : Kirigami.Units.largeSpacing
        y: Kirigami.Units.smallSpacing
        width: Math.min(implicitWidth, entry.width - Kirigami.Units.gridUnit * 3)
        sourceComponent: {
            switch (entry.kind) {
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
            readonly property real padding: Kirigami.Units.largeSpacing
            readonly property real maxTextWidth: entry.width * 0.8 - padding * 2
            readonly property bool markdown: entry.kind === "agent"
            // Natural (unwrapped) width decides the bubble width; the label wraps inside.
            implicitWidth: Math.min(measure.implicitWidth, maxTextWidth) + padding * 2
            implicitHeight: label.implicitHeight + padding * 1.5
            radius: Kirigami.Units.cornerRadius * 2
            color: entry.mine ? Kirigami.Theme.highlightColor
                 : markdown ? Kirigami.Theme.alternateBackgroundColor
                 : Kirigami.ColorUtils.tintWithAlpha(Kirigami.Theme.backgroundColor, Kirigami.Theme.textColor, 0.08)
            opacity: entry.kind.startsWith("live") ? 0.7 : 1
            Text {
                id: measure
                visible: false
                text: entry.text
                textFormat: label.textFormat
                font: label.font
            }
            QQC2.Label {
                id: label
                x: parent.padding
                anchors.verticalCenter: parent.verticalCenter
                width: parent.width - parent.padding * 2
                text: entry.text
                wrapMode: Text.Wrap
                textFormat: parent.markdown ? Text.MarkdownText : Text.PlainText
                color: entry.mine ? Kirigami.Theme.highlightedTextColor : Kirigami.Theme.textColor
                font.pointSize: parent.markdown ? Kirigami.Theme.smallFont.pointSize : Kirigami.Theme.defaultFont.pointSize
            }
        }
    }

    Component {
        id: marker
        QQC2.Label {
            width: entry.width - Kirigami.Units.largeSpacing * 2
            horizontalAlignment: Text.AlignHCenter
            text: entry.text
            opacity: 0.6
            font.pointSize: Kirigami.Theme.smallFont.pointSize
        }
    }

    Component {
        id: errorCard
        QQC2.Label {
            width: entry.width * 0.8
            text: "⚠ " + entry.text
            wrapMode: Text.Wrap
            color: Kirigami.Theme.negativeTextColor
        }
    }

    Component {
        id: commandCard
        Rectangle {
            property bool expanded: false
            implicitWidth: entry.width * 0.85
            implicitHeight: column.implicitHeight + Kirigami.Units.largeSpacing
            radius: Kirigami.Units.cornerRadius
            color: Kirigami.Theme.alternateBackgroundColor
            border.color: Kirigami.ColorUtils.tintWithAlpha(Kirigami.Theme.backgroundColor, Kirigami.Theme.textColor, 0.15)
            ColumnLayout {
                id: column
                anchors { left: parent.left; right: parent.right; top: parent.top; margins: Kirigami.Units.smallSpacing * 2 }
                RowLayout {
                    QQC2.BusyIndicator { visible: entry.status === "running"; running: visible; implicitWidth: Kirigami.Units.iconSizes.small; implicitHeight: implicitWidth }
                    // A non-zero exit is often just a probe that found nothing: keep it quiet.
                    Kirigami.Icon {
                        visible: entry.status !== "running"
                        source: entry.exitCode === "0" ? "emblem-success" : "dialog-information"
                        opacity: entry.exitCode === "0" ? 1 : 0.5
                        implicitWidth: Kirigami.Units.iconSizes.small; implicitHeight: implicitWidth
                    }
                    QQC2.Label {
                        Layout.fillWidth: true
                        text: entry.command.replace(/^\/bin\/bash -lc '([\s\S]*)'$/, "$1")
                        font.family: "monospace"
                        font.pointSize: Kirigami.Theme.smallFont.pointSize
                        elide: Text.ElideRight
                        maximumLineCount: 2
                        wrapMode: Text.WrapAnywhere
                    }
                    QQC2.Label {
                        visible: entry.status !== "running" && entry.exitCode !== "0" && entry.exitCode !== ""
                        text: "退出码 " + entry.exitCode
                        opacity: 0.6
                        font.pointSize: Kirigami.Theme.smallFont.pointSize
                    }
                }
                QQC2.Label {
                    Layout.fillWidth: true
                    visible: parent.parent.expanded && entry.output.length > 0
                    text: entry.output
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
            implicitWidth: entry.width * 0.85
            implicitHeight: filesLabel.implicitHeight + Kirigami.Units.largeSpacing
            radius: Kirigami.Units.cornerRadius
            color: Kirigami.Theme.alternateBackgroundColor
            QQC2.Label {
                id: filesLabel
                anchors { left: parent.left; right: parent.right; verticalCenter: parent.verticalCenter; margins: Kirigami.Units.smallSpacing * 2 }
                text: "📝 修改了文件\n" + entry.text
                wrapMode: Text.WrapAnywhere
                font.pointSize: Kirigami.Theme.smallFont.pointSize
            }
        }
    }

    Component {
        id: approvalCard
        Rectangle {
            implicitWidth: entry.width * 0.85
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
                    text: entry.command.length > 0 ? entry.command : entry.text
                    font.family: entry.command.length > 0 ? "monospace" : Kirigami.Theme.defaultFont.family
                    wrapMode: Text.WrapAnywhere
                }
                QQC2.Label { Layout.fillWidth: true; visible: entry.text.length > 0 && entry.command.length > 0; text: entry.text; wrapMode: Text.Wrap; opacity: 0.7 }
                RowLayout {
                    visible: entry.status === "pending"
                    QQC2.Button { text: "允许"; icon.name: "dialog-ok"; onClicked: AgentClient.approve(entry.itemId, "allow") }
                    QQC2.Button { text: "本次对话都允许"; onClicked: AgentClient.approve(entry.itemId, "allow-session") }
                    QQC2.Button { text: "拒绝"; icon.name: "dialog-cancel"; onClicked: AgentClient.approve(entry.itemId, "deny") }
                }
                QQC2.Label {
                    visible: entry.status !== "pending"
                    text: entry.status === "decline" ? "已拒绝" : entry.status === "accept" ? "已允许" : "已过期"
                    opacity: 0.7
                }
            }
        }
    }
}
