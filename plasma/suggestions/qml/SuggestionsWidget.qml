// SPDX-License-Identifier: GPL-2.0-or-later
import QtQuick
import QtQuick.Window
import QtQuick.Layouts
import QtQuick.Controls as QQC2
import com.rungic.design
import com.rungic.suggestions

Item {
    id: widget
    implicitWidth: 340
    implicitHeight: 340
    property bool activeView: visible && Window.active
    property var pending: []
    property bool refreshPending: false
    property var selection: ({})
    property bool stackMoving: false
    function remember(groupId, recordId) {
        const next = Object.assign({}, selection)
        next[groupId] = recordId
        selection = next
    }
    function flushRefresh() {
        if (!pointer.pressed && !list.moving && !stackMoving && refreshPending) rebuild()
    }
    readonly property var clientItems: client.groups
    onClientItemsChanged: {
        if (list && (list.moving || pointer.pressed || stackMoving)) refreshPending = true
        else rebuild()
    }
    function rebuild() {
        if (!list) return
        const top = list.atYBeginning
        const offset = list.contentY - list.originY
        const groups = client.groups
        const next = {}
        for (const group of groups) {
            const previous = selection[group.id]
            next[group.id] = group.members.some(record => record.id === previous) ? previous : group.members[0].id
        }
        selection = next
        pending = groups
        refreshPending = false
        Qt.callLater(() => {
            if (top) list.positionViewAtBeginning()
            else list.contentY = list.originY + Math.max(0, Math.min(offset, list.contentHeight - list.height))
        })
    }
    SuggestionsClient { id: client }
    PresentationTracker { view: list; suggestionsClient: client; active: widget.activeView && !pointer.pressed && !widget.stackMoving }
    onActiveViewChanged: client.watching(activeView)
    Component.onCompleted: { rebuild(); client.watching(activeView) }
    Component.onDestruction: client.watching(false)
    Accessible.role: Accessible.Grouping
    Accessible.name: "Agent 建议小组件"

    // The desktop and wallpaper remain the surrounding surface. Only individual
    // cards have a background; neither the widget nor its scrolling viewport does.
    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 8
        spacing: 10
        RowLayout {
            Layout.fillWidth: true
            Text {
                text: "Agent 建议"
                color: "white"
                font.pixelSize: 15
                font.weight: Font.DemiBold
                style: Text.Raised; styleColor: "#70000000"
                Layout.fillWidth: true
                opacity: titleTap.pressed ? 0.6 : 1
                MouseArea { id: titleTap; anchors.fill: parent; onClicked: client.open() }
            }
            QQC2.AbstractButton {
                text: widget.pending.length ? widget.pending.length + " 项  ›" : "查看  ›"
                implicitWidth: label.implicitWidth + 20
                implicitHeight: 30
                Accessible.name: "打开 Agent 建议"
                contentItem: Text { id: label; text: parent.text; color: "white"; font.pixelSize: 13; verticalAlignment: Text.AlignVCenter; horizontalAlignment: Text.AlignHCenter; style: Text.Raised; styleColor: "#70000000" }
                background: Rectangle { radius: 15; color: parent.down ? "#50000000" : "#20000000" }
                onClicked: client.open()
            }
        }
        ListView {
            id: list
            objectName: "suggestionsWidgetList"
            Layout.fillWidth: true
            Layout.fillHeight: true
            clip: true
            spacing: 12
            boundsBehavior: Flickable.StopAtBounds
            // Folio's outer SwipeArea steals a normal nested Flickable's drag.
            // Own this viewport's pointer sequence using Qt's preventStealing;
            // keep ListView's layout, bounds and kinetic flick implementation.
            interactive: false
            reuseItems: true
            model: widget.pending
            onMovingChanged: widget.flushRefresh()
            QQC2.ScrollBar.vertical: QQC2.ScrollBar {
                implicitWidth: 3; padding: 0
                policy: QQC2.ScrollBar.AsNeeded
                background: null
                contentItem: Rectangle { radius: 2; color: "#90ffffff" }
            }
            delegate: DesktopStack {
                id: card
                required property var modelData
                item: modelData
                selectedId: widget.selection[modelData.id] || ""
                onSelected: recordId => widget.remember(modelData.id, recordId)
                onPresentationMovingChanged: {
                    widget.stackMoving = presentationMoving
                    if (!presentationMoving) Qt.callLater(widget.flushRefresh)
                }
                width: list.width
                onOpenRequested: recordId => client.open(recordId)
                pressedFeedback: pointer.pressed && !pointer.dragged && pointer.pressId === modelData.id
            }
            Rectangle {
                visible: widget.pending.length === 0
                width: list.width; height: 106; radius: 22; color: Theme.background
                ColumnLayout {
                    anchors.fill: parent; anchors.margins: 18; spacing: 7
                    Text { text: "暂时没有待处理建议"; color: Theme.text; font.pixelSize: 16; Layout.fillWidth: true; wrapMode: Text.Wrap }
                    Text { text: client.error || (client.coverage.length ? "部分检查尚未完成，可以在 Agent 中查看。" : "有新发现时会留在这里。" ); color: Theme.dim; font.pixelSize: 12; Layout.fillWidth: true; wrapMode: Text.Wrap }
                }
            }
        }
    }
    // Capture once at the widget boundary. A press in a stack belongs to that
    // stack until release; header/gaps belong to the outer list. Never hand a
    // boundary drag to Folio's drawer halfway through a sequence.
    MouseArea {
        id: pointer
        objectName: "suggestionsWidgetPointer"
        anchors.fill: parent
        z: 2
        preventStealing: true
        scrollGestureEnabled: false
        property real startX: 0
        property real startY: 0
        property real startContentY: 0
        property real lastY: 0
        property double lastTime: 0
        property real velocity: 0
        property bool dragged: false
        property bool held: false
        property bool blocked: false
        property bool header: false
        property string pressId: ""
        property var pressCard: null
        property real cardY: 0
        function bounded(y) { return Math.max(list.originY, Math.min(y, list.originY + Math.max(0, list.contentHeight - list.height))) }
        onPressed: mouse => {
            blocked = widget.stackMoving
            list.cancelFlick()
            startX = mouse.x
            startY = lastY = mouse.y
            startContentY = list.contentY
            lastTime = Date.now(); velocity = 0; dragged = false; held = false
            const pos = mapToItem(list, mouse.x, mouse.y)
            header = pos.y < 0
            pressCard = pos.y >= 0 && pos.y < list.height
                ? list.itemAt(pos.x + list.contentX, pos.y + list.contentY) : null
            pressId = pressCard ? pressCard.item.id : ""
            cardY = pressCard ? mapToItem(pressCard, mouse.x, mouse.y).y : 0
        }
        onPositionChanged: mouse => {
            if (!pressed || blocked || held) return
            const distance = mouse.y - startY
            if (Math.max(Math.abs(distance), Math.abs(mouse.x - startX)) > Qt.styleHints.startDragDistance) dragged = true
            if (dragged) {
                const now = Date.now()
                velocity = (mouse.y - lastY) * 1000 / Math.max(1, now - lastTime)
                lastY = mouse.y; lastTime = now
                if (pressCard && pressCard.count > 1) pressCard.move(distance)
                else list.contentY = bounded(startContentY - distance)
            }
        }
        onPressAndHold: held = true // Folio handles native widget editing.
        onReleased: mouse => {
            if (blocked) return
            const recentVelocity = Date.now() - lastTime < 100 ? velocity : 0
            if (dragged && pressCard && pressCard.count > 1) pressCard.finish(recentVelocity, held)
            else if (dragged && !held) {
                if (Math.abs(recentVelocity) > 80) list.flick(0, Math.max(-1800, Math.min(1800, recentVelocity)))
            } else if (!held && mouse.x >= 0 && mouse.x < width && mouse.y >= 0 && mouse.y < height) {
                if (pressCard) pressCard.openAt(cardY)
                else if (header) client.open()
            }
        }
        onCanceled: {
            if (pressCard && !blocked) pressCard.finish(0, true)
            held = true
        }
        onPressedChanged: if (!pressed) Qt.callLater(widget.flushRefresh)
        onWheel: wheel => { list.contentY = bounded(list.contentY - wheel.angleDelta.y / 2); wheel.accepted = true }
    }
}
