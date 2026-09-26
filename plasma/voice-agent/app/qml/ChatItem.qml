// SPDX-License-Identifier: GPL-2.0-or-later
// One entry of the chat (docs/59): the user's words in a glass bubble on the right, the
// assistant's as plain text (an answer after agent work in larger type), an agent turn
// as a card that opens to its steps, a proxied call as a card with its controls
// (docs/63), approvals.
import QtQuick
import QtQuick.Controls as QQC2
import QtQuick.Layouts
import org.kde.kirigami as Kirigami
import com.rungic.voiceassistant

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
    // The view spans the page (its scroll bar at the screen's edge); entries keep to a
    // centred reading column.
    width: ListView.view.width
    readonly property real column: Math.min(width - 40, Style.readingWidth)
    readonly property real inset: (width - column) / 2
    implicitHeight: loader.implicitHeight + 16

    readonly property bool mine: kind === "message" && role === "user" || kind === "live-user"
    // What the agent's work led to: said in larger type.
    readonly property bool answer: !mine && (kind === "message" || kind === "live-assistant") && index > 0
                                   && ListView.view.model.get(index - 1).kind === "work"

    Loader {
        id: loader
        x: entry.mine ? entry.inset + entry.column - width : entry.inset
        y: 8
        width: entry.mine ? Math.min(implicitWidth, entry.column * 0.8) : entry.column
        sourceComponent: {
            switch (entry.kind) {
            case "work": return workCard
            case "call": return callCard
            case "approval": return approvalCard
            case "marker": return marker
            case "error": return errorLine
            default: return entry.mine ? bubble : speech
            }
        }
    }

    Component {
        id: bubble
        Rectangle {
            readonly property real padX: 16
            // Natural (unwrapped) width decides the bubble width; the text wraps inside.
            implicitWidth: Math.min(measure.implicitWidth, entry.column * 0.8 - padX * 2) + padX * 2
            implicitHeight: label.implicitHeight + 20
            radius: 20
            bottomRightRadius: 6
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
                textFormat: Text.PlainText
                wrapMode: Text.Wrap
                color: Style.ink
                font.pixelSize: 16
                lineHeight: 1.12
            }
        }
    }

    Component {
        id: speech
        Text {
            text: entry.text
            textFormat: Text.PlainText
            wrapMode: Text.Wrap
            color: Style.ink
            opacity: entry.kind.startsWith("live") ? 0.8 : 1
            font.pixelSize: entry.answer ? 19 : 17
            font.weight: entry.answer ? Font.Medium : Font.Normal
            lineHeight: 1.16
        }
    }

    Component {
        id: marker
        Text {
            horizontalAlignment: Text.AlignHCenter
            text: entry.text
            color: Style.faint
            font.pixelSize: 13
        }
    }

    Component {
        id: errorLine
        Text {
            text: entry.text
            wrapMode: Text.Wrap
            color: Style.error
            font.pixelSize: 14
        }
    }

    // An agent turn, folded like ChatGPT/Codex: a status line while it runs, a summary
    // when done; tap to see each step (what was said, the agent's notes, commands with
    // their output, file changes).
    Component {
        id: workCard
        Card {
            id: card
            readonly property bool running: entry.status === "running" || entry.status === "live"
            property real now: Date.now() / 1000
            readonly property int seconds: Math.max(0, Math.round((running ? now : entry.finished) - entry.started))
            live: running
            Timer { interval: 1000; repeat: true; running: card.running; onTriggered: card.now = Date.now() / 1000 }

            QQC2.AbstractButton {
                Layout.fillWidth: true
                implicitHeight: Math.max(48, head.implicitHeight + 16)
                leftPadding: 14
                rightPadding: 14
                Accessible.name: headline.text
                onClicked: entry.ListView.view.model.setProperty(entry.index, "expanded", !entry.expanded)
                contentItem: RowLayout {
                    id: head
                    spacing: 10
                    Item {
                        implicitWidth: 16
                        implicitHeight: 16
                        Spinner { anchors.fill: parent; visible: card.running }
                        Kirigami.Icon {
                            anchors.fill: parent
                            visible: !card.running
                            source: entry.status === "stopped" ? "media-playback-stop-symbolic" : "checkmark-symbolic"
                            color: Style.dim
                            isMask: true
                        }
                    }
                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 2
                        Text {
                            id: headline
                            Layout.fillWidth: true
                            text: card.running ? "正在处理 · " + card.seconds + " 秒"
                                : (entry.status === "stopped" ? "已停止" : "已处理") + " · " + entry.steps.count + " 步 · 用时 " + card.seconds + " 秒"
                            color: Style.ink
                            font.pixelSize: 14
                            font.weight: Font.Medium
                        }
                        // The latest step while running; folded, a reminder of what it did.
                        Text {
                            Layout.fillWidth: true
                            visible: text.length > 0 && (card.running || !entry.expanded)
                            text: Style.command(entry.text).split("\n")[0]
                            elide: Text.ElideRight
                            color: Style.dim
                            font.pixelSize: 13
                        }
                    }
                    Kirigami.Icon {
                        implicitWidth: 16
                        implicitHeight: 16
                        source: entry.expanded ? "arrow-up-symbolic" : "arrow-down-symbolic"
                        color: Style.faint
                        isMask: true
                    }
                }
            }
            Repeater {
                model: entry.expanded ? entry.steps : null
                delegate: stepDelegate
            }
            Item { visible: entry.expanded; implicitHeight: 4 }
        }
    }

    Component {
        id: stepDelegate
        RowLayout {
            id: stepItem
            required property string kind
            required property string text
            required property string command
            required property string output
            required property string status
            required property string exitCode
            property bool open: false
            readonly property bool isCommand: kind === "command"
            // A non-zero exit is often just a probe that found nothing: said, not alarmed.
            readonly property string title: isCommand ? (status === "running" ? "命令 · 运行中"
                                                         : exitCode === "0" || exitCode === "" ? "命令 · 完成" : "命令 · 退出码 " + exitCode)
                                          : kind === "files" ? "修改了文件" : kind === "said" ? "说了" : kind === "answer" ? "答复" : "说明"
            Layout.fillWidth: true
            Layout.leftMargin: 14
            Layout.rightMargin: 14
            spacing: 10
            Kirigami.Icon {
                Layout.alignment: Qt.AlignTop
                Layout.topMargin: 2
                implicitWidth: 14
                implicitHeight: 14
                source: stepItem.isCommand ? "utilities-terminal-symbolic" : stepItem.kind === "files" ? "document-edit-symbolic"
                      : stepItem.kind === "said" ? "audio-speakers-symbolic" : "view-pim-notes-symbolic"
                color: Style.faint
                isMask: true
            }
            ColumnLayout {
                Layout.fillWidth: true
                spacing: 6
                Text {
                    text: stepItem.title
                    color: Style.faint
                    font.pixelSize: 12
                    font.letterSpacing: 0.5
                }
                Text {
                    Layout.fillWidth: true
                    visible: !stepItem.isCommand
                    text: stepItem.text
                    textFormat: stepItem.kind === "note" || stepItem.kind === "answer" ? Text.MarkdownText : Text.PlainText
                    linkColor: Style.accent
                    wrapMode: Text.Wrap
                    color: Style.inkSoft
                    font.pixelSize: 14
                    font.italic: stepItem.kind === "said"
                    lineHeight: 1.1
                }
                // The command and its output in one block; long output folds (tap to open).
                QQC2.AbstractButton {
                    Layout.fillWidth: true
                    visible: stepItem.isCommand
                    implicitHeight: codeText.implicitHeight + 20
                    Accessible.name: stepItem.open ? "收起输出" : "展开输出"
                    onClicked: stepItem.open = !stepItem.open
                    background: Rectangle { radius: 12; color: Style.code }
                    contentItem: Text {
                        id: codeText
                        leftPadding: 12
                        rightPadding: 12
                        text: Style.command(stepItem.command) + (stepItem.output ? "\n\n" + stepItem.output.replace(/\s+$/, "") : "")
                        textFormat: Text.PlainText
                        wrapMode: Text.WrapAnywhere
                        maximumLineCount: stepItem.open ? 400 : 8
                        elide: Text.ElideRight
                        color: Style.codeInk
                        font.family: "monospace"
                        font.pixelSize: 12
                        lineHeight: 1.12
                    }
                }
            }
        }
    }

    // A call the assistant takes part in (docs/63): who says what, questions for the
    // user, and the controls. role = contact, text = goal, output = summary.
    Component {
        id: callCard
        Card {
            id: callBox
            readonly property bool running: entry.status === "running" || entry.status === "user"
            readonly property bool userTalks: entry.status === "user"
            property real now: Date.now() / 1000
            Timer { interval: 1000; repeat: true; running: callBox.running; onTriggered: callBox.now = Date.now() / 1000 }
            readonly property int seconds: Math.max(0, Math.round((running ? now : entry.finished) - entry.started))
            live: running
            padding: 16
            spacing: 14

            RowLayout {
                Layout.fillWidth: true
                spacing: 10
                Rectangle {
                    implicitWidth: 8
                    implicitHeight: 8
                    radius: 4
                    color: callBox.running ? Style.accent : Style.faint
                    SequentialAnimation on opacity {
                        running: callBox.running
                        loops: Animation.Infinite
                        NumberAnimation { to: 0.35; duration: 800; easing.type: Easing.InOutSine }
                        NumberAnimation { to: 1; duration: 800; easing.type: Easing.InOutSine }
                    }
                }
                Text {
                    Layout.fillWidth: true
                    elide: Text.ElideRight
                    color: Style.ink
                    font.pixelSize: 15
                    font.weight: Font.DemiBold
                    text: (callBox.userTalks ? "你在通话中"
                           : !callBox.running ? "通话结束"
                           : entry.command === "dialing" ? "正在拨号…"
                           : entry.command === "ringing" ? "已拨出，等待接听"
                           : entry.command === "dial-failed" ? "没能拨出"
                           : entry.command === "hanging-up" ? "正在挂断…"
                           : entry.command === "hangup-failed" ? "没能挂断，请在微信里挂断"
                           : "助理通话中")
                          + (entry.role ? " · " + entry.role : "")
                }
                Text {
                    text: Math.floor(callBox.seconds / 60).toString().padStart(2, "0") + ":" + (callBox.seconds % 60).toString().padStart(2, "0")
                    color: Style.dim
                    font.pixelSize: 13
                    font.family: "monospace"
                }
            }
            Text {
                Layout.fillWidth: true
                visible: callBox.userTalks
                text: "语音助手已暂停，挂断后自动恢复"
                wrapMode: Text.Wrap
                color: Style.dim
                font.pixelSize: 13
            }
            Text {
                Layout.fillWidth: true
                visible: entry.text.length > 0
                text: "目的：" + entry.text
                wrapMode: Text.Wrap
                color: Style.dim
                font.pixelSize: 13
            }
            Rectangle { Layout.fillWidth: true; implicitHeight: 1; color: Style.line; visible: entry.steps.count > 0 }
            Repeater {
                model: entry.steps
                delegate: Loader {
                    id: said
                    required property string kind
                    required property string text
                    Layout.fillWidth: true
                    sourceComponent: kind === "ask" ? askLine : saidLine
                    Component {
                        id: saidLine
                        RowLayout {
                            spacing: 10
                            Text {
                                Layout.alignment: Qt.AlignTop
                                Layout.preferredWidth: 34
                                text: ({ remote: "对方", agent: "助理", owner: "你", note: "记录" })[said.kind] || ""
                                color: Style.faint
                                font.pixelSize: 15
                            }
                            Text {
                                Layout.fillWidth: true
                                text: said.text
                                wrapMode: Text.Wrap
                                color: said.kind === "remote" ? Style.ink : said.kind === "note" ? Style.dim : Style.inkSoft
                                font.pixelSize: 15
                                lineHeight: 1.12
                            }
                        }
                    }
                    // A question for the user: set apart in the light's gold.
                    Component {
                        id: askLine
                        Rectangle {
                            implicitHeight: askColumn.implicitHeight + 24
                            radius: 14
                            color: Style.accentFill
                            border.color: Style.accentBorder
                            ColumnLayout {
                                id: askColumn
                                anchors { left: parent.left; right: parent.right; verticalCenter: parent.verticalCenter; margins: 14 }
                                spacing: 4
                                Text { text: "问你"; color: Style.accent; font.pixelSize: 12; font.letterSpacing: 0.5 }
                                Text {
                                    Layout.fillWidth: true
                                    text: said.text
                                    wrapMode: Text.Wrap
                                    color: Style.ink
                                    font.pixelSize: 15
                                }
                            }
                        }
                    }
                }
            }
            Text {
                Layout.fillWidth: true
                visible: !callBox.running && entry.output.length > 0
                text: "结果：" + entry.output
                wrapMode: Text.Wrap
                color: Style.ink
                font.pixelSize: 15
                font.weight: Font.Medium
            }
            RowLayout {
                Layout.fillWidth: true
                visible: callBox.running
                spacing: 8
                PillButton {
                    visible: !callBox.userTalks
                    iconName: "audio-headphones-symbolic"
                    text: entry.callMonitor ? "停止旁听" : "旁听"
                    checked: entry.callMonitor
                    onClicked: AgentClient.callCommand(entry.callMonitor ? "monitor-off" : "monitor-on")
                }
                PillButton {
                    visible: !callBox.userTalks
                    iconName: "call-start-symbolic"
                    text: "我来接"
                    onClicked: AgentClient.callCommand("take-over")
                }
                PillButton {
                    iconName: "call-stop-symbolic"
                    text: "挂断"
                    danger: true
                    onClicked: AgentClient.callCommand("hang-up")
                }
            }
        }
    }

    Component {
        id: approvalCard
        Card {
            live: entry.status === "pending"
            padding: 16
            spacing: 10
            Text { text: "需要你的批准"; color: Style.accent; font.pixelSize: 14; font.weight: Font.DemiBold }
            Text {
                Layout.fillWidth: true
                text: entry.command.length > 0 ? entry.command : entry.text
                font.family: entry.command.length > 0 ? "monospace" : ""
                wrapMode: Text.WrapAnywhere
                color: Style.ink
                font.pixelSize: 14
            }
            Text {
                Layout.fillWidth: true
                visible: entry.text.length > 0 && entry.command.length > 0
                text: entry.text
                wrapMode: Text.Wrap
                color: Style.dim
                font.pixelSize: 13
            }
            Flow {
                Layout.fillWidth: true
                visible: entry.status === "pending"
                spacing: 8
                PillButton { text: "允许"; onClicked: AgentClient.approve(entry.itemId, "allow") }
                PillButton { text: "本次对话都允许"; onClicked: AgentClient.approve(entry.itemId, "allow-session") }
                PillButton { text: "拒绝"; onClicked: AgentClient.approve(entry.itemId, "deny") }
            }
            Text {
                visible: entry.status !== "pending"
                text: entry.status === "decline" ? "已拒绝" : entry.status === "accept" ? "已允许" : "已过期"
                color: Style.dim
                font.pixelSize: 13
            }
        }
    }

    // A rounded surface; gold-edged while something in it is live.
    component Card: Rectangle {
        id: cardBox
        default property alias content: cardColumn.data
        property bool live: false
        property real padding: 0
        property alias spacing: cardColumn.spacing
        implicitHeight: cardColumn.implicitHeight + padding * 2
        radius: 20
        color: Style.surface
        border.width: 1
        border.color: live ? Style.accentBorder : Style.line
        ColumnLayout {
            id: cardColumn
            anchors { left: parent.left; right: parent.right; top: parent.top; margins: cardBox.padding }
            spacing: 12
        }
    }

    component PillButton: QQC2.AbstractButton {
        id: pb
        property string iconName
        property bool danger: false
        Layout.fillWidth: true
        implicitHeight: 48
        implicitWidth: row.implicitWidth + 32
        checkable: false
        Accessible.name: text
        background: Rectangle {
            radius: height / 2
            color: pb.danger ? (pb.pressed ? Qt.darker(Style.danger, 1.2) : Style.danger)
                 : pb.pressed || pb.checked ? Style.glassPressed : Style.glass
            border.width: 1
            border.color: Style.glassBorder
        }
        contentItem: Item {
            Row {
                id: row
                anchors.centerIn: parent
                spacing: 6
                Kirigami.Icon {
                    visible: pb.iconName !== ""
                    anchors.verticalCenter: parent.verticalCenter
                    width: 18
                    height: 18
                    source: pb.iconName
                    color: pb.danger ? "white" : Style.ink
                    isMask: true
                }
                Text {
                    anchors.verticalCenter: parent.verticalCenter
                    text: pb.text
                    color: pb.danger ? "white" : Style.ink
                    font.pixelSize: 14
                    font.weight: Font.Medium
                }
            }
        }
    }
}
