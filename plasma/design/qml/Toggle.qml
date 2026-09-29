// SPDX-License-Identifier: GPL-2.0-or-later
// An on/off switch (48 × 28): strong when on.
// States: off, on, pressed-off, pressed-on (the knob widens a little), disabled-off, disabled-on.
import QtQuick
import QtQuick.Layouts
import QtQuick.Templates as T
import com.rungic.design

T.AbstractButton {
    id: control
    checkable: true
    property string forcedState: ""
    readonly property string visualState: forcedState !== "" ? forcedState
        : (!enabled ? "disabled-" : down ? "pressed-" : "") + (checked ? "on" : "off")
    state: visualState
    property color track: Theme.fill2
    property color knob: Theme.background
    property real knobX: 3
    property real knobW: 22
    states: [
        State { name: "off"; PropertyChanges { control.track: Theme.fill2; control.knob: Theme.background; control.knobX: 3; control.knobW: 22 } },
        State { name: "on"; PropertyChanges { control.track: Theme.strong; control.knob: Theme.background; control.knobX: 23; control.knobW: 22 } },
        State { name: "pressed-off"; PropertyChanges { control.track: Theme.fill2; control.knob: Theme.background; control.knobX: 3; control.knobW: 26 } },
        State { name: "pressed-on"; PropertyChanges { control.track: Theme.strong; control.knob: Theme.background; control.knobX: 19; control.knobW: 26 } },
        State { name: "disabled-off"; PropertyChanges { control.track: Theme.alpha(Theme.fill2, 0.5); control.knob: Theme.alpha(Theme.background, 0.7); control.knobX: 3; control.knobW: 22 } },
        State { name: "disabled-on"; PropertyChanges { control.track: Theme.alpha(Theme.strong, 0.35); control.knob: Theme.alpha(Theme.background, 0.7); control.knobX: 23; control.knobW: 22 } }
    ]
    implicitWidth: 48
    implicitHeight: 28
    padding: 0
    Accessible.role: Accessible.CheckBox
    Accessible.name: text
    Accessible.checked: checked
    background: Rectangle {
        radius: height / 2
        color: control.track
        Behavior on color { ColorAnimation { duration: 150 } }
        Rectangle {
            x: control.knobX
            y: 3
            width: control.knobW
            height: 22
            radius: 11
            color: control.knob
            // The design's hairline shadow: a white knob on a light track stays visible.
            border.width: 1
            border.color: Qt.rgba(0, 0, 0, Theme.dark ? 0.35 : 0.14)
            Behavior on x { NumberAnimation { duration: 150; easing.type: Easing.Bezier; easing.bezierCurve: Theme.easing } }
            Behavior on width { NumberAnimation { duration: 150 } }
        }
    }
    contentItem: Item {}
}
