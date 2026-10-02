// SPDX-License-Identifier: GPL-3.0-or-later
// Test stand-in for plasma-keyboard 6.6.6's zh_CN/symbols.qml (see main.qml).
import QtQuick
import QtQuick.Layouts
import QtQuick.VirtualKeyboard
import QtQuick.VirtualKeyboard.Components

KeyboardLayout {
    function createInputMethod() {
        return Qt.createQmlObject('import QtQuick; import QtQuick.VirtualKeyboard.Plugins; PinyinInputMethod {}', parent, "inputMethodSymbols.qml")
    }
    sharedLayouts: ['main']
    KeyboardRow {
        Key { key: Qt.Key_1; text: "1" }
        Key { key: Qt.Key_Comma; text: "," }
        BackspaceKey {}
        SymbolModeKey {}
    }
}
