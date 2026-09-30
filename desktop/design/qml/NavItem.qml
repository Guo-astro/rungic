// SPDX-License-Identifier: GPL-2.0-or-later
// A row of the side panel: a conversation, "New Chat", "Settings".
// States: normal, pressed, current (the open conversation), disabled.
import QtQuick
import QtQuick.Layouts
import QtQuick.Templates as T
import com.rungic.design

T.AbstractButton {
    id: item
    property string iconName
    property bool current: false
    property string forcedState: ""
    readonly property string visualState: forcedState !== "" ? forcedState
        : !enabled ? "disabled" : down ? "pressed" : current ? "current" : "normal"
    state: visualState
    property color fill: "transparent"
    property color ink: Theme.text
    property int weight: Font.Normal
    states: [
        State { name: "normal"; PropertyChanges { item.fill: "transparent"; item.ink: Theme.text; item.weight: Font.Normal } },
        State { name: "pressed"; PropertyChanges { item.fill: Theme.fill2; item.ink: Theme.text; item.weight: Font.Normal } },
        State { name: "current"; PropertyChanges { item.fill: Theme.fill2; item.ink: Theme.text; item.weight: Font.Medium } },
        State { name: "disabled"; PropertyChanges { item.fill: "transparent"; item.ink: Theme.dim; item.weight: Font.Normal } }
    ]
    Layout.fillWidth: true
    Layout.leftMargin: 8
    Layout.rightMargin: 8
    implicitHeight: Theme.touch
    leftPadding: 12
    rightPadding: 12
    Accessible.name: text
    background: Rectangle {
        radius: Theme.radiusItem
        color: item.fill
    }
    contentItem: RowLayout {
        spacing: 12
        Icon {
            visible: item.iconName !== ""
            name: item.iconName
            color: item.ink
            implicitWidth: 20
            implicitHeight: 20
        }
        Text {
            Layout.fillWidth: true
            text: item.text
            font.family: Theme.fontFamily
            font.pixelSize: Theme.bodySize
            font.weight: item.weight
            color: item.ink
            elide: Text.ElideRight
        }
    }
}
