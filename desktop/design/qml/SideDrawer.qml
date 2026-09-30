// SPDX-License-Identifier: GPL-2.0-or-later
// The side panel that slides in from the left over a scrim (the conversation list).
import QtQuick
import QtQuick.Controls as QQC2
import com.rungic.design

QQC2.Drawer {
    id: drawer
    edge: Qt.LeftEdge
    width: Math.min(Theme.drawerWidth, parent ? parent.width * 0.86 : Theme.drawerWidth)
    height: parent ? parent.height : 0
    padding: 0
    background: Rectangle { color: Theme.side }
    QQC2.Overlay.modal: Rectangle { color: Theme.scrim }
    enter: Transition { NumberAnimation { property: "position"; to: 1; duration: Theme.slide; easing.type: Easing.Bezier; easing.bezierCurve: Theme.easing } }
    exit: Transition { NumberAnimation { property: "position"; to: 0; duration: Theme.normal; easing.type: Easing.Bezier; easing.bezierCurve: Theme.easing } }
}
