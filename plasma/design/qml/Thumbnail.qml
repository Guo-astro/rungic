// SPDX-License-Identifier: GPL-2.0-or-later
// A picture in the conversation (docs/88): shown whole at its own proportions, fitted into
// maxWidth x maxHeight, with rounded corners; a tap is `clicked` (the app opens it large).
// States: loading (a quiet box of the usual size), ready, pressed, error (the file could not be
// read: a short line with its name instead of an empty box).
import QtQuick
import QtQuick.Effects
import QtQuick.Templates as T
import com.rungic.design

T.AbstractButton {
    id: thumb
    property url source
    property string name
    property real maxWidth: 260
    property real maxHeight: 320
    // The state shown: the picture's own, or `forcedState` (the state gallery, docs/87).
    property string forcedState: ""
    readonly property string loadState: image.status === Image.Ready ? "ready"
        : image.status === Image.Error || String(source) === "" ? "error" : "loading"
    readonly property string visualState: forcedState !== "" ? forcedState
        : loadState === "ready" && down ? "pressed" : loadState
    state: visualState
    // Sized from the picture and the limits only, never from this item's own size (docs/87).
    readonly property real ratio: image.implicitWidth > 0 ? image.implicitHeight / image.implicitWidth : 0.75
    readonly property real fitWidth: Math.min(maxWidth, maxHeight / ratio)
    property bool pictureShown: false
    property bool placeholderShown: true
    property bool problemShown: false
    property real shade: 0
    states: [
        State { name: "loading"; PropertyChanges { thumb.pictureShown: false; thumb.placeholderShown: true; thumb.problemShown: false; thumb.shade: 0 } },
        State { name: "ready"; PropertyChanges { thumb.pictureShown: true; thumb.placeholderShown: false; thumb.problemShown: false; thumb.shade: 0 } },
        State { name: "pressed"; PropertyChanges { thumb.pictureShown: true; thumb.placeholderShown: false; thumb.problemShown: false; thumb.shade: 0.18 } },
        State { name: "error"; PropertyChanges { thumb.pictureShown: false; thumb.placeholderShown: false; thumb.problemShown: true; thumb.shade: 0 } }
    ]
    implicitWidth: problemShown ? Math.min(maxWidth, problem.implicitWidth + 28) : fitWidth
    implicitHeight: problemShown ? 48 : fitWidth * ratio
    enabled: visualState !== "error"
    padding: 0
    Accessible.role: Accessible.Graphic
    Accessible.name: name
    background: Rectangle {
        radius: Theme.radiusInput
        color: Theme.fill
    }
    contentItem: Item {
        Item {
            id: picture
            anchors.fill: parent
            visible: thumb.pictureShown
            layer.enabled: true
            layer.effect: MultiEffect {
                maskEnabled: true
                maskSource: corners
            }
            Image {
                id: image
                anchors.fill: parent
                source: thumb.source
                sourceSize: Qt.size(Math.round(thumb.maxWidth * 2), Math.round(thumb.maxHeight * 2))
                fillMode: Image.PreserveAspectFit
                asynchronous: true
                smooth: true
            }
            Rectangle {
                anchors.fill: parent
                color: "black"
                opacity: thumb.shade
                Behavior on opacity { NumberAnimation { duration: Theme.quick } }
            }
        }
        Rectangle {
            id: corners
            anchors.fill: parent
            radius: Theme.radiusInput
            visible: false
            layer.enabled: true
        }
        Icon {
            anchors.centerIn: parent
            visible: thumb.placeholderShown
            name: "image"
            color: Theme.faint
        }
        Row {
            id: problem
            anchors { left: parent.left; leftMargin: 14; verticalCenter: parent.verticalCenter }
            visible: thumb.problemShown
            spacing: 8
            Icon { anchors.verticalCenter: parent.verticalCenter; name: "alert"; color: Theme.dim }
            Text {
                id: problemLabel
                anchors.verticalCenter: parent.verticalCenter
                text: "图片打不开"
                font.family: Theme.fontFamily
                font.pixelSize: Theme.metaSize
                color: Theme.dim
            }
            Text {
                anchors.verticalCenter: parent.verticalCenter
                visible: thumb.name !== ""
                // Only the name gives way, measured from the limit, not from the row it sits in.
                width: Math.max(0, Math.min(implicitWidth, thumb.maxWidth - 28 - 30 - problemLabel.implicitWidth - 8))
                text: thumb.name
                elide: Text.ElideMiddle
                font.family: Theme.fontFamily
                font.pixelSize: Theme.metaSize
                color: Theme.dim
            }
        }
    }
}
