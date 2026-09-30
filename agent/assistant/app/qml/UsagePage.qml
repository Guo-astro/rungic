// SPDX-License-Identifier: GPL-2.0-or-later
import QtQuick
import QtQuick.Window
import com.rungic.design
import com.rungic.suggestions
Rectangle {
    id: page
    color: Theme.background
    IconButton { id: back; anchors { top: parent.top; left: parent.left; margins: 6 } iconName: "back"; text: i18nc("@action:button", "Back"); onClicked: page.Window.window.back() }
    Text { anchors { verticalCenter: back.verticalCenter; horizontalCenter: parent.horizontalCenter } text: i18nc("@title", "Agent Usage"); color: Theme.text; font.pixelSize: 18 }
    AgentUsageDetails { anchors { top: back.bottom; left: parent.left; right: parent.right; bottom: parent.bottom } }
}
