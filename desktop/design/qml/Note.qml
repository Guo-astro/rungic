// SPDX-License-Identifier: GPL-2.0-or-later
// A short note under a field: plain, "positive" (with a tick) or "negative" (with a mark).
import QtQuick
import QtQuick.Layouts
import com.rungic.design

RowLayout {
    property alias text: label.text
    property string tone: ""
    spacing: 8
    Icon {
        visible: parent.tone !== ""
        Layout.alignment: Qt.AlignTop
        Layout.topMargin: 1
        name: parent.tone === "negative" ? "alert" : "check"
        color: label.color
        implicitWidth: 16
        implicitHeight: 16
    }
    Text {
        id: label
        Layout.fillWidth: true
        font.family: Theme.fontFamily
        font.pixelSize: Theme.labelSize
        lineHeight: 19
        lineHeightMode: Text.FixedHeight
        wrapMode: Text.Wrap
        color: parent.tone === "negative" ? Theme.negative : parent.tone === "positive" ? Theme.positive : Theme.dim
    }
}
