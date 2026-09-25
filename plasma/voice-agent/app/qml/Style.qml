// SPDX-License-Identifier: GPL-2.0-or-later
// The assistant's look (docs/59, docs/67): always dark, warm light on a cool ground.
pragma Singleton
import QtQuick

QtObject {
    readonly property color ground: "#0A0B10"
    readonly property color groundLow: "#12142A"      // where the light comes from, at the bottom
    readonly property color ink: "#F4F1EA"
    readonly property color dim: Qt.rgba(1, 1, 1, 0.64)
    readonly property color faint: Qt.rgba(1, 1, 1, 0.46)
    readonly property color glass: Qt.rgba(1, 1, 1, 0.10)    // the user's bubbles, buttons
    readonly property color surface: Qt.rgba(1, 1, 1, 0.045) // cards
    readonly property color line: Qt.rgba(1, 1, 1, 0.08)
    readonly property color code: Qt.rgba(0, 0, 0, 0.35)
    readonly property color gold: "#F0C27E"
    readonly property color danger: "#B3392F"
    readonly property real readingWidth: 680                 // a conversation's column on wide screens

    // A command without the shell wrapper Codex adds.
    function command(text) {
        return text.replace(/^\/bin\/(?:ba)?sh -lc '([\s\S]*)'$/, "$1")
    }
}
