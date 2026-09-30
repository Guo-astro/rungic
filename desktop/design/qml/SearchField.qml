// SPDX-License-Identifier: GPL-2.0-or-later
// The search box at the top of the side panel.
import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as QQC2
import com.rungic.design

Rectangle {
    property alias text: input.text
    property alias placeholderText: input.placeholderText
    implicitHeight: Theme.touch
    radius: Theme.touch / 2
    color: Theme.fill2
    RowLayout {
        anchors.fill: parent
        anchors.leftMargin: 12
        anchors.rightMargin: 12
        spacing: 8
        Icon { name: "search"; color: Theme.dim; implicitWidth: 18; implicitHeight: 18 }
        QQC2.TextField {
            id: input
            Layout.fillWidth: true
            background: null
            padding: 0
            font.family: Theme.fontFamily
            font.pixelSize: Theme.bodySize
            color: Theme.text
            placeholderTextColor: Theme.dim
            Accessible.name: placeholderText
        }
    }
}
