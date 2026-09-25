// SPDX-License-Identifier: GPL-2.0-or-later
import QtQuick
import org.kde.kirigami as Kirigami

Kirigami.ApplicationWindow {
    id: root
    // --conversation ID: open straight in that conversation (the overlay's "open in app").
    property string initialConversation: ""
    title: "语音助手"
    width: Kirigami.Units.gridUnit * 26
    height: Kirigami.Units.gridUnit * 40
    pageStack.initialPage: ConversationsPage {}
    pageStack.globalToolBar.style: Kirigami.ApplicationHeaderStyle.ToolBar
    function openConversation(id) {
        const top = pageStack.currentItem
        if (top && top.conversationId === id) return
        while (pageStack.depth > 1) pageStack.pop()
        pageStack.push(Qt.resolvedUrl("ChatPage.qml"), { conversationId: id })
    }
    Component.onCompleted: if (initialConversation) openConversation(initialConversation)
}
