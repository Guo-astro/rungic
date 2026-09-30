// SPDX-License-Identifier: GPL-2.0-or-later
// What the agent is doing this moment, on the task card (docs/89): an icon for the kind of
// step, the step in plain words and how long it has run, the last line it printed, and a
// bar when it says how far it is.
// States: thinking (between steps: "Planning the next step", shining), working (a step, no measure of how
// far), progress (a step with a fraction done: the bar).
import QtQuick
import QtQuick.Layouts
import com.rungic.design

Rectangle {
    id: card
    // command | files | screen | tool | search | look | image | wait; "" between steps.
    property string kind: ""
    property string text: ""
    property string detail: ""
    property real progress: -1        // 0..1, or -1 when unknown
    property int seconds: 0
    // The state shown: the card's own, or `forcedState` (the state gallery, docs/87).
    property string forcedState: ""
    readonly property string visualState: forcedState !== "" ? forcedState
        : text === "" ? "thinking" : progress >= 0 ? "progress" : "working"
    state: visualState
    property bool barShown: false
    property bool detailShown: false
    property bool shining: false
    states: [
        State { name: "thinking"; PropertyChanges { card.barShown: false; card.detailShown: false; card.shining: true } },
        State { name: "working"; PropertyChanges { card.barShown: false; card.detailShown: card.detail !== ""; card.shining: false } },
        State { name: "progress"; PropertyChanges { card.barShown: true; card.detailShown: card.detail !== ""; card.shining: false } }
    ]
    readonly property string iconName: ({ command: "terminal", files: "file", screen: "open-in-app", tool: "settings",
                                          search: "search", look: "eye", image: "image" })[kind] || ""
    implicitHeight: column.implicitHeight + 20
    radius: Theme.radiusInput
    color: Theme.fill
    Accessible.role: Accessible.StaticText
    readonly property string thinkingText: DesignI18n.i18nc("@info:status the agent between two steps", "Planning the next step")
    Accessible.name: detail ? DesignI18n.i18nc("@info accessible name: %1 the step, %2 the last line it printed", "%1, %2", text || thinkingText, detail)
        : text || thinkingText

    ColumnLayout {
        id: column
        anchors { left: parent.left; right: parent.right; top: parent.top; margins: 10; leftMargin: 12; rightMargin: 12 }
        spacing: 6
        RowLayout {
            Layout.fillWidth: true
            spacing: 8
            Icon {
                visible: card.iconName !== "" && !card.shining
                name: card.iconName
                color: Theme.dim
                implicitWidth: 18
                implicitHeight: 18
            }
            Text {
                Layout.fillWidth: true
                visible: !card.shining
                text: card.text
                elide: Text.ElideRight
                font.family: Theme.fontFamily
                font.pixelSize: Theme.metaSize
                color: Theme.text
            }
            ShineText {
                Layout.fillWidth: true
                visible: card.shining
                text: card.thinkingText
                pixelSize: Theme.metaSize
            }
            Text {
                visible: !card.shining && card.seconds >= 3
                text: card.seconds < 60 ? DesignI18n.i18nc("@info a short duration", "%1s", card.seconds)
                    : DesignI18n.i18nc("@info a short duration", "%1m %2s", Math.floor(card.seconds / 60), card.seconds % 60)
                font.family: Theme.fontFamily
                font.pixelSize: Theme.labelSize
                color: Theme.dim
            }
        }
        Text {
            Layout.fillWidth: true
            visible: card.detailShown
            text: card.detail
            elide: Text.ElideMiddle
            font.family: Theme.monoFamily
            font.pixelSize: 12
            color: Theme.dim
        }
        Progress {
            Layout.fillWidth: true
            Layout.topMargin: 2
            visible: card.barShown
            value: Math.max(0, Math.min(1, card.progress))
        }
    }
}
