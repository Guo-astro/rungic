// SPDX-License-Identifier: GPL-2.0-or-later
import QtQuick
import QtQuick.Window
import QtQuick.Layouts
import QtQuick.Controls as QQC2
import com.rungic.design
import org.kde.ki18n
import com.rungic.suggestions
import "UsageText.js" as UsageText

QQC2.ScrollView {
    id: view
    clip: true
    property double now: Date.now() / 1000
    KI18nContext { id: l10n; translationDomain: "rungic-suggestions" }
    UsageClient { id: usage }
    readonly property var usageData: usage.data
    Timer { interval: 60000; running: view.visible && view.Window.active; repeat: true; onTriggered: { view.now = Date.now() / 1000; usage.refresh() } }
    ColumnLayout {
        width: view.availableWidth; spacing: 16
        RowLayout {
            Layout.margins: 20
            PixelAgent { animate: view.visible && view.Window.active; working: view.usageData.activity === "working" }
            ColumnLayout {
                Text { text: "Codex"; color: Theme.text; font.pixelSize: 24; font.weight: Font.DemiBold }
                Text { text: UsageText.mode(l10n, view.usageData) + " · " + (view.usageData.model || l10n.i18n("Model not read yet")); color: Theme.dim; font.pixelSize: 12 }
            }
            Item { Layout.fillWidth: true }
            PillButton { text: l10n.i18n("Refresh"); onClicked: { view.now = Date.now() / 1000; usage.refresh() } }
        }
        Text { text: UsageText.token(l10n, view.usageData); color: Theme.text; font.pixelSize: 22; wrapMode: Text.Wrap; Layout.fillWidth: true; Layout.leftMargin: 20; Layout.rightMargin: 20 }
        Text { text: l10n.i18n("Recorded today: %1 tokens. Counts only the Codex turns this account ran through the assistant on this device; it leaves out voice and is not the account's bill.", UsageText.number(l10n, view.usageData.todayRecordedTokens)); color: Theme.dim; font.pixelSize: 13; wrapMode: Text.Wrap; Layout.fillWidth: true; Layout.leftMargin: 20; Layout.rightMargin: 20 }
        Text { visible: view.usageData.authMode === "apiKey"; text: l10n.i18n("An API key is billed as you go; it has no subscription limits or reset times."); color: Theme.dim; font.pixelSize: 14; wrapMode: Text.Wrap; Layout.fillWidth: true; Layout.margins: 20 }
        Text { visible: view.usageData.authMode === "chatgpt"; text: l10n.i18n("Account tokens to date: %1", UsageText.number(l10n, ((view.usageData.accountUsage || {}).summary || {}).lifetimeTokens)); color: Theme.text; font.pixelSize: 16; Layout.fillWidth: true; Layout.margins: 20 }
        Repeater {
            model: view.usageData.windows || []
            ColumnLayout {
                required property var modelData
                Layout.fillWidth: true; Layout.leftMargin: 20; Layout.rightMargin: 20; spacing: 8
                Text { text: modelData.bucket + " · " + UsageText.windowName(l10n, modelData); font.pixelSize: 16; color: Theme.text; Layout.fillWidth: true; wrapMode: Text.Wrap }
                Text { text: (view.usageData.stale || modelData.expired ? l10n.i18n("Last read: %1% used", modelData.usedPercent) : l10n.i18n("%1% used", modelData.usedPercent)); font.pixelSize: 14; color: Theme.dim }
                QQC2.ProgressBar { Layout.fillWidth: true; value: Math.min(1, Math.max(0, modelData.usedPercent / 100)) }
                Text { text: UsageText.reset(l10n, modelData, view.now); color: Theme.dim; font.pixelSize: 13; Layout.fillWidth: true; wrapMode: Text.Wrap }
            }
        }
        Text { visible: !!view.usageData.error; text: view.usageData.error || ""; color: Theme.negative; Layout.fillWidth: true; Layout.margins: 20; wrapMode: Text.Wrap }
        Text { text: view.usageData.updatedAt ? l10n.i18n("Last read %1", new Date(view.usageData.updatedAt * 1000).toLocaleString(Qt.locale(), Locale.ShortFormat)) : l10n.i18n("Waiting for usage data"); color: Theme.dim; font.pixelSize: 12; Layout.margins: 20 }
    }
}
