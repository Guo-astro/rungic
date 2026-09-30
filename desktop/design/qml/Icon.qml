// SPDX-License-Identifier: GPL-2.0-or-later
// One of the design's stroke icons (icons/*.svg, 24 px grid) in an exact colour: the colour
// is written into the SVG, its alpha is the opacity (docs/87). Kirigami's mask colouring lost
// white and half-transparent colours (the state gallery showed it).
import QtQuick
import QtQuick.Window
import com.rungic.design
import "icons.js" as Icons

Item {
    id: icon
    property string name
    property color color: Theme.text
    implicitWidth: 22
    implicitHeight: 22
    Image {
        anchors.fill: parent
        opacity: icon.color.a
        fillMode: Image.PreserveAspectFit
        smooth: true
        sourceSize: Qt.size(Math.ceil(icon.width * Screen.devicePixelRatio), Math.ceil(icon.height * Screen.devicePixelRatio))
        source: {
            const svg = icon.name ? Icons.svg(icon.name, Qt.rgba(icon.color.r, icon.color.g, icon.color.b, 1).toString()) : ""
            return svg ? "data:image/svg+xml;utf8," + encodeURIComponent(svg) : ""
        }
    }
}
