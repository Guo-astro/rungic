// SPDX-License-Identifier: GPL-2.0-or-later
// Text with light passing over it: work in progress (Working · 12s · …).
import QtQuick
import QtQuick.Effects
import com.rungic.design

Item {
    id: shine
    property alias text: base.text
    property int pixelSize: 15
    property bool running: visible
    implicitWidth: base.implicitWidth
    implicitHeight: base.implicitHeight
    Text {
        id: base
        width: parent.width
        font.family: Theme.fontFamily
        font.pixelSize: shine.pixelSize
        color: Theme.dim
        elide: Text.ElideRight
    }
    Text {
        id: bright
        width: parent.width
        text: base.text
        font: base.font
        elide: base.elide
        color: Theme.text
        visible: false
        layer.enabled: true
    }
    Item {
        id: band
        width: parent.width
        height: parent.height
        visible: false
        layer.enabled: true
        Rectangle {
            property real at: -0.5
            x: (at * 2) * parent.width - width / 2
            width: parent.width * 0.6
            height: parent.height
            gradient: Gradient {
                orientation: Gradient.Horizontal
                GradientStop { position: 0; color: "transparent" }
                GradientStop { position: 0.5; color: "black" }
                GradientStop { position: 1; color: "transparent" }
            }
            NumberAnimation on at { from: 1; to: -0.25; duration: 1800; loops: Animation.Infinite; running: shine.running }
        }
    }
    MultiEffect {
        anchors.fill: bright
        source: bright
        maskEnabled: true
        maskSource: band
        visible: shine.running
    }
}
