// SPDX-License-Identifier: GPL-2.0-or-later
import QtQuick
import QtQuick.Window
import QtQuick.Layouts
import QtQuick.Controls as QQC2
import com.rungic.design
import org.kde.ki18n
import com.rungic.suggestions
import "UsageText.js" as UsageText

Item {
    id: widget
    implicitWidth: 340; implicitHeight: 126
    property bool activeView: visible && Window.active
    property double now: Date.now() / 1000
    KI18nContext { id: l10n; translationDomain: "rungic-suggestions" }
    UsageClient { id: usage }
    SuggestionsClient { id: navigation }
    readonly property var usageData: usage.data
    readonly property var windows: usageData.windows || []
    Timer { interval: 60000; repeat: true; running: widget.activeView; onTriggered: { widget.now = Date.now() / 1000; usage.refresh() } }
    onActiveViewChanged: if (activeView) usage.refresh()
    Rectangle {
        anchors.fill: parent; anchors.margins: 8
        radius: 20; color: Theme.background; border.color: Theme.line
        RowLayout {
            anchors.fill: parent; anchors.margins: 12; spacing: 12
            QQC2.AbstractButton {
                implicitWidth: 54; implicitHeight: 66
                Accessible.name: l10n.i18n("Open the Codex assistant")
                onClicked: navigation.openAgent()
                background: null
                contentItem: ColumnLayout {
                    spacing: 4
                    PixelAgent { Layout.alignment: Qt.AlignHCenter; animate: widget.activeView; working: widget.usageData.activity === "working" }
                    Text { text: "Codex"; color: Theme.text; font.pixelSize: 11; Layout.alignment: Qt.AlignHCenter }
                }
            }
            QQC2.AbstractButton {
                Layout.fillWidth: true; Layout.fillHeight: true
                Accessible.name: l10n.i18n("View Agent usage")
                onClicked: navigation.openAgent(true)
                background: Rectangle { radius: 10; color: parent.down ? Theme.hover : "transparent" }
                contentItem: ColumnLayout {
                    spacing: 4
                    Text { text: (({working: l10n.i18n("Working"), ready: l10n.i18n("Ready"), offline: l10n.i18n("Not connected")})[widget.usageData.activity] || l10n.i18n("Connecting")) + " · " + UsageText.mode(l10n, widget.usageData); color: Theme.dim; font.pixelSize: 11; Layout.fillWidth: true; elide: Text.ElideRight }
                    Text { text: UsageText.token(l10n, widget.usageData); color: Theme.text; font.pixelSize: 13; font.weight: Font.DemiBold; Layout.fillWidth: true; elide: Text.ElideRight }
                    Text {
                        text: widget.usageData.error ? l10n.i18n("Usage not updated yet · View details") : widget.windows.length ? l10n.i18nc("@info %1 percent used, %2 when it resets", "%1% used · %2", widget.windows[0].usedPercent, UsageText.reset(l10n, widget.windows[0], widget.now)) : widget.usageData.authMode === "apiKey" ? l10n.i18n("Pay as you go · no subscription reset") : l10n.i18n("View account usage and limits")
                        color: Theme.dim; font.pixelSize: 10; Layout.fillWidth: true; wrapMode: Text.Wrap; maximumLineCount: 2; elide: Text.ElideRight
                    }
                }
            }
        }
    }
}
