// SPDX-License-Identifier: GPL-2.0-or-later
// A small spinning ring for work in progress (20 px); its colours follow what it sits on.
import QtQuick
import QtQuick.Shapes
import com.rungic.design

Item {
    id: ring
    property color track: Theme.fill2
    property color ring: Theme.text
    implicitWidth: 20
    implicitHeight: 20
    Rectangle {
        anchors.fill: parent
        radius: width / 2
        color: "transparent"
        border.width: 2
        border.color: ring.track
    }
    Shape {
        anchors.fill: parent
        preferredRendererType: Shape.CurveRenderer
        RotationAnimation on rotation { from: 0; to: 360; duration: 900; loops: Animation.Infinite; running: ring.visible }
        ShapePath {
            strokeWidth: 2
            strokeColor: ring.ring
            fillColor: "transparent"
            capStyle: ShapePath.RoundCap
            PathAngleArc { centerX: ring.width / 2; centerY: ring.height / 2; radiusX: ring.width / 2 - 1; radiusY: radiusX; startAngle: -90; sweepAngle: 90 }
        }
    }
}
