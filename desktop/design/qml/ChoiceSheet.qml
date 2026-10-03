// SPDX-License-Identifier: GPL-2.0-or-later
// A choice from a short list, in a sheet up from the bottom (docs/102): a handle, the title, one
// ChoiceRow per choice. The tapped choice is marked at once and the sheet closes a moment later,
// so the change is seen; the scrim, dragging the sheet down, and Back close it without choosing.
// `choices`: [{ value, text, subtitle }]; `current`: the chosen value; `chosen(value)` is emitted.
import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as QQC2
import com.rungic.design

QQC2.Drawer {
    id: sheet
    property string title
    property var choices: []
    property var current
    property var pending: undefined         // tapped, shown as chosen until the sheet has closed
    signal chosen(var value)
    edge: Qt.BottomEdge
    width: parent ? parent.width : 0
    height: Math.min(column.implicitHeight, parent ? parent.height * 0.8 : column.implicitHeight)
    dragMargin: 0                           // opened by the app only; dragged down to close
    modal: true
    padding: 0
    background: Rectangle {
        color: Theme.background
        topLeftRadius: Theme.radiusSheet
        topRightRadius: Theme.radiusSheet
    }
    QQC2.Overlay.modal: Rectangle { color: Theme.scrim }
    enter: Transition { NumberAnimation { property: "position"; to: 1; duration: Theme.slide; easing.type: Easing.Bezier; easing.bezierCurve: Theme.easing } }
    exit: Transition { NumberAnimation { property: "position"; to: 0; duration: Theme.normal; easing.type: Easing.Bezier; easing.bezierCurve: Theme.easing } }
    onClosed: pending = undefined
    // The phone's back (Android's edge gesture, Alt+Left here, docs/46): the Drawer itself closes on
    // Escape only, and while it is open, modal, the page's own Back shortcut does not fire.
    Shortcut {
        sequence: StandardKey.Back
        enabled: sheet.opened
        onActivated: sheet.close()
    }

    contentItem: ColumnLayout {
        id: column
        spacing: 0
        Rectangle {
            Layout.alignment: Qt.AlignHCenter
            Layout.topMargin: 10
            implicitWidth: 36
            implicitHeight: 4
            radius: Theme.radiusXs
            color: Theme.fill2
        }
        Text {
            Layout.fillWidth: true
            Layout.leftMargin: Theme.gutter
            Layout.rightMargin: Theme.gutter
            Layout.topMargin: Theme.spaceM
            Layout.bottomMargin: Theme.spaceS
            visible: sheet.title !== ""
            text: sheet.title
            elide: Text.ElideRight
            font.family: Theme.fontFamily
            font.pixelSize: Theme.titleSize
            font.weight: Theme.weightStrong
            color: Theme.text
            Accessible.role: Accessible.Heading
        }
        ListGroup {
            Layout.fillWidth: true
            Layout.leftMargin: Theme.groupMargin
            Layout.rightMargin: Theme.groupMargin
            Layout.bottomMargin: Theme.spaceXxl
            Repeater {
                model: sheet.choices
                ChoiceRow {
                    required property var modelData
                    text: modelData.text
                    subtitle: modelData.subtitle || ""
                    checked: (sheet.pending !== undefined ? sheet.pending : sheet.current) === modelData.value
                    onClicked: {
                        if (sheet.pending !== undefined) return
                        sheet.pending = modelData.value
                        sheet.chosen(modelData.value)
                        closing.restart()
                    }
                }
            }
        }
    }
    // Long enough to see the mark move, short enough not to wait for it.
    Timer { id: closing; interval: Theme.normal + Theme.quick; onTriggered: sheet.close() }
}
