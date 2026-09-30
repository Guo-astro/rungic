// SPDX-License-Identifier: GPL-2.0-or-later
// Rows on one rounded fill, hairlines between them (settings).
import QtQuick
import QtQuick.Layouts
import com.rungic.design

Rectangle {
    id: group
    default property alias rows: column.data
    implicitHeight: column.implicitHeight
    radius: Theme.radiusGroup
    color: Theme.fill
    clip: true
    ColumnLayout {
        id: column
        width: parent.width
        spacing: 0
        // Every visible row after the first draws the hairline above it; the first and
        // last take the group's corners (their pressed fill).
        function mark() {
            const rows = []
            for (let i = 0; i < children.length; i++) {
                const row = children[i]
                if (row.separator !== undefined && row.visible) rows.push(row)
            }
            rows.forEach((row, i) => {
                row.separator = i > 0
                row.roundTop = i === 0
                row.roundBottom = i === rows.length - 1
            })
        }
        Component.onCompleted: mark()
        onChildrenChanged: mark()
    }
}
