// SPDX-License-Identifier: GPL-2.0-or-later
// A thin progress track: `value` 0..1, or indeterminate (value < 0) creeping forward.
import QtQuick
import com.rungic.design

Rectangle {
    id: track
    property real value: -1
    implicitHeight: 4
    radius: 2
    color: Theme.fill2
    clip: true
    Rectangle {
        id: bar
        height: parent.height
        radius: 2
        color: Theme.strong
        width: track.value >= 0 ? track.width * track.value : track.width * creep
        property real creep: 0.08
        SequentialAnimation on creep {
            running: track.value < 0 && track.visible
            loops: Animation.Infinite
            NumberAnimation { from: 0.08; to: 0.62; duration: 6000; easing.type: Easing.Bezier; easing.bezierCurve: Theme.easing }
        }
    }
}
