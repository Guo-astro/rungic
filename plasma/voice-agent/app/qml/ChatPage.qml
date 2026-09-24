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
    title: "新对话"
    padding: 0

    readonly property var phaseText: ({
        connecting: "正在连接…", ready: "按住说话", listening: "正在听，松开结束",
        speaking: "正在回答（按住可打断）", working: "正在处理…", closed: "已断开"
    })

    ListModel { id: chat }

    function entry(fields) {
        return Object.assign({ kind: "", role: "", text: "", itemId: "", command: "", output: "",
                               status: "", exitCode: "" }, fields)
    }
    function find(kind, id) {
        for (let i = chat.count - 1; i >= 0; i--) {
            const e = chat.get(i)
            if (e.kind === kind && e.itemId === id) return i
        }
        return -1
    }
    function apply(e, live) {
        switch (e.type) {
        case "delta": {
            if (!live || !e.text) return
            const kind = e.role === "user" ? "live-user" : "live-assistant"
            const last = chat.count > 0 ? chat.get(chat.count - 1) : null
            if (last && last.kind === kind) chat.setProperty(chat.count - 1, "text", last.text + e.text)
            else chat.append(entry({ kind: kind, role: e.role === "user" ? "user" : "assistant", text: e.text }))
            break
        }
        case "message": {
            const kind = e.role === "user" ? "live-user" : "live-assistant"
            for (let i = chat.count - 1; i >= 0 && i >= chat.count - 4; i--) {
                if (chat.get(i).kind === kind) { chat.remove(i); break }
            }
            const last = chat.count > 0 ? chat.get(chat.count - 1) : null
            // The agent can start before the transcript of what started it arrives.
            if (e.role === "user" && last && last.kind === "marker" && last.text === "开始处理")
                chat.insert(chat.count - 1, entry({ kind: "message", role: e.role, text: e.text }))
            else
                chat.append(entry({ kind: "message", role: e.role, text: e.text }))
            if (e.role === "user" && page.title === "新对话") page.title = e.text.slice(0, 20)
            break
        }
        case "agent-started": chat.append(entry({ kind: "marker", text: "开始处理" })); break
        case "agent-finished": chat.append(entry({ kind: "marker", text: "处理完成" })); break
        case "agent-message": chat.append(entry({ kind: "agent", text: e.text, itemId: e.id || "" })); break
        case "command": {
            const fields = { status: e.status, exitCode: e.exitCode === null || e.exitCode === undefined ? "" : String(e.exitCode),
                             output: e.output || "" }
            const at = find("command", e.id)
            if (at >= 0) { for (const k in fields) chat.setProperty(at, k, fields[k]) }
            else chat.append(entry(Object.assign({ kind: "command", itemId: e.id, command: e.command }, fields)))
            break
        }
        case "files": chat.append(entry({ kind: "files", text: (e.paths || []).join("\n") })); break
        case "approval": {
            const pending = e.status === "pending" && live
            chat.append(entry({ kind: "approval", itemId: e.id, text: e.reason || "",
                                command: e.kind === "command" ? e.text : "", status: pending ? "pending" : "expired" }))
            break
        }
        case "approval-result": {
            const at = find("approval", e.id)
            if (at >= 0) chat.setProperty(at, "status", e.decision === "decline" ? "decline" : "accept")
            break
        }
        case "error": chat.append(entry({ kind: "error", text: e.text })); break
        case "state": page.phase = e.phase; break
        }
    }

    Connections {
        target: AgentClient
        function onConversationOpened(json) {
            const opened = JSON.parse(json)
            page.conversationId = opened.conversation
            page.title = opened.title
            chat.clear()
            for (const e of opened.history) page.apply(e, false)
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
        }
    }
}
