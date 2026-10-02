// Fullscreen's own keyboard (docs/research/97 §19.9): Qt Virtual Keyboard with the phone keyboard's
// Rime and layouts (rungic-plasma-input), inside the stage, so it turns with the picture; the phone's
// keyboard (plasma-keyboard, placed by KWin at the phone's bottom) can neither turn nor float.
//
// Floating, as a tablet's floating keyboard: about a phone keyboard's size, moved by its top strip
// (let go, it settles at the bottom's middle or a corner), resized with two fingers; pinched out to
// the full width it docks at the bottom, pinched in it floats again. Size, place and docking are
// remembered. The strip has what a desktop needs and a phone keyboard has not: Esc, Tab, Ctrl and
// Alt (held for the next key), the arrows; and what is being composed (pinyin).
//
// What it types goes to the focused field it is given (Main's keyboardField), as any input method's.
import QtCore
import QtQuick
import QtQuick.Effects
import QtQuick.VirtualKeyboard
import QtQuick.VirtualKeyboard.Settings
import org.kde.kirigami as Kirigami

Item {
    id: board
    required property Item area              // where it floats: the stage
    required property string place           // remembered apart: desktop mode, the assistant's screens
    property string composing: ""            // the field's preedit
    property bool ctrl: false
    property bool alt: false
    signal keyWanted(int code)                // a remote key (Linux key code)
    signal hideWanted()

    readonly property real pad: 6
    readonly property real stripHeight: 40
    // Floating: a phone keyboard's width, between a third and most of the stage's.
    readonly property real smallest: area.width * 0.34
    readonly property real largest: area.width * 0.8
    readonly property real standard: Math.min(area.height * 1.05, area.width * 0.5)
    property real floatWidth: standard
    property bool docked: false
    // The bottom's strip, where a swipe up shows the toolbar (FullTouch), stays free.
    readonly property real bottomGap: docked ? 0 : 52
    width: docked ? area.width : Math.max(smallest, Math.min(largest, floatWidth))
    height: stripHeight + panel.height + pad
    // Its place: the centre's share of the stage (it keeps it when the stage turns).
    property real cx: 0.5
    property real cy: 1
    x: docked ? 0 : clampX(cx * area.width - width / 2)
    y: docked ? area.height - height : clampY(cy * area.height - height / 2)
    function clampX(v) { return Math.max(8, Math.min(area.width - width - 8, v)) }
    function clampY(v) { return Math.max(8, Math.min(area.height - height - bottomGap, v)) }
    Behavior on x { enabled: !move.active && !pinch.active; NumberAnimation { duration: 220; easing.type: Easing.OutCubic } }
    Behavior on y { enabled: !move.active && !pinch.active; NumberAnimation { duration: 220; easing.type: Easing.OutCubic } }
    Behavior on width { enabled: !pinch.active; NumberAnimation { duration: 220; easing.type: Easing.OutCubic } }

    Settings {
        category: "Keyboard-" + board.place
        location: StandardPaths.writableLocation(StandardPaths.ConfigLocation) + "/rungic-agent-screenrc"
        property alias floatWidth: board.floatWidth
        property alias docked: board.docked
        property alias cx: board.cx
        property alias cy: board.cy
    }
    // The phone keyboard's languages (plasmakeyboardrc, its settings page).
    Settings {
        id: phoneKeyboard
        category: "General"
        location: StandardPaths.writableLocation(StandardPaths.ConfigLocation) + "/plasmakeyboardrc"
        property var enabledLocales: []
    }
    function locales() {
        const list = [].concat(phoneKeyboard.enabledLocales || []).filter(l => !!l)
        return list.length ? list : ["zh_CN", "en_US"]
    }

    // Let go: to the bottom's middle or a corner, whichever is nearest.
    function settle() {
        const half = width / 2 / area.width
        const spots = [half + 8 / area.width, 0.5, 1 - half - 8 / area.width]
        const centre = (x + width / 2) / area.width
        cx = spots.reduce((a, b) => Math.abs(b - centre) < Math.abs(a - centre) ? b : a)
        cy = 1
    }

    RectangularShadow {
        anchors.fill: background
        radius: background.radius
        blur: 24
        offset.y: 6
        color: Qt.rgba(0, 0, 0, 0.45)
        visible: !board.docked
    }
    Rectangle {
        id: background
        anchors.fill: parent
        radius: board.docked ? 0 : 14
        color: "#1c1e22"
        border.color: Qt.rgba(1, 1, 1, board.docked ? 0 : 0.12)
        border.width: 1
    }
    // Touches between the keys stay here (not to the picture below).
    TapHandler { gesturePolicy: TapHandler.WithinBounds }
    // Two fingers: its size; out past the largest docks it, in from docked floats it.
    PinchHandler {
        id: pinch
        target: null
        property real from
        onActiveChanged: {
            if (active) {
                from = board.docked ? board.area.width : board.width
            } else if (!board.docked) {
                board.cx = (board.x + board.width / 2) / board.area.width
                board.settle()
            }
        }
        onActiveScaleChanged: {
            const wanted = from * activeScale
            if (!board.docked && wanted > board.largest * 1.12) {
                board.docked = true
            } else if (board.docked && wanted < board.area.width * 0.85) {
                board.docked = false
                board.floatWidth = board.standard
            } else if (!board.docked) {
                board.floatWidth = Math.max(board.smallest, Math.min(board.largest, wanted))
            }
        }
    }

    // ---- the strip: the handle, what is composed, the desktop's keys -----------------------------------
    component StripKey: Item {
        id: key
        property string icon: ""
        property string label: ""
        property bool checked: false
        signal tapped()
        width: label ? Math.max(board.stripHeight, caption.implicitWidth + 18) : board.stripHeight - 4
        height: board.stripHeight - 4
        Rectangle {
            anchors.fill: parent
            anchors.margins: 3
            radius: 7
            color: Qt.rgba(1, 1, 1, tap.pressed ? 0.24 : key.checked ? 0.2 : 0.08)
            border.color: key.checked ? Qt.rgba(1, 1, 1, 0.4) : "transparent"
            border.width: 1
        }
        Kirigami.Icon {
            anchors.centerIn: parent
            visible: !!key.icon
            width: 17; height: width
            source: key.icon
            color: "white"
            isMask: true
        }
        Text {
            id: caption
            anchors.centerIn: parent
            visible: !!key.label
            text: key.label
            color: "white"
            font.pixelSize: 13
        }
        TapHandler { id: tap; gesturePolicy: TapHandler.ReleaseWithinBounds; onTapped: key.tapped() }
    }
    Item {
        id: strip
        anchors { left: parent.left; right: parent.right; top: parent.top; leftMargin: board.pad; rightMargin: board.pad }
        height: board.stripHeight
        // The handle: the strip's free space moves the keyboard (not while docked).
        DragHandler {
            id: move
            target: null
            enabled: !board.docked
            property point offset
            onActiveChanged: {
                const p = board.area.mapFromItem(null, centroid.scenePosition.x, centroid.scenePosition.y)
                if (active)
                    offset = Qt.point(p.x - (board.x + board.width / 2), p.y - (board.y + board.height / 2))
                else
                    board.settle()
            }
            onCentroidChanged: {
                if (!active)
                    return
                const p = board.area.mapFromItem(null, centroid.scenePosition.x, centroid.scenePosition.y)
                board.cx = (p.x - offset.x) / board.area.width
                board.cy = (p.y - offset.y) / board.area.height
            }
        }
        Rectangle {  // the grip
            anchors { horizontalCenter: parent.horizontalCenter; top: parent.top; topMargin: 4 }
            width: 36; height: 4; radius: 2
            color: Qt.rgba(1, 1, 1, 0.3)
            visible: !board.docked
        }
        Row {
            id: left
            anchors { left: parent.left; verticalCenter: parent.verticalCenter; verticalCenterOffset: 2 }
            StripKey { label: "Esc"; onTapped: board.keyWanted(1) }
            StripKey { label: "Tab"; onTapped: board.keyWanted(15) }
            StripKey { label: "Ctrl"; checked: board.ctrl; onTapped: board.ctrl = !board.ctrl }
            StripKey { label: "Alt"; checked: board.alt; onTapped: board.alt = !board.alt }
        }
        Text {
            anchors { left: left.right; right: right.left; verticalCenter: parent.verticalCenter; margins: 8 }
            text: board.composing
            color: "#8ec5ff"
            font.pixelSize: 15
            elide: Text.ElideLeft
            horizontalAlignment: Text.AlignHCenter
        }
        Row {
            id: right
            anchors { right: parent.right; verticalCenter: parent.verticalCenter; verticalCenterOffset: 2 }
            StripKey { icon: "go-previous"; onTapped: board.keyWanted(105) }
            StripKey { icon: "go-up"; onTapped: board.keyWanted(103) }
            StripKey { icon: "go-down"; onTapped: board.keyWanted(108) }
            StripKey { icon: "go-next"; onTapped: board.keyWanted(106) }
            StripKey {
                icon: board.docked ? "window-restore" : "view-fullscreen"
                onTapped: { board.docked = !board.docked; if (!board.docked) { board.floatWidth = board.standard; board.settle() } }
            }
            StripKey { icon: "arrow-down"; onTapped: board.hideWanted() }
        }
    }

    InputPanel {
        id: panel
        anchors { top: strip.bottom; horizontalCenter: parent.horizontalCenter }
        width: board.width - 2 * board.pad
        // Its languages are switched on its own key, not by a list of the phone's.
        externalLanguageSwitchEnabled: false
        Component.onCompleted: {
            VirtualKeyboardSettings.styleName = "default"
            VirtualKeyboardSettings.activeLocales = board.locales()
            VirtualKeyboardSettings.locale = board.locales()[0]
            VirtualKeyboardSettings.wordCandidateList.alwaysVisible = true
            VirtualKeyboardSettings.closeOnReturn = false
        }
    }
}
