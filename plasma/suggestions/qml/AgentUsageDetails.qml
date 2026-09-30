// SPDX-License-Identifier: GPL-2.0-or-later
import QtQuick
import QtQuick.Window
import QtQuick.Layouts
import QtQuick.Controls as QQC2
import com.rungic.design
import com.rungic.suggestions
import "UsageText.js" as UsageText

QQC2.ScrollView {
    id: view
    clip: true
    property double now: Date.now() / 1000
    UsageClient { id: usage }
    readonly property var data: usage.data
    Timer { interval: 60000; running: view.visible && view.Window.active; repeat: true; onTriggered: { view.now = Date.now() / 1000; usage.refresh() } }
    ColumnLayout {
        width: view.availableWidth; spacing: 16
        RowLayout {
            Layout.margins: 20
            PixelAgent { animate: view.visible && view.Window.active; working: view.data.activity === "working" }
            ColumnLayout {
                Text { text: "Codex"; color: Theme.text; font.pixelSize: 24; font.weight: Font.DemiBold }
                Text { text: UsageText.mode(view.data) + " · " + (view.data.model || "模型尚未读取"); color: Theme.dim; font.pixelSize: 12 }
            }
            Item { Layout.fillWidth: true }
            PillButton { text: "刷新"; onClicked: { view.now = Date.now() / 1000; usage.refresh() } }
        }
        Text { text: UsageText.token(view.data); color: Theme.text; font.pixelSize: 22; wrapMode: Text.Wrap; Layout.fillWidth: true; Layout.leftMargin: 20; Layout.rightMargin: 20 }
        Text { text: "今日记录 " + UsageText.number(view.data.todayRecordedTokens) + " token。仅统计此账户通过本机助理收到的 Codex 回合用量；不包含语音消耗，也不是账户账单。"; color: Theme.dim; font.pixelSize: 13; wrapMode: Text.Wrap; Layout.fillWidth: true; Layout.leftMargin: 20; Layout.rightMargin: 20 }
        Text { visible: view.data.authMode === "apiKey"; text: "API Key 按量使用，未提供订阅额度和重置时间。"; color: Theme.dim; font.pixelSize: 14; wrapMode: Text.Wrap; Layout.fillWidth: true; Layout.margins: 20 }
        Text { visible: view.data.authMode === "chatgpt"; text: "账户累计 token：" + UsageText.number(((view.data.accountUsage || {}).summary || {}).lifetimeTokens); color: Theme.text; font.pixelSize: 16; Layout.fillWidth: true; Layout.margins: 20 }
        Repeater {
            model: view.data.windows || []
            ColumnLayout {
                required property var modelData
                Layout.fillWidth: true; Layout.leftMargin: 20; Layout.rightMargin: 20; spacing: 8
                Text { text: modelData.bucket + " · " + UsageText.windowName(modelData); font.pixelSize: 16; color: Theme.text; Layout.fillWidth: true; wrapMode: Text.Wrap }
                Text { text: (view.data.stale || modelData.expired ? "上次读取：" : "") + "已用 " + modelData.usedPercent + "%"; font.pixelSize: 14; color: Theme.dim }
                QQC2.ProgressBar { Layout.fillWidth: true; value: Math.min(1, Math.max(0, modelData.usedPercent / 100)) }
                Text { text: UsageText.reset(modelData, view.now); color: Theme.dim; font.pixelSize: 13; Layout.fillWidth: true; wrapMode: Text.Wrap }
            }
        }
        Text { visible: !!view.data.error; text: view.data.error || ""; color: Theme.negative; Layout.fillWidth: true; Layout.margins: 20; wrapMode: Text.Wrap }
        Text { text: view.data.updatedAt ? "上次读取 " + new Date(view.data.updatedAt * 1000).toLocaleString(Qt.locale("zh_CN"), "M/d HH:mm") : "等待用量数据"; color: Theme.dim; font.pixelSize: 12; Layout.margins: 20 }
    }
}
