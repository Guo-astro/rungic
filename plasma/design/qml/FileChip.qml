// SPDX-License-Identifier: GPL-2.0-or-later
// A file in the conversation (docs/88): its icon and name in a quiet box; a tap is `clicked`
// (the app opens it). `iconName` "file" by default.
// States: normal, pressed, disabled.
import QtQuick
import QtQuick.Templates as T
import com.rungic.design

T.AbstractButton {
    id: chip
    property string name
    property string iconName: "file"
    property real maxWidth: 300
    // The state shown: the chip's own, or `forcedState` (the state gallery, docs/87).
    property string forcedState: ""
    readonly property string visualState: forcedState !== "" ? forcedState
        : !enabled ? "disabled" : down ? "pressed" : "normal"
    state: visualState
    property color fill: Theme.fill
    property color ink: Theme.text
    states: [
        State { name: "normal"; PropertyChanges { chip.fill: Theme.fill; chip.ink: Theme.text } },
        State { name: "pressed"; PropertyChanges { chip.fill: Theme.fill2; chip.ink: Theme.text } },
        State { name: "disabled"; PropertyChanges { chip.fill: Theme.fill; chip.ink: Theme.alpha(Theme.text, 0.4) } }
    ]
    implicitWidth: Math.min(maxWidth, label.implicitWidth + 22 + 8 + 28)
    implicitHeight: 48
    padding: 0
    text: name
    Accessible.name: name
    background: Rectangle {
        radius: Theme.radiusInput
        color: chip.fill
        Behavior on color { ColorAnimation { duration: Theme.quick } }
    }
    contentItem: Item {
        Icon {
            id: glyph
            anchors { left: parent.left; leftMargin: 14; verticalCenter: parent.verticalCenter }
            name: chip.iconName
            color: chip.visualState === "disabled" ? chip.ink : Theme.dim
        }
        Text {
            id: label
            anchors { left: glyph.right; leftMargin: 8; right: parent.right; rightMargin: 14; verticalCenter: parent.verticalCenter }
            text: chip.name
            elide: Text.ElideMiddle
            font.family: Theme.fontFamily
            font.pixelSize: Theme.metaSize
            color: chip.ink
        }
    }
}
