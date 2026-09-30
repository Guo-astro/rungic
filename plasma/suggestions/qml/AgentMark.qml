// SPDX-License-Identifier: GPL-2.0-or-later
// An agent's own mark: the icon its usage provider ships (docs/research/95), light or dark to
// match the theme, or its initial on a tile when it ships none. `muted`: signed out or offline.
import QtQuick
import QtQuick.Window
import com.rungic.design

Item {
    id: mark
    property string name
    property var icon: ({})
    property bool muted: false
    implicitWidth: 20
    implicitHeight: 20
    opacity: muted ? 0.4 : 1
    readonly property string path: icon ? ((Theme.dark && icon.dark) ? icon.dark : (icon.light || "")) : ""
    Image {
        id: picture
        anchors.fill: parent
        visible: mark.path !== "" && status === Image.Ready
        source: mark.path ? "file://" + mark.path : ""
        fillMode: Image.PreserveAspectFit
        sourceSize: Qt.size(Math.ceil(width * Screen.devicePixelRatio), Math.ceil(height * Screen.devicePixelRatio))
        asynchronous: false
    }
    Rectangle {
        anchors.fill: parent
        visible: !picture.visible   // no mark shipped, or its file is missing
        radius: 6
        color: Theme.fill
        border.width: 1
        border.color: Theme.line
        Text {
            anchors.centerIn: parent
            text: (mark.name || "?").charAt(0).toUpperCase()
            font.family: Theme.fontFamily
            font.pixelSize: 11
            font.weight: Font.DemiBold
            color: Theme.text
        }
    }
}
