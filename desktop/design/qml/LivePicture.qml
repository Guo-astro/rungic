// SPDX-License-Identifier: GPL-2.0-or-later
// A picture that keeps coming (docs/90): a render's passes as the agent's work shows them. Each
// new `source` loads behind the one shown and fades in over it once it is there, so the picture
// never blinks empty between passes. What it is (`text`, e.g. "Blender render · 28/64 samples") sits in
// a capsule over its bottom edge, with a thin bar for `progress` (0..1, or -1 unknown). A tap is
// `clicked` (the app opens it large).
// States: waiting (no picture yet: a quiet box and a ring), live (passes coming: the dot
// breathes), done (the last one: a check, no bar).
import QtQuick
import QtQuick.Effects
import QtQuick.Templates as T
import com.rungic.design

T.AbstractButton {
    id: live
    property url source
    property real progress: -1
    property bool finished: false
    property real maxWidth: 320
    property real maxHeight: 360
    // The state shown: the picture's own, or `forcedState` (the state gallery, docs/87).
    property string forcedState: ""
    readonly property bool hasPicture: shown !== null
    readonly property string visualState: forcedState !== "" ? forcedState
        : !hasPicture ? "waiting" : finished ? "done" : "live"
    state: visualState
    property bool ringShown: true
    property bool dotShown: false
    property bool checkShown: false
    property bool barShown: false
    states: [
        State { name: "waiting"; PropertyChanges { live.ringShown: true; live.dotShown: false; live.checkShown: false; live.barShown: live.progress >= 0 } },
        State { name: "live"; PropertyChanges { live.ringShown: false; live.dotShown: true; live.checkShown: false; live.barShown: live.progress >= 0 } },
        State { name: "done"; PropertyChanges { live.ringShown: false; live.dotShown: false; live.checkShown: true; live.barShown: false } }
    ]

    // Two images take turns: `shown` is on top, the other loads the next source.
    property Image shown: null
    readonly property real ratio: shown && shown.implicitWidth > 0 ? shown.implicitHeight / shown.implicitWidth : 1
    // Sized from the picture and the limits only, never from this item's own size (docs/87).
    readonly property real fitWidth: Math.min(maxWidth, maxHeight / ratio)
    implicitWidth: fitWidth
    implicitHeight: fitWidth * ratio
    padding: 0
    Accessible.role: Accessible.Graphic
    Accessible.name: text

    function take(image) {
        if (image.status !== Image.Ready || String(image.source) !== String(live.source)) return
        const other = image === first ? second : first
        image.z = 1
        other.z = 0
        image.opacity = 1
        live.shown = image
    }
    onSourceChanged: {
        if (String(source) === "") return
        const back = shown === first ? second : first
        back.opacity = shown ? 0 : 1
        back.source = source
        take(back)
    }

    background: Rectangle {
        radius: Theme.radiusInput
        color: Theme.fill
    }
    contentItem: Item {
        Item {
            id: pictures
            anchors.fill: parent
            layer.enabled: true
            layer.effect: MultiEffect {
                maskEnabled: true
                maskSource: corners
            }
            Image {
                id: first
                anchors.fill: parent
                fillMode: Image.PreserveAspectFit
                asynchronous: true
                cache: false
                smooth: true
                sourceSize: Qt.size(Math.round(live.maxWidth * 2), Math.round(live.maxHeight * 2))
                onStatusChanged: live.take(first)
                Behavior on opacity { NumberAnimation { duration: Theme.normal } }
            }
            Image {
                id: second
                anchors.fill: parent
                fillMode: Image.PreserveAspectFit
                asynchronous: true
                cache: false
                smooth: true
                sourceSize: first.sourceSize
                onStatusChanged: live.take(second)
                Behavior on opacity { NumberAnimation { duration: Theme.normal } }
            }
            Rectangle {
                anchors { left: parent.left; right: parent.right; bottom: parent.bottom }
                visible: live.barShown
                height: 3
                color: Qt.rgba(0, 0, 0, 0.35)
                Rectangle {
                    height: parent.height
                    width: parent.width * Math.max(0, Math.min(1, live.progress))
                    color: "#fcfcfc"
                    Behavior on width { NumberAnimation { duration: Theme.slide; easing.type: Easing.OutCubic } }
                }
            }
            Rectangle {
                anchors.fill: parent
                color: "black"
                opacity: live.down ? 0.18 : 0
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
        BusyRing {
            anchors.centerIn: parent
            visible: live.ringShown
        }
        // What it is, over the bottom edge: always on a dark capsule, as a caption over a picture.
        Rectangle {
            anchors { left: parent.left; bottom: parent.bottom; margins: 8 }
            visible: live.text !== ""
            width: Math.min(parent.width - 16, captionRow.implicitWidth + 20)
            height: 26
            radius: 13
            color: Qt.rgba(0.08, 0.09, 0.1, 0.72)
            Row {
                id: captionRow
                anchors { left: parent.left; leftMargin: 10; verticalCenter: parent.verticalCenter }
                spacing: 6
                Rectangle {
                    id: dot
                    anchors.verticalCenter: parent.verticalCenter
                    visible: live.dotShown || live.ringShown
                    width: 6; height: 6; radius: 3
                    color: "#63d471"
                    SequentialAnimation on opacity {
                        running: live.dotShown && live.visible
                        loops: Animation.Infinite
                        onRunningChanged: if (!running) dot.opacity = 1
                        NumberAnimation { to: 0.25; duration: 700; easing.type: Easing.InOutSine }
                        NumberAnimation { to: 1; duration: 700; easing.type: Easing.InOutSine }
                    }
                }
                Icon {
                    anchors.verticalCenter: parent.verticalCenter
                    visible: live.checkShown
                    name: "check"
                    color: "#fcfcfc"
                    implicitWidth: 14
                    implicitHeight: 14
                }
                Text {
                    anchors.verticalCenter: parent.verticalCenter
                    // From the limit, not from the capsule whose width follows it.
                    width: Math.min(implicitWidth, live.maxWidth - 16 - 20 - 12)
                    text: live.text
                    elide: Text.ElideRight
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.footSize
                    color: "#fcfcfc"
                }
            }
        }
    }
}
