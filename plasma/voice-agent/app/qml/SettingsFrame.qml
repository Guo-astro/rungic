// SPDX-License-Identifier: GPL-2.0-or-later
// A settings page (docs/87): back, a centred title, scrolling content, and the page's
// actions fixed at the bottom (`footer`).
import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as QQC2
import com.rungic.design

Rectangle {
    id: frame
    default property alias content: column.data
    property alias footer: footerColumn.data
    property string title
    color: Theme.background

    function push(page, properties) { QQC2.StackView.view.push(page, properties || {}) }
    function back() { QQC2.StackView.view.pop() }

    Item {
        id: top
        anchors { left: parent.left; right: parent.right; top: parent.top }
        height: Theme.topBar
        IconButton {
            anchors { left: parent.left; leftMargin: 6; verticalCenter: parent.verticalCenter }
            iconName: "back"
            text: "返回"
            onClicked: frame.back()
        }
        Text {
            anchors { left: parent.left; right: parent.right; leftMargin: 64; rightMargin: 64; verticalCenter: parent.verticalCenter }
            horizontalAlignment: Text.AlignHCenter
            text: frame.title
            elide: Text.ElideRight
            font.family: Theme.fontFamily
            font.pixelSize: Theme.titleSize
            font.weight: Font.DemiBold
            color: Theme.text
            Accessible.role: Accessible.Heading
        }
    }
    Flickable {
        id: flick
        anchors { left: parent.left; right: parent.right; top: top.bottom; bottom: footerBox.top }
        contentHeight: column.implicitHeight
        clip: true
        boundsBehavior: Flickable.StopAtBounds
        ColumnLayout {
            id: column
            width: Math.min(flick.width, Theme.readingWidth)
            x: (flick.width - width) / 2
            spacing: 0
        }
        QQC2.ScrollIndicator.vertical: QQC2.ScrollIndicator {}
    }
    Item {
        id: footerBox
        anchors { left: parent.left; right: parent.right; bottom: parent.bottom }
        height: footerColumn.children.length > 0 ? footerColumn.implicitHeight + 32 : 0
        ColumnLayout {
            id: footerColumn
            width: Math.min(parent.width - 40, Theme.readingWidth)
            anchors { horizontalCenter: parent.horizontalCenter; top: parent.top; topMargin: 12 }
            spacing: 4
        }
    }
}
