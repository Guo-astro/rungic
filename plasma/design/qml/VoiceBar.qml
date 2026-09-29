// SPDX-License-Identifier: GPL-2.0-or-later
// The composer's voice bar: a rounded fill the whole length of which can be held to talk.
// Its content (buttons, the wave) goes in as children and takes `ink`. `holdable`: the
// bar itself can be held (under its buttons, which keep their taps): pressed, moved,
// released and canceled report it, with the finger's position in the bar.
// States: idle, pressed (touched, before the hold starts), hot (held: strong, taller),
// cancel (held over ×), handsFree (listening without a hold), disabled.
import QtQuick
import QtQuick.Layouts
import com.rungic.design

Rectangle {
    id: bar
    default property alias content: row.data
    property string mode: "idle"
    property string forcedState: ""
    readonly property string visualState: forcedState !== "" ? forcedState : mode
    state: visualState
    property color ink: Theme.text
    property real barHeight: Theme.field
    property bool holdable: false
    readonly property alias held: holdArea.pressed
    signal pressed()
    signal moved(point position)
    signal released()
    signal canceled()
    states: [
        State { name: "idle"; PropertyChanges { bar.color: Theme.fill; bar.ink: Theme.text; bar.barHeight: Theme.field } },
        State { name: "pressed"; PropertyChanges { bar.color: Theme.fill2; bar.ink: Theme.text; bar.barHeight: Theme.field } },
        State { name: "hot"; PropertyChanges { bar.color: Theme.strong; bar.ink: Theme.strongInk; bar.barHeight: 64 } },
        State { name: "cancel"; PropertyChanges { bar.color: Theme.fill2; bar.ink: Theme.dim; bar.barHeight: 64 } },
        State { name: "handsFree"; PropertyChanges { bar.color: Theme.fill; bar.ink: Theme.text; bar.barHeight: Theme.field } },
        State { name: "disabled"; PropertyChanges { bar.color: Theme.fill; bar.ink: Theme.dim; bar.barHeight: Theme.field } }
    ]
    implicitHeight: barHeight
    radius: Theme.radiusField
    Behavior on color { ColorAnimation { duration: 150 } }
    Behavior on barHeight { NumberAnimation { duration: 150; easing.type: Easing.Bezier; easing.bezierCurve: Theme.easing } }
    MouseArea {
        id: holdArea
        anchors.fill: parent
        enabled: bar.holdable
        preventStealing: true
        onPressed: bar.pressed()
        onPositionChanged: mouse => bar.moved(Qt.point(mouse.x, mouse.y))
        onReleased: bar.released()
        onCanceled: bar.canceled()
    }
    RowLayout {
        id: row
        anchors.fill: parent
        anchors.margins: 6
        spacing: 0
    }
}
