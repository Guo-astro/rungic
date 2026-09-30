// SPDX-License-Identifier: GPL-2.0-or-later
// What the user said or typed: a light grey bubble on the right.
import QtQuick
import com.rungic.design

Rectangle {
    id: bubble
    property alias text: label.text
    property real maxWidth: 300
    property bool faded: false
    implicitWidth: Math.min(maxWidth, label.implicitWidth + 32)
    implicitHeight: label.implicitHeight + 18
    radius: 20
    color: Theme.fill
    opacity: faded ? 0.4 : 1
    TextEdit {
        id: label
        x: 16
        y: 9
        width: bubble.width - 32
        readOnly: true
        selectByMouse: false
        wrapMode: Text.Wrap
        font.family: Theme.fontFamily
        font.pixelSize: Theme.bodySize
        color: Theme.text
        textFormat: TextEdit.PlainText
    }
}
