// SPDX-License-Identifier: GPL-2.0-or-later
// The home-screen widgets in every state, side by side on a wallpaper tone (like the design
// library's gallery, docs/87): rungic-suggestions-gallery [--theme light|dark] [--shot FILE].
// Fixed sample data; nothing here talks to the services.
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import com.rungic.design
import org.kde.ki18n

ApplicationWindow {
    id: gallery
    property string initialTheme: "system"
    property string section: ""
    width: 4 * 380 + 5 * 20
    height: 1760
    visible: true
    color: Theme.dark ? "#1e2822" : "#6d8a74"
    Component.onCompleted: Theme.mode = initialTheme

    KI18nContext { id: l10n; translationDomain: "rungic-suggestions" }
    readonly property double now: Date.now() / 1000
    readonly property var crashes: ({ id: "c1", kind: "issues", refs: ["r1"],
        title: "Several apps quit unexpectedly this week",
        body: "12 crashes in 5 apps since Monday, most of them in the desktop shell. Nothing was lost, but it keeps happening. Want to go through them together?",
        action: { label: "Go through them" } })
    readonly property var video: ({ id: "c2", kind: "improvement", refs: ["r2"],
        title: "Videos in Firefox are decoded without the GPU",
        body: "Hardware decoding would make playback smoother and use less battery. Agent can check whether it works with this Firefox.",
        action: { label: "Have Agent check" } })
    readonly property var fix: ({ id: "c3", kind: "result", refs: ["r3"],
        title: "The desktop crashes have one cause",
        body: "All 9 come from the volume popup when no speaker is connected. A fix is ready; applying it restarts the desktop for about 5 seconds.",
        action: { label: "Review the fix" } })
    readonly property var longest: ({ id: "c4", kind: "issues", refs: ["r1"],
        title: "Firefox, Krita and the desktop shell quit after the update",
        body: "Since yesterday’s system update these three apps quit 23 times in total, usually right after opening a file. Agent can compare the crash reports and check the update.",
        action: { label: "Go through them" } })
    readonly property var fallback: ({ id: "c5", kind: "issues", refs: ["r1", "r2"],
        title: "14 new findings on this phone",
        body: "Codex couldn’t sort them just now: its usage limit is reached until 14:47. You can still ask it to go through them.",
        action: { label: "Ask Agent to look" } })
    readonly property var sorted: ({ generatedAt: now - 600, source: "agent" })

    ScrollView {
        anchors.fill: parent
        contentWidth: availableWidth
        GridLayout {
            width: gallery.width
            columns: 4
            columnSpacing: 20
            rowSpacing: 24
            anchors.margins: 20
            Repeater {
                model: [
                    { label: "cards · top card", cards: [gallery.crashes, gallery.video, gallery.fix] },
                    { label: "cards · second of three", cards: [gallery.crashes, gallery.video, gallery.fix], index: 1 },
                    { label: "working (Agent is on it)", cards: [gallery.crashes, gallery.video], items: [{ id: "r1", state: "working", task: { started: gallery.now - 240 } }] },
                    { label: "result ready", cards: [gallery.fix, gallery.video] },
                    { label: "curating", cards: [gallery.crashes, gallery.video, gallery.fix], briefing: { generatedAt: gallery.now - 600, source: "agent", curating: true } },
                    { label: "mid-swipe", cards: [gallery.crashes, gallery.video, gallery.fix], offset: -150 },
                    { label: "fallback (Agent unavailable)", cards: [gallery.fallback], briefing: { generatedAt: gallery.now - 60, source: "fallback" } },
                    { label: "longest text, five cards", cards: [gallery.longest, gallery.video, gallery.fix, gallery.crashes, gallery.fallback] },
                    { label: "empty", state: "empty", briefing: { generatedAt: gallery.now - 300, source: "agent" } },
                    { label: "first run", state: "firstrun", briefing: {} },
                    { label: "offline", state: "offline", briefing: {} },
                    { label: "size 4×2", cards: [gallery.crashes, gallery.video], height: 220 },
                    { label: "size 4×4", cards: [gallery.longest, gallery.video], height: 440 }
                ]
                ColumnLayout {
                    required property var modelData
                    Layout.alignment: Qt.AlignTop
                    spacing: 8
                    Label { text: modelData.label; color: "white"; font.pixelSize: 13; font.weight: Font.DemiBold }
                    SuggestionsWidget {
                        Layout.preferredWidth: 340
                        Layout.preferredHeight: modelData.height || 330
                        Layout.leftMargin: 20; Layout.rightMargin: 20
                        forcedState: modelData.state || ""
                        forcedCards: modelData.cards || []
                        forcedBriefing: modelData.briefing || gallery.sorted
                        forcedItems: modelData.items || []
                        forcedIndex: modelData.index === undefined ? -1 : modelData.index
                        forcedOffset: modelData.offset || 0
                    }
                }
            }
        }
    }
}
