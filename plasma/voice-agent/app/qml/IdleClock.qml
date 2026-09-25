// SPDX-License-Identifier: GPL-2.0-or-later
// The resting light's slow clock (docs/59): an idle LightPill's colours keep turning,
// once in about 24 s. One clock for every pill on show, ticking 20 times a second and only
// while one is: a still window does not redraw at the display's rate.
pragma Singleton
import QtQuick

QtObject {
    property real time: 0      // in the pill's time units: 1/3.4 of its working speed
    property int users: 0      // idle pills on show
    readonly property Timer tick: Timer {
        interval: 50
        repeat: true
        running: users > 0
        onTriggered: time += 0.05 / 3.4
    }
}
