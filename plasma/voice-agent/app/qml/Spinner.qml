// SPDX-License-Identifier: GPL-2.0-or-later
// A small gold arc turning: work in progress.
import QtQuick
import QtQuick.Shapes

Item {
    id: spinner
    implicitWidth: 16
    implicitHeight: 16
    Rectangle {
        anchors.fill: parent
        radius: width / 2
        color: "transparent"
        border.width: 2
        border.color: Style.track
    }
    Shape {
        anchors.fill: parent
        preferredRendererType: Shape.CurveRenderer
        ShapePath {
            strokeColor: Style.accent
            strokeWidth: 2
            fillColor: "transparent"
            capStyle: ShapePath.RoundCap
            PathAngleArc {
                centerX: 8; centerY: 8; radiusX: 7; radiusY: 7
                startAngle: -90; sweepAngle: 100
            }
        }
    }
    RotationAnimator on rotation {
        from: 0; to: 360; duration: 900
        loops: Animation.Infinite
        // Its own visibility: `parent` here was the item it sits in, visible with a finished
        // card's hidden spinner, which kept the window redrawing at 120 Hz (docs/59).
        running: spinner.visible
    }
}
