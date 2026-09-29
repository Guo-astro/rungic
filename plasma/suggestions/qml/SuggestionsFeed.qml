// SPDX-License-Identifier: GPL-2.0-or-later
import QtQuick
import QtQuick.Window
import QtQuick.Layouts
import QtQuick.Controls as QQC2
import com.rungic.design
import com.rungic.suggestions

Rectangle {
    id: feed
    property bool home: false
    property string selectedId: ""
    property bool activeView: visible && Window.active
    property bool history: false
    property string message: ""
    property var pendingItem: ({})
    property var shown: []
    property bool pendingRefresh: false
    property bool populated: false
    property bool positioned: false
    color: Theme.side
    SuggestionsClient { id: client }
    readonly property var clientItems: client.items
    onClientItemsChanged: {
        if (list.moving) pendingRefresh = true
        else rebuild()
    }
    onHistoryChanged: rebuild()
    onActiveViewChanged: client.watching(activeView)
    Component.onCompleted: { rebuild(); client.watching(activeView) }
    Component.onDestruction: client.watching(false)
    function rebuild() {
        const atBeginning = !populated || list.atYBeginning
        const y = list.contentY - list.originY
        populated = client.items.length > 0
        shown = client.items.filter(i => history ? ["resolved", "dismissed"].includes(i.state) : !["resolved", "dismissed"].includes(i.state))
        pendingRefresh = false
        Qt.callLater(() => {
            if (selectedId && !positioned && client.items.some(i => i.id === selectedId)) {
                positioned = true; select(selectedId)
            }
            else if (atBeginning) list.positionViewAtBeginning()
            else list.contentY = list.originY + Math.max(-list.topMargin, Math.min(y, Math.max(0, list.contentHeight - list.height)))
        })
    }
    function select(id) {
        selectedId = id
        const item = client.items.find(i => i.id === id)
        if (item && ["resolved", "dismissed"].includes(item.state)) history = true
        const index = shown.findIndex(i => i.id === id)
        if (index >= 0) list.positionViewAtIndex(index, ListView.Center)
    }
    onSelectedIdChanged: { positioned = false; Qt.callLater(rebuild) }
    Connections {
        target: client
        function onReplied(id, action, result) {
            if (result.error) feed.message = result.error
            else if (result.message) feed.message = result.message
            else if (action === "investigate") feed.message = "Agent 已接到检查请求，可离开此页面，结果会留在建议中。"
        }
    }
    ListView {
        id: list
        objectName: "suggestionsFeed"
        anchors.fill: parent
        clip: true
        spacing: 14
        topMargin: 12; bottomMargin: 24
        boundsBehavior: Flickable.StopAtBounds
        reuseItems: true
        model: feed.shown
        onMovingChanged: if (!moving && feed.pendingRefresh) feed.rebuild()
        QQC2.ScrollBar.vertical: QQC2.ScrollBar { policy: QQC2.ScrollBar.AsNeeded }
        header: ColumnLayout {
            width: list.width
            spacing: 14
            Item { implicitHeight: feed.home ? 14 : 0 }
            RowLayout {
                Layout.fillWidth: true; Layout.leftMargin: 22; Layout.rightMargin: 22
                Text { text: feed.home ? "今天" : "建议"; font.pixelSize: feed.home ? 32 : 26; font.weight: Font.DemiBold; color: Theme.text; Layout.fillWidth: true }
                PillButton { text: "Agent"; onClicked: client.open() }
            }
            Text {
                Layout.leftMargin: 22; Layout.rightMargin: 22; Layout.fillWidth: true
                text: feed.home ? new Date().toLocaleDateString(Qt.locale("zh_CN"), "M月d日 dddd") + " · 为你留意手机的使用情况" : "发现的问题、改善建议和处理进展，都保留在这里。"
                font.pixelSize: 13; color: Theme.dim; wrapMode: Text.Wrap
            }
            RowLayout {
                Layout.leftMargin: 20; Layout.rightMargin: 20
                PillButton { text: "待处理"; checked: !feed.history; onClicked: feed.history = false }
                PillButton { text: "历史"; checked: feed.history; onClicked: feed.history = true }
                Item { Layout.fillWidth: true }
                PillButton { text: "刷新"; enabled: !client.busy; onClicked: { client.scan(); feed.message = "正在复查，系统诊断每分钟更新。" } }
            }
            Text {
                Layout.fillWidth: true; Layout.leftMargin: 22; Layout.rightMargin: 22
                visible: !!client.error || !!feed.message
                text: client.error || feed.message; textFormat: Text.PlainText; color: client.error ? Theme.negative : Theme.dim; font.pixelSize: 13; wrapMode: Text.Wrap
            }
            Rectangle {
                Layout.fillWidth: true; Layout.leftMargin: 20; Layout.rightMargin: 20
                visible: feed.shown.length === 0
                implicitHeight: 150; radius: 20; color: Theme.background; border.color: Theme.line
                ColumnLayout {
                    anchors { fill: parent; margins: 22 }
                    Text { text: feed.history ? "还没有历史记录" : "暂时没有需要处理的建议"; color: Theme.text; font.pixelSize: 18; wrapMode: Text.Wrap; Layout.fillWidth: true }
                    Text { text: client.coverage.length ? "部分检查暂未完成，可稍后刷新查看。" : "有新的发现时，卡片会出现在这里。"; color: Theme.dim; font.pixelSize: 14; wrapMode: Text.Wrap; Layout.fillWidth: true }
                }
            }
            Text {
                Layout.fillWidth: true; Layout.leftMargin: 22; Layout.rightMargin: 22
                visible: client.coverage.length > 0
                text: client.coverage.join("\n"); textFormat: Text.PlainText; font.pixelSize: 12; color: Theme.dim; wrapMode: Text.Wrap
            }
            Item { implicitHeight: 2 }
        }
        delegate: Item {
            required property var modelData
            width: list.width
            height: card.height
            SuggestionCard {
            id: card
            item: parent.modelData
            width: Math.min(list.width - 32, 680)
            anchors.horizontalCenter: parent.horizontalCenter
            expanded: item.id === feed.selectedId
            onAction: (name, args) => {
                if (name === "snooze-menu") { feed.pendingItem = item; snooze.open() }
                else if (name === "apply-confirm") { feed.pendingItem = item; applyDialog.open() }
                else if (name === "conversation") client.conversation(item.conversation || "")
                else client.act(item.id, name, args)
            }
        }
        }
        footer: Item { width: list.width; height: 40 }
    }
    QQC2.Popup {
        id: snooze
        parent: QQC2.Overlay.overlay
        anchors.centerIn: parent
        width: Math.min(340, feed.width - 24)
        modal: true; focus: true; padding: 18
        background: Rectangle { color: Theme.background; radius: 20; border.color: Theme.line }
        contentItem: ColumnLayout {
            spacing: 12
            Text { text: "什么时候再处理？"; color: Theme.text; font.pixelSize: 20; font.weight: Font.DemiBold }
            Text { Layout.fillWidth: true; text: "只安排提醒，不会自动修改软件。"; color: Theme.dim; font.pixelSize: 13; wrapMode: Text.Wrap }
            QQC2.Button { Layout.fillWidth: true; text: "保留待处理"; onClicked: { client.act(feed.pendingItem.id, "later"); snooze.close() } }
            QQC2.Button { Layout.fillWidth: true; text: "一小时后提醒"; onClicked: { client.act(feed.pendingItem.id, "snooze", { at: Math.floor(Date.now() / 1000) + 3600 }); snooze.close() } }
            QQC2.Button { Layout.fillWidth: true; text: "明天 10:00 提醒"; onClicked: { client.act(feed.pendingItem.id, "snooze", { at: client.tomorrow(10) }); snooze.close() } }
            QQC2.Button { Layout.fillWidth: true; visible: !!feed.pendingItem.process; text: "应用关闭后提醒"; onClicked: { client.act(feed.pendingItem.id, "closed"); snooze.close() } }
            QQC2.Button { Layout.fillWidth: true; text: "取消"; onClicked: snooze.close() }
        }
    }
    QQC2.Dialog {
        id: applyDialog
        parent: QQC2.Overlay.overlay
        anchors.centerIn: parent
        width: Math.min(340, feed.width - 24)
        height: Math.min(500, feed.height - 40)
        title: "应用修复方案"
        modal: true
        standardButtons: QQC2.Dialog.Ok | QQC2.Dialog.Cancel
        contentItem: QQC2.ScrollView {
          clip: true
          Text {
            width: applyDialog.availableWidth
            text: "Agent 将按已展示的方案执行，并验证结果。涉及的关闭应用或重启步骤以方案为准。\n\n" + (feed.pendingItem.plan || "")
            textFormat: Text.PlainText; wrapMode: Text.Wrap; color: Theme.text; font.pixelSize: 14
        }
        }
        onAccepted: client.act(feed.pendingItem.id, "apply")
    }
}
