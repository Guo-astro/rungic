// SPDX-License-Identifier: GPL-2.0-or-later
// Bars that move with the voice: `level` 0..1 (the microphone), `active` false leaves
// them flat and faint (nothing heard, or a hold about to be cancelled).
import QtQuick
import com.rungic.design

Row {
    id: wave
    property real level: 0.5
    property bool active: true
    property color color: Theme.text
    property int bars: 30
    property int barHeight: 28
    spacing: 3
    height: barHeight
    property real phase: 0
    NumberAnimation on phase { from: 0; to: Math.PI * 2; duration: 1000; loops: Animation.Infinite; running: wave.active && wave.visible }
    Repeater {
        model: wave.bars
        Rectangle {
            required property int index
            width: 3
            radius: 1.5
            anchors.verticalCenter: parent.verticalCenter
            // A travelling sine, scaled by the level; flat at 15 % when inactive.
            readonly property real swing: 0.5 + 0.5 * Math.sin(wave.phase - index * 0.86)
            height: wave.barHeight * (wave.active ? Math.max(0.2, (0.25 + 0.75 * wave.level) * swing) : 0.15)
            color: wave.color
            opacity: wave.active ? 1 : 0.3
        }
    }
}
