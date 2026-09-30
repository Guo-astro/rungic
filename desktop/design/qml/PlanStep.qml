// SPDX-License-Identifier: GPL-2.0-or-later
// One step of the agent's plan on the task card (docs/89): a marker and the step's words.
// States: pending (a hollow ring, dim), active (a dot that breathes, the words in full ink),
// done (a check, dim).
import QtQuick
import QtQuick.Layouts
import com.rungic.design

Item {
    id: step
    property string text
    // pending | inProgress | completed, as Codex's plan says (turn/plan/updated).
    property string status: "pending"
    // The state shown: the step's own, or `forcedState` (the state gallery, docs/87).
    property string forcedState: ""
    readonly property string visualState: forcedState !== "" ? forcedState
        : status === "completed" ? "done" : status === "inProgress" ? "active" : "pending"
    state: visualState
    property color ink: Theme.dim
    property bool ringShown: true
    property bool dotShown: false
    property bool checkShown: false
    property int weight: Font.Normal
    states: [
        State { name: "pending"; PropertyChanges { step.ink: Theme.dim; step.ringShown: true; step.dotShown: false; step.checkShown: false; step.weight: Font.Normal } },
        State { name: "active"; PropertyChanges { step.ink: Theme.text; step.ringShown: true; step.dotShown: true; step.checkShown: false; step.weight: Font.DemiBold } },
        State { name: "done"; PropertyChanges { step.ink: Theme.dim; step.ringShown: false; step.dotShown: false; step.checkShown: true; step.weight: Font.Normal } }
    ]
    implicitWidth: row.implicitWidth
    implicitHeight: Math.max(26, label.implicitHeight + 6)
    Accessible.role: Accessible.StaticText
    Accessible.name: visualState === "done" ? DesignI18n.i18nc("@info accessible name of a plan step", "%1, done", text)
        : visualState === "active" ? DesignI18n.i18nc("@info accessible name of a plan step", "%1, in progress", text)
        : DesignI18n.i18nc("@info accessible name of a plan step", "%1, not started", text)

    RowLayout {
        id: row
        anchors.fill: parent
        spacing: 10
        Item {
            Layout.alignment: Qt.AlignTop
            Layout.topMargin: (Math.min(26, label.implicitHeight + 6) - 18) / 2 + 1
            implicitWidth: 18
            implicitHeight: 18
            Rectangle {
                anchors.centerIn: parent
                width: 14; height: 14; radius: 7
                visible: step.ringShown
                color: "transparent"
                border.width: 1.5
                border.color: step.visualState === "active" ? Theme.text : Theme.faint
            }
            Rectangle {
                id: dot
                anchors.centerIn: parent
                width: 6; height: 6; radius: 3
                visible: step.dotShown
                color: Theme.text
                SequentialAnimation on opacity {
                    running: dot.visible
                    loops: Animation.Infinite
                    onRunningChanged: if (!running) dot.opacity = 1
                    NumberAnimation { to: 0.25; duration: 700; easing.type: Easing.InOutSine }
                    NumberAnimation { to: 1; duration: 700; easing.type: Easing.InOutSine }
                }
            }
            Icon {
                anchors.centerIn: parent
                visible: step.checkShown
                name: "check"
                color: Theme.dim
                implicitWidth: 18
                implicitHeight: 18
            }
        }
        Text {
            id: label
            Layout.fillWidth: true
            text: step.text
            wrapMode: Text.Wrap
            font.family: Theme.fontFamily
            font.pixelSize: Theme.metaSize
            font.weight: step.weight
            color: step.ink
        }
    }
}
