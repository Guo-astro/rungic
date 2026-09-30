// SPDX-License-Identifier: GPL-2.0-or-later
// A settings row: title and subtitle, a value (with a status dot), then a chevron,
// an outward arrow or a control of its own (`trailing`).
// States: normal, pressed (only when `interactive`), disabled.
import QtQuick
import QtQuick.Layouts
import QtQuick.Templates as T
import com.rungic.design

T.AbstractButton {
    id: row
    property string subtitle
    property string value
    property bool valueMono: false
    property string dot: ""                  // "" | "positive" | "negative"
    property string accessory: ""            // "" | "chevron" | "external"
    property bool interactive: accessory !== ""
    property bool separator: false
    // Set by ListGroup: the first and last rows' pressed fill follows the group's corners.
    property bool roundTop: false
    property bool roundBottom: false
    // Rows shown or hidden later: the group marks its first and last again.
    onVisibleChanged: if (parent && parent.mark) parent.mark()
    property alias leading: leadingSlot.data
    property alias trailing: trailingSlot.data
    property string forcedState: ""
    readonly property string visualState: forcedState !== "" ? forcedState
        : !enabled ? "disabled" : down && interactive ? "pressed" : "normal"
    state: visualState
    property color fill: "transparent"
    property color ink: Theme.text
    property color inkDim: Theme.dim
    property real dotOpacity: 1
    states: [
        State { name: "normal"; PropertyChanges { row.fill: "transparent"; row.ink: Theme.text; row.inkDim: Theme.dim; row.dotOpacity: 1 } },
        State { name: "pressed"; PropertyChanges { row.fill: Theme.fill2; row.ink: Theme.text; row.inkDim: Theme.dim; row.dotOpacity: 1 } },
        State { name: "disabled"; PropertyChanges { row.fill: "transparent"; row.ink: Theme.dim; row.inkDim: Theme.alpha(Theme.dim, 0.6); row.dotOpacity: 0.4 } }
    ]
    Layout.fillWidth: true
    implicitHeight: Math.max(Theme.row, implicitContentHeight + topPadding + bottomPadding)
    leftPadding: 16
    rightPadding: 16
    topPadding: 8
    bottomPadding: 8
    hoverEnabled: false
    Accessible.name: text + (subtitle ? "，" + subtitle : "") + (value ? "，" + value : "")
    background: Rectangle {
        color: row.fill
        topLeftRadius: row.roundTop ? Theme.radiusGroup : 0
        topRightRadius: topLeftRadius
        bottomLeftRadius: row.roundBottom ? Theme.radiusGroup : 0
        bottomRightRadius: bottomLeftRadius
        Rectangle {
            visible: row.separator
            x: 16
            width: parent.width - 16
            height: 1
            color: Theme.line
        }
    }
    contentItem: RowLayout {
        spacing: 12
        Item {
            id: leadingSlot
            visible: children.length > 0
            implicitWidth: childrenRect.width
            implicitHeight: childrenRect.height
        }
        ColumnLayout {
            Layout.fillWidth: true
            spacing: 1
            Text {
                Layout.fillWidth: true
                text: row.text
                font.family: Theme.fontFamily
                font.pixelSize: Theme.bodySize
                color: row.ink
                elide: Text.ElideRight
            }
            Text {
                Layout.fillWidth: true
                visible: row.subtitle !== ""
                text: row.subtitle
                font.family: Theme.fontFamily
                font.pixelSize: Theme.labelSize
                lineHeight: 18
                lineHeightMode: Text.FixedHeight
                color: row.inkDim
                wrapMode: Text.Wrap
            }
        }
        Rectangle {
            visible: row.dot !== ""
            implicitWidth: 8
            implicitHeight: 8
            radius: 4
            opacity: row.dotOpacity
            color: row.dot === "negative" ? Theme.negative : Theme.positive
        }
        Text {
            visible: row.value !== ""
            text: row.value
            font.family: row.valueMono ? Theme.monoFamily : Theme.fontFamily
            font.pixelSize: 15
            color: row.inkDim
        }
        Item {
            id: trailingSlot
            visible: children.length > 0
            implicitWidth: childrenRect.width
            implicitHeight: childrenRect.height
        }
        Icon {
            visible: row.accessory !== ""
            name: row.accessory === "external" ? "external" : "chevron"
            color: row.inkDim
            implicitWidth: row.accessory === "external" ? 16 : 18
            implicitHeight: implicitWidth
        }
    }
}
