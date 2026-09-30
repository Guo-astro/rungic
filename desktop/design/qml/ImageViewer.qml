// SPDX-License-Identifier: GPL-2.0-or-later
// A picture over the whole window (docs/88): black ground, the picture fitted; a bar on top
// closes it or opens the file in the system's viewer (`openExternally`). A tap on the picture
// or Back closes it. show(source, name) opens it.
// States: loading, ready, error.
import QtQuick
import QtQuick.Templates as T
import com.rungic.design

T.Popup {
    id: viewer
    property url source
    property string name
    signal openExternally(url source)
    function show(url, title) {
        source = url
        name = title || ""
        open()
    }
    // The state shown: the picture's own, or `forcedState` (the state gallery, docs/87).
    property string forcedState: ""
    readonly property string visualState: forcedState !== "" ? forcedState
        : picture.status === Image.Ready ? "ready" : picture.status === Image.Error ? "error" : "loading"
    property bool busy: true
    property bool problem: false
    parent: T.Overlay.overlay
    x: 0
    y: 0
    width: parent ? parent.width : 0
    height: parent ? parent.height : 0
    padding: 0
    modal: true
    focus: true
    closePolicy: T.Popup.CloseOnEscape
    enter: Transition { NumberAnimation { property: "opacity"; from: 0; to: 1; duration: Theme.normal } }
    exit: Transition { NumberAnimation { property: "opacity"; from: 1; to: 0; duration: Theme.quick } }
    background: Rectangle { color: "#000000" }
    contentItem: Item {
        state: viewer.visualState
        states: [
            State { name: "loading"; PropertyChanges { viewer.busy: true; viewer.problem: false } },
            State { name: "ready"; PropertyChanges { viewer.busy: false; viewer.problem: false } },
            State { name: "error"; PropertyChanges { viewer.busy: false; viewer.problem: true } }
        ]
        Image {
            id: picture
            anchors.fill: parent
            anchors.topMargin: bar.height
            source: viewer.opened || viewer.visible ? viewer.source : ""
            fillMode: Image.PreserveAspectFit
            asynchronous: true
            smooth: true
            visible: !viewer.problem
            Accessible.role: Accessible.Graphic
            Accessible.name: viewer.name
            TapHandler { onTapped: viewer.close() }
        }
        BusyRing {
            anchors.centerIn: picture
            visible: viewer.busy
            track: Qt.rgba(1, 1, 1, 0.2)
            ring: "#fcfcfc"
        }
        Text {
            anchors.centerIn: picture
            visible: viewer.problem
            text: DesignI18n.i18nc("@info", "Can't open this image")
            font.family: Theme.fontFamily
            font.pixelSize: Theme.bodySize
            color: "#a1a9b1"
        }
        Item {
            id: bar
            anchors { left: parent.left; right: parent.right; top: parent.top }
            height: Theme.topBar
            IconButton {
                id: closeButton
                anchors { left: parent.left; leftMargin: 6; verticalCenter: parent.verticalCenter }
                iconName: "close"
                text: DesignI18n.i18nc("@action:button", "Close")
                tint: "#fcfcfc"
                onClicked: viewer.close()
            }
            Text {
                anchors { left: closeButton.right; right: openButton.left; leftMargin: 8; rightMargin: 8; verticalCenter: parent.verticalCenter }
                text: viewer.name
                elide: Text.ElideMiddle
                horizontalAlignment: Text.AlignHCenter
                font.family: Theme.fontFamily
                font.pixelSize: Theme.titleSize
                color: "#fcfcfc"
            }
            IconButton {
                id: openButton
                anchors { right: parent.right; rightMargin: 6; verticalCenter: parent.verticalCenter }
                iconName: "external"
                text: DesignI18n.i18nc("@action:button", "Open in another app")
                tint: "#fcfcfc"
                enabled: !viewer.problem
                onClicked: viewer.openExternally(viewer.source)
            }
        }
    }
}
