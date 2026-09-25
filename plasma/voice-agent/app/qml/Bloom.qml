// SPDX-License-Identifier: GPL-2.0-or-later
// The light rising from the Home button (docs/67, shaders/bloom.frag).
import QtQuick

ShaderEffect {
    property real time: 0
    property real level: 0        // voice, 0..1
    property real rise: 0         // 0 gone .. 1 fully up
    property real rim: 1          // edge light
    property real spread: width   // bloom width, px
    readonly property size area: Qt.size(width, height)
    fragmentShader: "qrc:/shaders/bloom.frag.qsb"
}
