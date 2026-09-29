// SPDX-License-Identifier: GPL-2.0-or-later
// One entry of the thread (docs/59, docs/87). What the user said or typed is a light grey
// bubble on the right; the assistant's words are the page's text. An agent turn shows as
// shining text while it runs ("正在处理 · 12 秒 · …") and as "已处理 N 步 · 用时 N 秒 ›"
// afterwards, which opens its steps; the answer under it has copy and read-aloud. Calls
// (docs/63), approvals and the "set up first" prompt are outlined blocks.
import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as QQC2
import com.rungic.design
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
    property real column: 350
    property bool callMonitor: false
    signal readAloud(string text)
    signal openSettings(string page)
    // A command without the shell wrapper Codex adds.
    function summary(text) { return text.replace(/^\/bin\/(?:ba)?sh -lc '([\s\S]*)'$/, "$1") }

    width: ListView.view ? ListView.view.width : column
    implicitHeight: loader.implicitHeight
    readonly property real inset: (width - column) / 2
    readonly property var model: ListView.view ? ListView.view.model : null
    readonly property bool mine: kind === "message" && role === "user" || kind === "live-user"
    readonly property bool said: !mine && (kind === "message" || kind === "live-assistant")
    // The next entry, to know whether this is the end of a turn.
    readonly property var next: model && index + 1 < model.count ? model.get(index + 1) : null
    // A finished agent turn whose answer nobody spoke (typed turns, or the voice was off):
    // its final answer is shown under it.
    readonly property string finalAnswer: {
        if (kind !== "work" || status === "running" || status === "live") return ""
        if (next && (next.kind === "message" || next.kind === "live-assistant") && next.role !== "user") return ""
        for (let i = steps.count - 1; i >= 0; i--) if (steps.get(i).kind === "answer") return steps.get(i).text
        return ""
    }

    Loader {
        id: loader
        x: entry.mine ? entry.inset + entry.column - width : entry.inset
        width: entry.mine ? Math.min(implicitWidth, entry.column * 0.78) : entry.column
        sourceComponent: {
            switch (entry.kind) {
            case "work": return work
            case "call": return call
            case "approval": return approval
            case "setup": return setup
            case "marker": return marker
            case "error": return errorLine
            default: return entry.mine ? bubble : speech
            }
        }
    }

    // What the user said or typed; what they attached sits above it, on the right.
    Component {
        id: bubble
        ColumnLayout {
            id: mineBox
            readonly property var files: entry.output ? JSON.parse(entry.output) : []
            spacing: 6
            Row {
                Layout.alignment: Qt.AlignRight
                visible: mineBox.files.length > 0
                layoutDirection: Qt.RightToLeft
                spacing: 6
                Repeater {
                    model: mineBox.files
                    Rectangle {
                        required property var modelData
                        width: modelData.kind === "image" ? 120 : fileName.implicitWidth + 48
                        height: modelData.kind === "image" ? 120 : 48
                        radius: Theme.radiusInput
                        color: Theme.fill
                        clip: true
                        Image {
                            anchors.fill: parent
                            visible: modelData.kind === "image"
                            source: modelData.kind === "image" ? "file://" + modelData.path : ""
                            sourceSize: Qt.size(240, 240)
                            fillMode: Image.PreserveAspectCrop
                            asynchronous: true
                            Accessible.name: modelData.name
                        }
                        Row {
                            anchors.centerIn: parent
                            visible: modelData.kind !== "image"
                            spacing: 8
                            Icon { name: "file"; color: Theme.dim; anchors.verticalCenter: parent.verticalCenter }
                            Text { id: fileName; text: modelData.name; font.family: Theme.fontFamily; font.pixelSize: Theme.metaSize; color: Theme.text; anchors.verticalCenter: parent.verticalCenter }
                        }
                    }
                }
            }
            UserBubble {
                Layout.alignment: Qt.AlignRight
                visible: entry.text !== ""
                text: entry.text
                maxWidth: entry.column * 0.78
                faded: entry.kind === "live-user"
            }
            // In place from the press on (docs/87): listening while held, then the transcript on its way.
            Rectangle {
                Layout.alignment: Qt.AlignRight
                visible: entry.kind === "live-user" && entry.text === ""
                implicitWidth: entry.status === "listening" ? 112 : waitLabel.implicitWidth + 32
                implicitHeight: 44
                radius: 20
                color: Theme.fill
                Accessible.name: entry.status === "listening" ? "正在听" : "正在识别"
                Wave {
                    anchors.centerIn: parent
                    visible: entry.status === "listening"
                    bars: 12
                    barHeight: 18
                    level: 0.6
                    color: Theme.dim
                }
                ShineText {
                    id: waitLabel
                    anchors.centerIn: parent
                    visible: entry.status !== "listening"
                    pixelSize: Theme.metaSize
                    text: "正在识别…"
                }
            }
        }
    }

    // The assistant's words, with copy and read-aloud once a turn has ended on them.
    Component {
        id: speech
        ColumnLayout {
            spacing: 8
            Body { text: entry.text; opacity: entry.kind === "live-assistant" ? 0.8 : 1 }
            Actions {
                visible: entry.kind === "message" && (!entry.next || entry.next.kind === "message" && entry.next.role === "user")
                answer: entry.text
            }
        }
    }

    component Body: TextEdit {
        Layout.fillWidth: true
        readOnly: true
        selectByMouse: false
        wrapMode: Text.Wrap
        textFormat: TextEdit.MarkdownText
        font.family: Theme.fontFamily
        font.pixelSize: Theme.bodySize
        color: Theme.text
        onLinkActivated: link => Qt.openUrlExternally(link)
    }

    component Actions: RowLayout {
        property string answer
        Layout.leftMargin: -8
        spacing: 2
        IconButton {
            small: true
            iconName: "copy"
            text: "复制"
            onClicked: { clip.text = parent.answer; clip.selectAll(); clip.copy(); clip.text = "" }
        }
        IconButton {
            small: true
            iconName: "speaker"
            text: "朗读"
            onClicked: entry.readAloud(parent.answer)
        }
        TextEdit { id: clip; visible: false }
    }

    Component {
        id: marker
        Text {
            horizontalAlignment: Text.AlignHCenter
            text: entry.text
            font.family: Theme.fontFamily
            font.pixelSize: Theme.labelSize
            color: Theme.dim
        }
    }

    Component {
        id: errorLine
        Text {
            text: entry.text
            wrapMode: Text.Wrap
            font.family: Theme.fontFamily
            font.pixelSize: Theme.metaSize
            color: Theme.negative
        }
    }

    // An agent turn.
    Component {
        id: work
        ColumnLayout {
            id: turn
            readonly property bool running: entry.status === "running" || entry.status === "live"
            property real now: Date.now() / 1000
            readonly property int seconds: Math.max(0, Math.round((running ? now : entry.finished) - entry.started))
            Timer { interval: 1000; repeat: true; running: turn.running; onTriggered: turn.now = Date.now() / 1000 }
            spacing: 8
            ShineText {
                Layout.fillWidth: true
                visible: turn.running
                text: "正在处理 · " + turn.seconds + " 秒" + (entry.text ? " · " + entry.summary(entry.text).split("\n")[0] : "")
            }
            MetaButton {
                visible: !turn.running
                text: (entry.status === "stopped" ? "已停止 · " : "已处理 ") + entry.steps.count + " 步 · 用时 " + turn.seconds + " 秒"
                expanded: entry.expanded
                onClicked: entry.model.setProperty(entry.index, "expanded", !entry.expanded)
            }
            // The steps, when opened: what was said, notes, commands with their output.
            Repeater {
                model: entry.expanded ? entry.steps : null
                delegate: Step {}
            }
            Body { visible: entry.finalAnswer !== ""; text: entry.finalAnswer }
            Actions { visible: entry.finalAnswer !== ""; answer: entry.finalAnswer }
        }
    }

    component Step: ColumnLayout {
        id: step
        required property string kind
        required property string text
        required property string command
        required property string output
        required property string status
        required property string exitCode
        property bool open: false
        readonly property bool isCommand: kind === "command"
        Layout.fillWidth: true
        Layout.leftMargin: 2
        spacing: 4
        Text {
            text: step.isCommand ? (step.status === "running" ? "命令 · 运行中"
                                    : step.exitCode === "0" || step.exitCode === "" ? "命令 · 完成" : "命令 · 退出码 " + step.exitCode)
                : step.kind === "files" ? "修改了文件" : step.kind === "said" ? "说了" : step.kind === "answer" ? "答复" : "说明"
            font.family: Theme.fontFamily
            font.pixelSize: Theme.footSize
            color: Theme.dim
        }
        Text {
            Layout.fillWidth: true
            visible: !step.isCommand
            text: step.text
            textFormat: step.kind === "note" || step.kind === "answer" ? Text.MarkdownText : Text.PlainText
            wrapMode: Text.Wrap
            font.family: Theme.fontFamily
            font.pixelSize: Theme.metaSize
            color: Theme.text
            linkColor: Theme.link
        }
        // The command and its output in one block; long output folds (tap to open).
        QQC2.AbstractButton {
            Layout.fillWidth: true
            visible: step.isCommand
            implicitHeight: code.implicitHeight + 24
            Accessible.name: step.open ? "收起输出" : "展开输出"
            onClicked: step.open = !step.open
            background: Rectangle { radius: Theme.radiusInput; color: Theme.fill }
            contentItem: Text {
                id: code
                leftPadding: 14
                rightPadding: 14
                text: entry.summary(step.command) + (step.output ? "\n\n" + step.output.replace(/\s+$/, "") : "")
                textFormat: Text.PlainText
                wrapMode: Text.WrapAnywhere
                maximumLineCount: step.open ? 400 : 8
                elide: Text.ElideRight
                font.family: Theme.monoFamily
                font.pixelSize: 12
                lineHeight: 19
                lineHeightMode: Text.FixedHeight
                color: Theme.dim
            }
        }
    }

    // A call the assistant takes part in (docs/63): role = contact, text = goal,
    // output = summary; steps are who said what.
    Component {
        id: call
        Outlined {
            id: callBox
            readonly property bool running: entry.status === "running" || entry.status === "user"
            readonly property bool userTalks: entry.status === "user"
            property real now: Date.now() / 1000
            Timer { interval: 1000; repeat: true; running: callBox.running; onTriggered: callBox.now = Date.now() / 1000 }
            readonly property int seconds: Math.max(0, Math.round((running ? now : entry.finished) - entry.started))
            RowLayout {
                Layout.fillWidth: true
                spacing: 8
                Rectangle { implicitWidth: 8; implicitHeight: 8; radius: 4; color: callBox.running ? Theme.positive : Theme.faint }
                Text {
                    Layout.fillWidth: true
                    elide: Text.ElideRight
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.bodySize
                    font.weight: Font.DemiBold
                    color: Theme.text
                    text: (callBox.userTalks ? "你在通话中"
                           : !callBox.running ? "通话结束"
                           : entry.command === "dialing" ? "正在拨号…"
                           : entry.command === "ringing" ? "已拨出，等待接听"
                           : entry.command === "dial-failed" ? "没能拨出"
                           : entry.command === "hanging-up" ? "正在挂断…"
                           : entry.command === "hangup-failed" ? "没能挂断，请在微信里挂断"
                           : "助理通话中") + (entry.role ? " · " + entry.role : "")
                }
                Text {
                    text: String(Math.floor(callBox.seconds / 60)).padStart(2, "0") + ":" + String(callBox.seconds % 60).padStart(2, "0")
                    font.family: Theme.monoFamily
                    font.pixelSize: 13
                    color: Theme.dim
                }
            }
            Text {
                Layout.fillWidth: true
                visible: callBox.userTalks || entry.text.length > 0
                text: callBox.userTalks ? "语音助手已暂停，挂断后自动恢复" : "目的：" + entry.text
                wrapMode: Text.Wrap
                font.family: Theme.fontFamily
                font.pixelSize: Theme.labelSize
                color: Theme.dim
            }
            Repeater {
                model: entry.steps
                Text {
                    required property string kind
                    required property string text
                    Layout.fillWidth: true
                    wrapMode: Text.Wrap
                    textFormat: Text.StyledText
                    font.family: Theme.fontFamily
                    font.pixelSize: 15
                    lineHeight: 24
                    lineHeightMode: Text.FixedHeight
                    font.weight: kind === "ask" ? Font.DemiBold : Font.Normal
                    color: Theme.text
                    readonly property string who: ({ remote: "对方", agent: "助理", owner: "你", note: "记录", ask: "问你" })[kind] || ""
                    text: "<font color='" + Theme.dim + "'>" + who + "：</font>" + text.replace(/&/g, "&amp;").replace(/</g, "&lt;")
                }
            }
            Text {
                Layout.fillWidth: true
                visible: !callBox.running && entry.output.length > 0
                text: "结果：" + entry.output
                wrapMode: Text.Wrap
                font.family: Theme.fontFamily
                font.pixelSize: 15
                color: Theme.text
            }
            RowLayout {
                Layout.fillWidth: true
                Layout.topMargin: 4
                visible: callBox.running
                spacing: 8
                PillButton {
                    Layout.fillWidth: true
                    visible: !callBox.userTalks
                    iconName: "headset"
                    text: entry.callMonitor ? "停止旁听" : "旁听"
                    onClicked: AgentClient.callCommand(entry.callMonitor ? "monitor-off" : "monitor-on")
                }
                PillButton {
                    Layout.fillWidth: true
                    visible: !callBox.userTalks
                    iconName: "phone"
                    text: "我来接"
                    onClicked: AgentClient.callCommand("take-over")
                }
                PillButton {
                    Layout.fillWidth: true
                    iconName: "hang-up"
                    text: "挂断"
                    negative: true
                    onClicked: AgentClient.callCommand("hang-up")
                }
            }
        }
    }

    Component {
        id: approval
        Outlined {
            Text {
                text: "需要你的批准"
                font.family: Theme.fontFamily
                font.pixelSize: Theme.bodySize
                font.weight: Font.DemiBold
                color: Theme.text
            }
            Text {
                Layout.fillWidth: true
                text: entry.command.length > 0 ? entry.command : entry.text
                font.family: entry.command.length > 0 ? Theme.monoFamily : Theme.fontFamily
                font.pixelSize: Theme.metaSize
                wrapMode: Text.WrapAnywhere
                color: Theme.text
            }
            Flow {
                Layout.fillWidth: true
                visible: entry.status === "pending"
                spacing: 8
                PillButton { text: "允许"; onClicked: AgentClient.approve(entry.itemId, "allow") }
                PillButton { text: "本次对话都允许"; onClicked: AgentClient.approve(entry.itemId, "allow-session") }
                PillButton { text: "拒绝"; negative: true; onClicked: AgentClient.approve(entry.itemId, "deny") }
            }
            Text {
                visible: entry.status !== "pending"
                text: entry.status === "decline" ? "已拒绝" : entry.status === "accept" ? "已允许" : "已过期"
                font.family: Theme.fontFamily
                font.pixelSize: Theme.labelSize
                color: Theme.dim
            }
        }
    }

    // The agent cannot work until it is set up (docs/87): what is missing and a way there.
    Component {
        id: setup
        Outlined {
            RowLayout {
                Layout.fillWidth: true
                spacing: 12
                Icon { Layout.alignment: Qt.AlignTop; name: "key" }
                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: 2
                    Text {
                        Layout.fillWidth: true
                        text: entry.text || "还差一步：配置 OpenAI API Key"
                        wrapMode: Text.Wrap
                        font.family: Theme.fontFamily
                        font.pixelSize: Theme.bodySize
                        font.weight: Font.DemiBold
                        color: Theme.text
                    }
                    Text {
                        Layout.fillWidth: true
                        text: entry.output || "配好之后我就能替你操作手机。"
                        wrapMode: Text.Wrap
                        font.family: Theme.fontFamily
                        font.pixelSize: Theme.metaSize
                        color: Theme.dim
                    }
                }
            }
            PillButton { text: "去设置"; onClicked: entry.openSettings(entry.command) }
        }
    }

    // An outlined block (calls, approvals, prompts).
    component Outlined: Rectangle {
        default property alias content: box.data
        implicitHeight: box.implicitHeight + 28
        radius: Theme.radiusGroup
        color: "transparent"
        border.width: 1
        border.color: Theme.line
        ColumnLayout {
            id: box
            anchors { left: parent.left; right: parent.right; top: parent.top; leftMargin: 16; rightMargin: 16; topMargin: 14 }
            spacing: 10
        }
    }
}
