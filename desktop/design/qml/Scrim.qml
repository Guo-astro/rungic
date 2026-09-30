// SPDX-License-Identifier: GPL-2.0-or-later
// The dimming behind a panel or sheet; a tap on it is `tapped`.
import QtQuick
import com.rungic.design

Rectangle {
    id: scrim
    signal tapped()
    color: Theme.scrim
    opacity: visible ? 1 : 0
    Behavior on opacity { NumberAnimation { duration: Theme.normal } }
    MouseArea { anchors.fill: parent; onClicked: scrim.tapped() }
}
