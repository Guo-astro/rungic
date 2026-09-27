// SPDX-License-Identifier: GPL-2.0-or-later
// The assistant's overlay (docs/67): holding Home darkens and blurs the whole screen and
// light rises from under the finger, listening at once; it shows the one assistant
// conversation. Dark or light as the system is (Style).
//
// What it shows:
// - listen: the light up from Home, following the voice; "正在听" and a hint.
// - work: the light gathered into a capsule above Home, what was asked at the top and
//   what the agent is doing above the capsule.
// - answer: the latest turn in a glass panel around the capsule; pulled up, the whole
//   conversation.
//
// Talking: holding Home (or the capsule) is push-to-talk and lifting ends what was said.
// A press lifted before anything was said keeps listening hands-free until speech ends;
// a tap then sends at once. Tap the backdrop or swipe the panel down to dismiss:
// listening is dropped and a spoken reply stops, agent work goes on and its result
// brings the overlay back.
import QtQuick
import QtQuick.Window
import QtQuick.Controls as QQC2
import org.kde.kirigami as Kirigami
import org.kde.plasma.private.mobileshell.state as MobileShellState
import com.rungic.voiceassistant

Window {
    id: win
    visible: false
    color: "transparent"
    flags: Qt.FramelessWindowHint
    width: 360
    height: 800

    property string screenName: ""
    property bool shown: false                // up (animated through `appear`)
    property string conversation: ""          // the assistant's conversation id
    property bool holding: false              // Home or the capsule is held
    property real micLevel: -90
    property bool expanded: false             // the panel pulled up: the whole conversation
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
    readonly property bool newTurn: lastUser >= floor
    readonly property bool pending: chat.agentBusy || chat.phase === "working" || chat.phase === "speaking" || awaiting
    readonly property string view: listening ? "listen" : pending && !(newTurn && replied) ? "work" : "answer"

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
    // Touch stays with the navigation panel below `above`; blur and saturation behind the rest.
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
            if (idle && !panelArea.containsPress) win.dismiss()
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
        } else {
            awaiting = true
            awaitTimer.restart()
        }
        refreshTurn()
    }

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
                win.summon(screen)
                win.holding = true
                AgentClient.assistantTalk(screen)
            } else if (win.holding) {
                win.holding = false
                AgentClient.releaseTalking()
            }
        }
        function onShowRequested(screen) { win.summon(screen) }
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
        function onEvent(json) {
            const e = JSON.parse(json)
            if (e.type === "assistant-reset") { AgentClient.openAssistant(); return }
            if (!win.conversation || (e.conversation && e.conversation !== win.conversation)) return
            if (e.type === "level") { win.micLevel = e.db; return }
            if (e.type === "listen-cancelled") { win.awaiting = false; return }
            chat.apply(e, true)
            if (e.type === "state") return
            idleTimer.restart()
            if (list.follow) Qt.callLater(list.positionViewAtEnd)
            // Work finished while the overlay was away: bring the result up.
            if (e.type === "agent-finished" && !win.shown && win.screenName) win.summon(win.screenName)
        }
    }
    Component.onCompleted: AgentClient.openAssistant()

    // ---- motion -----------------------------------------------------------------
    property real appear: shown ? 1 : 0
    Behavior on appear { NumberAnimation { duration: win.shown ? 360 : 220; easing.type: Easing.OutCubic } }
    // The light moves at 60 Hz, not the panel's 120: slow, soft motion looks the same and
    // Qt, KWin's compositing and its blur behind the overlay do half the frames (docs/67).
    property real time: 0
    Timer {
        property real last: 0
        interval: 16
        repeat: true
        running: win.visible && win.appear > 0
        onRunningChanged: last = Date.now()
        onTriggered: {
            const now = Date.now()
            const dt = Math.min(0.1, (now - last) / 1000)
            win.time += dt
            // Eased here, on this clock: an animation per level event (~50 a second) would
            // keep the window at the panel's full rate.
            win.energy += (win.voice - win.energy) * (1 - Math.exp(-dt / 0.08))
            last = now
        }
    }
    // The voice, 0..1, smoothed so the light swells and settles rather than flickers.
    readonly property real voice: listening ? Math.max(0, Math.min(1, (micLevel + 55) / 35)) : 0
    property real energy: 0
    property real now: Date.now() / 1000
    Timer {
        interval: 1000; repeat: true
        running: win.visible && win.view === "work"
        onTriggered: win.now = Date.now() / 1000
    }

    readonly property real contentWidth: Math.min(width - 24, Kirigami.Units.gridUnit * 30)
    readonly property real contentX: (width - contentWidth) / 2

    Item {
        anchors.fill: parent
        Kirigami.Theme.colorSet: Style.dark ? Kirigami.Theme.Complementary : Kirigami.Theme.Window
        Kirigami.Theme.inherit: false

        // Darkens what is behind (KWin blurs it too): the light and the words stand out.
        Rectangle {
            width: parent.width
            height: win.above
            opacity: win.appear
            gradient: Gradient {
                GradientStop { position: 0.0; color: Style.veil(Style.scrimTop) }
                GradientStop { position: 0.55; color: Style.veil(Style.scrimMiddle) }
                GradientStop { position: 1.0; color: Style.veil(Style.scrimBottom) }
            }
            // Over the navigation panel as well, lighter: its buttons stay visible (and theirs to touch).
            Rectangle {
                anchors.top: parent.bottom
                width: parent.width
                height: win.navHeight
                color: Style.veil(0.72)
            }
            MouseArea {
                anchors.fill: parent
                onClicked: {
                    if (chat.handsFree) AgentClient.stopTalking()
                    else if (win.expanded) win.expanded = false
                    else win.dismiss()
                }
            }
        }

        // The light from Home: fully up while listening, sunk behind the capsule while working.
        // (Not a layer at a lower resolution: its update asked for a second frame per tick,
        // costing more than the fragments it saved; docs/67.)
        Item {
            width: parent.width
            height: bloom.height
            anchors.bottom: parent.bottom
            visible: bloom.lit
            Bloom {
                id: bloom
                width: parent.width
                height: Math.min(win.height * 0.62, 620)
                spread: Math.min(win.width, Kirigami.Units.gridUnit * 34)
                time: win.time
                level: win.energy
                property real target: win.view === "listen" ? 1 : win.view === "work" ? 0.3 : 0
                rise: target * win.appear
                Behavior on target { NumberAnimation { duration: 420; easing.type: Easing.OutCubic } }
                property real edge: win.view === "listen" ? (chat.handsFree ? 0.5 : 1) : 0
                Behavior on edge { NumberAnimation { duration: 300 } }
                rim: edge * win.appear
                readonly property bool lit: rise > 0.001 || rim > 0.001
            }
        }

        // listen: "正在听", then what was said (or an invitation), then how it ends.
        Column {
            x: win.contentX + 20
            width: win.contentWidth - 40
            y: win.height * 0.27
            spacing: 18
            opacity: win.view === "listen" ? Math.max(0, (win.appear - 0.55) / 0.45) : 0
            Behavior on opacity { NumberAnimation { duration: 200 } }
            visible: opacity > 0
            GlowLabel {
                text: "正在听"
                time: win.time
                font.pixelSize: 15
                font.weight: Font.Medium
            }
            Text {
                width: parent.width
                text: win.newTurn ? win.userText : "请说"
                wrapMode: Text.Wrap
                color: win.newTurn ? Style.ink : Style.dim
                font.pixelSize: Math.round(Math.min(win.width, 430) * 0.075)
                font.weight: Font.Medium
                lineHeight: 1.2
            }
            Text {
                text: win.holding ? "松开 Home 发送" : chat.handsFree ? "说完自动发送 · 轻点结束" : ""
                color: Style.dim
                font.pixelSize: 14
            }
        }

        // work: what was asked, at the top.
        Text {
            x: win.contentX + 20
            width: win.contentWidth - 40
            y: win.topHeight + 56
            text: win.newTurn ? win.userText : ""
            wrapMode: Text.Wrap
            maximumLineCount: 4
            elide: Text.ElideRight
            color: Style.ink
            font.pixelSize: 22
            font.weight: Font.Medium
            lineHeight: 1.15
            opacity: win.view === "work" ? win.appear : 0
            Behavior on opacity { NumberAnimation { duration: 200 } }
            visible: opacity > 0
        }

        // answer: the glass panel around the turn and the controls.
        Rectangle {
            id: panel
            readonly property real topY: win.expanded ? win.topHeight + 12 : list.y - 30
            x: win.contentX
            width: win.contentWidth
            y: topY
            height: controls.y + controls.height + 20 - topY
            radius: 34
            color: Style.panel
            border.width: 1
            border.color: Style.line
            opacity: win.view === "answer" ? win.appear : 0
            Behavior on opacity { NumberAnimation { duration: 240 } }
            visible: opacity > 0
            Behavior on y { NumberAnimation { duration: 320; easing.type: Easing.OutCubic } }

            // Drag up for the whole conversation, down to fold it or dismiss; tap the grip to toggle.
            MouseArea {
                id: panelArea
                anchors.fill: parent
                property real startY: 0
                onPressed: mouse => startY = mouse.y
                onReleased: mouse => {
                    const dy = mouse.y - startY
                    if (dy > Kirigami.Units.gridUnit * 2) { if (win.expanded) win.expanded = false; else win.dismiss() }
                    else if (dy < -Kirigami.Units.gridUnit * 2) win.expanded = true
                    else if (mouse.y < 36) win.expanded = !win.expanded
                }
            }
            Rectangle {
                anchors.horizontalCenter: parent.horizontalCenter
                y: 12
                width: 36
                height: 4
                radius: 2
                color: Style.track
            }
            Text {
                anchors.horizontalCenter: parent.horizontalCenter
                y: 26
                visible: win.expanded
                text: "语音助手"
                color: Style.inkSoft
                font.pixelSize: 15
                font.weight: Font.DemiBold
            }
        }

        ListView {
            id: list
            readonly property real bottomY: status.y - 14
            readonly property real maxHeight: win.expanded ? bottomY - (win.topHeight + 12 + 56) : win.height * 0.42
            x: win.contentX + 22
            width: win.contentWidth - 44
            height: Math.max(win.lastUser < 0 ? hint.implicitHeight : 0, Math.min(contentHeight, maxHeight))
            y: bottomY - height
            opacity: panel.opacity
            visible: panel.visible
            clip: true
            interactive: contentHeight > height
            model: chat.entries
            delegate: OverlayItem {
                from: win.expanded ? 0 : Math.max(0, win.lastUser)
                compact: !win.expanded
            }
            // Follows new content only while at the end (scrolling up re-estimates the height).
            property bool follow: true
            onContentHeightChanged: if (follow && !moving) Qt.callLater(positionViewAtEnd)
            onMovementStarted: follow = false
            onMovementEnded: follow = atYEnd
            Text {
                id: hint
                visible: chat.entries.count === 0
                width: parent.width
                horizontalAlignment: Text.AlignHCenter
                text: "有什么可以帮你？"
                color: Style.ink
                font.pixelSize: 19
                font.weight: Font.Medium
            }
        }

        // What is going on, above the capsule.
        Column {
            id: status
            readonly property bool active: win.view === "work" || chat.phase === "speaking" || chat.agentBusy
            anchors.horizontalCenter: parent.horizontalCenter
            y: controls.y - height - 16
            spacing: 6
            opacity: win.view === "listen" ? 0 : win.appear
            Behavior on opacity { NumberAnimation { duration: 200 } }
            visible: opacity > 0
            readonly property bool working: win.hasWork && win.newTurn
            GlowLabel {
                anchors.horizontalCenter: parent.horizontalCenter
                time: win.time
                glowing: status.active
                font.pixelSize: status.active && win.view === "work" ? 17 : 13
                font.weight: Font.Medium
                text: chat.phase === "speaking" ? "正在回答 · 按住可打断"
                    : win.view === "work" && status.working ? "正在处理 · " + Math.max(0, Math.round(win.now - win.workStarted)) + " 秒"
                    : win.view === "work" ? "正在处理"
                    : chat.agentBusy ? "正在处理"
                    : "按住说话，轻点免提"
            }
            Text {
                anchors.horizontalCenter: parent.horizontalCenter
                width: Math.min(implicitWidth, win.contentWidth - 48)
                visible: win.view === "work" && text !== ""
                elide: Text.ElideRight
                color: Style.dim
                font.pixelSize: 14
                text: status.working ? win.workStep : ""
            }
        }

        // The capsule between "在应用中查看" and stop/close, right above Home.
        Item {
            id: controls
            x: win.contentX + 20
            width: win.contentWidth - 40
            height: 56
            y: win.above - height - 24
            opacity: win.view === "listen" ? 0 : win.appear
            Behavior on opacity { NumberAnimation { duration: 220 } }

            GlassButton {
                anchors { left: parent.left; verticalCenter: parent.verticalCenter }
                enabled: controls.opacity > 0
                iconName: "view-conversation-balloon-symbolic"
                label: "在应用中查看"
                onClicked: {
                    Overlay.openInApp(win.conversation)
                    win.dismiss()
                }
            }

            LightPill {
                id: pill
                anchors.centerIn: parent
                time: win.time
                mode: win.view === "work" ? "work" : chat.phase === "speaking" ? "speak" : "idle"
                // Kept while listening (only faded): the finger holding it must keep its press.
                MouseArea {
                    anchors.fill: parent
                    anchors.margins: -8
                    // Hold to talk; a quick tap listens hands-free (the service decides on release).
                    onPressed: {
                        if (chat.handsFree) { AgentClient.stopTalking(); return }
                        win.holding = true
                        AgentClient.assistantTalk(win.screenName)
                    }
                    onReleased: if (win.holding) { win.holding = false; AgentClient.releaseTalking() }
                    onCanceled: if (win.holding) { win.holding = false; AgentClient.releaseTalking() }
                }
            }

            // Stop the work or the answer; otherwise close.
            GlassButton {
                anchors { right: parent.right; verticalCenter: parent.verticalCenter }
                enabled: controls.opacity > 0
                readonly property bool stops: chat.agentBusy || chat.phase === "speaking"
                iconName: stops ? "media-playback-stop-symbolic" : "window-close-symbolic"
                label: stops ? "停止" : "关闭"
                onClicked: stops ? AgentClient.stopTask() : win.dismiss()
            }
        }
    }
}
