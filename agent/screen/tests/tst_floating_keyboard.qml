// FloatingKeyboard on the phone, offscreen (docs/research/97 §19.9): it loads with the phone keyboard's
// layouts and Rime, and pinyin types Chinese. Run in the container as the desktop user, from a
// directory holding this file and a copy of qml/FloatingKeyboard.qml, with a Rime directory and a
// configuration of its own (not the user's dictionary, which a running keyboard may hold):
//   XDG_CONFIG_HOME=$PWD/cfg RUNGIC_RIME_USER_DIR=$PWD/rime QT_QPA_PLATFORM=offscreen \
//   QT_IM_MODULE=qtvirtualkeyboard QT_VIRTUALKEYBOARD_DESKTOP_DISABLE=1 \
//   QT_VIRTUALKEYBOARD_LAYOUT_PATH=/usr/share/rungic-rime/plasma/keyboard/layouts \
//   QML_IMPORT_PATH=/usr/lib/rungic-rime/qml /usr/lib/qt6/bin/qmltestrunner -input tst_floating_keyboard.qml
import QtQuick
import QtTest
import QtQuick.VirtualKeyboard
TestCase {
    name: "kbd"; when: windowShown; width: 2400; height: 1080
    Item { id: stage; width: 2400; height: 1080 }
    property string typed: ""
    TextInput { id: field; width: 1; height: 1
        onTextEdited: { typed += text; text = "" }
        inputMethodHints: Qt.ImhNoAutoUppercase | Qt.ImhNoPredictiveText }
    FloatingKeyboard { id: kb; area: stage; place: "test"; composing: field.preeditText }
    function test_load() {
        field.forceActiveFocus(); Qt.inputMethod.show()
        wait(2500)
        console.log("BOARD", kb.x, kb.y, kb.width, kb.height, "visible", Qt.inputMethod.visible, "locale", Qt.inputMethod.locale.name)
        verify(kb.height > 150)
    }
    function test_pinyin() {
        field.forceActiveFocus(); Qt.inputMethod.show(); wait(500)
        typed = ""
        for (const c of "nihao") InputContext.inputEngine.virtualKeyClick(Qt.Key_A + c.charCodeAt(0) - 97, c, 0)
        wait(300)
        console.log("PREEDIT", field.preeditText, "COMPOSING", kb.composing)
        InputContext.inputEngine.virtualKeyClick(Qt.Key_Space, " ", 0)
        wait(300)
        console.log("TYPED", typed)
        compare(typed, "你好")
    }
}
