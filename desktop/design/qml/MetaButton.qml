// SPDX-License-Identifier: GPL-2.0-or-later
// "Worked through 2 steps · 7s ›": opens the steps behind an answer.
// States: collapsed, expanded, pressed.
import QtQuick
import QtQuick.Layouts
import QtQuick.Templates as T
import com.rungic.design

T.AbstractButton {
    id: control
    property bool expanded: false
    property string forcedState: ""
    readonly property string visualState: forcedState !== "" ? forcedState
        : down ? "pressed" : expanded ? "expanded" : "collapsed"
    state: visualState
    property color ink: Theme.dim
    property real turn: 0
    states: [
        State { name: "collapsed"; PropertyChanges { control.ink: Theme.dim; control.turn: 0 } },
        State { name: "expanded"; PropertyChanges { control.ink: Theme.dim; control.turn: 90 } },
        State { name: "pressed"; PropertyChanges { control.ink: Theme.text; control.turn: control.expanded ? 90 : 0 } }
    ]
    implicitHeight: 32
    implicitWidth: implicitContentWidth
    padding: 0
    Accessible.name: expanded ? DesignI18n.i18nc("@info accessible name of an opened button", "%1, expanded", text) : text
    contentItem: RowLayout {
        spacing: 4
        Text {
            text: control.text
            font.family: Theme.fontFamily
            font.pixelSize: Theme.metaSize
            color: control.ink
        }
        Icon {
            name: "chevron"
            color: control.ink
            implicitWidth: 14
            implicitHeight: 14
            rotation: control.turn
            Behavior on rotation { NumberAnimation { duration: Theme.normal } }
        }
    }
}
