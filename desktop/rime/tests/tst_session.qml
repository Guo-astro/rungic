// SPDX-License-Identifier: GPL-3.0-or-later
// The Rime session inside Qt Virtual Keyboard (docs/41, 2026-10-03): none until a key needs
// Rime; closed when the panel hides, focus leaves or the keys stop, never during a composition.
// Run by run.sh: offscreen, QT_IM_MODULE=qtvirtualkeyboard, the layouts from layouts.py.
import QtQuick
import QtTest
import QtQuick.VirtualKeyboard
import QtQuick.VirtualKeyboard.Settings

Item {
    width: 720
    height: 1280

    TextInput { id: field; width: parent.width; height: 50 }
    TextInput { id: number; y: 60; width: parent.width; height: 50; inputMethodHints: Qt.ImhPreferNumbers }
    Rectangle { id: elsewhere; y: 120; width: 50; height: 50; focus: false }
    InputPanel { id: panel; y: parent.height - height; width: parent.width }

    TestCase {
        name: "RimeSession"
        when: windowShown

        function im() { return InputContext.inputEngine.inputMethod }
        function isRime() { return !!im() && im().sessionOpen !== undefined }
        function type(text) {
            for (const c of text)
                InputContext.inputEngine.virtualKeyClick(c.toUpperCase().charCodeAt(0), c, 0)
        }
        function show(item) {
            item.forceActiveFocus()
            Qt.inputMethod.show()
            tryVerify(() => Qt.inputMethod.visible, 5000, "the panel shows")
            tryVerify(isRime, 5000, "the Rime input method is active")
            tryCompare(InputContext.inputEngine, "inputMode", InputEngine.InputMode.Pinyin)
        }
        function commitFirst() {
            const model = InputContext.inputEngine.wordCandidateListModel
            tryVerify(() => model.count > 0, 2000, "candidates")
            model.selectItem(0)
        }
        function closed() { return !im().sessionOpen }

        function initTestCase() {
            VirtualKeyboardSettings.activeLocales = ["zh_CN"]
            VirtualKeyboardSettings.locale = "zh_CN"
        }
        function init() {
            field.text = ""
            number.text = ""
        }

        // Runs first: the symbols page is the first page, and it must create Rime (layouts.py).
        function test_1_symbols_page_first() {
            show(number)
            verify(panel.keyboard.symbolMode, "a number field opens the symbols page")
            compare(im().sessionOpen, false, "showing the keyboard opens no session")
            type(",")
            tryCompare(number, "text", "，")
            verify(im().sessionShared, "the session uses the user dictionary")
            Qt.inputMethod.hide()
            tryVerify(closed, 2000, "hiding the keyboard closes the session")
        }
        function test_2_typing_then_hide() {
            show(field)
            compare(im().sessionOpen, false, "showing the keyboard opens no session")
            InputContext.inputEngine.virtualKeyClick(Qt.Key_Backspace, "", 0)
            compare(im().sessionOpen, false, "an editing key outside a composition opens none")
            type("nihao")
            verify(im().sessionOpen && im().sessionShared, "the first letter opens a shared session")
            commitFirst()
            tryCompare(field, "text", "你好")
            Qt.inputMethod.hide()
            tryVerify(closed, 2000, "hiding the keyboard closes the session")
            show(field)
            type("zhongguo")
            commitFirst()
            tryCompare(field, "text", "你好中国")
        }
        function test_3_composition_survives_hide() {
            show(field)
            type("zhong")
            Qt.inputMethod.hide()
            wait(300)
            verify(im().sessionOpen, "a composition keeps the session while hidden")
            im().idleInterval = 100
            Qt.inputMethod.reset()
            tryVerify(closed, 2000, "after the reset the session closes")
            compare(field.text, "")
            im().idleInterval = 5000
        }
        function test_4_idle_closes_while_visible() {
            show(field)
            im().idleInterval = 200
            type("hao")
            wait(500)
            verify(im().sessionOpen, "a composition outlasts the idle time")
            commitFirst()
            tryCompare(field, "text", "好")
            tryVerify(closed, 2000, "the idle time closes the session")
            verify(Qt.inputMethod.visible, "while the keyboard stays shown")
            type("hao")
            verify(im().sessionOpen, "the next key opens it again")
            commitFirst()
            tryCompare(field, "text", "好好")
            im().idleInterval = 5000
        }
        function test_5_focus_loss() {
            show(field)
            type("ni")
            commitFirst()
            tryCompare(field, "text", "你")
            elsewhere.forceActiveFocus()
            tryVerify(() => !Qt.inputMethod.visible, 2000, "no input item: the panel hides")
            tryVerify(closed, 2000, "and the session closes")
        }
    }
}
