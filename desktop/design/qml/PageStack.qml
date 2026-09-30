// SPDX-License-Identifier: GPL-2.0-or-later
// A stack of pages that slide over from the right, with the swipe back (docs/102). A drag to the
// right anywhere on a page other than the first follows the finger: the page moves with it and the
// one below comes back from the left, as Kirigami's page row does it. Let go while moving right
// and the page goes; moving left, it comes back. A vertical drag is the page's own scrolling
// (PageSwipe). StandardKey.Back (Alt+Left, which Android's right-edge back sends, docs/46) and
// the Back key go back too.
// Pages reach it as QQC2.StackView.view (push, pop), as with a plain StackView.
import QtQuick
import QtQuick.Controls as QQC2
import com.rungic.design

PageSwipe {
    id: root
    property alias initialItem: view.initialItem
    readonly property alias depth: view.depth
    readonly property alias currentItem: view.currentItem
    readonly property alias busy: view.busy
    readonly property alias view: view
    // Off for a page that uses horizontal drags itself.
    property bool swipeBack: true
    function push(item, properties, operation) { return view.push(item, properties || {}, operation === undefined ? QQC2.StackView.PushTransition : operation) }
    function pop(item, operation) { return view.pop(item === undefined ? undefined : item, operation === undefined ? QQC2.StackView.PopTransition : operation) }
    function back() { if (view.depth > 1) view.pop() }

    active: swipeBack && view.depth > 1 && !view.busy && !settle.running

    // The page going and the one it goes back to, while a swipe runs.
    property Item going: null
    property Item below: null
    readonly property real parallax: 0.3            // how far left the page below waits (the pop transition's)

    onStarted: {
        going = view.currentItem
        below = view.get(view.depth - 2, QQC2.StackView.DontLoad)
        if (below) {
            below.visible = true
            below.x = -view.width * parallax
        }
    }
    onMoved: distance => place(distance)
    onReleased: (distance, forward) => finish(forward && distance > 0)
    onCancelled: finish(false)

    function place(distance) {
        if (going) going.x = distance
        if (below) below.x = -view.width * parallax * (1 - Math.min(1, distance / view.width))
    }
    function finish(backward) {
        settle.backward = backward
        settle.from = going ? going.x : 0
        settle.to = backward ? view.width : 0
        settle.restart()
    }
    NumberAnimation {
        id: settle
        property bool backward: false
        target: root
        property: "progress"
        duration: Theme.slide
        easing.type: Easing.Bezier
        easing.bezierCurve: Theme.easing
        onStopped: {
            const went = root.going, stayed = root.below
            root.going = null
            root.below = null
            if (backward) {
                if (went) went.x = 0
                if (stayed) stayed.x = 0
                view.pop(QQC2.StackView.Immediate)
            } else {
                if (went) went.x = 0
                if (stayed) { stayed.x = 0; stayed.visible = false }
            }
        }
    }
    // What settle animates: the page's x, and the page below with it.
    property real progress: 0
    onProgressChanged: if (settle.running) place(progress)

    QQC2.StackView {
        id: view
        anchors.fill: parent
        pushEnter: Transition { XAnimator { from: view.width; to: 0; duration: Theme.slide; easing.type: Easing.Bezier; easing.bezierCurve: Theme.easing } }
        pushExit: Transition { XAnimator { from: 0; to: -view.width * root.parallax; duration: Theme.slide; easing.type: Easing.Bezier; easing.bezierCurve: Theme.easing } }
        popEnter: Transition { XAnimator { from: -view.width * root.parallax; to: 0; duration: Theme.slide; easing.type: Easing.Bezier; easing.bezierCurve: Theme.easing } }
        popExit: Transition { XAnimator { from: 0; to: view.width; duration: Theme.slide; easing.type: Easing.Bezier; easing.bezierCurve: Theme.easing } }
    }

    Shortcut {
        sequences: [StandardKey.Back, "Back"]
        enabled: view.depth > 1
        onActivated: root.back()
    }
}
