// The team's board in the director (rungic_cua.team, docs/research/91 §14), as the app draws it on
// the TV and fullscreen (DirectorArt): the phase, the brief, each member's state and latest words,
// the lead's decision or result. `compact` (a tile in the column): the phase, the brief and a dot
// for each member.
import QtQuick

Rectangle {
    id: root
    required property var board
    property bool compact: false
    readonly property var members: (root.board && root.board.members) || []
    readonly property string phase: (root.board && root.board.phase) || ""
    readonly property string footer: root.board ? (root.board.result || root.board.decision || "") : ""
    readonly property real unit: compact ? 0.55 : 1
    color: Qt.rgba(0.055, 0.07, 0.086, 0.92)

    function phaseName(phase) {
        return ({ brief: i18nc("@info:status the team's phase", "Brief"),
                  review: i18nc("@info:status the team's phase", "In review"),
                  working: i18nc("@info:status the team's phase", "At work"),
                  done: i18nc("@info:status the team's phase", "Done"),
                  failed: i18nc("@info:status the team's phase", "Failed") })[phase] || ""
    }
    function stateName(kind) {
        return ({ review: i18nc("@info:status a team member reviews the brief", "reviewing"),
                  progress: i18nc("@info:status a team member works", "working"),
                  blocked: i18nc("@info:status a team member cannot go on", "blocked"),
                  question: i18nc("@info:status a team member asks", "has a question"),
                  done: i18nc("@info:status a team member finished", "done"),
                  failed: i18nc("@info:status", "failed"),
                  ended: i18nc("@info:status a team member stopped", "ended"),
                  brief: i18nc("@info:status the lead writes the brief", "briefing"),
                  decision: i18nc("@info:status the lead decides", "deciding") })[kind] || ""
    }
    function dotColor(kind) {
        if (kind === "blocked" || kind === "question") return "#f0b35e"
        if (kind === "failed") return "#e0606d"
        if (kind === "" || kind === "ended") return "#8b97a3"
        return "#63d471"
    }
    function phaseColor(phase) {
        return phase === "failed" ? "#e0606d" : (phase === "working" || phase === "done") ? "#63d471" : "#3daee9"
    }

    Column {
        // The rows stop above the decision line; what does not fit is cut, not drawn over it.
        anchors { fill: parent; margins: root.compact ? 6 : 12; bottomMargin: footerRow.visible ? footerRow.height + 18 : (root.compact ? 6 : 12) }
        clip: true
        spacing: root.compact ? 3 : 6
        Row {
            spacing: 5
            Text {
                text: i18nc("@label the team's board in the director", "Team board").toUpperCase()
                color: Qt.rgba(0.95, 0.96, 0.97, 0.6)
                font { pixelSize: Math.max(6, 8 * root.unit); bold: true }
                anchors.verticalCenter: parent.verticalCenter
            }
            Rectangle {
                visible: phaseLabel.text !== ""
                width: phaseLabel.implicitWidth + 8 * root.unit; height: phaseLabel.implicitHeight + 2
                radius: height / 2
                color: root.phaseColor(root.phase)
                Text {
                    id: phaseLabel
                    anchors.centerIn: parent
                    text: root.phaseName(root.phase)
                    color: "#0a1016"
                    font { pixelSize: Math.max(6, 8 * root.unit); bold: true }
                }
            }
        }
        Text {
            width: parent.width
            text: (root.board && root.board.title) || ""
            color: "white"
            font { pixelSize: Math.max(7, 14 * root.unit); bold: true }
            elide: Text.ElideRight
        }
        Row {  // small: a dot for each member
            visible: root.compact
            spacing: 4
            Repeater {
                model: root.compact ? root.members : []
                delegate: Rectangle { required property var modelData; width: 5; height: 5; radius: 2.5; color: root.dotColor(modelData.kind) }
            }
        }
        Rectangle { visible: !root.compact; width: parent.width; height: 1; color: Qt.rgba(1, 1, 1, 0.12) }
        Repeater {
            model: root.compact ? [] : root.members
            delegate: Row {
                required property var modelData
                width: parent ? parent.width : 0
                spacing: 6
                Rectangle {
                    width: 7; height: 7; radius: 3.5
                    color: root.dotColor(modelData.kind)
                    anchors.verticalCenter: parent.verticalCenter
                }
                Text {
                    id: roleText
                    text: modelData.role || ""
                    color: "white"
                    font { pixelSize: 11; bold: true }
                }
                Text {
                    id: stateText
                    text: root.stateName(modelData.kind)
                    color: "#a9b4bd"
                    font.pixelSize: 9
                    anchors.baseline: roleText.baseline
                }
                Text {
                    width: Math.max(0, parent.width - roleText.width - stateText.width - 7 - 3 * 6)
                    text: modelData.text || ""
                    color: Qt.rgba(0.95, 0.96, 0.97, 0.78)
                    font.pixelSize: 10
                    elide: Text.ElideRight
                    anchors.baseline: roleText.baseline
                }
            }
        }
    }
    Row {  // the lead's decision, later its result
        id: footerRow
        visible: !root.compact && root.footer !== ""
        anchors { left: parent.left; right: parent.right; bottom: parent.bottom; margins: 12 }
        spacing: 6
        Rectangle {
            width: footTag.implicitWidth + 8; height: footTag.implicitHeight + 2; radius: 3
            color: root.board && root.board.result ? root.phaseColor(root.phase) : "#3daee9"
            Text {
                id: footTag
                anchors.centerIn: parent
                text: root.board && root.board.result ? i18nc("@label the lead's result", "Result")
                                                         : i18nc("@label the lead's decision", "Decision")
                color: "#0a1016"
                font { pixelSize: 8; bold: true }
            }
        }
        Text {
            width: parent.width - footTag.width - 14
            text: root.footer
            color: "white"
            font.pixelSize: 10
            elide: Text.ElideRight
        }
    }
}
