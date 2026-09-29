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

    // The app's look, also here.
    Settings {
        id: appSettings
        category: "App"
        property string theme: "system"
    }
    Binding { target: Theme; property: "mode"; value: appSettings.theme }

    property string screenName: ""
    property bool shown: false
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
        : awaiting && !newTurn ? "sending"
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
        Overlay.setTouchableHeight(above)
        Overlay.setCard(Qt.rect(0, 0, width, above), 0)
    }

    function summon(screen) {
        hideTimer.stop()
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
        hideTimer.restart()
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
            if (e.type === "assistant-reset") { AgentClient.openAssistant(); return }
            if (e.type === "preferences") { win.homeHold = e.homeHold !== false; return }
            if (!win.conversation || (e.conversation && e.conversation !== win.conversation)) return
            if (e.type === "level") { win.micLevel = e.db; return }
            if (e.type === "listen-cancelled") { win.awaiting = false; win.cancelled = true; return }
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
        running: win.visible && win.view === "work"
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
        visible: win.appear > 0
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
                onReadAloud: text => AgentClient.readAloud(text)
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
}
