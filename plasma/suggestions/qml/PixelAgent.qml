// SPDX-License-Identifier: GPL-2.0-or-later
import QtQuick
import com.rungic.design
Item {
    id: robot
    property bool animate: false
    property bool working: false
    property bool blink: false
    implicitWidth: 48; implicitHeight: 48
    readonly property var pixels: ["0000001100000000", "0000001100000000", "0001111111111000", "0011111111111100", "0011000000001100", "1111022002201111", "1111022002201111", "0011000000001100", "0011002222001100", "0011111111111100", "0001111111111000", "0000011111100000", "0001111111111000", "0001101111011000", "0001100000011000", "0000000000000000"]
    Repeater {
        model: 256
        Rectangle {
            required property int index
            readonly property string pixel: robot.pixels[Math.floor(index / 16)][index % 16]
            x: (index % 16) * robot.width / 16; y: Math.floor(index / 16) * robot.height / 16
            width: robot.width / 16; height: robot.height / 16
            visible: pixel !== "0" && !(robot.blink && Math.floor(index / 16) === 5 && pixel === "2")
            color: pixel === "2" ? Theme.text : Theme.link
        }
    }
    Timer { interval: robot.working ? 1100 : 4300; repeat: true; running: robot.animate; onTriggered: { robot.blink = true; reopen.restart() } }
    Timer { id: reopen; interval: 140; onTriggered: robot.blink = false }
    onAnimateChanged: if (!animate) blink = false
}
