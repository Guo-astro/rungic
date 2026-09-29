// SPDX-License-Identifier: GPL-2.0-or-later
// The mark of a single choice (22 px). States: off, on, disabled-off, disabled-on.
import QtQuick
import com.rungic.design

Rectangle {
    id: mark
    property bool on: false
    property bool enabled: true
    property string forcedState: ""
    readonly property string visualState: forcedState !== "" ? forcedState : (enabled ? "" : "disabled-") + (on ? "on" : "off")
    state: visualState
    states: [
        State { name: "off"; PropertyChanges { mark.border.width: 2; mark.border.color: Theme.dim } },
        State { name: "on"; PropertyChanges { mark.border.width: 7; mark.border.color: Theme.strong } },
        State { name: "disabled-off"; PropertyChanges { mark.border.width: 2; mark.border.color: Theme.alpha(Theme.dim, 0.4) } },
        State { name: "disabled-on"; PropertyChanges { mark.border.width: 7; mark.border.color: Theme.alpha(Theme.strong, 0.4) } }
    ]
    implicitWidth: 22
    implicitHeight: 22
    radius: 11
    color: "transparent"
    Behavior on border.width { NumberAnimation { duration: Theme.quick } }
}
