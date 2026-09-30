// SPDX-License-Identifier: GPL-2.0-or-later
import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as QQC2
import com.rungic.design
import org.kde.ki18n

QQC2.AbstractButton {
    id: card
    required property var item
    property var displayRecord: item
    property int pageIndex: -1 // Desktop stack; the app's group overview stays unchanged.
    readonly property bool browsing: pageIndex >= 0
    property bool pressedFeedback: false
    KI18nContext { id: l10n; translationDomain: "rungic-suggestions" }
    readonly property int count: item.count || 1
    readonly property string title: displayRecord.displayTitle || displayRecord.title || l10n.i18n("Suggestion")
    readonly property string certainty: ({confirmed: l10n.i18n("Confirmed"), suspected: l10n.i18n("Suspected cause"), unknown: l10n.i18n("Cause not yet known")})[displayRecord.confidence] || ""
    implicitHeight: count > 1 ? 226 : 206
    Accessible.name: count <= 1 ? l10n.i18nc("@action %1 is a suggestion's title", "%1, view suggestion", title)
        : browsing ? l10n.i18np("%2, %1 related record, card %3 of %1, view suggestion", "%2, %1 related records, card %3 of %1, view suggestion", count, title, pageIndex + 1)
        : l10n.i18np("%2, %1 related record, view suggestion", "%2, %1 related records, view suggestion", count, title)
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
            Text { text: card.count > 1 ? (card.browsing ? l10n.i18np("%1 record in all  ›", "%1 records in all  ›", card.count) : l10n.i18np("%1 related record", "%1 related records", card.count) + " · " + l10n.i18np("%1 report", "%1 reports", card.item.reports || card.count)) : (card.certainty || (card.displayRecord.state === "working" ? l10n.i18n("Investigating") : l10n.i18nc("@info a card that is a usage suggestion", "Suggestion"))); color: Theme.dim; font.pixelSize: 11; Layout.fillWidth: true }
            Text { text: card.browsing && card.count > 1 ? (card.pageIndex + 1) + " / " + card.count : "›"; color: Theme.dim; font.pixelSize: 12 }
        }
        Text { text: card.title; textFormat: Text.PlainText; color: Theme.text; font.pixelSize: 16; font.weight: Font.DemiBold; Layout.fillWidth: true; wrapMode: Text.Wrap; maximumLineCount: 2; elide: Text.ElideRight }
        Text {
            text: (!card.browsing && card.count > 1 && card.item.result ? l10n.i18n("One finding: ") : "") + (card.displayRecord.summary || card.displayRecord.body || l10n.i18n("Waiting for its actual impact to be checked."))
            textFormat: Text.PlainText; color: Theme.dim; font.pixelSize: 12; lineHeight: 1.2
            Layout.fillWidth: true; wrapMode: Text.Wrap; maximumLineCount: 4; elide: Text.ElideRight
        }
        Text {
            visible: !!card.displayRecord.nextStep || card.count > 1
            text: card.count > 1 ? (card.browsing ? (card.pageIndex === 0 ? l10n.i18n("↑ Swipe up for the next · Tap for details") : card.pageIndex === card.count - 1 ? l10n.i18n("↓ Swipe down for the previous · Tap for details") : l10n.i18n("↑↓ Swipe to switch · Tap for details")) : l10n.i18n("See each investigation and its progress")) : card.displayRecord.nextStep || ""
            textFormat: Text.PlainText; color: Theme.link; font.pixelSize: 11
            Layout.fillWidth: true; wrapMode: Text.Wrap; maximumLineCount: 2; elide: Text.ElideRight
        }
    }
}
