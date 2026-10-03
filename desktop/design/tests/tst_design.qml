// SPDX-License-Identifier: GPL-2.0-or-later
// The design system's C++ halves in their QML (docs/87, docs/102), as an app has them: the real
// com.rungic.design module built from this tree. Run by tools/system/tests/design_system.py with
// qmltestrunner, offscreen, which also turns the system's colours in kdeglobals dark and light
// (with KConfig's change notice) all the while this test runs.
import QtQuick
import QtQuick.Controls as QQC2
import QtTest
import com.rungic.design

Item {
    id: root
    width: 400
    height: 800
    property int clicks: 0              // rows clicked on the second page

    PageStack {
        id: stack
        anchors.fill: parent
        initialItem: Rectangle { objectName: "first"; color: "white" }
    }

    Component {
        id: secondPage
        Rectangle {
            objectName: "second"
            color: "lightgray"
            property alias list: list
            ListView {
                id: list
                anchors.fill: parent
                model: 60
                delegate: QQC2.ItemDelegate {
                    width: ListView.view.width
                    height: 60
                    text: "Row " + index
                    onClicked: root.clicks++
                }
            }
        }
    }

    SignalSpy { id: started; target: stack; signalName: "started" }

    TestCase {
        name: "Design"
        when: windowShown

        function init() {
            while (stack.depth > 1) stack.pop(undefined, QQC2.StackView.Immediate)
            stack.push(secondPage, {}, QQC2.StackView.Immediate)
            tryCompare(stack, "busy", false)
            tryVerify(() => stack.active, 2000, "a page to go back to: the swipe is on")
            started.clear()
            root.clicks = 0
        }
        // A one-finger drag from (x, y) through each point of `path` ([dx, dy] from the start),
        // then lifted there.
        function drag(x, y, path) {
            const touch = touchEvent(stack)
            touch.press(0, stack, x, y).commit()
            for (const [dx, dy] of path) {
                touch.move(0, stack, x + dx, y + dy).commit()
                wait(16)
            }
            const [dx, dy] = path[path.length - 1]
            touch.release(0, stack, x + dx, y + dy).commit()
        }
        function steps(fromX, toX, step, dy) {
            const out = []
            for (let dx = fromX; step > 0 ? dx <= toX : dx >= toX; dx += step) out.push([dx, dy || 0])
            return out
        }

        // covers[system]: desktop.design-system/E4
        // Anywhere on the page (here on a row, a control): the page follows the finger, the page
        // below comes back from the left, and letting go while moving right goes back. The row
        // under the finger is not clicked.
        function test_1_swipe_follows_the_finger_and_goes_back() {
            const page = stack.currentItem
            const touch = touchEvent(stack)
            touch.press(0, stack, 100, 300).commit()
            for (const [dx] of steps(10, 160, 10)) {
                touch.move(0, stack, 100 + dx, 300).commit()
                wait(16)
            }
            compare(started.count, 1, "past the threshold the swipe starts")
            verify(stack.dragging)
            const moved = page.x
            verify(moved > 100 && moved <= 160, "the page follows the finger (" + moved + ")")
            touch.move(0, stack, 300, 300).commit()
            wait(16)
            fuzzyCompare(page.x - moved, 40, 1, "and keeps following it")
            const below = stack.view.get(0, QQC2.StackView.DontLoad)
            verify(below.visible && below.x < 0 && below.x > -stack.width * 0.3, "the page below comes back from the left")
            touch.release(0, stack, 300, 300).commit()
            tryCompare(stack, "depth", 1, 2000, "let go moving right: back to the first page")
            compare(root.clicks, 0, "the row under the finger was not clicked")
        }
        // covers[system]: desktop.design-system/E4
        // Let go while moving left: the page comes back and stays.
        function test_2_let_go_moving_left_stays() {
            const page = stack.currentItem
            drag(100, 300, steps(10, 200, 10).concat(steps(190, 140, -10)))
            compare(started.count, 1)
            tryCompare(page, "x", 0, 2000, "the page settles back")
            wait(400)
            compare(stack.depth, 2, "and stays")
            compare(root.clicks, 0, "the row under the finger was not clicked")
        }
        // covers[system]: desktop.design-system/E4
        // A vertical drag is the page's own scrolling, even when it drifts right later.
        function test_3_vertical_drag_scrolls_the_page() {
            const page = stack.currentItem
            drag(200, 600, steps(-10, -300, -10).map(([d]) => [0, d]).concat([[80, -300], [160, -300]]))
            compare(started.count, 0, "no swipe")
            verify(page.list.contentY > 100, "the list scrolled (" + page.list.contentY + ")")
            wait(400)
            compare(stack.depth, 2)
            compare(page.x, 0)
        }
        // covers[system]: desktop.design-system/E4
        // A tap on a row is still the row's.
        function test_4_tap_is_the_rows() {
            const page = stack.currentItem
            drag(200, 300, [[0, 0]])
            compare(started.count, 0)
            tryCompare(root, "clicks", 1)
            compare(stack.depth, 2)
        }

        // covers[system]: desktop.design-system/E1
        // The system's colours (kdeglobals, changed with KConfig's notice, as System Settings does):
        // SystemTheme follows them while running, and Theme with it unless the app pins a look.
        function test_5_follows_the_systems_colours() {
            let dark = 0, light = 0
            const counter = () => { if (SystemTheme.dark) ++dark; else ++light }
            SystemTheme.darkChanged.connect(counter)
            tryVerify(() => dark >= 1 && light >= 1, 20000, "the system turned dark and light while running")
            SystemTheme.darkChanged.disconnect(counter)
            Theme.mode = "system"
            compare(Theme.dark, SystemTheme.dark)
            tryVerify(() => Theme.dark !== SystemTheme.dark || true)
            Theme.mode = "light"
            const seen = SystemTheme.dark
            tryVerify(() => SystemTheme.dark !== seen, 10000, "the system turns again")
            compare(Theme.dark, false, "pinned light stays light")
            compare(String(Theme.background), "#ffffff")
            Theme.mode = "dark"
            const again = SystemTheme.dark
            tryVerify(() => SystemTheme.dark !== again, 10000, "the system turns again")
            compare(Theme.dark, true, "pinned dark stays dark")
            Theme.mode = "system"
            compare(Theme.dark, SystemTheme.dark, "following again")
        }
    }
}
