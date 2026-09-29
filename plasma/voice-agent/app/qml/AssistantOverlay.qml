// SPDX-License-Identifier: GPL-2.0-or-later
// The assistant's overlay (docs/67, docs/87): holding Home dims the screen and a sheet comes
// up from the bottom, listening at once; it shows the one assistant conversation.
//
// It is in exactly one view at a time (`view`), each with its own content in the sheet:
//   listen   what is being said (or "请说"), the voice bar held (the wave, the time)
//   sending  released: what was said is on its way, not yet transcribed
//   work     what was asked, the agent's progress shining, stop
//   answer   the latest turn as in the app (pulled up: the whole conversation)
//
// Talking: holding Home (or the sheet's bar) is push-to-talk and lifting ends what was said.
// A press lifted before anything was said keeps listening hands-free until speech ends; a
// tap then sends at once. Tap the backdrop or swipe the sheet down to dismiss: listening is
// dropped and a spoken reply stops, agent work goes on and its result brings the sheet back.
// "长按 Home 呼出" off in the app's settings: holding Home does nothing here.
import QtQuick
import QtQuick.Layouts
import QtQuick.Window
import QtQuick.Controls as QQC2
import QtCore
import org.kde.kirigami as Kirigami
import org.kde.plasma.private.mobileshell.state as MobileShellState
import com.rungic.design
import com.rungic.voiceassistant

Window {
    id: win
    visible: false
    color: "transparent"
    flags: Qt.FramelessWindowHint
    width: 360
    height: 800

    // Call status is global (it can belong to the app's conversation, not this overlay's).
    property bool callLive: false
    property string callConversation: ""
    property string callContact: ""
    property string callStatus: "connecting"
    property string callPhase: "agent"
    property string callNote: ""
    property real callStarted: 0
    property bool callDetails: false
    property bool callCanMonitor: false
    readonly property bool compactCall: callLive && !shown
    onCompactCallChanged: Qt.callLater(updateMaterial)

    function callEvent(e) {
        if (e.type === "call-started") {
            callLive = true; callPhase = "agent"; callStatus = "connecting"
            callConversation = e.conversation || win.conversation
            callContact = e.contact || "电话"; callStarted = 0; callNote = ""
            callCanMonitor = e.independentMonitor !== false
            callDetails = false; shown = false; hideTimer.stop()
            Overlay.present(screenName)
        } else if (e.type === "call-state") {
            callStatus = e.state
            if (e.state === "connected" && !callStarted) callStarted = Date.now() / 1000
        } else if (e.type === "call-phase") { callPhase = e.phase
        } else if (e.type === "call-ask" || e.type === "call-error" || e.type === "call-note") {
            callNote = e.text || ""
        } else if (e.type === "call-ended") {
            callLive = false; callDetails = false
            if (!shown) Overlay.conceal()
        } else if (e.type === "state" && e.callInfo && !callLive) {
            callConversation = e.conversation || win.conversation
            callLive = true; callContact = e.callInfo.contact; callPhase = e.callPhase
            callCanMonitor = e.callInfo.independentMonitor !== false
            callStatus = "ongoing"; callStarted = 0
            if (!shown) { hideTimer.stop(); Overlay.present(screenName) }
        } else if (e.type === "agent-restarted") {
            callLive = false
            if (!shown) Overlay.conceal()
        }
        if (compactCall) Qt.callLater(updateMaterial)
    }

    // The app's look, also here.
    Settings {
        id: appSettings
        category: "App"
        property string theme: "system"
    }
    Binding { target: Theme; property: "mode"; value: appSettings.theme }

    property string screenName: ""
    property bool shown: false
    onShownChanged: AgentClient.setWatching(shown)          // docs/89: the voice says less while shown
    Binding { target: AgentClient; property: "conversation"; value: win.conversation }   // 朗读 goes to it (docs/89)
    property string conversation: ""          // the assistant's conversation id
    property bool holding: false              // Home or the sheet's bar is held
    property real micLevel: -90
    property bool expanded: false             // the sheet pulled up: the whole conversation
    property bool homeHold: true              // the app's "长按 Home 呼出"
    readonly property bool listening: chat.phase === "listening" || holding

    // The current turn (refreshTurn): entries from `floor` on are this turn's.
    property int floor: 0                     // entries.count when listening began
    property int lastUser: -1                 // the latest user entry
    property bool replied: false              // something came back after it
    property string userText: ""              // what the user said in it
    property real workStarted: 0              // its agent work, if any
    property string workStep: ""              //   and the latest step
    property bool hasWork: false
    property bool awaiting: false             // released; what was said is on its way
    property bool cancelled: false            // the service dropped the listening (nothing sent)
    readonly property bool newTurn: lastUser >= floor
    readonly property bool pending: chat.agentBusy || chat.phase === "working" || chat.phase === "speaking" || awaiting
    readonly property string view: listening ? "listen"
        // The user's bubble is in place from the press on: sending until its words arrive.
        : awaiting && (!newTurn || userText === "") ? "sending"
        : pending && !(newTurn && replied) ? "work" : "answer"

    ChatModel { id: chat }

    MobileShellState.PanelSettingsDBusClient {
        id: panels
        screenName: win.screenName
    }
    // As mobileshell's Constants (not imported: that singleton writes KWin settings).
    readonly property real navHeight: panels.navigationPanelHeight > 0 ? panels.navigationPanelHeight : Kirigami.Units.gridUnit * 2
    readonly property real topHeight: panels.statusBarHeight > 0 ? panels.statusBarHeight : Kirigami.Units.gridUnit * 1.5
    readonly property real above: height - navHeight        // the overlay's own area, over the navigation panel
    onAboveChanged: updateMaterial()
    onWidthChanged: updateMaterial()
    // Touch stays with the navigation panel below `above`.
    function updateMaterial() {
        Overlay.setKeyboardEnabled(compactCall && callDetails)
        if (compactCall) {
            const rect = Qt.rect(callBar.x, callBar.y, callBar.width, callBar.height)
            Overlay.setTouchableRect(rect)
            Overlay.setCard(rect, 18)
        } else {
            Overlay.setTouchableHeight(above)
            Overlay.setCard(Qt.rect(0, 0, width, above), 0)
        }
    }

    property bool reopen: false            // the service restarted while hidden: open again when shown
    function summon(screen) {
        hideTimer.stop()
        if (reopen) { reopen = false; AgentClient.openAssistant() }
        if (screen) win.screenName = screen
        Overlay.present(win.screenName)
        updateMaterial()
        win.shown = true
        idleTimer.restart()
    }
    function dismiss() {
        if (!win.shown) return
        if (chat.phase === "listening") AgentClient.cancelTalking()
        else if (chat.phase === "speaking" && !chat.agentBusy) AgentClient.interrupt()
        win.holding = false
        win.shown = false
        win.expanded = false
        if (callLive) { hideTimer.stop(); updateMaterial() }
        else hideTimer.restart()
    }
    Timer {
        id: hideTimer
        interval: 260      // the exit animation
        onTriggered: Overlay.conceal()
    }
    // Nothing going on for a while: the overlay leaves by itself.
    Timer {
        id: idleTimer
        interval: 8000
        onTriggered: {
            const idle = !win.listening && !win.pending && !win.expanded
            if (idle && !bar.held) win.dismiss()
            else restart()
        }
    }
    // Released, and nothing came of it (not even a transcript): stop waiting.
    Timer {
        id: awaitTimer
        interval: 8000
        onTriggered: win.awaiting = false
    }
    onListeningChanged: {
        if (listening) {
            floor = chat.entries.count
            awaiting = false
            expanded = false
            list.follow = true
            heldSeconds = 0
        } else {
            // A cancel (the service said listen-cancelled first) sent nothing: nothing to wait for.
            awaiting = !cancelled
            if (awaiting) awaitTimer.restart()
        }
        cancelled = false
        refreshTurn()
    }
    property real heldSeconds: 0
    Timer { interval: 250; repeat: true; running: win.listening && win.shown; onTriggered: win.heldSeconds += 0.25 }

    function refreshTurn() {
        const entries = chat.entries
        let user = -1
        for (let i = entries.count - 1; i >= 0; i--) {
            const e = entries.get(i)
            if (e.role === "user" && (e.kind === "message" || e.kind === "live-user")) { user = i; break }
        }
        let reply = false, work = null
        for (let i = user + 1; i < entries.count; i++) {
            const e = entries.get(i)
            if (e.kind === "work") work = e
            else if (e.role === "assistant" && (e.kind === "message" || e.kind === "live-assistant")) reply = true
        }
        lastUser = user
        userText = user >= 0 ? entries.get(user).text : ""
        replied = reply
        hasWork = work !== null
        workStarted = work ? work.started : 0
        // A command without the shell wrapper Codex adds.
        workStep = work ? work.text.replace(/^\/bin\/(?:ba)?sh -lc '([\s\S]*)'$/, "$1").split("\n")[0] : ""
        if (awaiting && newTurn && replied) awaiting = false
    }
    Connections {
        target: chat.entries
        function onCountChanged() { Qt.callLater(win.refreshTurn) }
        function onDataChanged() { Qt.callLater(win.refreshTurn) }
    }

    // A hold whose lift never came kept the microphone open and the overlay up (2026-09-28: a
    // touch lost while the desktop went to the background, docs/49). Past a minute it is taken as
    // lost and cancelled; what was said is not sent.
    Timer {
        interval: 60000
        running: win.holding
        onTriggered: {
            win.holding = false
            win.dismiss()   // cancels the listening
        }
    }

    Connections {
        target: Overlay
        function onHoldRequested(pressed, screen) {
            if (pressed) {
                if (!win.homeHold) return
                win.summon(screen)
                win.holding = true
                AgentClient.assistantTalk(screen)
            } else if (win.holding) {
                win.holding = false
                AgentClient.releaseTalking()
            }
        }
        function onShowRequested(screen) { if (win.homeHold) win.summon(screen) }
        function onHideRequested() { win.dismiss() }
    }

    Connections {
        target: AgentClient
        function onAssistantOpened(json) {
            const opened = JSON.parse(json)
            win.conversation = opened.conversation
            chat.load(opened)
            win.floor = 0
            win.refreshTurn()
        }
        function onReplied(method, json) {
            if (method === "Setup") win.homeHold = (JSON.parse(json).preferences || {}).homeHold !== false
        }
        function onEvent(json) {
            const e = JSON.parse(json)
            win.callEvent(e)
            if (e.type === "assistant-reset") { AgentClient.openAssistant(); return }
            // The service restarted: the assistant's conversation is opened again, but only once
            // the overlay is shown. Opening it now would close the conversation the app just
            // reopened, and the app's next press would talk into this one (docs/89).
            if (e.type === "agent-restarted") {
                AgentClient.request("Setup")
                if (win.shown) AgentClient.openAssistant(); else win.reopen = true
                return
            }
            if (e.type === "preferences") { win.homeHold = e.homeHold !== false; return }
            if (!win.conversation || (e.conversation && e.conversation !== win.conversation)) return
            if (e.type === "level") { win.micLevel = e.db; return }
            if (e.type === "listen-cancelled") { win.awaiting = false; win.cancelled = true }
            chat.apply(e, true)
            if (e.type === "state") return
            idleTimer.restart()
            if (list.follow) Qt.callLater(list.positionViewAtEnd)
            // Work finished while the overlay was away: bring the result up.
            if (e.type === "agent-finished" && !win.shown && win.screenName) win.summon(win.screenName)
        }
    }
    Component.onCompleted: {
        AgentClient.openAssistant()
        AgentClient.request("Setup")
    }

    property real now: Date.now() / 1000
    Timer {
        interval: 1000; repeat: true
        running: win.visible && (win.view === "work" || win.callLive)
        onTriggered: win.now = Date.now() / 1000
    }

    // ---- the scrim ----------------------------------------------------------------
    property real appear: shown ? 1 : 0
    Behavior on appear { NumberAnimation { duration: win.shown ? 280 : 200; easing.type: Easing.Bezier; easing.bezierCurve: Theme.easing } }

    Rectangle {
        width: parent.width
        height: win.above
        color: Theme.scrim
        opacity: win.appear
        visible: !win.compactCall
        MouseArea {
            anchors.fill: parent
            onClicked: {
                if (chat.handsFree) AgentClient.stopTalking()
                else if (win.expanded) win.expanded = false
                else win.dismiss()
            }
        }
    }

    // ---- the sheet ------------------------------------------------------------------
    BottomSheet {
        id: sheet
        readonly property real maxHeight: win.above - win.topHeight - 12
        width: Math.min(win.width, Theme.readingWidth + 40)
        x: (win.width - width) / 2
        height: Math.min(implicitHeight, maxHeight)
        // Slides up from below the screen's own area.
        y: win.above - height * win.appear
        visible: !win.compactCall && win.appear > 0
        spacing: 14
        // Down folds or dismisses, up shows the whole conversation; the handle toggles.
        onSwipedDown: { if (win.expanded) win.expanded = false; else win.dismiss() }
        onSwipedUp: win.expanded = true
        onHandleTapped: win.expanded = !win.expanded

        // listen: what is being said.
        Text {
            Layout.fillWidth: true
            visible: win.view === "listen"
            text: win.newTurn && win.userText ? win.userText : "请说"
            wrapMode: Text.Wrap
            font.family: Theme.fontFamily
            font.pixelSize: Theme.liveSize
            font.weight: Font.Medium
            lineHeight: 30
            lineHeightMode: Text.FixedHeight
            color: win.newTurn && win.userText ? Theme.text : Theme.dim
        }

        // work: what was asked, then what the agent is doing.
        UserBubble {
            Layout.alignment: Qt.AlignRight
            visible: win.view === "work" && win.newTurn && win.userText !== ""
            text: win.userText
            maxWidth: sheet.width * 0.78
        }
        ShineText {
            Layout.fillWidth: true
            visible: win.view === "sending"
            text: "正在识别…"
        }
        ShineText {
            Layout.fillWidth: true
            visible: win.view === "work"
            text: chat.phase === "speaking" ? "正在回答"
                : "正在处理" + (win.hasWork && win.newTurn ? " · " + Math.max(0, Math.round(win.now - win.workStarted)) + " 秒"
                                + (win.workStep ? " · " + win.workStep : "") : "")
        }

        // answer: the latest turn (pulled up: all of it), as in the app.
        ListView {
            id: list
            Layout.fillWidth: true
            Layout.preferredHeight: Math.min(contentHeight, win.expanded ? sheet.maxHeight - 140 : win.height * 0.42)
            visible: win.view === "answer" && chat.entries.count > 0
            clip: true
            spacing: 16
            interactive: contentHeight > height
            model: chat.entries
            delegate: ChatEntry {
                // Folded: from the latest thing the user said.
                readonly property bool shownNow: index >= (win.expanded ? 0 : Math.max(0, win.lastUser))
                visible: shownNow
                height: shownNow ? implicitHeight : 0
                column: width
                callMonitor: chat.callMonitor
                callCanMonitor: chat.callCanMonitor
                onReadAloud: text => AgentClient.readAloud(text)
                onOpenImage: source => Qt.openUrlExternally(source)
                onOpenSettings: page => { Overlay.openInApp(win.conversation); win.dismiss() }
            }
            // Follows new content only while at the end.
            property bool follow: true
            onContentHeightChanged: if (follow && !moving) Qt.callLater(positionViewAtEnd)
            onMovementStarted: follow = false
            onMovementEnded: follow = atYEnd
        }
        Text {
            Layout.alignment: Qt.AlignHCenter
            visible: win.view === "answer" && chat.entries.count === 0
            text: "有什么可以帮你？"
            font.family: Theme.fontFamily
            font.pixelSize: Theme.liveSize
            font.weight: Font.DemiBold
            color: Theme.text
        }

        // The bar: held to talk (hot while listening), with open-in-app and stop or close.
        VoiceBar {
            id: bar
            Layout.fillWidth: true
            mode: win.view === "listen" ? (chat.handsFree && !win.holding ? "handsFree" : "hot")
                : chat.callPhase === "user" ? "disabled" : "idle"
            // Held anywhere between its buttons: talk.
            holdable: chat.callPhase !== "user"
            onPressed: {
                if (chat.handsFree) { AgentClient.stopTalking(); return }
                win.holding = true
                AgentClient.assistantTalk(win.screenName)
            }
            onReleased: if (win.holding) { win.holding = false; AgentClient.releaseTalking() }
            onCanceled: if (win.holding) { win.holding = false; AgentClient.releaseTalking() }
            IconButton {
                visible: win.view !== "listen"
                iconName: "open-in-app"
                text: "在应用中查看"
                tint: bar.ink
                onClicked: { Overlay.openInApp(win.conversation); win.dismiss() }
            }
            Wave {
                visible: win.view === "listen"
                Layout.fillWidth: true
                Layout.leftMargin: 14
                Layout.rightMargin: 8
                bars: Math.max(8, Math.floor((bar.width - 120) / 6))
                barHeight: 32
                level: Math.max(0, Math.min(1, (win.micLevel + 55) / 35))
                color: bar.ink
                clip: true
            }
            Text {
                visible: win.view === "listen"
                rightPadding: 14
                text: Math.floor(win.heldSeconds / 60) + ":" + String(Math.floor(win.heldSeconds) % 60).padStart(2, "0")
                font.family: Theme.monoFamily
                font.pixelSize: 13
                color: bar.ink
                opacity: 0.75
            }
            Text {
                visible: win.view !== "listen"
                Layout.fillWidth: true
                horizontalAlignment: Text.AlignHCenter
                text: win.view === "work" ? "按住补充说明" : win.view === "sending" ? "按住说话" : "按住继续说"
                font.family: Theme.fontFamily
                font.pixelSize: Theme.bodySize
                font.weight: Font.DemiBold
                color: bar.ink
            }
            // Stop the work or the answer; otherwise close.
            CircleButton {
                visible: win.view !== "listen" && (chat.agentBusy || chat.phase === "speaking")
                iconName: "stop"
                text: "停止"
                onClicked: AgentClient.stopTask()
            }
            IconButton {
                visible: win.view !== "listen" && !(chat.agentBusy || chat.phase === "speaking")
                iconName: "close"
                text: "关闭"
                tint: bar.ink
                onClicked: win.dismiss()
            }
        }
        Text {
            Layout.fillWidth: true
            Layout.topMargin: -6
            visible: text !== ""
            horizontalAlignment: Text.AlignHCenter
            text: win.view !== "listen" ? ""
                : win.holding ? "正在听 · 松开 Home 发送 · 手指滑开取消"
                : chat.handsFree ? "说完自动发送 · 轻点结束" : ""
            font.family: Theme.fontFamily
            font.pixelSize: Theme.footSize
            color: Theme.dim
        }
    }
    Rectangle {
        id: callBar
        visible: win.compactCall
        width: Math.min(340, win.width - 24)
        height: win.callDetails ? 250 : (win.callNote ? 94 : 64)
        x: win.width - width - 12
        y: win.above - height - 12
        radius: 18
        color: Theme.background
        border.width: 1
        border.color: Theme.dim
        onXChanged: if (visible) win.updateMaterial()
        onYChanged: if (visible) win.updateMaterial()
        onHeightChanged: {
            y = Math.max(win.topHeight + 8, Math.min(y, win.above - height - 12))
            if (visible) win.updateMaterial()
        }
        MouseArea {
            anchors.fill: parent
            drag.target: callBar
            drag.minimumX: 8
            drag.maximumX: win.width - callBar.width - 8
            drag.minimumY: win.topHeight + 8
            drag.maximumY: win.above - callBar.height - 8
            property bool moved: false
            onPressed: moved = false
            onPositionChanged: if (drag.active) moved = true
            onReleased: if (moved) callBar.x = callBar.x < (win.width-callBar.width)/2 ? 8 : win.width-callBar.width-8
            onClicked: if (!moved) win.callDetails = !win.callDetails
        }
        ColumnLayout {
            anchors.fill: parent
            anchors.margins: 12
            spacing: 8
            RowLayout {
                Layout.fillWidth: true
                Text {
                    Layout.fillWidth: true
                    color: Theme.text
                    font.family: Theme.fontFamily
                    font.pixelSize: 15
                    elide: Text.ElideRight
                    readonly property int seconds: win.callStarted ? Math.max(0, Math.floor(win.now-win.callStarted)) : 0
                    readonly property string stateText: win.callPhase === "user" ? "你在通话"
                        : ({connecting: "准备中", dialing: "拨号中", ringing: "等待接通", connected: "助理通话中",
                            ongoing: "通话中", "hanging-up": "正在挂断", "hangup-failed": "请检查电话"})[win.callStatus] || "通话中"
                    text: win.callContact + " · " + stateText + (win.callStarted ? "  " + Math.floor(seconds/60) + ":" + String(seconds%60).padStart(2,"0") : "")
                }
                QQC2.Button {
                    text: "挂断"
                    onClicked: AgentClient.callCommand("hang-up")
                }
            }
            Text {
                Layout.fillWidth: true
                visible: win.callNote !== ""
                text: win.callNote
                color: Theme.text
                font.pixelSize: 13
                maximumLineCount: win.callDetails ? 3 : 1
                wrapMode: Text.Wrap
                elide: Text.ElideRight
            }
            RowLayout {
                visible: win.callDetails
                QQC2.Button {
                    text: "我来接"
                    enabled: win.callPhase === "agent"
                    onClicked: AgentClient.callCommand("take-over")
                }
                QQC2.Button {
                    text: "通话记录"
                    onClicked: Overlay.openInApp(win.callConversation)
                }
                QQC2.Button {
                    text: "收起"
                    onClicked: win.callDetails = false
                }
            }
            QQC2.TextField {
                id: callText
                Layout.fillWidth: true
                visible: win.callDetails && win.callPhase === "agent"
                placeholderText: "私下给助理的文字指令"
                onAccepted: {
                    if (!text.trim()) return
                    AgentClient.callCommand(JSON.stringify({op: "instruct", text: text}))
                    text = ""
                }
            }
            Text {
                visible: win.callDetails
                text: "拖动可移动 · 点按可收起"
                color: Theme.dim
                font.pixelSize: 12
            }
            Item { Layout.fillHeight: true; visible: win.callDetails }
        }
    }
}
