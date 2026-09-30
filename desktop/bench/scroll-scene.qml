// SPDX-License-Identifier: MIT
import QtQuick
Rectangle {
    id: root
    width: 360; height: 726
    color: "#17232d"
    property real travel: 0
    NumberAnimation on travel {
        from: 0; to: 880; duration: 4000
        loops: Animation.Infinite
    }
    Item {
        anchors.fill: parent
        clip: true
        Column {
            width: parent.width
            y: -root.travel
            spacing: 12
            Repeater {
                model: 24
                Rectangle {
                    required property int index
                    width: root.width - 24; height: 98; x: 12
                    radius: 12
                    color: index % 2 ? "#355768" : "#294555"
                    Rectangle {
                        x: 14; y: 18; width: 60; height: 60; radius: 15
                        gradient: Gradient {
                            GradientStop { position: 0; color: "#2fcae8" }
                            GradientStop { position: 1; color: "#ac65e7" }
                        }
                    }
                    Text {
                        x: 86; y: 18; color: "white"; font.pixelSize: 17
                        text: "Linux 桌面 · " + parent.index
                    }
                    Text {
                        x: 86; y: 49; color: "#c5dce4"; font.pixelSize: 12
                        text: "相同场景 · 原生 GPU 渲染"
                    }
                }
            }
        }
    }
}
