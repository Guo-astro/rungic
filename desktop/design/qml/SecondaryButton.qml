// SPDX-License-Identifier: GPL-2.0-or-later
// A quiet full-width text button (48 px): Not Now, Cancel Installation, Remove Key.
// States: normal, pressed, disabled.
import QtQuick
import QtQuick.Layouts
import QtQuick.Templates as T
import com.rungic.design

T.AbstractButton {
    id: control
    property bool negative: false
    // The state shown: the control's own, or `forcedState` (the state gallery, docs/87).
    property string forcedState: ""
    readonly property string visualState: forcedState !== "" ? forcedState
        : !enabled ? "disabled" : down ? "pressed" : checked ? "checked" : "normal"
    state: visualState
    readonly property color label: negative ? Theme.negative : Theme.text
    property color fill: "transparent"
    property color ink: label
    states: [
        State { name: "normal"; PropertyChanges { control.fill: "transparent"; control.ink: control.label } },
        State { name: "pressed"; PropertyChanges { control.fill: Theme.fill; control.ink: control.label } },
        State { name: "checked"; PropertyChanges { control.fill: "transparent"; control.ink: control.label } },
        State { name: "disabled"; PropertyChanges { control.fill: "transparent"; control.ink: Theme.alpha(control.label, 0.4) } }
    ]
    implicitHeight: 48
    implicitWidth: 200
    Accessible.name: text
    background: Rectangle {
        radius: height / 2
        color: control.fill
    }
    contentItem: Text {
        text: control.text
        horizontalAlignment: Text.AlignHCenter
        verticalAlignment: Text.AlignVCenter
        font.family: Theme.fontFamily
        font.pixelSize: Theme.bodySize
        color: control.ink
    }
}
