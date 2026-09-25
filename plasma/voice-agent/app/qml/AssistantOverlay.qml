// SPDX-License-Identifier: GPL-2.0-or-later
// The assistant's overlay (docs/67): holding Home brings up a frosted card over whatever
// is on screen, listening at once; it shows the one assistant conversation.
//
// Talking: holding Home (or the orb) is push-to-talk and lifting ends what was said. A
// press lifted before anything was said keeps listening hands-free until speech ends.
// Tap outside or swipe the card down to dismiss: listening is dropped and a spoken
// reply stops, agent work goes on and its result brings the card back.
import QtQuick
import QtQuick.Window
import QtQuick.Controls as QQC2
import QtQuick.Layouts
import org.kde.kirigami as Kirigami
import org.kde.plasma.private.mobileshell.state as MobileShellState
import dev.moto.voiceassistant

Window {
    id: win
    visible: false
    color: "transparent"
    flags: Qt.FramelessWindowHint
    width: 360
    height: 800

    property string screenName: ""
    property bool shown: false                // the card is up (animated)
    property string conversation: ""          // the assistant's conversation id
    property bool holding: false              // Home or the orb is held
    property real micLevel: -90
    readonly property bool listening: chat.phase === "listening" || holding
    readonly property bool dark: Kirigami.ColorUtils.brightnessForColor(Kirigami.Theme.backgroundColor) === Kirigami.ColorUtils.Dark

    ChatModel { id: chat }

    MobileShellState.PanelSettingsDBusClient {
        id: panels
        screenName: win.screenName
    }
    // As mobileshell's Constants (not imported: that singleton writes KWin settings).
    readonly property real navHeight: panels.navigationPanelHeight > 0 ? panels.navigationPanelHeight : Kirigami.Units.gridUnit * 2
    readonly property real topHeight: panels.statusBarHeight > 0 ? panels.statusBarHeight : Kirigami.Units.gridUnit * 1.5
    onNavHeightChanged: Overlay.setTouchableHeight(height - navHeight)
    onHeightChanged: Overlay.setTouchableHeight(height - navHeight)

    function summon(screen) {
        hideTimer.stop()
        if (screen) win.screenName = screen
        Overlay.present(win.screenName)
        Overlay.setTouchableHeight(win.height - win.navHeight)
        win.shown = true
        list.positionViewAtEnd()
        idleTimer.restart()
    }
    function dismiss() {
        if (!win.shown) return
        if (chat.phase === "listening") AgentClient.cancelTalking()
        else if (chat.phase === "speaking" && !chat.agentBusy) AgentClient.interrupt()
        win.holding = false
        win.shown = false
        hideTimer.restart()
    }
    Timer {
        id: hideTimer
        interval: 260      // the card's exit animation
        onTriggered: Overlay.conceal()
    }
    // Nothing going on for a while: the card leaves by itself.
    Timer {
        id: idleTimer
        interval: 8000
        onTriggered: {
            // "connecting": the realtime link closed when idle; nothing is going on either.
            const idle = !win.listening && !chat.agentBusy && chat.phase !== "speaking" && chat.phase !== "working"
            if (idle && !cardArea.containsPress) win.dismiss()
            else restart()
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
            list.positionViewAtEnd()
        }
        function onEvent(json) {
            const e = JSON.parse(json)
            if (e.type === "assistant-reset") { AgentClient.openAssistant(); return }
            if (!win.conversation || (e.conversation && e.conversation !== win.conversation)) return
            if (e.type === "level") { win.micLevel = e.db; return }
            chat.apply(e, true)
            if (e.type === "state") return
            idleTimer.restart()
            Qt.callLater(list.positionViewAtEnd)
            // Work finished while the card was away: bring the result up.
            if (e.type === "agent-finished" && !win.shown && win.screenName) win.summon(win.screenName)
        }
    }
    Component.onCompleted: AgentClient.openAssistant()

    // Dims a little and catches taps outside the card (the navigation panel stays out of it).
    Rectangle {
        anchors { left: parent.left; right: parent.right; top: parent.top }
        height: parent.height - win.navHeight
        color: "black"
        opacity: win.shown ? (win.dark ? 0.25 : 0.12) : 0
        Behavior on opacity { NumberAnimation { duration: 220 } }
        MouseArea {
            anchors.fill: parent
            onClicked: win.dismiss()
        }
    }

    Item {
        id: card
        readonly property real margin: Kirigami.Units.largeSpacing
        readonly property real radius: Kirigami.Units.gridUnit * 1.6
        width: Math.min(win.width - margin * 2, Kirigami.Units.gridUnit * 30)
        height: content.implicitHeight + Kirigami.Units.largeSpacing * 2
        x: (win.width - width) / 2
        readonly property real restY: win.height - win.navHeight - margin - height
        y: win.shown ? restY : win.height + Kirigami.Units.gridUnit
        Behavior on y { NumberAnimation { duration: 320; easing.type: Easing.OutCubic } }
        opacity: win.shown ? 1 : 0
        Behavior on opacity { NumberAnimation { duration: 200 } }

        // Frosted material: KWin blurs (and saturates) behind this shape (Overlay.setCard).
        function updateMaterial() { Overlay.setCard(Qt.rect(x, y, width, height), radius) }
        onXChanged: updateMaterial()
        onYChanged: updateMaterial()
        onWidthChanged: updateMaterial()
        onHeightChanged: updateMaterial()

        Kirigami.ShadowedRectangle {
            anchors.fill: parent
            radius: card.radius
            color: win.dark ? Qt.rgba(0.11, 0.11, 0.12, 0.58) : Qt.rgba(0.98, 0.98, 1.0, 0.62)
            border.width: 1
            border.color: win.dark ? Qt.rgba(1, 1, 1, 0.12) : Qt.rgba(0, 0, 0, 0.06)
            shadow.size: Kirigami.Units.gridUnit * 1.5
            shadow.yOffset: Kirigami.Units.smallSpacing * 2
            shadow.color: Qt.rgba(0, 0, 0, win.dark ? 0.45 : 0.18)
        }

        // Swipe the card down to dismiss; taps inside do nothing.
        MouseArea {
            id: cardArea
            anchors.fill: parent
            property real startY: 0
            onPressed: mouse => startY = mouse.y
            onReleased: mouse => { if (mouse.y - startY > Kirigami.Units.gridUnit * 2) win.dismiss() }
        }

        ColumnLayout {
            id: content
            anchors { left: parent.left; right: parent.right; top: parent.top; margins: Kirigami.Units.largeSpacing }
            spacing: Kirigami.Units.largeSpacing

            ListView {
                id: list
                Layout.fillWidth: true
                Layout.preferredHeight: Math.min(contentHeight, win.height * 0.45 - win.topHeight)
                visible: chat.entries.count > 0
                clip: true
                spacing: Kirigami.Units.smallSpacing
                model: chat.entries
                delegate: OverlayItem { dark: win.dark }
                onContentHeightChanged: Qt.callLater(positionViewAtEnd)
            }
            QQC2.Label {
                Layout.fillWidth: true
                visible: chat.entries.count === 0
                horizontalAlignment: Text.AlignHCenter
                text: "有什么可以帮你？"
                font.pointSize: Kirigami.Theme.defaultFont.pointSize * 1.3
                font.weight: Font.Medium
                opacity: 0.85
            }

            Item {
                Layout.fillWidth: true
                implicitHeight: orb.height + status.implicitHeight + Kirigami.Units.smallSpacing

                // The whole conversation in the app.
                RoundButton {
                    anchors { left: parent.left; verticalCenter: orb.verticalCenter }
                    dark: win.dark
                    iconName: "view-conversation-balloon-symbolic"
                    label: "在应用中查看"
                    onClicked: {
                        Overlay.openInApp(win.conversation)
                        win.dismiss()
                    }
                }

                Orb {
                    id: orb
                    anchors.horizontalCenter: parent.horizontalCenter
                    mode: win.listening ? "listening" : chat.phase === "speaking" ? "speaking"
                        : chat.agentBusy || chat.phase === "working" ? "working" : "idle"
                    level: win.micLevel
                    MouseArea {
                        anchors.fill: parent
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
                RoundButton {
                    anchors { right: parent.right; verticalCenter: orb.verticalCenter }
                    readonly property bool stops: chat.agentBusy || chat.phase === "speaking"
                    dark: win.dark
                    iconName: stops ? "media-playback-stop-symbolic" : "window-close-symbolic"
                    label: stops ? "停止" : "关闭"
                    onClicked: stops ? AgentClient.stopTask() : win.dismiss()
                }

                QQC2.Label {
                    id: status
                    anchors { top: orb.bottom; horizontalCenter: parent.horizontalCenter }
                    anchors.topMargin: Kirigami.Units.smallSpacing
                    opacity: 0.65
                    font.pointSize: Kirigami.Theme.smallFont.pointSize
                    text: win.holding ? "正在听 · 松开发送"
                        : chat.phase === "listening" ? (chat.handsFree ? "正在听 · 说完自动发送，轻点结束" : "正在听")
                        : chat.phase === "speaking" ? "正在回答 · 按住可打断"
                        : chat.agentBusy || chat.phase === "working" ? "正在处理"
                        : chat.phase === "connecting" ? "按住说话" : "按住说话，轻点免提"
                }
            }
        }
    }

    component RoundButton: QQC2.AbstractButton {
        id: round
        property string iconName
        property string label
        property bool dark: true
        width: Kirigami.Units.gridUnit * 2.4
        height: width
        Accessible.name: label
        background: Rectangle {
            radius: width / 2
            color: round.dark ? Qt.rgba(1, 1, 1, round.pressed ? 0.2 : 0.1) : Qt.rgba(0, 0, 0, round.pressed ? 0.12 : 0.06)
        }
        contentItem: Item {
            Kirigami.Icon {
                anchors.centerIn: parent
                width: Kirigami.Units.iconSizes.smallMedium
                height: width
                source: round.iconName
            }
        }
    }
}
