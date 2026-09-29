// SPDX-License-Identifier: GPL-2.0-or-later
// The one main action of a page (52 px, strong fill).
// States: normal, pressed, disabled, busy (a ring before the label while it works).
import QtQuick
import QtQuick.Layouts
import QtQuick.Templates as T
import com.rungic.design

T.AbstractButton {
    id: control
    property string iconName
    property bool busy: false
    property string forcedState: ""
    readonly property string visualState: forcedState !== "" ? forcedState
        : busy ? "busy" : !enabled ? "disabled" : down ? "pressed" : "normal"
    state: visualState
    property color fill: Theme.strong
    property color ink: Theme.strongInk
    property real press: 1
    states: [
        State { name: "normal"; PropertyChanges { control.fill: Theme.strong; control.ink: Theme.strongInk; control.press: 1 } },
        State { name: "pressed"; PropertyChanges { control.fill: Theme.strong; control.ink: Theme.strongInk; control.press: 0.98 } },
        State { name: "disabled"; PropertyChanges { control.fill: Theme.fill2; control.ink: Theme.dim; control.press: 1 } },
        State { name: "busy"; PropertyChanges { control.fill: Theme.strong; control.ink: Theme.strongInk; control.press: 1 } }
    ]
    implicitHeight: 52
    implicitWidth: 200
    Accessible.name: text
    scale: press
    Behavior on scale { NumberAnimation { duration: Theme.quick; easing.type: Easing.OutQuad } }
    background: Rectangle {
        radius: height / 2
        color: control.fill
    }
    contentItem: RowLayout {
        spacing: 8
        Item { Layout.fillWidth: true }
        BusyRing {
            visible: control.visualState === "busy"
            track: Theme.alpha(control.ink, 0.25)
            ring: control.ink
        }
        Icon {
            visible: control.iconName !== "" && control.visualState !== "busy"
            name: control.iconName
            color: control.ink
            implicitWidth: 20
            implicitHeight: 20
        }
        Text {
            text: control.text
            font.family: Theme.fontFamily
            font.pixelSize: Theme.bodySize
            font.weight: Font.DemiBold
            color: control.ink
        }
        Item { Layout.fillWidth: true }
    }
}
