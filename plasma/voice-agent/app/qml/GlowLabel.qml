// SPDX-License-Identifier: GPL-2.0-or-later
// Status text in the light's colors (docs/67, shaders/glowtext.frag); plain when not glowing.
import QtQuick

Item {
    id: root
    property alias text: label.text
    property alias font: label.font
    property bool glowing: true
    property real time: 0
    implicitWidth: label.implicitWidth
    implicitHeight: label.implicitHeight

    Text {
        id: label
        color: Qt.rgba(1, 1, 1, 0.66)
        font.letterSpacing: 1.3
    }
    ShaderEffect {
        readonly property real margin: 10
        visible: root.glowing
        x: -margin
        y: -margin
        width: label.width + margin * 2
        height: label.height + margin * 2
        readonly property size area: Qt.size(width, height)
        readonly property real time: root.time
        readonly property var source: ShaderEffectSource {
            sourceItem: label
            hideSource: root.glowing
            sourceRect: Qt.rect(-10, -10, label.width + 20, label.height + 20)
        }
        fragmentShader: "qrc:/shaders/glowtext.frag.qsb"
    }
}
