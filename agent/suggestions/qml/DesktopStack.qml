// SPDX-License-Identifier: GPL-2.0-or-later
import QtQuick

Item {
    id: stack
    objectName: "desktopSuggestionStack"
    required property var item
    property string selectedId: ""
    property bool pressedFeedback: false
    readonly property var members: item.members || [item]
    readonly property int count: members.length
    readonly property int currentIndex: Math.max(0, members.findIndex(record => record.id === selectedId))
    readonly property var suggestionRecord: members[currentIndex] || item
    readonly property bool presentationMoving: settling.running || dragOffset !== 0
    property real dragOffset: 0
    property int targetIndex: -1
    readonly property int revealedIndex: targetIndex >= 0 ? targetIndex : currentIndex + (dragOffset < 0 ? 1 : -1)
    signal selected(string recordId)
    signal openRequested(string recordId)
    implicitHeight: count > 1 ? 226 : 206
    clip: true

    // Gesture ownership belongs to the widget. Only two faces are instantiated,
    // regardless of the number of members; neither face sends its own receipt.
    function move(distance) {
        if (settling.running) return
        const candidate = currentIndex + (distance < 0 ? 1 : -1)
        dragOffset = candidate >= 0 && candidate < count
            ? Math.max(-height, Math.min(height, distance))
            : Math.max(-32, Math.min(32, distance * 0.18))
    }
    function finish(velocity, cancelled) {
        if (settling.running) return
        const candidate = currentIndex + (dragOffset < 0 ? 1 : -1)
        const commit = !cancelled && candidate >= 0 && candidate < count
            && (Math.abs(dragOffset) >= Math.min(64, height * 0.25)
                || (Math.abs(dragOffset) > 16 && Math.abs(velocity) > 650 && velocity * dragOffset > 0))
        targetIndex = commit ? candidate : -1
        slide.to = commit ? (dragOffset < 0 ? -height : height) : 0
        settling.start()
    }
    function openAt(y) {
        if (!presentationMoving)
            openRequested(count > 1 && y < 48 ? item.id : suggestionRecord.id)
    }
    function step(direction) {
        if (presentationMoving) return
        const candidate = currentIndex + direction
        if (candidate >= 0 && candidate < count) selected(members[candidate].id)
    }
    Keys.onUpPressed: step(1)
    Keys.onDownPressed: step(-1)
    SequentialAnimation {
        id: settling
        NumberAnimation { id: slide; target: stack; property: "dragOffset"; duration: 170; easing.type: Easing.OutCubic }
        ScriptAction {
            script: {
                if (stack.targetIndex >= 0) stack.selected(stack.members[stack.targetIndex].id)
                stack.dragOffset = 0
                stack.targetIndex = -1
            }
        }
    }
    SuggestionStack {
        width: stack.width; height: stack.height
        item: stack.item
        displayRecord: stack.members[stack.revealedIndex] || stack.suggestionRecord
        pageIndex: stack.revealedIndex
        visible: stack.dragOffset !== 0 && stack.revealedIndex >= 0 && stack.revealedIndex < stack.count
        enabled: false
        Accessible.ignored: true
        scale: 0.97 + 0.03 * Math.min(1, Math.abs(stack.dragOffset) / stack.height)
    }
    SuggestionStack {
        width: stack.width; height: stack.height; y: stack.dragOffset
        item: stack.item; displayRecord: stack.suggestionRecord; pageIndex: stack.currentIndex
        pressedFeedback: stack.pressedFeedback
        onClicked: stack.openRequested(stack.suggestionRecord.id)
    }
}
