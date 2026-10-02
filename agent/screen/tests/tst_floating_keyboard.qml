// FloatingKeyboard on the phone, offscreen (docs/research/97 §19.9): it loads with the phone keyboard's
// layouts and Rime, and pinyin types Chinese. Run in the container as the desktop user, from a
// directory holding this file, a copy of qml/FloatingKeyboard.qml and of vkb/ (the style, under
// $PWD/imports/QtQuick/VirtualKeyboard/Styles/rungic/), with a Rime directory and a configuration
// of its own (not the user's dictionary). (Pictures taken offscreen came out empty or stale after
// typing, though the window on the phone draws them: look at the window itself for design.)
//   XDG_CONFIG_HOME=$PWD/cfg RUNGIC_RIME_USER_DIR=$PWD/rime QT_QPA_PLATFORM=offscreen \
//   QT_IM_MODULE=qtvirtualkeyboard QT_VIRTUALKEYBOARD_DESKTOP_DISABLE=1 \
//   QT_VIRTUALKEYBOARD_LAYOUT_PATH=/usr/share/rungic-rime/plasma/keyboard/layouts \
//   QML_IMPORT_PATH=/usr/lib/rungic-rime/qml:$PWD/imports /usr/lib/qt6/bin/qmltestrunner -input tst_floating_keyboard.qml
import QtQuick
import QtTest
import QtQuick.VirtualKeyboard

// The phone in landscape: 800x360 logical pixels.
TestCase {
    name: "kbd"; when: windowShown; width: 800; height: 360
    Rectangle {
        id: stage; width: 800; height: 360; color: "#3a4a5a"
        FloatingKeyboard { id: kb; area: stage; place: "test"; composing: field.preeditText }
    }
    property string typed: ""
    TextInput { id: field; width: 1; height: 1
        onTextEdited: { typed += text; text = "" }
        inputMethodHints: Qt.ImhNoAutoUppercase | Qt.ImhNoPredictiveText }
    function click(c) { InputContext.inputEngine.virtualKeyClick(Qt.Key_A + c.charCodeAt(0) - 97, c, 0) }
    function init() { field.forceActiveFocus(); Qt.inputMethod.show() }
    function test_1_load() {
        wait(1500)
        console.log("BOARD", kb.x, kb.y, kb.width, kb.height, "locale", Qt.inputMethod.locale.name, "state", kb.barState)
        compare(kb.barState, "keys")
        verify(kb.height > 150 && kb.height < 300)
        verify(kb.y + kb.height <= 360)
    }
    function test_2_pinyin() {
        typed = ""
        for (const c of "nihao") click(c)
        wait(300)
        compare(kb.barState, "composing")
        verify(kb.candidateCount > 1)
        kb.expanded = true
        compare(kb.barState, "expanded")
        kb.choose(0)
        wait(300)
        compare(typed, "你好")
        compare(kb.barState, "keys")
    }
}
