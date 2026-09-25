// SPDX-License-Identifier: GPL-2.0-or-later
// One entry of the chat: speech bubbles, an agent turn's work (folded), approvals.
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
    required property real started
    required property real finished
    required property bool expanded
    required property var steps
    property bool callMonitor: false   // a proxied call is being listened in on (docs/63)
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
            case "work": return workCard
            case "call": return callCard
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
            // Natural (unwrapped) width decides the bubble width; the label wraps inside.
            implicitWidth: Math.min(measure.implicitWidth, maxTextWidth) + padding * 2
            implicitHeight: label.implicitHeight + padding * 1.5
            radius: Kirigami.Units.cornerRadius * 2
            color: entry.mine ? Kirigami.Theme.highlightColor
                 : Kirigami.ColorUtils.tintWithAlpha(Kirigami.Theme.backgroundColor, Kirigami.Theme.textColor, 0.08)
            opacity: entry.kind.startsWith("live") ? 0.7 : 1
            Text {
                id: measure
                visible: false
                text: entry.text
                font: label.font
            }
            QQC2.Label {
                id: label
                x: parent.padding
                anchors.verticalCenter: parent.verticalCenter
                width: parent.width - parent.padding * 2
                text: entry.text
                wrapMode: Text.Wrap
                textFormat: Text.PlainText
                color: entry.mine ? Kirigami.Theme.highlightedTextColor : Kirigami.Theme.textColor
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

    // An agent turn, folded like ChatGPT/Codex: a status line while it runs, a
    // summary when done; tap to see each step (what was said, the agent's notes,
    // commands with their output, file changes).
    Component {
        id: workCard
        Rectangle {
            id: card
            readonly property bool running: entry.status === "running" || entry.status === "live"
            property real now: Date.now() / 1000
            readonly property int seconds: Math.max(0, Math.round((running ? now : entry.finished) - entry.started))
            implicitWidth: entry.width * 0.85
            implicitHeight: workColumn.implicitHeight + Kirigami.Units.smallSpacing * 4
            radius: Kirigami.Units.cornerRadius * 2
            color: Kirigami.Theme.alternateBackgroundColor
            border.color: Kirigami.ColorUtils.tintWithAlpha(Kirigami.Theme.backgroundColor, Kirigami.Theme.textColor, 0.12)
            Timer { interval: 1000; repeat: true; running: card.running; onTriggered: card.now = Date.now() / 1000 }
            ColumnLayout {
                id: workColumn
                anchors { left: parent.left; right: parent.right; top: parent.top; margins: Kirigami.Units.smallSpacing * 2 }
                spacing: Kirigami.Units.smallSpacing
                RowLayout {
                    Layout.fillWidth: true
                    QQC2.BusyIndicator {
                        visible: card.running; running: visible
                        implicitWidth: Kirigami.Units.iconSizes.small; implicitHeight: implicitWidth
                    }
                    Kirigami.Icon {
                        visible: !card.running
                        source: entry.status === "stopped" ? "media-playback-stop" : "emblem-success"
                        implicitWidth: Kirigami.Units.iconSizes.small; implicitHeight: implicitWidth
                    }
                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 0
                        QQC2.Label {
                            Layout.fillWidth: true
                            text: card.running ? "正在处理 · " + card.seconds + " 秒"
                                : (entry.status === "stopped" ? "已停止" : "已处理") + " · " + entry.steps.count + " 步 · 用时 " + card.seconds + " 秒"
                            font.pointSize: Kirigami.Theme.smallFont.pointSize
                            font.bold: true
                        }
                        // The latest step while running; folded, a reminder of what it did.
                        QQC2.Label {
                            Layout.fillWidth: true
                            visible: text.length > 0 && (card.running || !entry.expanded)
                            text: entry.text.replace(/^\/bin\/bash -lc '([\s\S]*)'$/, "$1").split("\n")[0]
                            elide: Text.ElideRight
                            opacity: 0.7
                            font.pointSize: Kirigami.Theme.smallFont.pointSize
                        }
                    }
                    Kirigami.Icon {
                        source: entry.expanded ? "arrow-up" : "arrow-down"
                        implicitWidth: Kirigami.Units.iconSizes.small; implicitHeight: implicitWidth
                        opacity: 0.6
                    }
                    TapHandler {
                        onTapped: entry.ListView.view.model.setProperty(entry.index, "expanded", !entry.expanded)
                    }
                }
                Repeater {
                    model: entry.expanded ? entry.steps : null
                    delegate: stepDelegate
                }
            }
        }
    }

    // A call the assistant takes part in (docs/63): who says what, questions for
    // the user, and the controls. role = contact, text = goal, output = summary.
    Component {
        id: callCard
        Rectangle {
            id: callBox
            readonly property bool live: entry.status === "running" || entry.status === "user"
            readonly property bool userTalks: entry.status === "user"
            implicitWidth: entry.width * 0.9
            implicitHeight: callColumn.implicitHeight + Kirigami.Units.largeSpacing * 2
            radius: Kirigami.Units.cornerRadius * 2
            color: Kirigami.ColorUtils.tintWithAlpha(Kirigami.Theme.backgroundColor, Kirigami.Theme.positiveTextColor, live ? 0.12 : 0.05)
            border.color: live ? Kirigami.Theme.positiveTextColor : Kirigami.ColorUtils.tintWithAlpha(Kirigami.Theme.backgroundColor, Kirigami.Theme.textColor, 0.15)
            ColumnLayout {
                id: callColumn
                anchors { left: parent.left; right: parent.right; top: parent.top; margins: Kirigami.Units.largeSpacing }
                spacing: Kirigami.Units.smallSpacing
                RowLayout {
                    Kirigami.Icon { source: "call-start"; implicitWidth: Kirigami.Units.iconSizes.small; implicitHeight: implicitWidth }
                    QQC2.Label {
                        Layout.fillWidth: true
                        font.bold: true
                        text: (callBox.userTalks ? "你在通话中"
                               : !callBox.live ? "通话结束"
                               : entry.command === "dialing" ? "正在拨号…"
                               : entry.command === "ringing" ? "已拨出，等待接听"
                               : entry.command === "dial-failed" ? "没能拨出"
                               : entry.command === "hanging-up" ? "正在挂断…"
                               : entry.command === "hangup-failed" ? "没能挂断，请在微信里挂断"
                               : "助理通话中")
                              + (entry.role ? " · " + entry.role : "")
                              + (callBox.userTalks ? " · 语音助手已暂停" : "")
                    }
                }
                QQC2.Label {
                    Layout.fillWidth: true
                    visible: entry.text.length > 0
                    text: "目的：" + entry.text
                    wrapMode: Text.Wrap
                    opacity: 0.7
                    font.pointSize: Kirigami.Theme.smallFont.pointSize
                }
                Repeater {
                    model: entry.steps
                    delegate: QQC2.Label {
                        required property string kind
                        required property string text
                        Layout.fillWidth: true
                        wrapMode: Text.Wrap
                        font.bold: kind === "ask"
                        color: kind === "ask" ? Kirigami.Theme.neutralTextColor : Kirigami.Theme.textColor
                        opacity: kind === "note" ? 0.6 : 1
                        text: ({ remote: "对方：", agent: "助理：", owner: "你：", ask: "问你：", note: "记录：" })[kind] + text
                    }
                }
                QQC2.Label {
                    Layout.fillWidth: true
                    visible: !callBox.live && entry.output.length > 0
                    text: "结果：" + entry.output
                    wrapMode: Text.Wrap
                    font.bold: true
                }
                RowLayout {
                    visible: callBox.live
                    QQC2.Button {
                        visible: !callBox.userTalks
                        text: entry.callMonitor ? "停止旁听" : "旁听"
                        icon.name: "audio-headphones"
                        onClicked: AgentClient.callCommand(entry.callMonitor ? "monitor-off" : "monitor-on")
                    }
                    QQC2.Button { visible: !callBox.userTalks; text: "我来接"; icon.name: "call-start"; onClicked: AgentClient.callCommand("take-over") }
                    QQC2.Button { text: "挂断"; icon.name: "call-stop"; onClicked: AgentClient.callCommand("hang-up") }
                }
            }
        }
    }

    Component {
        id: stepDelegate
        ColumnLayout {
            id: stepItem
            required property string kind
            required property string text
            required property string command
            required property string output
            required property string status
            required property string exitCode
            property bool open: false
            Layout.fillWidth: true
            spacing: 2
            RowLayout {
                Layout.fillWidth: true
                Kirigami.Icon {
                    Layout.alignment: Qt.AlignTop
                    source: stepItem.kind === "said" ? "audio-speakers-symbolic"
                          : stepItem.kind === "command" ? (stepItem.status === "running" ? "system-run"
                                                          : stepItem.exitCode === "0" ? "emblem-success" : "dialog-information")
                          : stepItem.kind === "files" ? "document-edit" : "documentinfo"
                    // A non-zero exit is often just a probe that found nothing: keep it quiet.
                    opacity: stepItem.kind === "command" && stepItem.exitCode !== "0" ? 0.5 : 0.8
                    implicitWidth: Kirigami.Units.iconSizes.small; implicitHeight: implicitWidth
                }
                QQC2.Label {
                    Layout.fillWidth: true
                    text: stepItem.kind === "command" ? stepItem.command.replace(/^\/bin\/bash -lc '([\s\S]*)'$/, "$1")
                        : stepItem.kind === "files" ? "修改了文件\n" + stepItem.text : stepItem.text
                    textFormat: stepItem.kind === "note" || stepItem.kind === "answer" ? Text.MarkdownText : Text.PlainText
                    font.family: stepItem.kind === "command" ? "monospace" : Kirigami.Theme.defaultFont.family
                    font.italic: stepItem.kind === "said"
                    font.pointSize: Kirigami.Theme.smallFont.pointSize
                    wrapMode: stepItem.kind === "command" ? Text.WrapAnywhere : Text.Wrap
                    maximumLineCount: stepItem.kind === "command" && !stepItem.open ? 2 : 1000
                    elide: Text.ElideRight
                }
                QQC2.Label {
                    visible: stepItem.kind === "command" && stepItem.status !== "running" && stepItem.exitCode !== "0" && stepItem.exitCode !== ""
                    text: "退出码 " + stepItem.exitCode
                    opacity: 0.6
                    font.pointSize: Kirigami.Theme.smallFont.pointSize
                }
                TapHandler { enabled: stepItem.kind === "command"; onTapped: stepItem.open = !stepItem.open }
            }
            QQC2.Label {
                Layout.fillWidth: true
                Layout.leftMargin: Kirigami.Units.iconSizes.small + Kirigami.Units.smallSpacing
                visible: stepItem.open && stepItem.output.length > 0
                text: stepItem.output
                font.family: "monospace"
                font.pointSize: Kirigami.Theme.smallFont.pointSize
                wrapMode: Text.WrapAnywhere
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
