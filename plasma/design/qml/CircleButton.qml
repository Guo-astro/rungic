// SPDX-License-Identifier: GPL-2.0-or-later
// The strong round button at the end of a bar: send, stop, talk (44 px).
// States: normal, pressed (shrinks a little), disabled.
import QtQuick
import QtQuick.Layouts
import QtQuick.Templates as T
import com.rungic.design

T.AbstractButton {
    id: control
    property string iconName
    // The state shown: the control's own, or `forcedState` (the state gallery, docs/87).
    property string forcedState: ""
    readonly property string visualState: forcedState !== "" ? forcedState
        : !enabled ? "disabled" : down ? "pressed" : checked ? "checked" : "normal"
    state: visualState
    property color fill: Theme.strong
    property color ink: Theme.strongInk
    property real press: 1
    states: [
        State { name: "normal"; PropertyChanges { control.fill: Theme.strong; control.ink: Theme.strongInk; control.press: 1 } },
        State { name: "pressed"; PropertyChanges { control.fill: Theme.strong; control.ink: Theme.strongInk; control.press: 0.94 } },
        State { name: "checked"; PropertyChanges { control.fill: Theme.strong; control.ink: Theme.strongInk; control.press: 1 } },
        State { name: "disabled"; PropertyChanges { control.fill: Theme.fill2; control.ink: Theme.dim; control.press: 1 } }
    ]
    implicitWidth: Theme.touch
    implicitHeight: Theme.touch
    padding: 0
    Accessible.name: text
    scale: press
    Behavior on scale { NumberAnimation { duration: Theme.quick; easing.type: Easing.OutQuad } }
    background: Rectangle {
        radius: width / 2
        color: control.fill
    }
    contentItem: Item {
        Icon {
            anchors.centerIn: parent
            name: control.iconName
            color: control.ink
            implicitWidth: 18
            implicitHeight: 18
        }
    }
}
