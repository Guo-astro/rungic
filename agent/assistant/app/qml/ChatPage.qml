// SPDX-License-Identifier: GPL-2.0-or-later
// A conversation (docs/59, docs/87): the top bar (conversations, title, new), the thread
// in a reading column, bottom-aligned, and the composer. A new conversation is only
// created in the agent when something is said or typed in it.
import QtQuick
import QtQuick.Layouts
import QtQuick.Window
import QtQuick.Controls as QQC2
import com.rungic.design
import com.rungic.voiceassistant

Item {
    id: page
    property var phone: ({sessionId: "", phase: "closed", muted: false})
    property string conversationId: ""        // "" = new, not created yet
    property string initialTitle: ""
    property bool loaded: true
    property bool creating: false             // the agent is creating this new conversation
    property var afterCreate: []              // what waits for it
    readonly property string screenName: Window.window ? Window.window.screen.name : ""
    Component.onCompleted: AgentClient.request("PhoneSnapshot")

    ChatModel { id: chat }
    readonly property alias model: chat

    // ---- opening and creating conversations -----------------------------------------
    function open(id, title) {
        if (id && id === conversationId) return
        if (conversationId) AgentClient.closeConversation(conversationId)
        chat.load({ title: "", history: [] })
        conversationId = id || ""
        initialTitle = title || ""
        creating = false
        afterCreate = []
        composer.reset()
        loaded = !id
        if (id) AgentClient.openConversation(id)
    }
    function newConversation() { open("", "") }
    // Runs `then` once the conversation exists in the agent.
    function ensure(then) {
        if (conversationId) { then(); return }
        afterCreate.push(then)
        if (creating) return
        creating = true
        AgentClient.openConversation("")
    }

    Connections {
        target: AgentClient
        function onConversationOpened(json) {
            const opened = JSON.parse(json)
            if (page.creating && !page.conversationId) {
                page.creating = false
                page.conversationId = opened.conversation
                // What was typed or said meanwhile is already on screen: keep it.
                const waiting = page.afterCreate
                page.afterCreate = []
                for (const then of waiting) then()
                drawer.refresh()
                AgentClient.request("PhoneSnapshot")
                return
            }
            if (opened.conversation !== page.conversationId) return
            chat.load(opened)
            AgentClient.request("PhoneSnapshot")
            view.follow = true
            view.positionViewAtEnd()
            page.loaded = true
        }
        function onEvent(json) {
            const e = JSON.parse(json)
            if (e.type === "phone-state") {
                page.phone = e
                for (const task of (e.tasks || [])) if (task.conversation === page.conversationId) chat.apply({type: "phone-task", task: task}, true)
                return
            }
            if (e.conversation && e.conversation !== page.conversationId) return
            if (e.type === "level") { composer.micLevel = e.db; return }
            // Codex restarted (a new key or sign-in) or the whole service did: this conversation
            // is opened again, and a turn that was running shows as ended.
            if (e.type === "agent-restarted") { if (page.conversationId) AgentClient.openConversation(page.conversationId); return }
            if (e.type === "preferences" || e.type === "account" || e.type === "install" || e.type === "agent-model" || e.type === "codex-update") return
            chat.apply(e, true)
            if (e.type !== "state") Qt.callLater(view.stickToEnd)
        }
        function onReplied(method, json) {
            const result = JSON.parse(json)
            if (result.error) { chat.apply({type: "error", text: result.error}, true); return }
            if (method === "PhoneSnapshot") {
                page.phone = result
                for (const task of (result.tasks || [])) if (task.conversation === page.conversationId) chat.apply({type: "phone-task", task: task}, true)
            }
        }
        function onFailed(message) { chat.apply({ type: "error", text: message }, true) }
        function onTextReady(json) { composer.dictated(JSON.parse(json).text || "") }
    }
    Component.onDestruction: if (conversationId) AgentClient.closeConversation(conversationId)
    // Presses, messages and Read aloud go to this page's conversation, whatever else was opened
    // meanwhile (the overlay, a restart, the warm-up; docs/89).
    Binding { target: AgentClient; property: "conversation"; value: page.conversationId }

    readonly property bool busy: chat.agentBusy || chat.phase === "working"
    readonly property bool speaking: chat.phase === "speaking"

    // ---- top bar -------------------------------------------------------------------
    Item {
        id: top
        anchors { left: parent.left; right: parent.right; top: parent.top }
        height: Theme.topBar
        IconButton {
            anchors { left: parent.left; leftMargin: 6; verticalCenter: parent.verticalCenter }
            iconName: "menu"
            text: i18nc("@action:button open the side panel", "Conversations")
            onClicked: drawer.open()
        }
        Text {
            anchors { left: parent.left; right: parent.right; leftMargin: 64; rightMargin: 64; verticalCenter: parent.verticalCenter }
            horizontalAlignment: Text.AlignHCenter
            text: !page.conversationId && chat.entries.count === 0 ? "Agent"
                : chat.titleText(page.loaded ? chat.title : page.initialTitle)
            elide: Text.ElideRight
            font.family: Theme.fontFamily
            font.pixelSize: Theme.titleSize
            font.weight: Font.DemiBold
            color: Theme.text
            Accessible.role: Accessible.Heading
        }
        IconButton {
            anchors { right: parent.right; rightMargin: 6; verticalCenter: parent.verticalCenter }
            iconName: "compose"
            text: i18nc("@action:button", "New conversation")
            enabled: page.conversationId !== "" || chat.entries.count > 0
            onClicked: page.newConversation()
        }
    }

    // ---- the thread ----------------------------------------------------------------
    ListView {
        id: view
        readonly property real column: Math.min(width - Theme.gutter * 2, Theme.readingWidth)
        anchors { left: parent.left; right: parent.right; top: top.bottom; bottom: phoneBar.top }
        clip: true
        // Short threads sit just above the composer.
        topMargin: Math.max(8, height - contentHeight - bottomMargin)
        // While held, the end of the thread (the user's waiting bubble) stays above the targets.
        bottomMargin: 12 + composer.overlap
        onBottomMarginChanged: if (follow) Qt.callLater(stickToEnd)
        spacing: 20
        opacity: page.loaded ? 1 : 0
        Behavior on opacity { NumberAnimation { duration: Theme.normal } }
        model: chat.entries
        delegate: ChatEntry {
            column: view.column
            callMonitor: chat.callMonitor
                callCanMonitor: chat.callCanMonitor
            onReadAloud: text => AgentClient.readAloud(text)
            onOpenImage: (source, name) => viewer.show(source, name)
            onOpenSettings: which => page.Window.window.openSettings(which === "codex" ? "CodexPage.qml" : "KeyPage.qml")
        }
        // New content keeps the view at the end only while the reader is there.
        property bool follow: true
        function stickToEnd() { if (follow) positionViewAtEnd() }
        onContentHeightChanged: if (follow && !moving) Qt.callLater(stickToEnd)
        onMovementStarted: follow = false
        onMovementEnded: follow = atYEnd
        boundsMovement: Flickable.StopAtBounds
        QQC2.ScrollIndicator.vertical: QQC2.ScrollIndicator {}
    }

    // Still loading: said after a moment (a quick load shows nothing in between).
    Timer { id: slowLoad; interval: 150; running: !page.loaded }
    ColumnLayout {
        anchors.centerIn: view
        spacing: 12
        visible: !page.loaded && !slowLoad.running
        BusyRing { Layout.alignment: Qt.AlignHCenter }
        Text { text: i18nc("@info:status a conversation loading", "Opening…"); color: Theme.dim; font.family: Theme.fontFamily; font.pixelSize: Theme.metaSize }
    }

    // ---- a new conversation: a question and a few things to try ----------------------
    ColumnLayout {
        anchors { left: parent.left; right: parent.right; top: top.bottom; bottom: phoneBar.top }
        anchors.leftMargin: 16
        anchors.rightMargin: 16
        // Only while the composer is a plain bar: typing, the + panel or a hold take its room.
        visible: page.loaded && chat.entries.count === 0 && ["voice", "busy", "unavailable"].indexOf(composer.phase) >= 0
        spacing: 8
        Item { Layout.fillHeight: true }
        Text {
            Layout.alignment: Qt.AlignHCenter
            text: i18nc("@title a new conversation", "How can I help?")
            font.family: Theme.fontFamily
            font.pixelSize: Theme.headingSize
            font.weight: Font.DemiBold
            color: Theme.text
        }
        Item { Layout.fillHeight: true }
        Repeater {
            // Sent as they read (in the desktop's language).
            model: [i18nc("@action:button a request to try", "How much storage is left on my phone?"),
                    i18nc("@action:button a request to try", "Make the screen a little dimmer"),
                    i18nc("@action:button a request to try", "Tidy up my Downloads folder")]
            PillButton {
                required property string modelData
                Layout.fillWidth: true
                Layout.maximumWidth: Theme.readingWidth
                Layout.alignment: Qt.AlignHCenter
                implicitHeight: 52
                radius: 16
                fontSize: 15
                alignment: Qt.AlignLeft
                text: modelData
                onClicked: page.send(modelData, [])
            }
        }
        Item { implicitHeight: 4 }
    }

    // Scrolled away from the end: a way back.
    PillButton {
        anchors { horizontalCenter: parent.horizontalCenter; bottom: phoneBar.top; bottomMargin: 8 }
        visible: !view.follow && !view.atYEnd && view.contentHeight > view.height
        iconName: "chevron-down"
        text: i18nc("@action:button scroll to the end of the thread", "Jump to latest")
        onClicked: { view.follow = true; view.positionViewAtEnd() }
    }

    function send(text, attachments) {
        view.follow = true
        ensure(() => AgentClient.sendText(text, JSON.stringify(attachments)))
    }

    Column {
        id: phoneBar
        anchors {left: parent.left; right: parent.right; bottom: composer.top}
        width: parent.width
        spacing: 6
        Text {
            anchors.horizontalCenter: parent.horizontalCenter
            visible: !!page.phone.sessionId
            text: page.phone.phase === "connecting" ? i18nc("@info:status", "Connecting phone mode…")
                  : page.phone.conversation !== page.conversationId ? i18nc("@info:status", "Phone mode in another conversation")
                  : page.phone.muted ? i18nc("@info:status", "Microphone muted") : i18nc("@info:status", "Phone mode · Listening")
            color: Theme.dim
            font.family: Theme.fontFamily
            font.pixelSize: Theme.metaSize
        }
        Flow {
            width: parent.width - 24
            anchors.horizontalCenter: parent.horizontalCenter
            spacing: 6
            PillButton {
                visible: !page.phone.sessionId
                text: i18nc("@action:button", "Phone mode")
                enabled: chat.callPhase !== "user" && !chat.inCall
                onClicked: page.ensure(() => AgentClient.request("StartPhoneMode", [page.conversationId]))
            }
            PillButton {
                visible: !!page.phone.sessionId
                text: page.phone.muted ? i18nc("@action:button", "Unmute") : i18nc("@action:button", "Mute")
                onClicked: AgentClient.request("SetPhoneMuted", [page.phone.sessionId, !page.phone.muted])
            }
            PillButton {
                visible: !!page.phone.sessionId
                text: i18nc("@action:button", "Stop speaking")
                onClicked: AgentClient.request("StopSpeaking", [page.phone.sessionId])
            }
            PillButton {
                visible: !!page.phone.sessionId
                negative: true
                text: i18nc("@action:button", "Hang up")
                onClicked: AgentClient.request("StopPhoneMode", [page.phone.sessionId])
            }
        }
    }

    Composer {
        id: composer
        anchors { left: parent.left; right: parent.right; bottom: parent.bottom }
        chat: chat
        busy: page.busy
        speaking: page.speaking
        canTalk: chat.callPhase !== "user" && !page.phone.sessionId && !(page.phone.tasks || []).some(t => ["queued", "starting", "running", "stopping", "waiting_input"].indexOf(t.status) >= 0)
        onTalkPressed: {
            view.follow = true
            view.positionViewAtEnd()
            if (chat.handsFree) { AgentClient.stopTalking(); return }
            page.ensure(() => {
                if (composer.holding) AgentClient.startTalking(page.screenName)
                else AgentClient.startListening(page.screenName)   // a tap while it was being created
            })
        }
        onTalkReleased: zone => {
            if (!page.conversationId) return            // the tap is handled once created
            if (zone === "cancel") AgentClient.cancelTalking()
            else if (zone === "text") AgentClient.talkToText()
            else AgentClient.releaseTalking()
        }
        onHandsFreeStopped: AgentClient.stopTalking()   // sends what was said, if anything
        onSendRequested: (text, attachments) => page.send(text, attachments)
        onStopRequested: AgentClient.stopTask()
    }

    ConversationDrawer {
        id: drawer
        // Only over the conversation: on a page above it, a drag to the right is that page's swipe back.
        interactive: page.QQC2.StackView.status === QQC2.StackView.Active
        current: page.conversationId
        onOpenRequested: (id, title) => { drawer.close(); page.open(id, title) }
        onNewRequested: { drawer.close(); page.newConversation() }
        onSettingsRequested: { drawer.close(); page.Window.window.openSettings() }
        onSuggestionsRequested: { drawer.close(); page.Window.window.openSuggestions("") }
        onDeleted: id => { if (id === page.conversationId) page.newConversation() }
    }

    // A picture of an answer, large (docs/88).
    ImageViewer {
        id: viewer
        onOpenExternally: source => { viewer.close(); Qt.openUrlExternally(source) }
    }
}
