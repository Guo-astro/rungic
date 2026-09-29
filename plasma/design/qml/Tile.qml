// SPDX-License-Identifier: GPL-2.0-or-later
// A big square choice in the attach panel: 拍照, 照片, 文件.
// States: normal, pressed, disabled.
import QtQuick
import QtQuick.Layouts
import QtQuick.Templates as T
import com.rungic.design

T.AbstractButton {
    id: tile
    property string iconName
    // The state shown: the tile's own, or `forcedState` (the state gallery, docs/87).
    property string forcedState: ""
    readonly property string visualState: forcedState !== "" ? forcedState
        : !enabled ? "disabled" : down ? "pressed" : checked ? "checked" : "normal"
    state: visualState
    property color fill: Theme.background
    property color ink: Theme.text
    states: [
        State { name: "normal"; PropertyChanges { tile.fill: Theme.background; tile.ink: Theme.text } },
        State { name: "pressed"; PropertyChanges { tile.fill: Theme.fill2; tile.ink: Theme.text } },
        State { name: "checked"; PropertyChanges { tile.fill: Theme.fill2; tile.ink: Theme.text } },
        State { name: "disabled"; PropertyChanges { tile.fill: Theme.background; tile.ink: Theme.alpha(Theme.text, 0.4) } }
    ]
    implicitHeight: 84
    Accessible.name: text
    background: Rectangle {
        radius: Theme.radiusGroup
        color: tile.fill
    }
    contentItem: ColumnLayout {
        spacing: 6
        Item { Layout.fillHeight: true }
        Icon { Layout.alignment: Qt.AlignHCenter; name: tile.iconName; color: tile.ink }
        Text {
            Layout.alignment: Qt.AlignHCenter
            text: tile.text
            font.family: Theme.fontFamily
            font.pixelSize: Theme.metaSize
            color: tile.ink
        }
        Item { Layout.fillHeight: true }
    }
}
