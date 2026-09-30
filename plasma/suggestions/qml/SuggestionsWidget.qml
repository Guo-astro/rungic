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
    readonly property var clientItems: client.groups
    onClientItemsChanged: {
        if (list && (list.moving || pointer.pressed)) refreshPending = true
        else rebuild()
    }
    function rebuild() {
        if (!list) return
        const top = list.atYBeginning
        const offset = list.contentY - list.originY
        pending = client.groups
        refreshPending = false
        Qt.callLater(() => {
            if (top) list.positionViewAtBeginning()
            else list.contentY = list.originY + Math.max(0, Math.min(offset, list.contentHeight - list.height))
        })
    }
    SuggestionsClient { id: client }
    PresentationTracker { view: list; suggestionsClient: client; active: widget.activeView && !pointer.pressed }
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
            onMovingChanged: if (!moving && !pointer.pressed && widget.refreshPending) widget.rebuild()
            QQC2.ScrollBar.vertical: QQC2.ScrollBar {
                implicitWidth: 3; padding: 0
                policy: QQC2.ScrollBar.AsNeeded
                background: null
                contentItem: Rectangle { radius: 2; color: "#90ffffff" }
            }
            delegate: SuggestionStack {
                id: card
                required property var modelData
                item: modelData
                readonly property var suggestionRecord: modelData.members[0]
                width: list.width
                onClicked: client.open(modelData.id)
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
            MouseArea {
                id: pointer
                parent: list
                anchors.fill: parent
                z: 2
                preventStealing: true
                scrollGestureEnabled: false
                property real startY: 0
                property real startContentY: 0
                property real lastY: 0
                property double lastTime: 0
                property real velocity: 0
                property bool dragged: false
                property bool held: false
                property string pressId: ""
                function bounded(y) { return Math.max(list.originY, Math.min(y, list.originY + Math.max(0, list.contentHeight - list.height))) }
                onPressed: mouse => {
                    list.cancelFlick()
                    startY = lastY = mouse.y
                    startContentY = list.contentY
                    lastTime = Date.now(); velocity = 0; dragged = false; held = false
                    const index = list.indexAt(mouse.x + list.contentX, mouse.y + list.contentY)
                    pressId = index >= 0 ? widget.pending[index].id : ""
                }
                onPositionChanged: mouse => {
                    if (!pressed) return
                    if (Math.abs(mouse.y - startY) > Qt.styleHints.startDragDistance) dragged = true
                    if (dragged) {
                        const now = Date.now()
                        velocity = (mouse.y - lastY) * 1000 / Math.max(1, now - lastTime)
                        lastY = mouse.y; lastTime = now
                        list.contentY = bounded(startContentY + startY - mouse.y)
                    }
                }
                onPressAndHold: held = true // Folio's parent handles native widget editing.
                onReleased: mouse => {
                    if (dragged) {
                        if (Date.now() - lastTime < 100 && Math.abs(velocity) > 80)
                            list.flick(0, Math.max(-1800, Math.min(1800, velocity)))
                    } else if (!held && mouse.x >= 0 && mouse.x < width && mouse.y >= 0 && mouse.y < height) {
                        client.open(pressId)
                    }
                }
                onPressedChanged: if (!pressed && !list.moving && widget.refreshPending) Qt.callLater(widget.rebuild)
                onWheel: wheel => { list.contentY = bounded(list.contentY - wheel.angleDelta.y / 2); wheel.accepted = true }
            }
        }
    }
}
