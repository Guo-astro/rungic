// SPDX-License-Identifier: GPL-2.0-or-later
// One entry of the thread (docs/59, docs/87). What the user said or typed is a light grey
// bubble on the right; the assistant's words are the page's text. An agent turn shows as
// shining text while it runs ("Working · 12s · …") and as "Worked through N steps · Ns ›"
// afterwards, which opens its steps; the answer under it has copy and read-aloud. Calls
// (docs/63), approvals and the "set up first" prompt are outlined blocks.
import QtCore
import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as QQC2
import com.rungic.design
import com.rungic.voiceassistant
import "media.js" as Media

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
    required property string callBackend
    required property string callNumber
    required property real connectedAt
    required property bool privateVoiceInstructions
    required property bool independentMonitor
    // The turn in words (task_state, docs/89): JSON of plan, current step, recent, files.
    required property string task
    property real column: 350
    property bool callMonitor: false
    property bool callCanMonitor: true
    signal readAloud(string text)
    signal openSettings(string page)
    // A picture of an answer tapped (docs/88): the page shows it large.
    signal openImage(url source, string name)
    // A command without the shell wrapper Codex adds.
    function summary(text) { return text.replace(/^\/bin\/(?:ba)?sh -lc '([\s\S]*)'$/, "$1") }
    function duration(seconds) { return i18nc("@info a short duration", "%1s", seconds) }

    width: ListView.view ? ListView.view.width : column
    implicitHeight: loader.implicitHeight
    readonly property real inset: (width - column) / 2
    readonly property var model: ListView.view ? ListView.view.model : null
    readonly property bool mine: kind === "message" && role === "user" || kind === "live-user"
    readonly property bool said: !mine && (kind === "message" || kind === "live-assistant")
    // The next entry, to know whether this is the end of a turn.
    readonly property var next: model && index + 1 < model.count ? model.get(index + 1) : null
    // A finished agent turn's answer, and what it shows (docs/88): its pictures and files come
    // out of the text (media.js) and sit under the turn even when the voice spoke the answer.
    readonly property string answerText: {
        if (kind !== "work" || status === "running" || status === "live") return ""
        for (let i = steps.count - 1; i >= 0; i--) if (steps.get(i).kind === "answer") return steps.get(i).text
        return ""
    }
    readonly property string home: StandardPaths.writableLocation(StandardPaths.HomeLocation)
    readonly property var answer: Media.parse(answerText, home)
    // The answer's text when nobody spoke it (typed turns, or the voice was off).
    readonly property string finalAnswer: {
        if (answer.text === "") return ""
        if (next && (next.kind === "message" || next.kind === "live-assistant") && next.role !== "user") return ""
        return answer.text
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
                Accessible.name: entry.status === "listening" ? i18nc("@info:status", "Listening") : i18nc("@info:status what was said is being transcribed", "Transcribing")
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
                    text: i18nc("@info:status what was said is being transcribed", "Transcribing…")
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
            text: i18nc("@action:button copy the answer", "Copy")
            onClicked: { clip.text = parent.answer; clip.selectAll(); clip.copy(); clip.text = "" }
        }
        IconButton {
            small: true
            iconName: "speaker"
            text: i18nc("@action:button the voice reads the answer out", "Read aloud")
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
            // The task card (docs/89): the plan and what is happening now, from the service's
            // task state; a turn without one (older history) shows the spoken progress instead.
            readonly property var card: entry.task ? JSON.parse(entry.task) : null
            readonly property var current: card && card.current ? card.current : null
            property real cardAt: Date.now() / 1000       // when `current` came, to count on from it
            onCurrentChanged: cardAt = Date.now() / 1000
            ShineText {
                Layout.fillWidth: true
                visible: turn.running
                text: i18nc("@info:status the agent at work; %1 is how long", "Working · %1", entry.duration(turn.seconds))
                      + (!turn.card && entry.text ? " · " + entry.summary(entry.text).split("\n")[0] : "")
            }
            MetaButton {
                visible: !turn.running
                text: entry.status === "stopped"
                    ? i18ncp("@action:button a stopped agent turn: its steps and how long it ran", "Stopped · %1 step · %2",
                             "Stopped · %1 steps · %2", entry.steps.count, entry.duration(turn.seconds))
                    : i18ncp("@action:button a finished agent turn: its steps and how long it took", "Worked through %1 step · %2",
                             "Worked through %1 steps · %2", entry.steps.count, entry.duration(turn.seconds))
                expanded: entry.expanded
                onClicked: entry.model.setProperty(entry.index, "expanded", !entry.expanded)
            }
            // The plan: while it runs, and when the finished turn is opened.
            Repeater {
                model: turn.card && (turn.running || entry.expanded) ? turn.card.plan : []
                PlanStep {
                    required property var modelData
                    Layout.fillWidth: true
                    text: modelData.step
                    status: modelData.status
                }
            }
            ActivityCard {
                Layout.fillWidth: true
                visible: turn.running && turn.card !== null
                kind: turn.current ? turn.current.kind : ""
                text: turn.current ? turn.current.text : ""
                detail: turn.current ? turn.current.detail || "" : ""
                progress: turn.current && turn.current.progress !== null && turn.current.progress !== undefined ? turn.current.progress : -1
                seconds: turn.current ? turn.current.seconds + Math.max(0, Math.round(turn.now - turn.cardAt)) : 0
            }
            // A live picture of the work (a render's passes, docs/90) while it runs; the finished
            // picture comes with the answer.
            LivePicture {
                readonly property var preview: turn.card ? turn.card.preview : null
                visible: turn.running && preview !== null && preview !== undefined
                source: visible ? "file://" + preview.image.split("/").map(encodeURIComponent).join("/") : ""
                text: visible ? preview.text : ""
                progress: visible && preview.progress !== null && preview.progress !== undefined ? preview.progress : -1
                finished: visible && preview.done === true
                maxWidth: Math.min(entry.column, 360)
                maxHeight: 360
                onClicked: entry.openImage(source, i18nc("@title a live picture of a render", "Render preview"))
            }
            // The files the turn changed, when opened: a tap opens one.
            Flow {
                Layout.fillWidth: true
                visible: entry.expanded && turn.card !== null && turn.card.files.length > 0
                spacing: 8
                Repeater {
                    model: entry.expanded && turn.card ? turn.card.files : []
                    FileChip {
                        required property var modelData
                        name: modelData.path.split("/").pop() + " · " + (modelData.kind === "delete" ? i18nc("@info a file the turn deleted", "Deleted")
                              : "+" + modelData.added + " −" + modelData.removed)
                        maxWidth: entry.column
                        enabled: modelData.kind !== "delete"
                        onClicked: Qt.openUrlExternally("file://" + modelData.path)
                    }
                }
            }
            // The steps, when opened: what was said, notes, commands with their output.
            Repeater {
                model: entry.expanded ? entry.steps : null
                delegate: Step {}
            }
            Body { visible: entry.finalAnswer !== ""; text: entry.finalAnswer }
            // Pictures, then files, of the answer.
            Flow {
                Layout.fillWidth: true
                Layout.topMargin: 2
                visible: entry.answer.images.length + entry.answer.files.length > 0
                spacing: 8
                Repeater {
                    model: entry.answer.images
                    Thumbnail {
                        required property var modelData
                        source: modelData.url
                        name: modelData.name
                        // From the column the entry is laid out in, never from this Flow.
                        maxWidth: entry.answer.images.length > 1 ? (entry.column - 8) / 2 : Math.min(entry.column, 320)
                        maxHeight: 360
                        onClicked: entry.openImage(source, name)
                    }
                }
                Repeater {
                    model: entry.answer.files
                    FileChip {
                        required property var modelData
                        name: modelData.name
                        maxWidth: entry.column
                        onClicked: Qt.openUrlExternally(modelData.url)
                    }
                }
            }
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
            text: step.isCommand ? (step.status === "running" ? i18nc("@info a step of an agent turn", "Command · Running")
                                    : step.exitCode === "0" || step.exitCode === "" ? i18nc("@info a step of an agent turn", "Command · Done")
                                    : i18nc("@info a step of an agent turn", "Command · Exit code %1", step.exitCode))
                : step.kind === "files" ? i18nc("@info a step of an agent turn", "Changed files")
                : step.kind === "said" ? i18nc("@info a step of an agent turn: what the voice said", "Said")
                : step.kind === "answer" ? i18nc("@info a step of an agent turn", "Answer") : i18nc("@info a step of an agent turn: the agent's note", "Note")
            font.family: Theme.fontFamily
            font.pixelSize: Theme.footSize
            color: Theme.dim
        }
        Text {
            Layout.fillWidth: true
            visible: !step.isCommand
            // Pictures show under the turn; a bare path would not load here (media.js).
            text: step.kind === "answer" || step.kind === "note" ? Media.parse(step.text, entry.home).text : step.text
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
            Accessible.name: step.open ? i18nc("@action:button", "Collapse output") : i18nc("@action:button", "Expand output")
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
            readonly property bool connected: entry.connectedAt > 0
            readonly property int seconds: connected ? Math.max(0, Math.floor((running ? now : entry.finished) - entry.connectedAt)) : 0
            function command(op, fields) {
                AgentClient.callCommand(JSON.stringify(Object.assign({op: op, callId: entry.itemId}, fields || {})))
            }
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
                    text: (callBox.userTalks ? i18nc("@info:status the user talks on the call", "You're on the call")
                           : !callBox.running ? (callBox.connected || !entry.itemId ? i18nc("@info:status", "Call ended") : i18nc("@info:status", "Call didn't connect"))
                           : entry.command === "connecting" ? i18nc("@info:status", "Preparing the call…")
                           : entry.command === "dialing" ? i18nc("@info:status", "Dialing…")
                           : entry.command === "ringing" ? i18nc("@info:status dialed, waiting to be answered", "Ringing…")
                           : entry.command === "dial-failed" ? i18nc("@info:status", "Couldn't place the call")
                           : entry.command === "hanging-up" ? i18nc("@info:status", "Hanging up…")
                           : entry.command === "hangup-failed" ? (entry.callBackend === "cellular" ? i18nc("@info:status", "Hang up in the Phone app")
                                                                  : i18nc("@info:status", "Hang up in the calling app"))
                           : i18nc("@info:status a call", "Assistant on the call")) + (entry.role ? " · " + entry.role : "")
                }
                Text {
                    visible: callBox.connected
                    text: String(Math.floor(callBox.seconds / 60)).padStart(2, "0") + ":" + String(callBox.seconds % 60).padStart(2, "0")
                    font.family: Theme.monoFamily
                    font.pixelSize: 13
                    color: Theme.dim
                }
            }
            Text {
                Layout.fillWidth: true
                text: entry.callBackend === "cellular" ? i18nc("@info the kind of call", "Phone call") + (entry.callNumber ? " · " + entry.callNumber : "")
                    : entry.callBackend === "wechat" ? i18nc("@info the kind of call", "WeChat call")
                    : i18nc("@info the kind of call; %1 is the app", "App call · %1", entry.callBackend)
                color: Theme.dim
                font.family: Theme.fontFamily
                font.pixelSize: Theme.labelSize
            }
            Text {
                Layout.fillWidth: true
                visible: callBox.userTalks || entry.text.length > 0
                text: callBox.userTalks ? i18nc("@info", "The voice assistant is paused and resumes when you hang up.")
                    : i18nc("@info what the call is for", "Goal: %1", entry.text)
                wrapMode: Text.Wrap
                font.family: Theme.fontFamily
                font.pixelSize: Theme.labelSize
                color: Theme.dim
            }
            Repeater {
                model: entry.steps
                ColumnLayout {
                    id: transcript
                    required property string kind
                    required property string text
                    Layout.fillWidth: true
                    Text {
                        Layout.fillWidth: true
                        wrapMode: Text.Wrap
                        textFormat: Text.StyledText
                        font.family: Theme.fontFamily
                        font.pixelSize: 15
                        lineHeight: 24
                        lineHeightMode: Text.FixedHeight
                        font.weight: transcript.kind === "ask" ? Font.DemiBold : Font.Normal
                        color: Theme.text
                        // Who said it, with the punctuation that introduces what was said (a fullwidth
                        // colon carries its own space).
                        readonly property string who: ({ remote: i18nc("@label a call transcript: the other party", "Them:"),
                                                         agent: i18nc("@label a call transcript", "Assistant:"),
                                                         owner: i18nc("@label a call transcript: the user", "You:"),
                                                         note: i18nc("@label a call transcript: the assistant's note", "Note:"),
                                                         ask: i18nc("@label a call transcript: the assistant asks the user", "Asks you:"),
                                                         error: i18nc("@label a call transcript: a problem", "Notice:") })[transcript.kind] || ""
                        text: "<font color='" + Theme.dim + "'>" + who + "</font>" + (/\uff1a$/.test(who) ? "" : " ") + transcript.text.replace(/&/g, "&amp;").replace(/</g, "&lt;")
                    }
                }
            }
            Text {
                Layout.fillWidth: true
                visible: !callBox.running && entry.output.length > 0
                text: i18nc("@info how the call went", "Result: %1", entry.output)
                wrapMode: Text.Wrap
                font.family: Theme.fontFamily
                font.pixelSize: 15
                color: Theme.text
            }
            RowLayout {
                Layout.fillWidth: true
                visible: callBox.running && !callBox.userTalks
                QQC2.TextField {
                    id: callInstruction
                    Layout.fillWidth: true
                    placeholderText: i18nc("@info:placeholder", "Text instruction for the call assistant")
                    function send() {
                        if (!text.trim()) return
                        callBox.command("instruct", {text: text.trim()})
                        text = ""
                    }
                    onAccepted: send()
                }
                PillButton {
                    text: i18nc("@action:button", "Send")
                    enabled: callInstruction.text.trim().length > 0
                    onClicked: callInstruction.send()
                }
            }
            Text {
                Layout.fillWidth: true
                visible: callBox.running && !callBox.userTalks && !entry.privateVoiceInstructions
                text: i18nc("@info", "Text instructions go only to the assistant. To speak yourself, tap “Take over”.")
                wrapMode: Text.Wrap
                color: Theme.dim
                font.pixelSize: Theme.labelSize
            }
            RowLayout {
                Layout.fillWidth: true
                Layout.topMargin: 4
                visible: callBox.running
                spacing: 8
                PillButton {
                    Layout.fillWidth: true
                    visible: !callBox.userTalks && entry.independentMonitor
                    iconName: "headset"
                    text: entry.callMonitor ? i18nc("@action:button stop hearing the call", "Stop listening in") : i18nc("@action:button hear the call", "Listen in")
                    onClicked: callBox.command(entry.callMonitor ? "monitor-off" : "monitor-on")
                }
                PillButton {
                    Layout.fillWidth: true
                    visible: !callBox.userTalks
                    iconName: "phone"
                    text: i18nc("@action:button the user takes the call over from the assistant", "Take over")
                    onClicked: callBox.command("take-over")
                }
                PillButton {
                    Layout.fillWidth: true
                    iconName: "hang-up"
                    text: i18nc("@action:button end the call", "Hang up")
                    negative: true
                    onClicked: callBox.command("hang-up")
                }
            }
        }
    }

    Component {
        id: approval
        Outlined {
            Text {
                text: i18nc("@title", "Needs your approval")
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
                PillButton { text: i18nc("@action:button", "Allow"); onClicked: AgentClient.approve(entry.itemId, "allow") }
                PillButton { text: i18nc("@action:button", "Allow for this conversation"); onClicked: AgentClient.approve(entry.itemId, "allow-session") }
                PillButton { text: i18nc("@action:button", "Deny"); negative: true; onClicked: AgentClient.approve(entry.itemId, "deny") }
            }
            Text {
                visible: entry.status !== "pending"
                text: entry.status === "decline" ? i18nc("@info:status an approval", "Denied")
                    : entry.status === "accept" ? i18nc("@info:status an approval", "Allowed") : i18nc("@info:status an approval", "Expired")
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
                        text: entry.text || i18nc("@title", "One more step: set up an OpenAI API key")
                        wrapMode: Text.Wrap
                        font.family: Theme.fontFamily
                        font.pixelSize: Theme.bodySize
                        font.weight: Font.DemiBold
                        color: Theme.text
                    }
                    Text {
                        Layout.fillWidth: true
                        text: entry.output || i18nc("@info", "Once it's set up, I can use the phone for you.")
                        wrapMode: Text.Wrap
                        font.family: Theme.fontFamily
                        font.pixelSize: Theme.metaSize
                        color: Theme.dim
                    }
                }
            }
            PillButton { text: i18nc("@action:button", "Go to settings"); onClicked: entry.openSettings(entry.command) }
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
