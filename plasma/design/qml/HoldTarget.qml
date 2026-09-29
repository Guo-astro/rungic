// SPDX-License-Identifier: GPL-2.0-or-later
// A place to slide to while holding to talk: 取消 (×) or 转文字 (文). Grows and fills
// when the finger is over it.
// States: idle, active (the finger is over it: red for cancel, strong for "to text").
import QtQuick
import QtQuick.Layouts
import com.rungic.design

ColumnLayout {
    id: holdTarget
    property string iconName
    property alias text: label.text
    property bool on: false
    property bool edit: false               // the "to text" target fills strong, not red
    property string forcedState: ""
    readonly property string visualState: forcedState !== "" ? forcedState : on ? "active" : "idle"
    state: visualState
    property color fill: Theme.fill
    property color ink: Theme.text
    property color labelInk: Theme.dim
    property real grow: 1
    states: [
        State { name: "idle"; PropertyChanges { holdTarget.fill: Theme.fill; holdTarget.ink: Theme.text; holdTarget.labelInk: Theme.dim; holdTarget.grow: 1 } },
        State { name: "active"; PropertyChanges {
            holdTarget.fill: holdTarget.edit ? Theme.strong : Theme.negative
            holdTarget.ink: holdTarget.edit ? Theme.strongInk : "#ffffff"
            holdTarget.labelInk: Theme.text
            holdTarget.grow: 1.25 } }
    ]
    spacing: 8
    Rectangle {
        Layout.alignment: Qt.AlignHCenter
        Layout.preferredWidth: 60
        Layout.preferredHeight: 60
        radius: 30
        scale: holdTarget.grow
        color: holdTarget.fill
        Behavior on scale { NumberAnimation { duration: 150; easing.type: Easing.Bezier; easing.bezierCurve: Theme.easing } }
        Behavior on color { ColorAnimation { duration: 150 } }
        Icon {
            anchors.centerIn: parent
            name: holdTarget.iconName
            color: holdTarget.ink
            implicitWidth: 26
            implicitHeight: 26
        }
    }
    Text {
        id: label
        Layout.alignment: Qt.AlignHCenter
        font.family: Theme.fontFamily
        font.pixelSize: Theme.labelSize
        font.weight: holdTarget.visualState === "active" ? Font.DemiBold : Font.Normal
        color: holdTarget.labelInk
    }
}
