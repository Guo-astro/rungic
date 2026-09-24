// SPDX-License-Identifier: GPL-2.0-or-later
import QtQuick
import QtQuick.Controls as QQC2
import QtQuick.Layouts
import org.kde.kirigami as Kirigami
import dev.moto.voiceassistant

Kirigami.ScrollablePage {
    id: page
    title: "语音助手"

    actions: [
        Kirigami.Action {
            icon.name: "list-add"
            text: "新对话"
            onTriggered: page.openChat("")
        }
    ]

    function openChat(id) {
        applicationWindow().pageStack.push(Qt.resolvedUrl("ChatPage.qml"), { conversationId: id })
    }

    function when(seconds) {
        const date = new Date(seconds * 1000)
        const today = new Date()
        return date.toDateString() === today.toDateString()
            ? date.toLocaleTimeString(Qt.locale(), "HH:mm")
            : date.toLocaleDateString(Qt.locale(), "M月d日")
    }

    ListModel { id: conversations }

    Connections {
        target: AgentClient
        function onConversationsListed(json) {
            conversations.clear()
            for (const c of JSON.parse(json)) {
                conversations.append({ cid: c.id, title: c.title || "新对话", updated: c.updated || c.created || 0 })
            }
        }
        function onEvent(json) {
            const e = JSON.parse(json)
            if (e.type === "message" && e.role === "user") AgentClient.listConversations()
        }
        function onFailed(message) { page.errorText = message }
    }
    property string errorText: ""

    Component.onCompleted: AgentClient.listConversations()
    onVisibleChanged: if (visible) AgentClient.listConversations()

    ListView {
        id: list
        model: conversations
        delegate: QQC2.ItemDelegate {
            required property string cid
            required property string title
            required property real updated
            width: ListView.view.width
            onClicked: page.openChat(cid)
            contentItem: RowLayout {
                spacing: Kirigami.Units.largeSpacing
                Kirigami.Icon { source: "dialog-messages"; implicitWidth: Kirigami.Units.iconSizes.medium; implicitHeight: implicitWidth }
                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: 0
                    QQC2.Label { text: title; elide: Text.ElideRight; Layout.fillWidth: true; font.bold: true }
                    QQC2.Label { text: page.when(updated); opacity: 0.6; font.pointSize: Kirigami.Theme.smallFont.pointSize }
                }
                QQC2.ToolButton {
                    icon.name: "delete"
                    onClicked: { AgentClient.deleteConversation(cid); conversations.remove(index) }
                    QQC2.ToolTip.text: "删除"
                }
            }
        }

        Kirigami.PlaceholderMessage {
            anchors.centerIn: parent
            width: parent.width - Kirigami.Units.gridUnit * 4
            visible: list.count === 0
            icon.name: "audio-input-microphone"
            text: page.errorText ? "无法连接语音助手服务" : "还没有对话"
            explanation: page.errorText || "点“新对话”，然后按住按钮说话"
            helpfulAction: Kirigami.Action {
                icon.name: "list-add"
                text: "新对话"
                onTriggered: page.openChat("")
            }
        }
    }
}
