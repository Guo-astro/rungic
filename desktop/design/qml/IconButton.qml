// SPDX-License-Identifier: GPL-2.0-or-later
// A round icon-only button (44 px); `small` is the 36 px dim one under an answer.
// The name for screen readers is `text`.
// States: normal, pressed, checked (a toggled tool), disabled.
import QtQuick
import QtQuick.Layouts
import QtQuick.Templates as T
import com.rungic.design

T.AbstractButton {
    id: control
    property string iconName
    property bool small: false
    property color tint: small ? Theme.dim : Theme.text
    // The state shown: the control's own, or `forcedState` (the state gallery, docs/87).
    property string forcedState: ""
    readonly property string visualState: forcedState !== "" ? forcedState
        : !enabled ? "disabled" : down ? "pressed" : checked ? "checked" : "normal"
    state: visualState
    // What the state shows.
    property color fill: "transparent"
    property color ink: tint
    states: [
        State { name: "normal"; PropertyChanges { control.fill: "transparent"; control.ink: control.tint } },
        State { name: "pressed"; PropertyChanges { control.fill: Theme.fill; control.ink: Theme.text } },
        State { name: "checked"; PropertyChanges { control.fill: Theme.fill; control.ink: Theme.text } },
        State { name: "disabled"; PropertyChanges { control.fill: "transparent"; control.ink: Theme.alpha(control.tint, 0.4) } }
    ]
    implicitWidth: small ? 36 : Theme.touch
    implicitHeight: implicitWidth
    padding: 0
    Accessible.name: text
    focusPolicy: Qt.TabFocus
    background: Rectangle {
        radius: width / 2
        color: control.fill
        Behavior on color { ColorAnimation { duration: Theme.quick } }
    }
    contentItem: Item {
        Icon {
            anchors.centerIn: parent
            name: control.iconName
            color: control.ink
            implicitWidth: control.small ? 18 : 22
            implicitHeight: implicitWidth
        }
    }
}
