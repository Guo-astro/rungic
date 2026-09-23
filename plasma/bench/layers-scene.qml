// SPDX-License-Identifier: MIT
// Cached translucent window textures: an API comparison, not a KWin replacement.
import QtQuick
Rectangle {
    id: root
    width: 360; height: 726; color: "#162534"
    property real phase: 0
    NumberAnimation on phase { from: 0; to: 6.283185307; duration: 4500; loops: Animation.Infinite }
    Repeater {
        model: 6
        Rectangle {
            required property int index
            width: root.width * 0.80; height: root.height * 0.73
            x: 20 + Math.sin(root.phase + index * 0.55) * 18
            y: 35 + index * 24 + Math.cos(root.phase + index * 0.55) * 16
            rotation: Math.sin(root.phase + index) * 4
            opacity: 0.84; radius: 18
            layer.enabled: true
            gradient: Gradient {
                GradientStop { position: 0; color: "#427daf" }
                GradientStop { position: 1; color: "#192e54" }
            }
            Text { x: 20; y: 18; text: "窗口 / Window " + parent.index; color: "white"; font.pixelSize: 19 }
            Repeater {
                model: 9
                Rectangle {
                    required property int index
                    x: 16; y: 62 + index * 43
                    width: parent.width - 32; height: 31; radius: 7
                    color: index % 2 ? "#7484b5" : "#566c99"
                    Text { anchors.centerIn: parent; text: "Vulkan · OpenGL ES · " + parent.index; color: "white"; font.pixelSize: 13 }
                }
            }
        }
    }
}
