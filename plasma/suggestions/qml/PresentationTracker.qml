// SPDX-License-Identifier: GPL-2.0-or-later
import QtQuick
import QtQuick.Window

// Record an item only after its summary remains inside both the list viewport
// and the active window. A visible shell/window does not mean every card was seen.
Timer {
    required property var view
    required property var suggestionsClient
    property bool active: false
    property string selectedId: ""
    property var entered: ({})
    interval: 500
    running: active
    repeat: true
    onRunningChanged: if (!running) entered = ({})
    onTriggered: {
        if (view.moving) { entered = ({}); return }
        const now = Date.now()
        const next = ({})
        const shown = [], opened = []
        for (const child of view.contentItem.children) {
            if (!("suggestionRecord" in child) || !child.visible) continue
            const record = child.suggestionRecord
            if (!record || !record.id) continue
            const pos = child.mapToItem(view, 0, 0)
            const global = child.mapToItem(null, 0, 0)
            const window = child.Window.window
            // First 70px contains the summary/title, including on very tall detail cards.
            if (!window || pos.y < 0 || pos.y + 70 > view.height || pos.x >= view.width || pos.x + child.width <= 0
                || global.y < 0 || global.y + 70 > window.height || global.x >= window.width || global.x + child.width <= 0) continue
            const key = record.id + ":" + record.deliveryRevision
            next[key] = entered[key] || now
            if (now - next[key] < 800) continue
            const receipt = { id: record.id, revision: record.deliveryRevision }
            shown.push(receipt)
            if (record.id === selectedId) opened.push(receipt)
        }
        entered = next
        if (shown.length) suggestionsClient.present(shown, false)
        if (opened.length) suggestionsClient.present(opened, true)
    }
}
