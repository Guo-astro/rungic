// SPDX-License-Identifier: GPL-2.0-or-later
import QtQuick
import QtQuick.Controls as QQC2
import QtQuick.Layouts
import org.kde.kirigami as Kirigami
import dev.moto.voiceassistant

Kirigami.Page {
    id: page
    property string conversationId: ""
    property string phase: "connecting"
    property bool agentBusy: false
    title: "新对话"
    padding: 0

    readonly property var phaseText: ({
        connecting: "正在连接…", ready: "按住说话", listening: "正在听，松开结束",
        speaking: "正在回答（按住可打断）", working: "正在处理…", closed: "已断开"
    })

    ListModel { id: chat }

    // The chat groups what happens in a turn, like ChatGPT/Codex (docs/59):
    // - all transcript pieces of one push-to-talk press form one user message;
    // - an agent turn is one collapsible "work" entry holding what the assistant
    //   said meanwhile, the agent's notes, commands and file changes;
    // - replies outside agent work are bubbles: the acknowledgement before it and
    //   the answer afterwards. Entries never disappear once shown.
    property int workAt: -1          // the work entry receiving agent activity
    property bool workOpen: false    // an agent turn is running
    property real lastTime: 0        // of the latest event (a turn the history left open ends there)

    function entry(fields) {
        return Object.assign({ kind: "", role: "", text: "", itemId: "", command: "", output: "",
                               status: "", exitCode: "", press: 0, started: 0, finished: 0,
                               expanded: false, steps: [] }, fields)
    }
    function step(fields) {
        return Object.assign({ kind: "", text: "", itemId: "", command: "", output: "", status: "", exitCode: "" }, fields)
    }
    function lastOf(kind, role) {
        for (let i = chat.count - 1; i >= 0; i--) {
            const e = chat.get(i)
            if (e.kind === kind && (role === undefined || e.role === role)) return i
        }
        return -1
    }
    // Chinese needs no space between pieces; Latin words do.
    function join(a, b) {
        return /[A-Za-z0-9,.!?]$/.test(a) && /^[A-Za-z0-9]/.test(b) ? a + " " + b : a + b
    }
    function addStep(fields) {
        if (page.workAt < 0) return
        chat.get(page.workAt).steps.append(step(fields))
        if (fields.kind !== "command" || !fields.status || fields.status === "running")
            chat.setProperty(page.workAt, "text", fields.kind === "command" ? fields.command : fields.text)
    }
    function removeAt(i) {
        chat.remove(i)
        if (page.workAt > i) page.workAt--
        else if (page.workAt === i) page.workAt = -1
    }
    function insertAt(i, fields) {
        chat.insert(i, entry(fields))
        if (page.workAt >= i) page.workAt++
    }

    function apply(e, live) {
        if (e.time && e.type !== "state") page.lastTime = e.time
        switch (e.type) {
        case "delta": {
            if (!live || !e.text) return
            if (e.role === "user") {
                const at = lastOf("live-user")
                if (at >= 0 && chat.get(at).press === (e.press || 0)) chat.setProperty(at, "text", chat.get(at).text + e.text)
                else chat.append(entry({ kind: "live-user", role: "user", text: e.text, press: e.press || 0 }))
            } else if (page.workOpen && page.workAt >= 0) {
                // Spoken progress streams into the work entry's status line.
                const w = chat.get(page.workAt)
                chat.setProperty(page.workAt, "text", w.status === "live" ? w.text + e.text : e.text)
                chat.setProperty(page.workAt, "status", "live")
            } else {
                const last = chat.count > 0 ? chat.get(chat.count - 1) : null
                if (last && last.kind === "live-assistant") chat.setProperty(chat.count - 1, "text", last.text + e.text)
                else chat.append(entry({ kind: "live-assistant", role: "assistant", text: e.text }))
            }
            break
        }
        case "message": {
            const liveAt = lastOf(e.role === "user" ? "live-user" : "live-assistant")
            if (liveAt >= 0 && liveAt >= chat.count - 4) page.removeAt(liveAt)
            if (e.role === "user") {
                const at = lastOf("message", "user")
                if (e.press && at >= 0 && chat.get(at).press === e.press) {
                    chat.setProperty(at, "text", page.join(chat.get(at).text, e.text))
                } else if (page.workAt >= 0 && page.workAt === chat.count - 1 && live
                           && chat.get(page.workAt).steps.count <= 1 && e.time - chat.get(page.workAt).started < 8) {
                    // The agent can start before the transcript of what started it arrives.
                    page.insertAt(page.workAt, { kind: "message", role: "user", text: e.text, press: e.press || 0 })
                } else {
                    // A new request: earlier turns' work folds away again.
                    for (let i = 0; i < chat.count; i++) {
                        if (chat.get(i).kind === "work" && chat.get(i).expanded) chat.setProperty(i, "expanded", false)
                    }
                    chat.append(entry({ kind: "message", role: "user", text: e.text, press: e.press || 0 }))
                }
                if (page.title === "新对话") page.title = e.text.slice(0, 20)
            } else if (page.workOpen && page.workAt >= 0) {
                if (chat.get(page.workAt).status === "live") chat.setProperty(page.workAt, "status", "running")
                page.addStep({ kind: "said", text: e.text })
            } else {
                chat.append(entry({ kind: "message", role: "assistant", text: e.text }))
            }
            break
        }
        case "agent-started": {
            // The acknowledgement before it ("好的，我来…") stays a bubble: it was shown
            // before anyone knew work would follow, and nothing on screen should vanish.
            chat.append(entry({ kind: "work", status: "running", started: e.time || Date.now() / 1000 }))
            page.workAt = chat.count - 1
            page.workOpen = true
            break
        }
        case "agent-finished":
            if (page.workAt >= 0) {
                if (chat.get(page.workAt).status !== "stopped") chat.setProperty(page.workAt, "status", "done")
                chat.setProperty(page.workAt, "finished", e.time || Date.now() / 1000)
            }
            page.workOpen = false
            break
        case "task-stopped":
            if (page.workAt >= 0 && page.workOpen) chat.setProperty(page.workAt, "status", "stopped")
            else chat.append(entry({ kind: "marker", text: "已停止" }))
            break
        case "agent-message":
            if (page.workAt < 0) {
                chat.append(entry({ kind: "work", status: "done", started: e.time || 0, finished: e.time || 0 }))
                page.workAt = chat.count - 1
            }
            page.addStep({ kind: e.final ? "answer" : "note", text: e.text, itemId: e.id || "" })
            break
        case "command": {
            if (page.workAt < 0) return
            const fields = { status: e.status, exitCode: e.exitCode === null || e.exitCode === undefined ? "" : String(e.exitCode),
                             output: e.output || "" }
            const steps = chat.get(page.workAt).steps
            let at = -1
            for (let i = steps.count - 1; i >= 0; i--) if (steps.get(i).kind === "command" && steps.get(i).itemId === e.id) { at = i; break }
            if (at >= 0) { for (const k in fields) steps.setProperty(at, k, fields[k]) }
            else page.addStep(Object.assign({ kind: "command", itemId: e.id, command: e.command }, fields))
            break
        }
        case "files": page.addStep({ kind: "files", text: (e.paths || []).join("\n") }); break
        case "approval": {
            const pending = e.status === "pending" && live
            chat.append(entry({ kind: "approval", itemId: e.id, text: e.reason || "",
                                command: e.kind === "command" ? e.text : "", status: pending ? "pending" : "expired" }))
            break
        }
        case "approval-result": {
            for (let i = chat.count - 1; i >= 0; i--) {
                if (chat.get(i).kind === "approval" && chat.get(i).itemId === e.id) {
                    chat.setProperty(i, "status", e.decision === "decline" ? "decline" : "accept")
                    break
                }
            }
            break
        }
        case "error": chat.append(entry({ kind: "error", text: e.text })); break
        case "state": page.phase = e.phase; page.agentBusy = !!e.agentBusy; break
        }
    }

    Connections {
        target: AgentClient
        function onConversationOpened(json) {
            const opened = JSON.parse(json)
            page.conversationId = opened.conversation
            page.title = opened.title
            chat.clear()
            page.workAt = -1
            page.workOpen = false
            for (const e of opened.history) page.apply(e, false)
            // A turn that was running when the history was saved is not running now.
            if (page.workOpen && page.workAt >= 0) {
                chat.setProperty(page.workAt, "status", "done")
                chat.setProperty(page.workAt, "finished", page.lastTime)
                page.workOpen = false
            }
            view.positionViewAtEnd()
        }
        function onEvent(json) {
            const e = JSON.parse(json)
            if (e.conversation && e.conversation !== page.conversationId) return
            page.apply(e, true)
            if (e.type !== "state") Qt.callLater(view.positionViewAtEnd)
        }
        function onFailed(message) { page.apply({ type: "error", text: message }, true) }
    }

    Component.onCompleted: AgentClient.openConversation(conversationId)
    Component.onDestruction: AgentClient.closeConversation()

    ColumnLayout {
        anchors.fill: parent
        spacing: 0

        ListView {
            id: view
            Layout.fillWidth: true
            Layout.fillHeight: true
            clip: true
            model: chat
            spacing: Kirigami.Units.smallSpacing
            topMargin: Kirigami.Units.largeSpacing
            bottomMargin: Kirigami.Units.largeSpacing
            delegate: ChatItem {}
            QQC2.ScrollBar.vertical: QQC2.ScrollBar {}

            Kirigami.PlaceholderMessage {
                anchors.centerIn: parent
                width: parent.width - Kirigami.Units.gridUnit * 4
                visible: chat.count === 0
                icon.name: "audio-input-microphone"
                text: "按住下面的按钮说话"
                explanation: "比如：“手机还剩多少存储空间？”“把屏幕调暗一点”“帮我整理一下下载文件夹”"
            }
        }

        Kirigami.Separator { Layout.fillWidth: true }

        Item {
            Layout.fillWidth: true
            implicitHeight: footer.implicitHeight + Kirigami.Units.largeSpacing * 2
            Column {
                id: footer
                anchors.centerIn: parent
                spacing: Kirigami.Units.smallSpacing
                QQC2.Label {
                    anchors.horizontalCenter: parent.horizontalCenter
                    text: talk.holding ? page.phaseText.listening : (page.phaseText[page.phase] || "")
                    opacity: 0.7
                }
                TalkButton {
                    id: talk
                    anchors.horizontalCenter: parent.horizontalCenter
                    enabled: page.conversationId.length > 0
                }
            }
            // Stops the running task (and the reply being spoken); speaking works as well.
            QQC2.Button {
                anchors.verticalCenter: footer.bottom
                anchors.verticalCenterOffset: -talk.height / 2
                anchors.left: footer.right
                anchors.leftMargin: Kirigami.Units.largeSpacing * 2
                visible: page.agentBusy || page.phase === "speaking"
                icon.name: "media-playback-stop"
                text: "停止"
                display: QQC2.AbstractButton.TextUnderIcon
                onClicked: AgentClient.stopTask()
            }
        }
    }
}
