// SPDX-License-Identifier: GPL-2.0-or-later
import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as QQC2
import com.rungic.design

QQC2.AbstractButton {
    id: card
    required property var item
    property var displayRecord: item
    property int pageIndex: -1 // Desktop stack; the app's group overview stays unchanged.
    readonly property bool browsing: pageIndex >= 0
    property bool pressedFeedback: false
    readonly property int count: item.count || 1
    readonly property string title: displayRecord.displayTitle || displayRecord.title || "建议"
    readonly property string certainty: ({confirmed: "已确认", suspected: "疑似原因", unknown: "原因待确认"})[displayRecord.confidence] || ""
    implicitHeight: count > 1 ? 226 : 206
    Accessible.name: title + (count > 1 ? "，" + count + " 条相关记录" : "") + (browsing && count > 1 ? "，第 " + (pageIndex + 1) + " / " + count + " 张" : "") + "，查看建议"
    background: Item {
        Rectangle { visible: card.count > 2; x: 12; y: 10; width: parent.width - 24; height: parent.height - 10; radius: 20; color: Theme.background; opacity: 0.5; border.color: Theme.line }
        Rectangle { visible: card.count > 1; x: 6; y: 5; width: parent.width - 12; height: parent.height - 10; radius: 20; color: Theme.background; opacity: 0.8; border.color: Theme.line }
        Rectangle { width: parent.width; height: parent.height - (card.count > 1 ? 10 : 0); radius: 20; color: card.down || card.pressedFeedback ? Theme.fill2 : Theme.background; border.color: Theme.line }
    }
    contentItem: ColumnLayout {
        id: body
        anchors { fill: parent; margins: 16; bottomMargin: card.count > 1 ? 26 : 16 }
        spacing: 7
        RowLayout {
            Layout.fillWidth: true
            Icon { name: card.displayRecord.kind === "fault" ? "alert" : "compose"; color: Theme.link; implicitWidth: 14; implicitHeight: 14 }
            Text { text: card.count > 1 ? (card.browsing ? "共 " + card.count + " 条记录  ›" : card.count + " 条相关记录 · " + (card.item.reports || card.count) + " 份报告") : (card.certainty || (card.displayRecord.state === "working" ? "正在调查" : "使用建议")); color: Theme.dim; font.pixelSize: 11; Layout.fillWidth: true }
            Text { text: card.browsing && card.count > 1 ? (card.pageIndex + 1) + " / " + card.count : "›"; color: Theme.dim; font.pixelSize: 12 }
        }
        Text { text: card.title; textFormat: Text.PlainText; color: Theme.text; font.pixelSize: 16; font.weight: Font.DemiBold; Layout.fillWidth: true; wrapMode: Text.Wrap; maximumLineCount: 2; elide: Text.ElideRight }
        Text {
            text: (!card.browsing && card.count > 1 && card.item.result ? "一条调查结论：" : "") + (card.displayRecord.summary || card.displayRecord.body || "等待检查实际影响。")
            textFormat: Text.PlainText; color: Theme.dim; font.pixelSize: 12; lineHeight: 1.2
            Layout.fillWidth: true; wrapMode: Text.Wrap; maximumLineCount: 4; elide: Text.ElideRight
        }
        Text {
            visible: !!card.displayRecord.nextStep || card.count > 1
            text: card.count > 1 ? (card.browsing ? (card.pageIndex === 0 ? "↑ 上滑切换 · 点击查看详情" : card.pageIndex === card.count - 1 ? "↓ 下滑查看上一张 · 点击查看详情" : "↑↓ 滑动切换 · 点击查看详情") : "查看各次调查与处理进度") : card.displayRecord.nextStep || ""
            textFormat: Text.PlainText; color: Theme.link; font.pixelSize: 11
            Layout.fillWidth: true; wrapMode: Text.Wrap; maximumLineCount: 2; elide: Text.ElideRight
        }
    }
}
