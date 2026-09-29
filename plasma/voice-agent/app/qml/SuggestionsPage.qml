// SPDX-License-Identifier: GPL-2.0-or-later
import QtQuick
import QtQuick.Window
import QtQuick.Controls as QQC2
import com.rungic.design
import com.rungic.suggestions

Rectangle {
    id: page
    property string suggestionId: ""
    color: Theme.side
    IconButton { id: back; anchors { top: parent.top; left: parent.left; margins: 6 } iconName: "back"; text: "返回"; onClicked: page.Window.window.back() }
    SuggestionsFeed {
        anchors { top: back.bottom; left: parent.left; right: parent.right; bottom: parent.bottom }
        selectedId: page.suggestionId
    }
}
