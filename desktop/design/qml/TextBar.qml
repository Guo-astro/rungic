// SPDX-License-Identifier: GPL-2.0-or-later
// The composer in keyboard mode: a rounded field outlined in the strong colour, with
// attachments above the text when there are any.
import QtQuick
import QtQuick.Layouts
import com.rungic.design

Rectangle {
    id: bar
    default property alias content: column.data
    implicitHeight: column.implicitHeight + 12
    radius: 26
    color: Theme.fill
    border.width: 1.5
    border.color: Theme.strong
    ColumnLayout {
        id: column
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: parent.top
        anchors.margins: 6
        spacing: 2
    }
}
