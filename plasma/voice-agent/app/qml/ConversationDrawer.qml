// SPDX-License-Identifier: GPL-2.0-or-later
// The conversations, in the side panel (docs/87): search, "新对话" and "主对话" (the one holding
// Home talks in, docs/67: always there, not deleted, not filtered by the search), then "其他对话",
// the user's own, by day (the open one marked), and the settings at the bottom. Holding one of
// those offers to delete it.
import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as QQC2
import com.rungic.design
import com.rungic.voiceassistant

SideDrawer {
    id: drawer
    property string current: ""
    property var all: []
    property string deleting: ""               // the conversation held to delete
    signal openRequested(string id, string title)
    signal newRequested()
    signal settingsRequested()
    signal suggestionsRequested()
    signal deleted(string id)

    function refresh() { AgentClient.listConversations() }
    onAboutToShow: { deleting = ""; search.text = ""; refresh() }

    Connections {
        target: AgentClient
        function onConversationsListed(json) { drawer.all = JSON.parse(json) }
    }

    // "今天", "昨天", "9月24日" (this year), "更早" (before this year's first days on the list).
    function dayOf(seconds) {
        const d = new Date(seconds * 1000)
        const today = new Date()
        today.setHours(0, 0, 0, 0)
        const days = Math.floor((today - new Date(d.getFullYear(), d.getMonth(), d.getDate())) / 86400000)
        if (days <= 0) return "今天"
        if (days === 1) return "昨天"
        if (days < 30) return (d.getMonth() + 1) + "月" + d.getDate() + "日"
        return "更早"
    }
    // The service marks the main conversation in the list (`assistant`).
    readonly property var main: all.find(c => c.assistant) || null
    readonly property var shown: {
        const q = search.text.trim().toLowerCase()
        return all.filter(c => !c.assistant)
                  .filter(c => !q || (c.title || "").toLowerCase().includes(q) || (c.preview || "").toLowerCase().includes(q))
                  .map(c => ({ cid: c.id, title: c.title || "新对话", day: dayOf(c.updated || c.created || 0) }))
    }
    // Sections need a ListModel.
    ListModel { id: rows }
    onShownChanged: {
        rows.clear()
        for (const c of shown) rows.append(c)
    }

    ColumnLayout {
        anchors.fill: parent
        spacing: 0
        Item { implicitHeight: 12 }
        SearchField {
            id: search
            Layout.fillWidth: true
            Layout.leftMargin: 12
            Layout.rightMargin: 12
            placeholderText: "搜索对话"
        }
        Item { implicitHeight: 8 }
        NavItem {
            iconName: "compose"
            text: "新对话"
            onClicked: drawer.newRequested()
        }
        // Beside "新对话", as one of the panel's own entries: the conversation holding Home talks in.
        NavItem {
            visible: drawer.main !== null
            iconName: "voice"
            text: "主对话"
            current: drawer.main !== null && drawer.main.id === drawer.current
            onClicked: drawer.openRequested(drawer.main.id, "主对话")
        }
        NavItem {
            iconName: "alert"
            text: "建议"
            onClicked: drawer.suggestionsRequested()
        }
        SectionLabel {
            Layout.fillWidth: true
            text: "其他对话"
            color: Theme.text
            font.weight: Font.Medium
            topPadding: 18
            bottomPadding: 0
        }
        ListView {
            id: list
            Layout.fillWidth: true
            Layout.fillHeight: true
            clip: true
            model: rows
            boundsBehavior: Flickable.StopAtBounds
            section.property: "day"
            section.delegate: SectionLabel {
                required property string section
                width: ListView.view.width
                text: section
                // The first day sits right under "其他对话".
                topPadding: rows.count > 0 && section === rows.get(0).day ? 6 : 18
                bottomPadding: 6
            }
            delegate: Item {
                id: row
                required property string cid
                required property string title
                width: ListView.view.width
                height: Theme.touch
                NavItem {
                    anchors { left: parent.left; right: parent.right; leftMargin: 8; rightMargin: 8 }
                    height: parent.height
                    visible: drawer.deleting !== row.cid
                    text: row.title
                    current: row.cid === drawer.current
                    onClicked: drawer.openRequested(row.cid, row.title)
                    onPressAndHold: drawer.deleting = row.cid
                }
                // Held: delete it, or not.
                RowLayout {
                    anchors { fill: parent; leftMargin: 16; rightMargin: 12 }
                    visible: drawer.deleting === row.cid
                    spacing: 8
                    Text {
                        Layout.fillWidth: true
                        text: row.title
                        elide: Text.ElideRight
                        font.family: Theme.fontFamily
                        font.pixelSize: Theme.bodySize
                        color: Theme.dim
                    }
                    PillButton {
                        text: "删除"
                        negative: true
                        onClicked: {
                            AgentClient.deleteConversation(row.cid)
                            drawer.all = drawer.all.filter(c => c.id !== row.cid)
                            drawer.deleted(row.cid)
                            drawer.deleting = ""
                        }
                    }
                    IconButton { small: true; iconName: "close"; text: "不删除"; onClicked: drawer.deleting = "" }
                }
            }
            Text {
                anchors.centerIn: parent
                visible: list.count === 0
                text: search.text ? "没有找到对话" : "还没有其他对话"
                font.family: Theme.fontFamily
                font.pixelSize: Theme.metaSize
                color: Theme.dim
            }
        }
        NavItem {
            Layout.bottomMargin: 12
            iconName: "settings"
            text: "设置"
            onClicked: drawer.settingsRequested()
        }
    }
}
