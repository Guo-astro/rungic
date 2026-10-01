// The floating window of the assistant's screen (docs/65).
//
// The surface covers the phone's screen and is transparent; the picture, the toolbar and the tab
// move inside it (Floater), and only they take touches. So a drag follows the finger frame by frame
// and every change of place or size is animated.
//
// Window: the live picture, looked at and not touched through. One finger moves it; let go with it
// a quarter past a side edge, or flick it so it would get there, and it tucks into a tab there. Two
// fingers pinch it between half and the full width of the phone; a pinch never tucks it. A tap, a drag or a pinch shows a toolbar of
// icons below the picture, a small gap away (above it near the bottom of the screen), which hides a
// few seconds later.
// Fullscreen: the Android host presents the assistant's screen over the whole phone itself (the APK's
// AgentFullscreen: zero-copy, turned a quarter for the phone held sideways, its own touch handling
// and toolbar); this window hides meanwhile, as it does while a TV shows the screen.
// Tab: a handle on the edge; tap to bring the window back, drag to slide it along the edge.
// Caption (docs/88): while the assistant works on this screen, what it is doing now sits over the
// bottom of the picture (its dot breathes on the tab); how it ended shows for a few seconds.
// While a TV or the phone's fullscreen presents the screen everything hides; then it comes back.
import QtQuick
import QtQuick.Effects
import QtQuick.Window
import org.kde.kirigami as Kirigami
import org.kde.pipewire as PipeWire

Window {
    id: root
    // Shown once main.cpp has made it a layer surface.
    property bool ready: false
    // The screen this window shows: its workspace's, or the director's focus (docs/58).
    readonly property QtObject screen: director ? director.focusScreen : agent
    readonly property bool directing: !!director
    readonly property int others: directing ? director.screens.length - 1 : 0
    visible: ready && root.screen.status !== "tv" && root.screen.status !== "fullscreen" && !(directing && director.fullscreenShown)
    title: "rungic-agent-screen"
    color: "transparent"

    property string mode: "window"      // window | tab
    // Tucked away, nobody sees the screen: the host renders it at a low rate (docs/65).
    onModeChanged: root.screen.setWatched(mode === "window")
    property string edge: "right"
    property real px: 12
    // Desktop mode's window above, the assistant's screen's below it: both may be out at once. A
    // team's workspaces 2, 3, 4 (docs/research/91) one under another from the top, all out at once.
    property real py: directing ? 110 : root.screen.workspace > 1 ? 50 + (root.screen.workspace - 2) * 165 : root.screen.workspace > 0 ? 330 : 110
    property real panelWidth: 260
    property real tabY: 180
    property bool toolbarShown: false
    property bool dragging: false
    property bool pinching: false
    readonly property rect area: floater.area
    readonly property real minWidth: area.width * 0.5
    // The director's other screens in a column on the right of its focus, live and small (docs/58),
    // as fullscreen and the TV lay them out.
    readonly property real columnWidth: others < 1 ? 0 : Math.round(panelWidth * 0.24)
    readonly property real pictureWidth: panelWidth - (others < 1 ? 0 : columnWidth + 4)
    readonly property real pictureHeight: Math.round(pictureWidth * 9 / 16)
    readonly property real stripHeight: 0
    readonly property real panelHeight: pictureHeight + stripHeight
    readonly property int gap: 10
    readonly property int tabWidth: 26
    readonly property int tabHeight: 76
    readonly property int btnLeft: 0x110
    readonly property int btnRight: 0x111
    readonly property int motion: 240
    // The toolbar goes above the picture when there is no room below it.
    readonly property bool barAbove: py + panelHeight + gap + toolbar.height + 12 > area.height
    readonly property bool onLeftHalf: px + panelWidth / 2 < area.width / 2

    // Keep the window on the screen (animated back after a drag or a turn of the phone).
    function settle() {
        panelWidth = Math.max(minWidth, Math.min(area.width, panelWidth))
        px = Math.max(0, Math.min(area.width - panelWidth, px))
        py = Math.max(0, Math.min(area.height - panelHeight, py))
        tabY = Math.max(0, Math.min(area.height - tabHeight, tabY))
    }
    // Show the toolbar; it hides by itself a few seconds after the last touch.
    function showToolbar() {
        if (mode !== "window")
            return
        toolbarShown = true
        hideTimer.restart()
    }
    function tuck(side) {
        edge = side
        tabY = py + panelHeight / 2 - tabHeight / 2
        toolbarShown = false
        mode = "tab"
        settle()
    }
    function expand() {
        mode = "window"
        py = tabY + tabHeight / 2 - panelHeight / 2
        px = edge === "left" ? 8 : area.width - panelWidth - 8
        settle()
    }
    // ---- the director's focus changes (docs/58) ----------------------------------------------------
    // Where a screen other than the focus sits in the column (0 first).
    function columnIndex(screen) {
        let at = 0
        for (const other of director.screens) {
            if (other === screen)
                return at
            if (other !== director.focusScreen)
                at++
        }
        return 0
    }
    function setFullscreen() {
        toolbarShown = false
        // The director goes fullscreen as a whole: its screens laid out (docs/58).
        if (directing && others > 0)
            director.fullscreen()
        else
            root.screen.fullscreen()
    }
    Component.onCompleted: {
        panelWidth = area.width * 0.72
        settle()
        followActivity()
    }
    onAreaChanged: settle()
    onReadyChanged: Qt.callLater(updateMask)

    // ---- caption: what the assistant is doing (docs/88) ---------------------------------------------
    // hidden, working, done, question, failed, stopped. An ending shows a few seconds, then hides.
    property string captionState: ""
    function followActivity() {
        const state = root.screen.activityState
        captionState = ["working", "done", "question", "failed", "stopped"].indexOf(state) >= 0 ? state : ""
        if (captionState !== "" && captionState !== "working")
            endTimer.restart()
    }
    Connections { target: root.screen; function onActivityChanged() { root.followActivity() } }
    Timer { id: endTimer; interval: 4000; onTriggered: if (root.captionState !== "working") root.captionState = "" }

    Timer {
        id: hideTimer
        interval: 3000
        onTriggered: if (root.dragging || root.pinching) restart(); else root.toolbarShown = false
    }

    // Only what is visible takes touches.
    function updateMask() {
        const rects = []
        if (mode === "window")
            rects.push(Qt.rect(panel.x, panel.y, panel.width, panel.height))
        else if (mode === "tab")
            rects.push(Qt.rect(tab.x, tab.y, tab.width, tab.height))
        if (toolbar.visible)
            rects.push(Qt.rect(toolbar.x, toolbar.y, toolbar.width, toolbar.height))
        floater.setInputRects(rects)
    }
    readonly property string maskKey: [mode, panel.x, panel.y, panel.width, panel.height, tab.x, tab.y,
                                       toolbar.visible, toolbar.x, toolbar.y, width, height].join()
    onMaskKeyChanged: Qt.callLater(updateMask)

    // ---- a capsule of icon buttons -----------------------------------------------------------------
    component Toolbar: Item {
        id: bar
        property bool shown: false
        property real slide: -8          // where it comes from while appearing
        property var actions: []
        signal used()
        width: row.implicitWidth + 16
        height: 40
        opacity: shown ? 1 : 0
        scale: shown ? 1 : 0.9
        visible: opacity > 0.01
        transform: Translate { y: bar.shown ? 0 : bar.slide }
        Behavior on opacity { NumberAnimation { duration: 180; easing.type: Easing.OutCubic } }
        Behavior on scale { NumberAnimation { duration: 180; easing.type: Easing.OutCubic } }

        // Touches on the capsule stay here, between the buttons too.
        TapHandler { gesturePolicy: TapHandler.WithinBounds }
        // Dark translucent material. A real blur of what is behind needs KWin's blur effect, which
        // Plasma Mobile does not load (docs/65).
        Rectangle {
            anchors.fill: parent
            radius: height / 2
            color: Qt.rgba(0.11, 0.12, 0.15, 0.84)
            border.color: Qt.rgba(1, 1, 1, 0.16)
            border.width: 1
        }
        Row {
            id: row
            anchors.centerIn: parent
            spacing: 4
            Repeater {
                model: bar.actions
                delegate: Item {
                    width: bar.height; height: bar.height
                    Rectangle {
                        anchors.centerIn: parent
                        width: parent.height - 8; height: width; radius: width / 2
                        color: Qt.rgba(1, 1, 1, press.pressed ? 0.22 : 0)
                        Behavior on color { ColorAnimation { duration: 90 } }
                    }
                    Kirigami.Icon {
                        anchors.centerIn: parent
                        width: 19; height: width
                        source: modelData.icon
                        color: "white"
                        isMask: true
                    }
                    TapHandler {
                        id: press
                        gesturePolicy: TapHandler.ReleaseWithinBounds
                        onTapped: { bar.used(); modelData.act() }
                    }
                }
            }
        }
    }

    // ---- picture ---------------------------------------------------------------------------------
    Item {
        id: panel
        readonly property bool tucked: root.mode === "tab"
        x: tucked ? (root.edge === "left" ? -width * 0.6 : root.width - width * 0.4) : root.px
        y: tucked ? root.tabY + root.tabHeight / 2 - height / 2 : root.py
        width: root.panelWidth
        height: root.panelHeight
        opacity: root.mode === "window" ? 1 : 0
        scale: tucked ? 0.6 : 1
        visible: opacity > 0.01
        // Follow the finger exactly while it is down; glide everywhere else.
        Behavior on x { enabled: !root.dragging && !root.pinching; NumberAnimation { duration: root.motion; easing.type: Easing.OutCubic } }
        Behavior on y { enabled: !root.dragging && !root.pinching; NumberAnimation { duration: root.motion; easing.type: Easing.OutCubic } }
        Behavior on width { enabled: !root.pinching; NumberAnimation { duration: root.motion; easing.type: Easing.OutCubic } }
        Behavior on height { enabled: !root.pinching; NumberAnimation { duration: root.motion; easing.type: Easing.OutCubic } }
        Behavior on opacity { NumberAnimation { duration: root.motion } }
        Behavior on scale { NumberAnimation { duration: root.motion; easing.type: Easing.OutCubic } }

        Rectangle {
            id: picture
            anchors { left: parent.left; top: parent.top }
            width: root.pictureWidth
            height: root.pictureHeight
            radius: 14
            color: "black"
            layer.enabled: true   // rounded corners for the picture too
            layer.effect: MultiEffect {
                maskEnabled: true
                maskSource: roundMask
            }
            PipeWire.PipeWireSourceItem {
                id: stream
                anchors.fill: parent
                // The director's screens have a picture each (below), never switched.
                nodeId: root.directing ? 0 : root.screen.nodeId
                visible: nodeId > 0
            }
            Kirigami.Icon {
                anchors.centerIn: parent
                width: 32; height: 32
                visible: !root.directing && (!stream.visible || !stream.ready)
                source: "video-display"
                color: "#99ffffff"
                isMask: true
            }
        }
        // ---- the director's screens (docs/58): each its own live picture, never switched, so a change
        // of focus only moves them (switching one picture's stream showed black while it connected):
        // the focus over the picture's place, the others in a column on the right. Tap one to focus it;
        // the new focus breathes in, from a little smaller to its size.
        Repeater {
            model: root.directing ? director.screens : []
            delegate: Item {
                id: tile
                required property QtObject modelData
                readonly property bool focused: modelData === director.focusScreen
                readonly property int place: root.columnIndex(modelData)
                readonly property real thumbHeight: Math.min(Math.round(root.columnWidth * 9 / 16),
                    (root.pictureHeight - 4 * (root.others - 1)) / Math.max(1, root.others))
                readonly property real columnTop: (root.pictureHeight - (root.others * thumbHeight + (root.others - 1) * 4)) / 2
                x: focused ? 0 : root.pictureWidth + 4
                y: focused ? 0 : columnTop + place * (thumbHeight + 4)
                width: focused ? root.pictureWidth : root.columnWidth
                height: focused ? root.pictureHeight : thumbHeight
                layer.enabled: true
                layer.effect: MultiEffect { maskEnabled: true; maskSource: tileMask }
                Rectangle { id: tileMask; anchors.fill: parent; radius: tile.focused ? 14 : 8; visible: false; layer.enabled: true }
                Rectangle { anchors.fill: parent; color: "black" }
                PipeWire.PipeWireSourceItem {
                    anchors.fill: parent
                    nodeId: tile.modelData.nodeId
                    visible: nodeId > 0
                }
                Rectangle {  // its number
                    visible: !tile.focused
                    anchors { left: parent.left; bottom: parent.bottom; margins: 3 }
                    width: Math.max(height, number.implicitWidth + 6); height: number.implicitHeight + 2
                    radius: height / 2
                    color: Qt.rgba(0.11, 0.12, 0.15, 0.8)
                    Text { id: number; anchors.centerIn: parent; text: tile.modelData.workspace; color: "white"; font.pixelSize: 9 }
                }
                Rectangle {  // the agent at work there
                    visible: !tile.focused && tile.modelData.activityState === "working"
                    anchors { right: parent.right; top: parent.top; margins: 4 }
                    width: 6; height: 6; radius: 3
                    color: "#63d471"
                }
                TapHandler { enabled: !tile.focused; onTapped: director.setFocus(tile.modelData.workspace) }
                onFocusedChanged: if (focused) breathe.restart()
                NumberAnimation on scale { id: breathe; running: false; from: 0.95; to: 1; duration: 260; easing.type: Easing.OutCubic }
            }
        }
        Rectangle {
            id: caption
            z: 2
            property string label: ""
            property color dot: "#63d471"
            property bool shown: false
            anchors { horizontalCenter: picture.horizontalCenter; bottom: picture.bottom; bottomMargin: 8 }
            width: Math.min(picture.width - 16, captionRow.implicitWidth + 20)
            height: captionText.implicitHeight + 10
            radius: Math.min(14, height / 2)
            color: Qt.rgba(0.11, 0.12, 0.15, 0.86)
            border.color: Qt.rgba(1, 1, 1, 0.16)
            border.width: 1
            opacity: shown ? 1 : 0
            visible: opacity > 0.01
            Behavior on opacity { NumberAnimation { duration: 180 } }
            state: root.captionState === "" ? "hidden" : root.captionState
            states: [
                State { name: "hidden"; PropertyChanges { caption.shown: false } },
                State { name: "working"; PropertyChanges { caption.shown: true; caption.dot: "#63d471"; caption.label: root.screen.activityText || i18nc("@info:status the agent is at work on this screen", "Working") } },
                State { name: "done"; PropertyChanges { caption.shown: true; caption.dot: "#8ab4f8"; caption.label: root.screen.activityText ? i18nc("@info:status %1 is what the agent did", "Done · %1", root.screen.activityText) : i18nc("@info:status", "Done") } },
                State { name: "question"; PropertyChanges { caption.shown: true; caption.dot: "#e0a83c"; caption.label: root.screen.activityText ? i18nc("@info:status %1 is the agent's question", "Needs your answer · %1", root.screen.activityText) : i18nc("@info:status", "Needs your answer") } },
                State { name: "failed"; PropertyChanges { caption.shown: true; caption.dot: "#e0606d"; caption.label: root.screen.activityText ? i18nc("@info:status %1 is what the agent tried", "Didn't work · %1", root.screen.activityText) : i18nc("@info:status", "Didn't work") } },
                State { name: "stopped"; PropertyChanges { caption.shown: true; caption.dot: "#a1a9b1"; caption.label: i18nc("@info:status", "Stopped") } }
            ]
            Row {
                id: captionRow
                anchors { left: parent.left; leftMargin: 10; verticalCenter: parent.verticalCenter }
                spacing: 7
                Rectangle {
                    id: captionDot
                    anchors.verticalCenter: parent.verticalCenter
                    width: 7; height: 7; radius: 3.5
                    color: caption.dot
                    SequentialAnimation on opacity {
                        running: root.captionState === "working" && caption.visible
                        loops: Animation.Infinite
                        onRunningChanged: if (!running) captionDot.opacity = 1
                        NumberAnimation { to: 0.3; duration: 700; easing.type: Easing.InOutSine }
                        NumberAnimation { to: 1; duration: 700; easing.type: Easing.InOutSine }
                    }
                }
                Text {
                    id: captionText
                    // Sized from the picture, not from the capsule (whose width follows this text).
                    width: Math.min(implicitWidth, picture.width - 16 - 20 - 14)
                    text: caption.label
                    color: "white"
                    font.pixelSize: 12
                    elide: Text.ElideRight
                    wrapMode: Text.Wrap
                    maximumLineCount: 2
                }
            }
        }
        // Which screen this is, with the toolbar: desktop mode's and the assistant's may both be out.
        Rectangle {
            anchors { left: parent.left; top: parent.top; margins: 8 }
            opacity: root.toolbarShown ? 1 : 0
            visible: opacity > 0.01
            Behavior on opacity { NumberAnimation { duration: 180 } }
            width: nameText.implicitWidth + 16
            height: nameText.implicitHeight + 8
            radius: height / 2
            color: Qt.rgba(0.11, 0.12, 0.15, 0.86)
            Text {
                id: nameText
                anchors.centerIn: parent
                text: root.directing ? i18nc("@label name of an assistant's screen, %1 its number", "Assistant Screen %1", root.screen.workspace)
                    : root.screen.workspace > 0 ? i18nc("@label name of the agent's screen", "Assistant Screen") : i18nc("@label name of the user's second screen", "Desktop")
                color: "white"
                font.pixelSize: 12
            }
        }
        Rectangle {
            id: roundMask
            anchors.fill: picture
            radius: 14
            visible: false
            layer.enabled: true
        }

        // One finger moves, two pinch; a tap shows or hides the toolbar.
        DragHandler {
            id: drag
            target: null
            maximumPointCount: 1
            property point offset
            // The finger was lifted. A second finger often lands while the first is already moving
            // out fast: this ends then with both fingers still down, and the pinch follows (docs/65).
            property bool lifted: false
            // A finger left over from a pinch: when one finger of a pinch lifts, the pinch lets the
            // other go and this takes it at once (it has long moved past the drag distance since it
            // was pressed), jumps the window by all that way and tucks it on the let-go (logged on
            // the phone, Qt 6.10, docs/65). Such a finger neither moves nor tucks the window.
            property bool leftover: false
            onGrabChanged: (transition, point) => {
                if (transition === PointerDevice.GrabExclusive)
                    leftover = pinch.took(point)
                if (point.state === EventPoint.Released)
                    lifted = true
            }
            onActiveChanged: {
                if (active) {
                    offset = Qt.point(centroid.scenePressPosition.x - root.px, centroid.scenePressPosition.y - root.py)
                    lifted = false
                    root.dragging = true
                } else {
                    root.dragging = false
                    // The finger's grab is given up right after this: decide then.
                    const flick = centroid.velocity.x
                    Qt.callLater(() => drag.letGo(flick))
                }
                root.showToolbar()
            }
            // Only a let-go may tuck it: a quarter of it past a side edge, there or where a flick
            // carries it (~0.15 s of its speed).
            function letGo(flick) {
                if (lifted)
                    pinch.fingers = ({})            // its fingers are all up
                if (!lifted || leftover || pinch.active || root.mode !== "window") {
                    if (!pinch.active)
                        root.settle()
                    return
                }
                const ahead = root.px + (Math.abs(flick) > 900 ? flick * 0.15 : 0)
                if (ahead < -root.panelWidth / 4)
                    root.tuck("left")
                else if (ahead + root.panelWidth > root.area.width + root.panelWidth / 4)
                    root.tuck("right")
                else
                    root.settle()
            }
            onCentroidChanged: if (active && !leftover) {
                root.px = centroid.scenePosition.x - offset.x
                root.py = Math.max(0, Math.min(root.area.height - root.panelHeight, centroid.scenePosition.y - offset.y))
            }
        }
        PinchHandler {
            id: pinch
            target: null
            // The fingers it took, by id and press time (Android reuses the ids), until a drag ends.
            property var fingers: ({})
            function key(point) { return point.id + ":" + point.pressTimestamp }
            function took(point) { return fingers[key(point)] === true }
            onGrabChanged: (transition, point) => {
                if (transition === PointerDevice.GrabExclusive)
                    fingers[key(point)] = true
            }
            property real startWidth
            property point centre
            onActiveChanged: {
                root.pinching = active
                if (active) {
                    startWidth = root.panelWidth
                    centre = Qt.point(root.px + root.panelWidth / 2, root.py + root.panelHeight / 2)
                } else {
                    root.settle()
                }
                root.showToolbar()
            }
            onActiveScaleChanged: if (active) {
                root.panelWidth = Math.max(root.minWidth, Math.min(root.area.width, startWidth * activeScale))
                root.px = centre.x - root.panelWidth / 2
                root.py = centre.y - root.panelHeight / 2
            }
        }
        TapHandler { onTapped: root.toolbarShown ? (root.toolbarShown = false) : root.showToolbar() }
    }

    Toolbar {
        id: toolbar
        shown: root.toolbarShown && root.mode === "window"
        slide: root.barAbove ? 8 : -8
        x: Math.max(6, Math.min(root.width - width - 6, panel.x + (panel.width - width) / 2))
        y: root.barAbove ? panel.y - root.gap - height : panel.y + panel.height + root.gap
        actions: [{ icon: "view-fullscreen", act: () => root.setFullscreen() },
                  { icon: "video-television", act: () => root.screen.castToTv() },
                  { icon: root.onLeftHalf ? "go-previous" : "go-next", act: () => root.tuck(root.onLeftHalf ? "left" : "right") },
                  { icon: "window-close", act: () => root.screen.close() }]
        onUsed: root.showToolbar()
    }

    // ---- tab on the edge -------------------------------------------------------------------------
    Rectangle {
        id: tab
        readonly property bool shown: root.mode === "tab"
        width: root.tabWidth
        height: root.tabHeight
        x: root.edge === "left" ? (shown ? 0 : -width) : (shown ? root.width - width : root.width)
        y: root.tabY
        opacity: shown ? 1 : 0
        visible: opacity > 0.01
        radius: 12
        color: Qt.rgba(0.11, 0.12, 0.15, 0.84)
        border.color: Qt.rgba(1, 1, 1, 0.2)
        border.width: 1
        Behavior on x { NumberAnimation { duration: root.motion; easing.type: Easing.OutCubic } }
        Behavior on opacity { NumberAnimation { duration: root.motion } }
        Kirigami.Icon {
            anchors.centerIn: parent
            width: 16; height: 16
            source: "video-display"
            color: "white"
            isMask: true
        }
        Rectangle {  // alive: green, starting: amber; breathes while the assistant works (docs/88)
            id: tabDot
            anchors { horizontalCenter: parent.horizontalCenter; top: parent.top; topMargin: 8 }
            width: 6; height: 6; radius: 3
            color: root.screen.status === "running" ? "#63d471" : "#e0a83c"
            SequentialAnimation on opacity {
                running: root.captionState === "working" && tab.visible
                loops: Animation.Infinite
                onRunningChanged: if (!running) tabDot.opacity = 1
                NumberAnimation { to: 0.25; duration: 700; easing.type: Easing.InOutSine }
                NumberAnimation { to: 1; duration: 700; easing.type: Easing.InOutSine }
            }
        }
        TapHandler { onTapped: root.expand() }
        DragHandler {
            target: null
            xAxis.enabled: false
            property real offset
            onActiveChanged: if (active) offset = centroid.scenePressPosition.y - root.tabY
            onCentroidChanged: if (active)
                root.tabY = Math.max(0, Math.min(root.area.height - root.tabHeight, centroid.scenePosition.y - offset))
        }
    }
}
