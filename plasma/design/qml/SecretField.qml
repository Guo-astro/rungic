// SPDX-License-Identifier: GPL-2.0-or-later
// A single-line field for a key or code: monospace, hidden unless revealed, red edge
// when `error`.
import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as QQC2
import com.rungic.design

Rectangle {
    id: box
    property alias text: input.text
    property alias placeholderText: input.placeholderText
    property alias input: input
    property bool error: false
    property bool secret: true
    property bool revealed: false
    property string accessibleName
    // States: normal, focused, error, disabled.
    property string forcedState: ""
    readonly property string visualState: forcedState !== "" ? forcedState
        : !enabled ? "disabled" : error ? "error" : input.activeFocus ? "focused" : "normal"
    state: visualState
    states: [
        State { name: "normal"; PropertyChanges { box.border.color: "transparent"; input.color: Theme.text } },
        State { name: "focused"; PropertyChanges { box.border.color: Theme.strong; input.color: Theme.text } },
        State { name: "error"; PropertyChanges { box.border.color: Theme.negative; input.color: Theme.text } },
        State { name: "disabled"; PropertyChanges { box.border.color: "transparent"; input.color: Theme.dim } }
    ]
    implicitHeight: 52
    radius: Theme.radiusInput
    color: Theme.fill
    border.width: 1.5
    RowLayout {
        anchors.fill: parent
        anchors.leftMargin: 16
        anchors.rightMargin: 4
        spacing: 4
        QQC2.TextField {
            id: input
            Layout.fillWidth: true
            Layout.preferredHeight: 48
            background: null
            leftPadding: 0
            rightPadding: 0
            font.family: Theme.monoFamily
            font.pixelSize: 15
            placeholderTextColor: Theme.dim
            echoMode: box.secret && !box.revealed ? TextInput.Password : TextInput.Normal
            inputMethodHints: Qt.ImhNoAutoUppercase | Qt.ImhNoPredictiveText | Qt.ImhSensitiveData
            Accessible.name: box.accessibleName
        }
        IconButton {
            visible: box.secret
            forcedState: box.visualState === "disabled" ? "disabled" : ""
            small: true
            iconName: box.revealed ? "eye-off" : "eye"
            text: box.revealed ? "隐藏密钥" : "显示密钥"
            onClicked: box.revealed = !box.revealed
        }
    }
}
