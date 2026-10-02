// SPDX-License-Identifier: GPL-3.0-or-later
// Test stand-in for plasma-keyboard 6.6.6's zh_CN/main.qml: the same input-method line and
// sharedLayouts, which layouts.py rewrites; one row of keys.
import QtQuick
import QtQuick.Layouts
import QtQuick.VirtualKeyboard
import QtQuick.VirtualKeyboard.Components

KeyboardLayout {
    function createInputMethod() {
        return Qt.createQmlObject('import QtQuick; import QtQuick.VirtualKeyboard.Plugins; PinyinInputMethod {}', parent, "inputMethod.qml")
    }
    sharedLayouts: ['symbols']
    KeyboardRow {
        Key { key: Qt.Key_N; text: "n" }
        Key { key: Qt.Key_I; text: "i" }
        BackspaceKey {}
        SymbolModeKey {}
    }
}
