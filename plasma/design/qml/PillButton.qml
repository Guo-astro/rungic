// SPDX-License-Identifier: GPL-2.0-or-later
// An outlined button (44 px): suggestions, call controls, "去设置".
// `negative` colours the label for destructive actions (挂断).
// States: normal, pressed, checked (on: 停止旁听), disabled.
import QtQuick
import QtQuick.Layouts
import QtQuick.Templates as T
import com.rungic.design

T.AbstractButton {
    id: control
    property string iconName
    property bool negative: false
    property int alignment: Qt.AlignHCenter
    property int radius: Theme.radiusPill
    property int fontSize: Theme.metaSize
    // The state shown: the control's own, or `forcedState` (the state gallery, docs/87).
    property string forcedState: ""
    readonly property string visualState: forcedState !== "" ? forcedState
        : !enabled ? "disabled" : down ? "pressed" : checked ? "checked" : "normal"
    state: visualState
    readonly property color label: negative ? Theme.negative : Theme.text
    property color fill: Theme.background
    property color ink: label
    states: [
        State { name: "normal"; PropertyChanges { control.fill: Theme.background; control.ink: control.label } },
        State { name: "pressed"; PropertyChanges { control.fill: Theme.fill; control.ink: control.label } },
        State { name: "checked"; PropertyChanges { control.fill: Theme.fill2; control.ink: control.label } },
        State { name: "disabled"; PropertyChanges { control.fill: Theme.background; control.ink: Theme.alpha(control.label, 0.4) } }
    ]
    implicitHeight: Math.max(Theme.touch, implicitContentHeight + topPadding + bottomPadding)
    implicitWidth: implicitContentWidth + leftPadding + rightPadding
    leftPadding: 16
    rightPadding: 16
    topPadding: 8
    bottomPadding: 8
    Accessible.name: text
    background: Rectangle {
        radius: control.radius
        color: control.fill
        border.width: 1
        border.color: Theme.line
    }
    contentItem: RowLayout {
        spacing: 6
        Item { Layout.fillWidth: control.alignment === Qt.AlignHCenter; visible: Layout.fillWidth }
        Icon {
            visible: control.iconName !== ""
            name: control.iconName
            color: control.ink
            implicitWidth: 16
            implicitHeight: 16
        }
        Text {
            Layout.fillWidth: control.alignment !== Qt.AlignHCenter
            text: control.text
            font.family: Theme.fontFamily
            font.pixelSize: control.fontSize
            color: control.ink
            elide: Text.ElideRight
        }
        Item { Layout.fillWidth: control.alignment === Qt.AlignHCenter; visible: Layout.fillWidth }
    }
}
