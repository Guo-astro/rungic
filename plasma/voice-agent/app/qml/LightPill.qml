// SPDX-License-Identifier: GPL-2.0-or-later
// The light gathered into a capsule near Home (docs/67, shaders/pill.frag): breathing
// while the agent works, pulsing while the answer plays, dim while it waits.
import QtQuick

Item {
    id: root
    property string mode: "idle"      // work | speak | idle
    property real time: 0
    property real capsuleWidth: mode === "work" ? 150 : 116
    property real capsuleHeight: mode === "work" ? 50 : 42
    Behavior on capsuleWidth { NumberAnimation { duration: 280; easing.type: Easing.OutCubic } }
    Behavior on capsuleHeight { NumberAnimation { duration: 280; easing.type: Easing.OutCubic } }
    implicitWidth: capsuleWidth
    implicitHeight: capsuleHeight

    property real beat: 0
    SequentialAnimation on beat {
        running: root.visible && root.opacity > 0 && root.mode !== "idle"
        loops: Animation.Infinite
        NumberAnimation { to: 1; duration: root.mode === "speak" ? 280 : 1300; easing.type: Easing.InOutSine }
        NumberAnimation { to: 0.35; duration: root.mode === "speak" ? 180 : 0 }
        NumberAnimation { to: 0.8; duration: root.mode === "speak" ? 200 : 0 }
        NumberAnimation { to: 0; duration: root.mode === "speak" ? 240 : 1300; easing.type: Easing.InOutSine }
    }

    ShaderEffect {
        readonly property real margin: 36
        anchors.centerIn: parent
        width: root.capsuleWidth + margin * 2
        height: root.capsuleHeight + margin * 2
        scale: root.mode === "speak" ? 1 + 0.07 * root.beat : root.mode === "work" ? 0.96 + 0.07 * root.beat : 1
        readonly property size area: Qt.size(width, height)
        readonly property size capsule: Qt.size(root.capsuleWidth, root.capsuleHeight)
        readonly property real time: root.time
        readonly property real glow: root.mode === "idle" ? 0.45 : 0.75 + 0.25 * root.beat
        readonly property real bright: root.mode === "idle" ? 0.5 : 1
        readonly property real light: Style.dark ? 0 : 1
        fragmentShader: "qrc:/shaders/pill.frag.qsb"
    }
}
