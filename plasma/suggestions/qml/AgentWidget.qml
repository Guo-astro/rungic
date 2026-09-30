// SPDX-License-Identifier: GPL-2.0-or-later
import QtQuick
import QtQuick.Window
import QtQuick.Layouts
import QtQuick.Controls as QQC2
import com.rungic.design
import com.rungic.suggestions
import "UsageText.js" as UsageText

Item {
    id: widget
    implicitWidth: 340; implicitHeight: 126
    property bool activeView: visible && Window.active
    property double now: Date.now() / 1000
    UsageClient { id: usage }
    SuggestionsClient { id: navigation }
    readonly property var data: usage.data
    readonly property var windows: data.windows || []
    Timer { interval: 60000; repeat: true; running: widget.activeView; onTriggered: { widget.now = Date.now() / 1000; usage.refresh() } }
    onActiveViewChanged: if (activeView) usage.refresh()
    Rectangle {
        anchors.fill: parent; anchors.margins: 8
        radius: 20; color: Theme.background; border.color: Theme.line
        RowLayout {
            anchors.fill: parent; anchors.margins: 12; spacing: 12
            QQC2.AbstractButton {
                implicitWidth: 54; implicitHeight: 66
                Accessible.name: "打开 Codex 助理"
                onClicked: navigation.openAgent()
                background: null
                contentItem: ColumnLayout {
                    spacing: 4
                    PixelAgent { Layout.alignment: Qt.AlignHCenter; animate: widget.activeView; working: widget.data.activity === "working" }
                    Text { text: "Codex"; color: Theme.text; font.pixelSize: 11; Layout.alignment: Qt.AlignHCenter }
                }
            }
            QQC2.AbstractButton {
                Layout.fillWidth: true; Layout.fillHeight: true
                Accessible.name: "查看 Agent 用量"
                onClicked: navigation.openAgent(true)
                background: Rectangle { radius: 10; color: parent.down ? Theme.hover : "transparent" }
                contentItem: ColumnLayout {
                    spacing: 4
                    Text { text: (widget.data.activity === "working" ? "正在处理" : "就绪") + " · " + UsageText.mode(widget.data); color: Theme.dim; font.pixelSize: 11; Layout.fillWidth: true; elide: Text.ElideRight }
                    Text { text: UsageText.token(widget.data); color: Theme.text; font.pixelSize: 13; font.weight: Font.DemiBold; Layout.fillWidth: true; elide: Text.ElideRight }
                    Text {
                        text: widget.data.error ? "用量暂未更新 · 查看详情" : widget.windows.length ? "已用 " + widget.windows[0].usedPercent + "% · " + UsageText.reset(widget.windows[0], widget.now) : widget.data.authMode === "apiKey" ? "按量使用 · 无订阅重置时间" : "查看账户用量与额度"
                        color: Theme.dim; font.pixelSize: 10; Layout.fillWidth: true; wrapMode: Text.Wrap; maximumLineCount: 2; elide: Text.ElideRight
                    }
                }
            }
        }
    }
}
