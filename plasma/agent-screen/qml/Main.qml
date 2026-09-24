// The floating window of the assistant's screen (docs/65).
//
// The surface covers the phone's screen and is transparent; the picture, the toolbar and the tab
// move inside it (Floater), and only they take touches. So a drag follows the finger frame by frame
// and every change of place or size is animated.
//
// Window: the live picture, looked at and not touched through. One finger moves it; let go with it
// a quarter past a side edge, or flick it towards one, and it tucks into a tab there. Two fingers
// pinch it between half and the full width of the phone. A tap, a drag or a pinch shows a toolbar of
// icons below the picture, a small gap away (above it near the bottom of the screen), which hides a
// few seconds later.
// Fullscreen: a window of its own above everything, showing the picture turned a quarter clockwise,
// so it fills the phone held sideways (top to the left). The phone itself stays portrait: turning
// its output re-laid out every phone app and made it overlap the assistant's screen in KWin's space.
// Touches reach the assistant's screen (tap = click, long press = right click, drag = drag, two
// fingers = scroll). Swiping up from the bottom of the sideways view shows the toolbar there for a
// few seconds.
// Tab: a handle on the edge; tap to bring the window back, drag to slide it along the edge.
// While a TV presents the screen everything hides; when the TV goes, it comes back.
import QtQuick
import QtQuick.Effects
import QtQuick.Window
import org.kde.kirigami as Kirigami
import org.kde.pipewire as PipeWire

Window {
    id: root
    // Shown once main.cpp has made it a layer surface.
    property bool ready: false
    visible: ready && agent.status !== "tv"
    title: "moto-agent-screen"
    color: "transparent"

    property string mode: "window"      // window | tab | fullscreen
    property string edge: "right"
    property real px: 12
    property real py: 110
    property real panelWidth: 260
    property real tabY: 180
    property bool toolbarShown: false
    property bool dragging: false
    property bool pinching: false
    property var fullscreenWindow: null
    readonly property rect area: floater.area
    readonly property real minWidth: area.width * 0.5
    readonly property real panelHeight: Math.round(panelWidth * 9 / 16)
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
    function setFullscreen(on) {
        toolbarShown = false
        if (on && !fullscreenWindow) {
            mode = "fullscreen"
            fullscreenWindow = fullscreenComponent.createObject(null)
        } else if (!on && fullscreenWindow) {
            fullscreenWindow.destroy()
            fullscreenWindow = null
            mode = "window"
            settle()
        }
    }
    Component.onCompleted: {
        panelWidth = area.width * 0.72
        settle()
    }
    onAreaChanged: settle()
    onReadyChanged: Qt.callLater(updateMask)

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
        property bool large: false
        property bool shown: false
        property real slide: -8          // where it comes from while appearing
        property var actions: []
        signal used()
        width: row.implicitWidth + 16
        height: large ? 46 : 40
        opacity: shown ? 1 : 0
        scale: shown ? 1 : 0.9
        visible: opacity > 0.01
        transform: Translate { y: bar.shown ? 0 : bar.slide }
        Behavior on opacity { NumberAnimation { duration: 180; easing.type: Easing.OutCubic } }
        Behavior on scale { NumberAnimation { duration: 180; easing.type: Easing.OutCubic } }

        // Touches on the capsule stay here (fullscreen: never a click on the picture below).
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
                        width: bar.large ? 22 : 19; height: width
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
            anchors.fill: parent
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
                // Nothing to draw while fullscreen shows the picture instead.
                nodeId: root.mode === "fullscreen" ? 0 : agent.nodeId
                visible: nodeId > 0
            }
            Kirigami.Icon {
                anchors.centerIn: parent
                width: 32; height: 32
                visible: !stream.visible || !stream.ready
                source: "video-display"
                color: "#99ffffff"
                isMask: true
            }
        }
        Rectangle {
            id: roundMask
            anchors.fill: parent
            radius: 14
            visible: false
            layer.enabled: true
        }

        // One finger moves, two pinch; a tap shows or hides the toolbar.
        DragHandler {
            target: null
            maximumPointCount: 1
            property point offset
            onActiveChanged: {
                if (active) {
                    offset = Qt.point(centroid.scenePressPosition.x - root.px, centroid.scenePressPosition.y - root.py)
                    root.dragging = true
                } else {
                    root.dragging = false
                    // A quarter of it past a side edge, or flicked towards one: tuck it there.
                    const flick = centroid.velocity.x
                    if (root.px < -root.panelWidth / 4 || (flick < -900 && root.px < root.area.width / 4))
                        root.tuck("left")
                    else if (root.px + root.panelWidth > root.area.width + root.panelWidth / 4
                             || (flick > 900 && root.px + root.panelWidth > root.area.width * 3 / 4))
                        root.tuck("right")
                    else
                        root.settle()
                }
                root.showToolbar()
            }
            onCentroidChanged: if (active) {
                root.px = centroid.scenePosition.x - offset.x
                root.py = Math.max(0, Math.min(root.area.height - root.panelHeight, centroid.scenePosition.y - offset.y))
            }
        }
        PinchHandler {
            target: null
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
        actions: [{ icon: "view-fullscreen", act: () => root.setFullscreen(true) },
                  { icon: "video-television", act: () => agent.castToTv() },
                  { icon: root.onLeftHalf ? "go-previous" : "go-next", act: () => root.tuck(root.onLeftHalf ? "left" : "right") },
                  { icon: "window-close", act: () => agent.close() }]
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
        Rectangle {  // alive: green, starting: amber
            anchors { horizontalCenter: parent.horizontalCenter; top: parent.top; topMargin: 8 }
            width: 6; height: 6; radius: 3
            color: agent.status === "running" ? "#63d471" : "#e0a83c"
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

    // ---- fullscreen: a window of its own above everything ------------------------------------------
    Component {
        id: fullscreenComponent
        Window {
            id: full
            visible: false
            color: "black"
            title: "moto-agent-screen fullscreen"
            property bool barShown: false
            readonly property int swipeZone: 56   // from the bottom of the sideways view
            function showBar() {
                barShown = true
                barTimer.restart()
            }
            Timer {
                id: barTimer
                interval: 3000
                onTriggered: full.barShown = false
            }
            Component.onCompleted: {
                floater.setupOverlay(full)
                visible = Qt.binding(() => agent.status !== "tv")
            }

            // The sideways view: the window turned a quarter clockwise; everything in it (picture,
            // touches, toolbar) works in its own upright coordinates.
            Item {
                id: sideways
                anchors.centerIn: parent
                width: full.height
                height: full.width
                rotation: 90

                PipeWire.PipeWireSourceItem {
                    id: fullStream
                    anchors.fill: parent
                    nodeId: agent.nodeId
                }

                Item {
                    id: touchArea
                    anchors.fill: parent
                    function move(p) {
                        const r = fullStream.paintedRect.width > 0 ? fullStream.paintedRect : Qt.rect(0, 0, width, height)
                        agent.pointerMove((p.x - r.x) / r.width, (p.y - r.y) / r.height)
                    }
                    function click(p, button) {
                        move(p)
                        agent.pointerButton(button, true)
                        agent.pointerButton(button, false)
                    }
                    TapHandler {
                        onTapped: (point) => touchArea.click(point.position, root.btnLeft)
                        onLongPressed: touchArea.click(point.position, root.btnRight)
                    }
                    DragHandler {
                        target: null
                        maximumPointCount: 1
                        property bool swipe: false   // up from the bottom zone: the toolbar, not a drag
                        onActiveChanged: {
                            if (active) {
                                swipe = centroid.pressPosition.y > touchArea.height - full.swipeZone
                                if (swipe)
                                    return
                                touchArea.move(centroid.pressPosition)
                                agent.pointerButton(root.btnLeft, true)
                            } else if (!swipe) {
                                agent.pointerButton(root.btnLeft, false)
                            }
                        }
                        onCentroidChanged: {
                            if (!active)
                                return
                            if (swipe) {
                                if (centroid.position.y - centroid.pressPosition.y < -20)
                                    full.showBar()
                            } else {
                                touchArea.move(centroid.position)
                            }
                        }
                    }
                    DragHandler {
                        target: null
                        minimumPointCount: 2
                        property point last
                        onActiveChanged: if (active) { last = centroid.position; touchArea.move(centroid.position) }
                        onCentroidChanged: if (active) {
                            // Natural scrolling: the content follows the fingers.
                            agent.scroll(-(centroid.position.x - last.x) * 2, -(centroid.position.y - last.y) * 2)
                            last = centroid.position
                        }
                    }
                }

                Toolbar {
                    large: true
                    shown: full.barShown
                    slide: 8
                    x: (sideways.width - width) / 2
                    y: sideways.height - height - 20
                    actions: [{ icon: "view-restore", act: () => root.setFullscreen(false) },
                              { icon: "video-television", act: () => { root.setFullscreen(false); agent.castToTv() } },
                              { icon: "window-close", act: () => { root.setFullscreen(false); agent.close() } }]
                    onUsed: full.showBar()
                }
            }
        }
    }
}
