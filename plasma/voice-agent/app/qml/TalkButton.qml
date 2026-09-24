// SPDX-License-Identifier: GPL-2.0-or-later
// Hold to talk; releasing (or dragging off and releasing) ends the turn.
import QtQuick
import QtQuick.Controls as QQC2
import org.kde.kirigami as Kirigami
import dev.moto.voiceassistant

Item {
    id: button
    readonly property bool holding: area.pressed
    implicitWidth: Kirigami.Units.gridUnit * 5
    implicitHeight: implicitWidth

    Rectangle {
        anchors.centerIn: parent
        width: button.holding ? parent.width : parent.width * 0.86
        height: width
        radius: width / 2
        color: button.holding ? Kirigami.Theme.negativeTextColor : Kirigami.Theme.highlightColor
        opacity: button.enabled ? 1 : 0.4
        Behavior on width { NumberAnimation { duration: Kirigami.Units.shortDuration } }
        Kirigami.Icon {
            anchors.centerIn: parent
            width: parent.width * 0.45
            height: width
            source: "audio-input-microphone"
            color: "white"
            isMask: true
        }
    }

    MouseArea {
        id: area
        anchors.fill: parent
        enabled: button.enabled
        onPressed: AgentClient.startTalking()
        onReleased: AgentClient.stopTalking()
        onCanceled: AgentClient.stopTalking()
    }
}
