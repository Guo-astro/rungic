// SPDX-License-Identifier: GPL-2.0-or-later
// A conversation (docs/59): its entries in a reading column, bottom-aligned, and the
// light at the bottom to talk. Holding it raises the light as in the Home button's
// overlay (docs/67); a tap listens hands-free.
import QtQuick
import QtQuick.Window
import QtQuick.Controls as QQC2
import org.kde.kirigami as Kirigami
import com.rungic.voiceassistant

Kirigami.Page {
    id: page
    property string conversationId: ""
    property string initialTitle: ""        // from the list, shown until the conversation arrives
    property bool loaded: false
    padding: 0
    globalToolBarStyle: Kirigami.ApplicationHeaderStyle.None
    background: Rectangle { color: "transparent" }   // the window draws the ground

    ChatModel { id: chat }
    title: chat.title

    property bool holding: false
    property real micLevel: -90
    readonly property bool listening: holding || chat.phase === "listening"
    readonly property bool busy: chat.agentBusy || chat.phase === "working"
    readonly property bool speaking: chat.phase === "speaking"
    readonly property string screenName: Window.window ? Window.window.screen.name : ""

    Connections {
        target: AgentClient
        function onConversationOpened(json) {
            const opened = JSON.parse(json)
            // Another page (the list starting a new conversation) may have asked for it.
            if (page.conversationId && opened.conversation !== page.conversationId) return
            page.conversationId = opened.conversation
            chat.load(opened)
            view.follow = true
            view.positionViewAtEnd()
            page.loaded = true
        }
        function onEvent(json) {
            const e = JSON.parse(json)
            if (e.conversation && e.conversation !== page.conversationId) return
            if (e.type === "level") { page.micLevel = e.db; return }
            chat.apply(e, true)
            if (e.type !== "state") Qt.callLater(view.stickToEnd)
        }
        function onFailed(message) { chat.apply({ type: "error", text: message }, true) }
    }

    Component.onCompleted: AgentClient.openConversation(conversationId)
    Component.onDestruction: if (conversationId) AgentClient.closeConversation(conversationId)

    // ---- the light's clock: 60 Hz while something happens, still otherwise --------
    property real time: 0
    property real energy: 0
    Timer {
        property real last: 0
        interval: 16
        repeat: true
        running: page.visible && (page.listening || page.busy || page.speaking || bloom.rise > 0.001)
        onRunningChanged: last = Date.now()
        onTriggered: {
            const now = Date.now()
            const dt = Math.min(0.1, (now - last) / 1000)
            page.time += dt
            const voice = page.listening ? Math.max(0, Math.min(1, (page.micLevel + 55) / 35)) : 0
            page.energy += (voice - page.energy) * (1 - Math.exp(-dt / 0.08))
            last = now
        }
    }
    // Seconds of the running agent turn, for the status line.
    property real now: Date.now() / 1000
    Timer { interval: 1000; repeat: true; running: page.visible && page.busy; onTriggered: page.now = Date.now() / 1000 }
    readonly property int workSeconds: chat.workOpen && chat.workAt >= 0 && chat.workAt < chat.entries.count
                                       ? Math.max(0, Math.round(now - chat.entries.get(chat.workAt).started)) : 0

    // ---- header ----------------------------------------------------------------------
    Item {
        id: header
        anchors { left: parent.left; right: parent.right; top: parent.top }
        height: 70
        GlassButton {
            id: back
            anchors { left: parent.left; leftMargin: 16; verticalCenter: parent.verticalCenter }
            visible: !applicationWindow().pageStack.wideMode
            iconName: "go-previous-symbolic"
            label: "返回"
            onClicked: applicationWindow().pageStack.goBack()
        }
        Text {
            anchors {
                left: back.visible ? back.right : parent.left; leftMargin: back.visible ? 12 : 40
                right: parent.right; rightMargin: 24; verticalCenter: parent.verticalCenter
            }
            text: page.loaded ? chat.title : page.initialTitle
            elide: Text.ElideRight
            color: Style.ink
            font.pixelSize: page.width > 700 ? 18 : 17
            font.weight: Font.DemiBold
        }
    }

    // ---- the conversation ------------------------------------------------------------
    ListView {
        id: view
        // The width of the page: the scroll bar sits at the screen's edge; ChatItem keeps the
        // entries to a centred reading column.
        readonly property real column: Math.min(page.width - 40, Style.readingWidth)
        // Short conversations sit just above the talk control, as speech does: the view is
        // only as tall as what it holds, up to the space there is.
        readonly property real room: dock.y + 8 - header.height
        anchors { bottom: dock.top; bottomMargin: -8; left: parent.left; right: parent.right }
        height: Math.min(contentHeight + 8, room)
        clip: true
        // Comes in once loaded, already at its end.
        opacity: page.loaded ? 1 : 0
        Behavior on opacity { NumberAnimation { duration: 220; easing.type: Easing.OutCubic } }
        model: chat.entries
        delegate: ChatItem { callMonitor: chat.callMonitor }
        // New content keeps the view at the end only while the reader is there. Scrolled up,
        // the view stays put: while it scrolls, ListView creates delegates and re-estimates its
        // content height, and following every change threw the reader back to the end.
        property bool follow: true
        function stickToEnd() { if (follow) positionViewAtEnd() }
        onContentHeightChanged: if (follow && !moving) Qt.callLater(stickToEnd)
        onMovementStarted: follow = false
        onMovementEnded: follow = atYEnd
        // Touch: an indicator only. The attached ScrollBar is a control: it wrote its clamped
        // position back when a drag past the end ended (or a finger at the edge touched it), so
        // the view snapped to the end in one frame instead of springing back.
        QQC2.ScrollIndicator.vertical: QQC2.ScrollIndicator {
            id: bar
            padding: 2
            contentItem: Rectangle {
                implicitWidth: 3
                radius: 1.5
                color: Style.track
                opacity: bar.active ? 1 : 0
                Behavior on opacity { NumberAnimation { duration: 300 } }
            }
        }
        // Past either end the content stretches a little and springs back, instead of
        // leaving empty space under the finger.
        boundsMovement: Flickable.StopAtBounds
        transform: Scale {
            origin.x: view.width / 2
            origin.y: view.verticalOvershoot > 0 ? view.height : 0
            yScale: 1 + 0.08 * Math.min(Math.abs(view.verticalOvershoot) / Math.max(1, view.height), 1)
        }
    }

    // Still loading: said after a moment (a quick load shows nothing in between).
    Timer { id: slowLoad; interval: 150; running: !page.loaded }
    Column {
        anchors.centerIn: parent
        spacing: 12
        opacity: !page.loaded && !slowLoad.running ? 1 : 0
        visible: opacity > 0
        Behavior on opacity { NumberAnimation { duration: 180 } }
        Spinner {
            anchors.horizontalCenter: parent.horizontalCenter
            scale: 1.5
        }
        Text {
            anchors.horizontalCenter: parent.horizontalCenter
            text: "正在打开…"
            color: Style.dim
            font.pixelSize: 14
        }
    }

    // Scrolled away from the end: a way back.
    GlassButton {
        anchors { horizontalCenter: parent.horizontalCenter; bottom: dock.top; bottomMargin: 4 }
        visible: !view.follow && !view.atYEnd && view.contentHeight > view.height
        iconName: "arrow-down-symbolic"
        label: "回到最新"
        onClicked: {
            view.follow = true
            view.positionViewAtEnd()
        }
    }

    // Nothing said yet.
    Column {
        anchors { horizontalCenter: parent.horizontalCenter; verticalCenter: parent.verticalCenter; verticalCenterOffset: -40 }
        width: view.column
        leftPadding: 8
        spacing: 22
        visible: page.loaded && chat.entries.count === 0
        Text {
            text: "有什么可以帮你？"
            color: Style.ink
            font.pixelSize: 28
            font.weight: Font.Medium
        }
        Column {
            width: parent.width - 16
            spacing: 8
            Text { text: "比如"; color: Style.faint; font.pixelSize: 13 }
            Repeater {
                model: ["手机还剩多少存储空间？", "把屏幕调暗一点", "帮我整理一下下载文件夹"]
                delegate: Rectangle {
                    required property string modelData
                    width: parent.width
                    height: 46
                    radius: 16
                    color: Style.surface
                    Text {
                        anchors { left: parent.left; leftMargin: 16; verticalCenter: parent.verticalCenter }
                        text: "“" + parent.modelData + "”"
                        color: Style.inkSoft
                        font.pixelSize: 15
                    }
                }
            }
        }
    }

    // ---- the light, rising while listening ---------------------------------------------
    Rectangle {
        anchors { left: parent.left; right: parent.right; bottom: parent.bottom }
        height: bloom.height
        opacity: bloom.rise
        gradient: Gradient {
            GradientStop { position: 0.0; color: Style.fade(0) }
            GradientStop { position: 0.55; color: Style.fade(0.9) }
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
        rise: page.listening ? 1 : 0
        Behavior on rise { NumberAnimation { duration: 380; easing.type: Easing.OutCubic } }
        visible: rise > 0.001
    }

    TalkDock {
        id: dock
        anchors { left: parent.left; right: parent.right; bottom: parent.bottom }
        time: page.time
        canTalk: page.conversationId.length > 0 && chat.callPhase !== "user"
        mode: page.listening ? "listen" : page.busy ? "work" : page.speaking ? "speak" : "idle"
        showStop: page.busy || page.speaking
        glowing: page.listening || page.busy || page.speaking
        label: chat.callPhase === "user" ? "你正在通话中，挂断后语音助手自动恢复"
             : chat.inCall ? (page.holding ? "正在听，松开后转给通话助理" : "按住回答助理（对方听不到）")
             : page.listening ? "正在听"
             : page.speaking ? "正在回答 · 按住可打断"
             : page.busy ? "正在处理 · " + page.workSeconds + " 秒"
             : chat.phase === "connecting" ? "正在连接…"
             : chat.phase === "closed" ? "已断开"
             : "按住说话，轻点免提"
        hint: chat.inCall ? ""
            : page.holding ? "松开发送 · 手指滑开取消"
            : chat.handsFree ? "说完自动发送 · 轻点结束" : ""
        onTalkPressed: {
            // Talking brings the conversation back to its end.
            view.follow = true
            view.positionViewAtEnd()
            if (chat.handsFree) { AgentClient.stopTalking(); return }
            page.holding = true
            AgentClient.startTalking(page.screenName)
        }
        onTalkReleased: inside => {
            if (!page.holding) return
            page.holding = false
            if (inside) AgentClient.releaseTalking()
            else AgentClient.cancelTalking()
        }
        onStopClicked: AgentClient.stopTask()
    }
}
