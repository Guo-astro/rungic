// SPDX-License-Identifier: GPL-2.0-or-later
import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as QQC2
import com.rungic.design

Rectangle {
    id: card
    required property var item
    property bool expanded: false
    signal action(string name, var args)
    readonly property string stateName: item.state || "new"
    implicitHeight: content.implicitHeight + 36
    radius: 20
    color: Theme.background
    border.width: 1
    border.color: expanded ? Theme.link : Theme.line
    Accessible.role: Accessible.Grouping
    Accessible.name: item.title || "建议"

    ColumnLayout {
        id: content
        anchors { left: parent.left; right: parent.right; top: parent.top; margins: 18 }
        spacing: 12
        RowLayout {
            Layout.fillWidth: true
            Icon { name: card.item.kind === "fault" ? "alert" : "compose"; color: card.item.severity >= 2 ? Theme.negative : Theme.link; implicitWidth: 20; implicitHeight: 20 }
            Text {
                Layout.fillWidth: true
                text: ({ working: "正在处理", attention: "需要你查看", snoozed: "已安排", resolved: "已完成", dismissed: "不再提醒" })[card.stateName] || (card.item.kind === "fault" ? "使用问题" : "改善建议")
                font.pixelSize: 12; color: Theme.dim
            }
            QQC2.ToolButton { text: "···"; Accessible.name: "建议选项"; onClicked: options.open() }
            QQC2.Menu {
                id: options
                QQC2.MenuItem { text: "查看详情"; onTriggered: card.expanded = !card.expanded }
                QQC2.MenuItem { text: "保留待处理"; enabled: card.stateName !== "working" && card.stateName !== "resolved"; onTriggered: card.action("later", {}) }
                QQC2.MenuItem { text: "不再提醒这个问题"; enabled: card.stateName !== "working"; onTriggered: card.action("dismiss", {}) }
                QQC2.MenuItem { text: "准备反馈材料"; onTriggered: card.action("feedback", {}) }
            }
        }
        Text { Layout.fillWidth: true; text: card.item.title || ""; textFormat: Text.PlainText; wrapMode: Text.Wrap; font.pixelSize: 19; font.weight: Font.DemiBold; color: Theme.text }
        Text { Layout.fillWidth: true; text: card.item.body || ""; textFormat: Text.PlainText; wrapMode: Text.Wrap; font.pixelSize: 14; lineHeight: 1.35; color: Theme.dim }
        Text { Layout.fillWidth: true; visible: !!card.item.note; text: card.item.note || ""; textFormat: Text.PlainText; wrapMode: Text.Wrap; font.pixelSize: 12; color: Theme.link }
        Text {
            Layout.fillWidth: true
            visible: card.expanded
            text: [card.item.result, card.item.plan ? "方案：" + card.item.plan : "", card.item.verification ? "验证：" + card.item.verification : "", card.item.rollback ? "回退：" + card.item.rollback : "", "诊断摘要：\n" + JSON.stringify(card.item.evidence || {}, null, 2)].filter(Boolean).join("\n\n")
            textFormat: Text.PlainText; wrapMode: Text.WrapAnywhere; font.pixelSize: 13; color: Theme.dim
        }
        RowLayout {
            Layout.fillWidth: true
            spacing: 8
            PillButton {
                text: card.stateName === "working" ? "查看进度" : card.item.conversation ? "查看处理结果" : card.stateName === "dismissed" ? "恢复建议" : card.stateName === "resolved" ? "查看详情" : "让 Agent 检查"
                onClicked: {
                    if (card.item.conversation) card.action("conversation", {})
                    else if (card.stateName === "resolved") card.expanded = !card.expanded
                    else card.action(card.stateName === "dismissed" ? "restore" : "investigate", {})
                }
            }
            PillButton {
                visible: card.stateName !== "resolved" && card.stateName !== "dismissed"
                text: card.stateName === "working" ? "停止" : "稍后"
                onClicked: card.action(card.stateName === "working" ? "stop" : "snooze-menu", {})
            }
            Item { Layout.fillWidth: true }
        }
        PillButton {
            visible: card.expanded && card.stateName === "attention" && !!card.item.plan && !!card.item.verification && !!card.item.rollback
            text: "应用上述方案"
            onClicked: card.action("apply-confirm", {})
        }
    }
}
