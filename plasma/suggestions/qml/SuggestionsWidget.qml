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
    readonly property var clientItems: client.items
    onClientItemsChanged: {
        if (list && (list.moving || pointer.pressed)) refreshPending = true
        else rebuild()
    }
    function rebuild() {
        if (!list) return
        const top = list.atYBeginning
        const offset = list.contentY - list.originY
        pending = client.items.filter(i => !["resolved", "dismissed"].includes(i.state))
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
            delegate: QQC2.AbstractButton {
                id: card
                required property var modelData
                readonly property var suggestionRecord: modelData
                width: list.width
                height: 139
                readonly property var evidence: modelData.evidence || ({})
                readonly property string title: evidence.package === "plasma-workspace" ? "桌面组件曾意外退出" : (modelData.title || "建议")
                Accessible.name: title + "，查看建议"
                onClicked: client.open(modelData.id)
                background: Rectangle {
                    radius: 22
                    color: card.down || (pointer.pressed && !pointer.dragged && pointer.pressId === card.modelData.id) ? Theme.hover : Theme.background
                    border.width: 1
                    border.color: Theme.line
                }
                contentItem: ColumnLayout {
                    anchors.fill: parent
                    anchors.margins: 16
                    spacing: 7
                    RowLayout {
                        Layout.fillWidth: true
                        Icon { name: card.modelData.kind === "fault" ? "alert" : "compose"; color: Theme.link; implicitWidth: 15; implicitHeight: 15 }
                        Text {
                            text: ({working: "正在处理", attention: "有处理结果", snoozed: "稍后处理"})[card.modelData.state] || (card.modelData.kind === "fault" ? "使用问题" : "改善建议")
                            font.pixelSize: 11; color: Theme.dim
                            Layout.fillWidth: true
                        }
                        Text { text: "›"; font.pixelSize: 18; color: Theme.dim }
                    }
                    Text { text: card.title; textFormat: Text.PlainText; Layout.fillWidth: true; color: Theme.text; font.pixelSize: 16; font.weight: Font.DemiBold; maximumLineCount: 1; elide: Text.ElideRight }
                    Text {
                        text: card.modelData.note || card.modelData.body || "可以让 Agent 检查，或留待稍后处理。"
                        textFormat: Text.PlainText
                        Layout.fillWidth: true; Layout.fillHeight: true
                        font.pixelSize: 12; lineHeight: 1.2; color: Theme.dim
                        wrapMode: Text.Wrap; maximumLineCount: 2; elide: Text.ElideRight
                    }
                }
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
