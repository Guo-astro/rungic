// SPDX-License-Identifier: GPL-2.0-or-later
// A sheet up from the bottom edge with a handle (the Home button's overlay). Dragging its
// top edge reports swipedUp or swipedDown; a tap on it, handleTapped.
import QtQuick
import QtQuick.Layouts
import com.rungic.design

Rectangle {
    id: sheet
    default property alias content: column.data
    property alias spacing: column.spacing
    signal swipedUp()
    signal swipedDown()
    signal handleTapped()
    implicitHeight: column.implicitHeight + 10 + 16
    color: Theme.background
    topLeftRadius: Theme.radiusSheet
    topRightRadius: Theme.radiusSheet
    MouseArea {
        anchors { left: parent.left; right: parent.right; top: parent.top }
        height: 28
        property real startY: 0
        onPressed: mouse => startY = mouse.y
        onReleased: mouse => {
            const dy = mouse.y - startY
            if (dy > 40) sheet.swipedDown()
            else if (dy < -40) sheet.swipedUp()
            else sheet.handleTapped()
        }
    }
    ColumnLayout {
        id: column
        anchors.fill: parent
        anchors.leftMargin: Theme.gutter
        anchors.rightMargin: Theme.gutter
        anchors.topMargin: 10
        anchors.bottomMargin: 16
        spacing: 14
        Rectangle {
            Layout.alignment: Qt.AlignHCenter
            Layout.preferredWidth: 36
            Layout.preferredHeight: 4
            radius: 2
            color: Theme.fill2
        }
    }
}
