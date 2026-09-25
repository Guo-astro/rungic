// SPDX-License-Identifier: GPL-2.0-or-later
// The overlay's voice orb (docs/67): still with a microphone when idle, following the
// voice while listening, breathing while the agent works, pulsing while it answers.
import QtQuick
import QtQuick.Effects
import QtQuick.Shapes
import org.kde.kirigami as Kirigami

Item {
    id: orb
    property string mode: "idle"      // idle | listening | working | speaking
    property real level: -90          // microphone, dBFS
    implicitWidth: Kirigami.Units.gridUnit * 4
    implicitHeight: implicitWidth

    // 0..1 from the voice, smoothed so the orb swells and settles rather than flickers.
    readonly property real energy: mode === "listening" ? Math.max(0, Math.min(1, (level + 55) / 35)) : 0
    property real smoothed: energy
    Behavior on smoothed { NumberAnimation { duration: 120; easing.type: Easing.OutQuad } }

    property real breath: 0
    SequentialAnimation on breath {
        running: orb.visible && (orb.mode === "working" || orb.mode === "speaking")
        loops: Animation.Infinite
        NumberAnimation { to: 1; duration: orb.mode === "speaking" ? 520 : 1300; easing.type: Easing.InOutSine }
        NumberAnimation { to: 0; duration: orb.mode === "speaking" ? 520 : 1300; easing.type: Easing.InOutSine }
    }
    property real angle: 0
    NumberAnimation on angle {
        running: orb.visible && orb.mode !== "idle"
        from: 0; to: 360; loops: Animation.Infinite
        duration: orb.mode === "working" ? 2600 : 5200
    }

    property real ballScale: {
        switch (mode) {
        case "listening": return 0.78 + 0.32 * smoothed
        case "working": return 0.74 + 0.06 * breath
        case "speaking": return 0.8 + 0.1 * breath
        default: return 0.72
        }
    }
    Behavior on ballScale { enabled: orb.mode !== "listening"; NumberAnimation { duration: 180 } }

    Item {
        id: ball
        anchors.centerIn: parent
        width: parent.width * orb.ballScale
        height: width
        visible: false          // drawn through the glow below and the copy on top
        layer.enabled: true

        Shape {
            anchors.fill: parent
            preferredRendererType: Shape.CurveRenderer
            ShapePath {
                strokeWidth: -1
                fillGradient: ConicalGradient {
                    centerX: ball.width / 2; centerY: ball.height / 2; angle: orb.angle
                    GradientStop { position: 0.0; color: "#5E5CE6" }
                    GradientStop { position: 0.22; color: "#BF5AF2" }
                    GradientStop { position: 0.45; color: "#FF375F" }
                    GradientStop { position: 0.62; color: "#FF9F0A" }
                    GradientStop { position: 0.82; color: "#64D2FF" }
                    GradientStop { position: 1.0; color: "#5E5CE6" }
                }
                PathAngleArc {
                    centerX: ball.width / 2; centerY: ball.height / 2
                    radiusX: ball.width / 2; radiusY: ball.height / 2
                    startAngle: 0; sweepAngle: 360
                }
            }
            // A soft light from the upper left: depth without an outline.
            ShapePath {
                strokeWidth: -1
                fillGradient: RadialGradient {
                    centerX: ball.width * 0.36; centerY: ball.height * 0.32; centerRadius: ball.width * 0.62
                    focalX: centerX; focalY: centerY
                    GradientStop { position: 0.0; color: Qt.rgba(1, 1, 1, 0.55) }
                    GradientStop { position: 1.0; color: Qt.rgba(1, 1, 1, 0) }
                }
                PathAngleArc {
                    centerX: ball.width / 2; centerY: ball.height / 2
                    radiusX: ball.width / 2; radiusY: ball.height / 2
                    startAngle: 0; sweepAngle: 360
                }
            }
        }
    }

    MultiEffect {
        source: ball
        anchors.centerIn: parent
        width: ball.width
        height: ball.height
        scale: 1.08 + 0.18 * orb.smoothed
        blurEnabled: true
        blur: 1.0
        blurMax: 20
        autoPaddingEnabled: true
        opacity: orb.mode === "idle" ? 0.25 : 0.45 + 0.3 * orb.smoothed
    }
    MultiEffect {
        source: ball
        anchors.centerIn: parent
        width: ball.width
        height: ball.height
    }

    Kirigami.Icon {
        anchors.centerIn: parent
        width: parent.width * 0.3
        height: width
        source: "audio-input-microphone-symbolic"
        color: "white"
        isMask: true
        opacity: orb.mode === "idle" ? 0.95 : 0
        Behavior on opacity { NumberAnimation { duration: 150 } }
    }
}
