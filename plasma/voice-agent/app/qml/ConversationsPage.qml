// SPDX-License-Identifier: GPL-2.0-or-later
// The conversations (docs/59): the Home button's assistant conversation pinned on top,
// the others by day with their last word; swipe one left to delete it. Holding the
// light at the bottom starts a new conversation and listens at once; the page opens
// when the finger lifts.
import QtQuick
import QtQuick.Window
import QtQuick.Controls as QQC2
import org.kde.kirigami as Kirigami
import dev.moto.voiceassistant

Kirigami.Page {
    id: page
    title: "语音助手"
    padding: 0
    globalToolBarStyle: Kirigami.ApplicationHeaderStyle.None
    background: Rectangle { color: "transparent" }   // the window draws the ground

    function openChat(id, title) {
        applicationWindow().openChat(id, title)
    }

    function when(seconds) {
        const date = new Date(seconds * 1000)
        const today = new Date()
        return date.toDateString() === today.toDateString()
            ? date.toLocaleTimeString(Qt.locale(), "HH:mm")
            : date.toLocaleDateString(Qt.locale(), "M月d日")
    }
    function day(seconds) {
        const date = new Date(seconds * 1000)
        return date.toDateString() === new Date().toDateString() ? "今天" : date.toLocaleDateString(Qt.locale(), "M月d日")
    }

    ListModel { id: conversations }
    property var pinned: null            // the assistant's conversation, if it has been used
    property string errorText: ""

    Connections {
        target: AgentClient
        function onConversationsListed(json) {
            conversations.clear()
            page.pinned = null
            for (const c of JSON.parse(json)) {
                const item = { cid: c.id, title: c.title || "新对话", preview: c.preview || "",
                               updated: c.updated || c.created || 0 }
                if (c.assistant) page.pinned = item
                else conversations.append(Object.assign(item, { day: page.day(item.updated) }))
            }
            page.errorText = ""
        }
        function onConversationOpened(json) {
            if (!newTalk.waiting) return
            newTalk.opened(JSON.parse(json).conversation)
        }
        function onEvent(json) {
            const e = JSON.parse(json)
            if (e.type === "message") listTimer.restart()
            if (e.type === "level" && newTalk.holding) page.micLevel = e.db
        }
        function onFailed(message) { page.errorText = message }
    }
    // Messages come in bursts: list once they settle.
    Timer { id: listTimer; interval: 600; onTriggered: AgentClient.listConversations() }

    Component.onCompleted: AgentClient.listConversations()
    onVisibleChanged: if (visible) AgentClient.listConversations()

    // Holding the light: a new conversation, listening from the first moment. The service
    // opens the conversation, then the microphone; a finger lifted before that is kept.
    QtObject {
        id: newTalk
        property bool holding: false
        property bool waiting: false         // the new conversation is being opened
        property bool lifted: false
        property bool keep: true             // lifted near the light (else dropped)
        property string conversation: ""
        function press() {
            holding = true; lifted = false; conversation = ""; waiting = true
            AgentClient.openConversation("")
        }
        function opened(id) {
            waiting = false
            conversation = id
            AgentClient.startTalking(page.Window.window ? page.Window.window.screen.name : "")
            if (lifted) finish()
        }
        function release(inside) {
            holding = false
            lifted = true
            keep = inside
            if (!waiting) finish()
        }
        function finish() {
            if (!conversation) return
            if (keep) AgentClient.releaseTalking()
            else AgentClient.cancelTalking()
            if (keep) page.openChat(conversation, "新对话")
            else AgentClient.closeConversation(conversation)
        }
    }
    property real micLevel: -90
    property real energy: 0
    property real time: 0
    Timer {
        property real last: 0
        interval: 16
        repeat: true
        running: page.visible && (newTalk.holding || bloom.rise > 0.001)
        onRunningChanged: last = Date.now()
        onTriggered: {
            const now = Date.now()
            const dt = Math.min(0.1, (now - last) / 1000)
            page.time += dt
            const voice = newTalk.holding ? Math.max(0, Math.min(1, (page.micLevel + 55) / 35)) : 0
            page.energy += (voice - page.energy) * (1 - Math.exp(-dt / 0.08))
            last = now
        }
    }

    Flickable {
        id: flick
        anchors { left: parent.left; right: parent.right; top: parent.top; bottom: dock.top }
        contentHeight: column.implicitHeight
        clip: true
        // Past either end the list stretches a little and springs back (no empty space).
        boundsMovement: Flickable.StopAtBounds
        transform: Scale {
            origin.x: flick.width / 2
            origin.y: flick.verticalOvershoot > 0 ? flick.height : 0
            yScale: 1 + 0.08 * Math.min(Math.abs(flick.verticalOvershoot) / Math.max(1, flick.height), 1)
        }

        Column {
            id: column
            width: flick.width
            spacing: 0

            Text {
                x: 24
                topPadding: 28
                bottomPadding: 8
                text: "语音助手"
                color: Style.ink
                font.pixelSize: 32
                font.weight: Font.DemiBold
            }

            // The Home button's conversation.
            QQC2.AbstractButton {
                id: pinnedCard
                visible: page.pinned !== null
                x: 16
                width: parent.width - 32
                implicitHeight: pinnedColumn.implicitHeight + 32
                Accessible.name: "语音助手对话"
                onClicked: page.openChat(page.pinned.cid, "语音助手")
                background: Rectangle {
                    radius: 24
                    color: pinnedCard.pressed ? Qt.rgba(1, 1, 1, 0.09) : Style.surface
                    border.width: 1
                    border.color: Style.line
                }
                contentItem: Column {
                    id: pinnedColumn
                    leftPadding: 18
                    rightPadding: 18
                    topPadding: 16
                    spacing: 10
                    Row {
                        width: pinnedCard.width - 36
                        spacing: 12
                        LightPill {
                            anchors.verticalCenter: parent.verticalCenter
                            capsuleWidth: 40
                            capsuleHeight: 16
                            time: 0
                        }
                        Text {
                            width: parent.width - 52 - stamp.width - 12
                            anchors.verticalCenter: parent.verticalCenter
                            text: "语音助手"
                            color: Style.ink
                            font.pixelSize: 17
                            font.weight: Font.DemiBold
                        }
                        Text {
                            id: stamp
                            anchors.verticalCenter: parent.verticalCenter
                            text: page.pinned ? page.when(page.pinned.updated) : ""
                            color: Style.faint
                            font.pixelSize: 12
                        }
                    }
                    Text {
                        width: pinnedCard.width - 36
                        visible: text !== ""
                        text: page.pinned ? page.pinned.preview : ""
                        wrapMode: Text.Wrap
                        maximumLineCount: 2
                        elide: Text.ElideRight
                        color: Qt.rgba(1, 1, 1, 0.84)
                        font.pixelSize: 15
                        lineHeight: 1.1
                    }
                    Text {
                        text: "长按 Home 也会回到这里"
                        color: Style.faint
                        font.pixelSize: 12
                    }
                }
            }

            Repeater {
                model: conversations
                delegate: Column {
                    id: rowBox
                    required property int index
                    required property string cid
                    required property string title
                    required property string preview
                    required property real updated
                    required property string day
                    width: column.width
                    readonly property bool firstOfDay: index === 0 || conversations.get(index - 1).day !== day

                    Text {
                        visible: rowBox.firstOfDay
                        x: 24
                        topPadding: 18
                        bottomPadding: 4
                        text: rowBox.day
                        color: Style.faint
                        font.pixelSize: 13
                        font.weight: Font.Medium
                        font.letterSpacing: 0.8
                    }

                    // Swipe left to reveal "删除".
                    Item {
                        id: swipe
                        width: parent.width
                        height: 68
                        clip: true
                        property real offset: 0
                        readonly property real reveal: 88
                        Behavior on offset { enabled: !drag.active; NumberAnimation { duration: 180; easing.type: Easing.OutCubic } }

                        QQC2.AbstractButton {
                            anchors { right: parent.right; top: parent.top; bottom: parent.bottom }
                            width: swipe.reveal
                            visible: swipe.offset < 0
                            Accessible.name: "删除这个对话"
                            onClicked: {
                                AgentClient.deleteConversation(rowBox.cid)
                                conversations.remove(rowBox.index)
                            }
                            background: Rectangle { color: Style.danger }
                            contentItem: Column {
                                spacing: 4
                                topPadding: 14
                                Kirigami.Icon {
                                    anchors.horizontalCenter: parent.horizontalCenter
                                    width: 20; height: 20
                                    source: "edit-delete-symbolic"
                                    color: "white"
                                    isMask: true
                                }
                                Text {
                                    anchors.horizontalCenter: parent.horizontalCenter
                                    text: "删除"
                                    color: "white"
                                    font.pixelSize: 12
                                }
                            }
                        }

                        QQC2.AbstractButton {
                            id: rowButton
                            x: swipe.offset
                            width: parent.width
                            height: parent.height
                            Accessible.name: rowBox.title
                            onClicked: swipe.offset < 0 ? swipe.offset = 0 : page.openChat(rowBox.cid, rowBox.title)
                            background: Rectangle { color: rowButton.pressed ? Qt.rgba(1, 1, 1, 0.05) : Style.ground }
                            contentItem: Column {
                                leftPadding: 24
                                rightPadding: 24
                                topPadding: 12
                                spacing: 3
                                Row {
                                    width: rowButton.width - 48
                                    spacing: 10
                                    Text {
                                        width: parent.width - time.width - 10
                                        text: rowBox.title
                                        elide: Text.ElideRight
                                        color: Style.ink
                                        font.pixelSize: 16
                                        font.weight: Font.Medium
                                    }
                                    Text {
                                        id: time
                                        text: page.when(rowBox.updated)
                                        color: Style.faint
                                        font.pixelSize: 12
                                    }
                                }
                                Text {
                                    width: rowButton.width - 48
                                    text: rowBox.preview
                                    elide: Text.ElideRight
                                    color: Style.dim
                                    font.pixelSize: 14
                                }
                            }
                            DragHandler {
                                id: drag
                                target: null
                                xAxis.enabled: true
                                yAxis.enabled: false
                                property real from: 0
                                onActiveChanged: {
                                    if (active) from = swipe.offset
                                    else swipe.offset = swipe.offset < -swipe.reveal / 2 ? -swipe.reveal : 0
                                }
                                onTranslationChanged: if (active) swipe.offset = Math.max(-swipe.reveal * 1.2, Math.min(0, from + translation.x))
                            }
                        }
                    }
                }
            }

            // Nothing yet, or no service.
            Column {
                visible: conversations.count === 0 && page.pinned === null
                width: parent.width
                topPadding: 80
                spacing: 8
                Text {
                    anchors.horizontalCenter: parent.horizontalCenter
                    text: page.errorText ? "无法连接语音助手服务" : "还没有对话"
                    color: Style.ink
                    font.pixelSize: 19
                    font.weight: Font.Medium
                }
                Text {
                    width: parent.width - 64
                    anchors.horizontalCenter: parent.horizontalCenter
                    horizontalAlignment: Text.AlignHCenter
                    wrapMode: Text.Wrap
                    text: page.errorText || "按住下面的光带说话，就会开始一个新对话"
                    color: Style.dim
                    font.pixelSize: 14
                }
            }
            Item { width: 1; height: 16 }
        }
    }

    // The light rising while a new conversation listens.
    Rectangle {
        anchors { left: parent.left; right: parent.right; bottom: parent.bottom }
        height: bloom.height
        opacity: bloom.rise
        gradient: Gradient {
            GradientStop { position: 0.0; color: Qt.rgba(0.03, 0.035, 0.05, 0) }
            GradientStop { position: 0.55; color: Qt.rgba(0.03, 0.035, 0.05, 0.9) }
        }
    }
    Bloom {
        id: bloom
        anchors { left: parent.left; right: parent.right; bottom: parent.bottom }
        height: Math.min(page.height * 0.45, 420)
        spread: Math.min(width, 600)
        time: page.time
        level: page.energy
        rim: 0
        rise: newTalk.holding ? 1 : 0
        Behavior on rise { NumberAnimation { duration: 380; easing.type: Easing.OutCubic } }
        visible: rise > 0.001
    }

    TalkDock {
        id: dock
        anchors { left: parent.left; right: parent.right; bottom: parent.bottom }
        time: page.time
        mode: newTalk.holding ? "listen" : "idle"
        glowing: newTalk.holding
        label: newTalk.holding ? "正在听" : "按住光带，开始新对话"
        hint: newTalk.holding ? "松开发送 · 手指滑开取消" : ""
        onTalkPressed: newTalk.press()
        onTalkReleased: inside => newTalk.release(inside)
    }
}
