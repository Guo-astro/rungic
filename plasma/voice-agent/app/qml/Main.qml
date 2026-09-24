// SPDX-License-Identifier: GPL-2.0-or-later
import QtQuick
import org.kde.kirigami as Kirigami

Kirigami.ApplicationWindow {
    id: root
    title: "语音助手"
    width: Kirigami.Units.gridUnit * 26
    height: Kirigami.Units.gridUnit * 40
    pageStack.initialPage: ConversationsPage {}
    pageStack.globalToolBar.style: Kirigami.ApplicationHeaderStyle.ToolBar
}
