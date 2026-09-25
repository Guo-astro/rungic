// SPDX-License-Identifier: GPL-2.0-or-later
import QtQuick
import QtQuick.Controls as QQC2
import QtQuick.Layouts
import org.kde.kirigami as Kirigami
import dev.moto.voiceassistant

Kirigami.Page {
    id: page
    property string conversationId: ""
    padding: 0

    readonly property var phaseText: ({
        connecting: "正在连接…", ready: "按住说话", listening: "正在听，松开结束",
        speaking: "正在回答（按住可打断）", working: "正在处理…", closed: "已断开"
    })

    ChatModel { id: chat }
    title: chat.title

    Connections {
        target: AgentClient
        function onConversationOpened(json) {
            const opened = JSON.parse(json)
            page.conversationId = opened.conversation
            chat.load(opened)
            view.positionViewAtEnd()
        }
        function onEvent(json) {
            const e = JSON.parse(json)
            if (e.conversation && e.conversation !== page.conversationId) return
            if (e.type === "level") return
            chat.apply(e, true)
            if (e.type !== "state") Qt.callLater(view.positionViewAtEnd)
        }
        function onFailed(message) { chat.apply({ type: "error", text: message }, true) }
    }

    Component.onCompleted: AgentClient.openConversation(conversationId)
    Component.onDestruction: AgentClient.closeConversation(page.conversationId)

    ColumnLayout {
        anchors.fill: parent
        spacing: 0

        ListView {
            id: view
            Layout.fillWidth: true
            Layout.fillHeight: true
            clip: true
            model: chat.entries
            spacing: Kirigami.Units.smallSpacing
            topMargin: Kirigami.Units.largeSpacing
            bottomMargin: Kirigami.Units.largeSpacing
            delegate: ChatItem { callMonitor: chat.callMonitor }
            QQC2.ScrollBar.vertical: QQC2.ScrollBar {}

            Kirigami.PlaceholderMessage {
                anchors.centerIn: parent
                width: parent.width - Kirigami.Units.gridUnit * 4
                visible: chat.entries.count === 0
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
                    text: chat.callPhase === "user" ? "你正在通话中，挂断后语音助手自动恢复"
                        : chat.inCall ? (talk.holding ? "正在听，松开后转给通话助理" : "按住对通话助理说（对方听不到）")
                        : talk.holding ? page.phaseText.listening : (page.phaseText[chat.phase] || "")
                    opacity: 0.7
                }
                TalkButton {
                    id: talk
                    anchors.horizontalCenter: parent.horizontalCenter
                    enabled: page.conversationId.length > 0 && chat.callPhase !== "user"
                }
            }
            // Stops the running task (and the reply being spoken); speaking works as well.
            QQC2.Button {
                anchors.verticalCenter: footer.bottom
                anchors.verticalCenterOffset: -talk.height / 2
                anchors.left: footer.right
                anchors.leftMargin: Kirigami.Units.largeSpacing * 2
                visible: chat.agentBusy || chat.phase === "speaking"
                icon.name: "media-playback-stop"
                text: "停止"
                display: QQC2.AbstractButton.TextUnderIcon
                onClicked: AgentClient.stopTask()
            }
        }
    }
}
