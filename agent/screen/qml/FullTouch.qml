// Fullscreen's touches (docs/research/97 §17, docs/66): the Linux port of the APK's AgentFullscreen
// gestures, with their rules and numbers (DirectGestures, TouchpadGestures, PointerTransfer,
// GestureRules, PointerOutput), so the phone works the same as it did there.
//
// Direct (the finger is the pointer, in the picture):
//   tap left click; two taps a double click; long press right click; press and move a drag from
//   where the finger went down; two-finger tap right click, three-finger middle; two fingers moving
//   scroll, the content following them, kinetic after the lift.
// Touchpad (the finger moves the pointer, anywhere but another screen of the director), after
// libinput's tap state machine:
//   one finger moves the pointer (1:1 as seen when slow, accelerating when fast); tap left click,
//   two-finger tap right, three-finger middle; tap, tap a double click; tap, then touch and move
//   (or hold past the tap timeout) a drag; two fingers moving scroll, kinetic after the lift.
// Both: a tap on another of the director's screens focuses it; a swipe up from the bottom edge
// shows the toolbar (a tap there still clicks); direct, a tap beside the picture shows or hides it.
import QtQuick
import QtQuick.Window

MultiPointTouchArea {
    id: root

    // The screen the touches work (AgentScreen: pointerMove, pointerButton, scroll).
    property QtObject target: null
    // The picture of that screen, in this item's coordinates.
    property rect picture
    // Its output's size, in the pixels its pointer and scroll take.
    property size output: Qt.size(1920, 1080)
    property bool touchpad: false
    // No screen under the picture (the team's board in focus): its touches go nowhere.
    property bool inert: false
    // Another screen of the director under a point (its tile's screen), or null.
    property var tileAt: function (point) { return null }

    signal toolbarWanted()       // the swipe up from the bottom edge
    signal toolbarToggled()      // a tap beside the picture
    signal tileTapped(QtObject screen)

    maximumTouchPoints: 3
    touchPoints: [TouchPoint {}, TouchPoint {}, TouchPoint {}]

    // ---- the rules (GestureRules, libinput 1.32.0) -------------------------------------------------
    readonly property real pxPerMm: Screen.pixelDensity     // logical pixels per millimetre
    readonly property int tapTimeout: 180                   // a touch ending sooner, unmoved, taps
    readonly property int dragTimeout: 160                  // after a tap, a touch within starts a drag
    readonly property real tapMoveMm: 1.3                   // travel under this has not moved
    readonly property int longPressTimeout: 400             // Android's (ViewConfiguration, 12 and later)
    readonly property int clickMs: 40                       // between a click's press and release
    readonly property real stripHeight: 48                  // the bottom edge the toolbar comes from
    readonly property real swipeMm: 3.2                     // up this far from there: the toolbar (20 dp)
    readonly property int btnLeft: 0x110
    readonly property int btnRight: 0x111
    readonly property int btnMiddle: 0x112
    function tapButton(fingers) { return fingers >= 3 ? btnMiddle : fingers === 2 ? btnRight : btnLeft }

    // ---- the touch now -----------------------------------------------------------------------------
    property string region: ""        // "screen" (worked), "tile", "beside"
    property QtObject tileScreen: null
    property bool fromStrip: false
    property bool toToolbar: false
    property bool moved: false
    property int maxFingers: 0
    property real downTime: 0
    property point start
    property point last

    function down() {
        const points = []
        for (let i = 0; i < touchPoints.length; i++)
            if (touchPoints[i].pressed)
                points.push(touchPoints[i])
        return points
    }
    function centroid(points) {
        let x = 0, y = 0
        for (const p of points) { x += p.x; y += p.y }
        return Qt.point(x / points.length, y / points.length)
    }
    // Moved: any finger further than tapMoveMm from where it went down (a finger landing or lifting
    // moves the centroid, and none has moved).
    function travelled(points) {
        for (const p of points)
            if (Math.hypot(p.x - p.startX, p.y - p.startY) / pxPerMm > tapMoveMm)
                return true
        return false
    }
    function within(r, p) { return p.x >= r.x && p.x < r.x + r.width && p.y >= r.y && p.y < r.y + r.height }

    // ---- the pointer (PointerOutput) ---------------------------------------------------------------
    // Where the pointer is, as fractions of the output: the touchpad moves it from there.
    property real pointerX: 0.5
    property real pointerY: 0.5
    function pointAt(fx, fy) {
        pointerX = Math.max(0, Math.min(1, fx))
        pointerY = Math.max(0, Math.min(1, fy))
        if (target)
            target.pointerMove(pointerX, pointerY)
    }
    // A point of the picture, in this item's coordinates.
    function pointTo(p) { pointAt((p.x - picture.x) / picture.width, (p.y - picture.y) / picture.height) }
    function moveBy(dx, dy) { pointAt(pointerX + dx / output.width, pointerY + dy / output.height) }
    function button(code, pressed) {
        if (target)
            target.pointerButton(code, pressed)
    }
    // A click: released clickMs after its press (a release in the same instant was ignored by some
    // controls, the panel's application launcher, docs/65).
    property int clickButton: 0
    function click(code) {
        if (release.running)
            release.triggered()
        button(code, true)
        clickButton = code
        release.restart()
    }
    Timer {
        id: release
        interval: root.clickMs
        onTriggered: { stop(); if (root.clickButton) root.button(root.clickButton, false); root.clickButton = 0 }
    }
    // Output pixels per pixel of finger travel at unity: the picture's scale.
    readonly property real outputPerPx: output.width / Math.max(1, picture.width)
    // Finger scroll in output pixels, positive up and left as a finger moving up would (natural).
    function scrollBy(dx, dy) {
        if (target)
            target.scroll(dx, dy)
        kinetic.note(dx, dy)
    }

    // ---- kinetic scrolling after the fingers lift --------------------------------------------------
    Timer {
        id: kinetic
        interval: 16
        repeat: true
        property real vx: 0          // output pixels per ms
        property real vy: 0
        property var samples: []     // [time, dx, dy] of the last scroll steps
        function note(dx, dy) {
            const now = Date.now()
            samples.push([now, dx, dy])
            while (samples.length && now - samples[0][0] > 80)
                samples.shift()
        }
        function fling() {
            const now = Date.now()
            const recent = samples.filter(s => now - s[0] <= 80)
            samples = []
            if (recent.length < 2)
                return
            const span = Math.max(16, recent[recent.length - 1][0] - recent[0][0])
            let dx = 0, dy = 0
            for (const s of recent) { dx += s[1]; dy += s[2] }
            vx = dx / span
            vy = dy / span
            if (Math.hypot(vx, vy) > 0.3)
                start()
        }
        function halt() { stop(); samples = []; vx = vy = 0 }
        onTriggered: {
            if (root.target)
                root.target.scroll(vx * interval, vy * interval)
            vx *= 0.94
            vy *= 0.94
            if (Math.hypot(vx, vy) < 0.05)
                stop()
        }
    }

    // ---- touchpad motion (PointerTransfer: libinput's touchpad profile, plateau 1) -----------------
    QtObject {
        id: transfer
        property var times: []
        property var xs: []
        property var ys: []
        property real lastVelocity: 0
        // The unitless factor at `speed` mm/s: 1/3 below 7 mm/s, 1 to 130, rising to 5.3x at 520.
        function factor(speed) {
            if (speed < 7)
                return Math.min(0.9, 0.1 * speed + 0.3) / 0.9
            if (speed < 130)
                return 1
            const v = Math.min(speed, 520)
            return (0.0025 * (v / 130) * (v - 130) + 0.9) / 0.9
        }
        function begin(p) {
            times = []; xs = []; ys = []
            lastVelocity = 0
            add(p, Date.now())
        }
        function add(p, t) {
            times.push(t); xs.push(p.x / root.pxPerMm); ys.push(p.y / root.pxPerMm)
            if (times.length > 20) { times.shift(); xs.shift(); ys.shift() }
        }
        // mm/s at the newest sample: lines fitted to x(t) and y(t) over the last 60 ms, cut at a
        // pause over 40 ms.
        function velocity() {
            const n0 = times.length
            if (n0 < 2)
                return 0
            const newest = times[n0 - 1]
            let s0 = 0, s1 = 0, s2 = 0, sx = 0, stx = 0, sy = 0, sty = 0, n = 0, previous = newest
            for (let i = n0 - 1; i >= 0; i--) {
                if (newest - times[i] > 60 || previous - times[i] > 40)
                    break
                previous = times[i]
                const t = times[i] - newest
                s0 += 1; s1 += t; s2 += t * t
                sx += xs[i]; stx += t * xs[i]
                sy += ys[i]; sty += t * ys[i]
                n++
            }
            if (n >= 3) {
                const d = s0 * s2 - s1 * s1
                if (d > 1e-9)
                    return Math.hypot((s0 * stx - s1 * sx) / d, (s0 * sty - s1 * sy) / d) * 1000
            }
            const dt = Math.max(1, times[n0 - 1] - times[n0 - 2])
            return Math.hypot(xs[n0 - 1] - xs[n0 - 2], ys[n0 - 1] - ys[n0 - 2]) * 1000 / dt
        }
        // Output pixels for the finger's move to p.
        function step(p) {
            const px = xs[xs.length - 1], py = ys[ys.length - 1]
            add(p, Date.now())
            const v = velocity()
            const f = (factor(lastVelocity) + 4 * factor((lastVelocity + v) / 2) + factor(v)) / 6
            lastVelocity = v
            const unity = root.pxPerMm * root.outputPerPx      // output pixels per mm
            return Qt.point((xs[xs.length - 1] - px) * f * unity, (ys[ys.length - 1] - py) * f * unity)
        }
    }

    // ---- direct (DirectGestures) -------------------------------------------------------------------
    property bool dragging: false
    property bool scrolling: false
    property bool longPressed: false
    Timer {
        id: longPress
        interval: root.longPressTimeout
        onTriggered: {
            if (root.moved || root.maxFingers > 1 || root.toToolbar || root.region !== "screen" || root.touchpad)
                return
            root.longPressed = true
            root.pointTo(root.start)
            root.click(root.btnRight)
        }
    }

    // ---- touchpad (TouchpadGestures) ---------------------------------------------------------------
    property string padState: "idle"     // idle, touch, tapped, dragOrDoubletap, dragging
    Timer {
        id: tapReleased                  // no second touch in time: the tap was a single click
        interval: root.dragTimeout
        onTriggered: if (root.padState === "tapped") { root.button(root.btnLeft, false); root.padState = "idle" }
    }
    Timer {
        id: holdToDrag                   // the second touch held past the tap timeout: a drag
        interval: root.tapTimeout
        onTriggered: if (root.padState === "dragOrDoubletap" && !root.scrolling) root.padState = "dragging"
    }

    // Let go of anything held: a gesture cut short, the mode changed, fullscreen left.
    function reset() {
        longPress.stop()
        tapReleased.stop()
        holdToDrag.stop()
        kinetic.halt()
        if (dragging || padState === "tapped" || padState === "dragOrDoubletap" || padState === "dragging")
            button(btnLeft, false)
        if (release.running)
            release.triggered()
        dragging = scrolling = false
        padState = "idle"
        region = ""
    }
    // The pointer where the drawn one is, from the start of the touchpad mode.
    function placePointer() {
        if (touchpad && enabled)
            pointAt(pointerX, pointerY)
    }
    onTouchpadChanged: { reset(); placePointer() }
    onEnabledChanged: if (!enabled) reset(); else placePointer()

    onPressed: (points) => {
        const now = down()
        const c = centroid(now)
        if (now.length === points.length) {          // the first finger(s) of a touch
            kinetic.halt()
            const p = Qt.point(points[0].x, points[0].y)
            start = last = c
            moved = dragging = scrolling = longPressed = toToolbar = false
            maxFingers = now.length
            downTime = Date.now()
            fromStrip = p.y > height - stripHeight
            tileScreen = tileAt(p)
            region = tileScreen ? "tile" : inert ? "beside" : touchpad || within(picture, p) ? "screen" : "beside"
            if (region !== "screen")
                return
            if (touchpad) {
                transfer.begin(p)
                if (padState === "tapped") {
                    // Touched again soon after a tap: the button stays down; a quick lift makes it a
                    // double click, moving (or holding past the tap timeout) a drag.
                    tapReleased.stop()
                    padState = "dragOrDoubletap"
                    holdToDrag.restart()
                } else {
                    padState = "touch"
                }
            } else {
                longPress.restart()
            }
            return
        }
        // More fingers.
        longPress.stop()
        if (dragging) {   // a second finger ends a direct drag: it is becoming a scroll or a tap
            button(btnLeft, false)
            dragging = false
        }
        maxFingers = Math.max(maxFingers, now.length)
        last = c
        if (touchpad && now.length > 0)
            transfer.begin(Qt.point(now[0].x, now[0].y))
    }

    onUpdated: {
        const now = down()
        if (now.length === 0 || toToolbar)
            return
        const c = centroid(now)
        // A touch from the bottom edge is held back until it shows its way (as the APK's): up, the
        // toolbar; anything else, the gestures, from where it started. A tap there still clicks.
        if (fromStrip && now.length === 1) {
            const up = start.y - c.y, side = Math.abs(c.x - start.x)
            if (up > swipeMm * pxPerMm && up > side) {
                toToolbar = true
                longPress.stop()
                toolbarWanted()
                return
            }
            if (Math.hypot(up, side) <= swipeMm * pxPerMm)
                return
            fromStrip = false
        } else if (fromStrip) {
            fromStrip = false   // a second finger: not the toolbar
        }
        if (!moved && travelled(now)) {
            moved = true
            longPress.stop()
            if (region === "screen" && !touchpad && now.length === 1 && maxFingers === 1 && !longPressed) {
                // A drag starts where the finger went down, not where it crossed the threshold.
                pointTo(start)
                button(btnLeft, true)
                dragging = true
            }
            if (touchpad && padState === "dragOrDoubletap")
                padState = "dragging"
        }
        if (region !== "screen") {
            last = c
            return
        }
        if (now.length >= 2) {
            if (moved) {
                // Natural scrolling at unity: the content follows the fingers.
                scrollBy(-(c.x - last.x) * outputPerPx, -(c.y - last.y) * outputPerPx)
                scrolling = true
                if (!touchpad)
                    pointTo(c)
            }
        } else if (touchpad) {
            if (!scrolling) {
                // From the first sample, as libinput does: the slow end of the curve keeps a tap's
                // jitter to a fraction of a pixel.
                const d = transfer.step(Qt.point(now[0].x, now[0].y))
                moveBy(d.x, d.y)
            }
        } else if (dragging) {
            pointTo(c)
        }
        last = c
    }

    onReleased: {
        const now = down()
        if (now.length > 0) {   // some fingers still down: go on from where they are
            last = centroid(now)
            if (touchpad)
                transfer.begin(Qt.point(now[0].x, now[0].y))
            return
        }
        longPress.stop()
        holdToDrag.stop()
        if (scrolling)
            kinetic.fling()
        const quick = Date.now() - downTime
        if (region === "screen" && touchpad) {
            const tap = !moved && !toToolbar && quick < tapTimeout
            if (padState === "dragOrDoubletap") {          // tap, tap: the first click ends, the second is one
                button(btnLeft, false)
                padState = "idle"
                if (tap && maxFingers === 1)
                    click(btnLeft)
            } else if (padState === "dragging") {
                button(btnLeft, false)
                padState = "idle"
            } else {
                padState = "idle"
                if (tap) {
                    if (maxFingers === 1) {
                        // Press now; release unless a touch follows within the drag timeout.
                        button(btnLeft, true)
                        padState = "tapped"
                        tapReleased.restart()
                    } else {
                        click(tapButton(maxFingers))
                    }
                }
            }
        } else if (region === "screen") {
            if (dragging)
                button(btnLeft, false)
            const tap = !moved && !longPressed && !toToolbar && quick < longPressTimeout
            if (tap) {
                // One finger clicks under it; two or three click between them.
                pointTo(maxFingers === 1 ? start : last)
                click(tapButton(maxFingers))
            }
        } else {
            const tap = !moved && !toToolbar && quick < longPressTimeout
            if (tap && region === "tile" && tileScreen)
                tileTapped(tileScreen)
            else if (tap && region === "beside")
                toolbarToggled()
        }
        dragging = scrolling = false
        region = ""
    }
    onCanceled: reset()
}
