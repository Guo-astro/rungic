// SPDX-License-Identifier: GPL-2.0-or-later
// The small label above a list group or a run of conversations.
import QtQuick
import com.rungic.design

Text {
    leftPadding: Theme.gutter
    rightPadding: Theme.gutter
    topPadding: 20
    bottomPadding: 8
    font.family: Theme.fontFamily
    font.pixelSize: Theme.labelSize
    lineHeight: 18
    lineHeightMode: Text.FixedHeight
    color: Theme.dim
    elide: Text.ElideRight
}
