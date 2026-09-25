// SPDX-License-Identifier: GPL-2.0-or-later
// The voice assistant's app (docs/59): the conversations, and one open beside them on a
// wide screen (the TV) or on top of them on the phone. Dark or light as the system is, like the Home
// button's overlay (docs/67).
import QtQuick
import org.kde.kirigami as Kirigami

Kirigami.ApplicationWindow {
    id: root
    // --conversation ID: open straight in that conversation (the overlay's "open in app").
    property string initialConversation: ""
    title: "语音助手"
    width: Kirigami.Units.gridUnit * 26
    height: Kirigami.Units.gridUnit * 40
    // Flat: the navigation panel below takes this same colour (MotoVoiceAssistant.colors).
    color: Style.ground

    pageStack.initialPage: ConversationsPage {}
    pageStack.globalToolBar.style: Kirigami.ApplicationHeaderStyle.None
    pageStack.defaultColumnWidth: Kirigami.Units.gridUnit * 20
    pageStack.separatorVisible: false

    // `title`, when known (the list), shows at once while the conversation loads.
    function openChat(id, title) {
        const top = pageStack.currentItem
        if (top && top.conversationId === id && pageStack.depth > 1) return
        while (pageStack.depth > 1) pageStack.pop()
        pageStack.push(Qt.resolvedUrl("ChatPage.qml"), { conversationId: id, initialTitle: title || "" })
    }
    // Called over D-Bus (a second start, the overlay's "open in app").
    function openConversation(id) { openChat(id, "") }
    Component.onCompleted: if (initialConversation) openConversation(initialConversation)
}
