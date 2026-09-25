// SPDX-License-Identifier: GPL-2.0-or-later
// A round glass icon button (48 px: a comfortable touch target).
import QtQuick
import QtQuick.Controls as QQC2
import org.kde.kirigami as Kirigami

QQC2.AbstractButton {
    id: round
    property string iconName
    property string label
    implicitWidth: 48
    implicitHeight: 48
    Accessible.name: label
    background: Rectangle {
        radius: width / 2
        color: round.pressed ? Style.glassPressed : Style.glass
        border.width: 1
        border.color: Style.glassBorder
    }
    contentItem: Item {
        Kirigami.Icon {
            anchors.centerIn: parent
            width: 20
            height: 20
            source: round.iconName
            color: Style.ink
            isMask: true
        }
    }
}
