// SPDX-License-Identifier: GPL-2.0-or-later
// The assistant's look (docs/59, docs/67), dark or light as the system is (SystemTheme).
// Every text colour here reads at 4.5:1 or better on the grounds it is used on (WCAG AA;
// the pairs were computed for both looks, docs/59).
pragma Singleton
import QtQuick
import com.rungic.voiceassistant

QtObject {
    readonly property bool dark: SystemTheme.dark

    // Grounds.
    readonly property color ground: dark ? "#0A0B10" : "#F6F4F0"
    readonly property color surface: dark ? Qt.rgba(1, 1, 1, 0.045) : Qt.rgba(0, 0, 0, 0.035)   // cards
    readonly property color glass: dark ? Qt.rgba(1, 1, 1, 0.10) : Qt.rgba(0, 0, 0, 0.065)     // the user's bubbles, buttons
    readonly property color glassPressed: dark ? Qt.rgba(1, 1, 1, 0.20) : Qt.rgba(0, 0, 0, 0.13)
    readonly property color glassBorder: dark ? Qt.rgba(1, 1, 1, 0.12) : Qt.rgba(0, 0, 0, 0.08)
    readonly property color pressed: dark ? Qt.rgba(1, 1, 1, 0.05) : Qt.rgba(0, 0, 0, 0.05)    // a row held down
    readonly property color line: dark ? Qt.rgba(1, 1, 1, 0.08) : Qt.rgba(0, 0, 0, 0.09)
    readonly property color code: dark ? Qt.rgba(0, 0, 0, 0.35) : Qt.rgba(0, 0, 0, 0.055)
    readonly property color track: dark ? Qt.rgba(1, 1, 1, 0.18) : Qt.rgba(0, 0, 0, 0.15)      // the spinner's ring

    // Text, strongest first. `faint` is for small labels on the app's own grounds only.
    readonly property color ink: dark ? "#F4F1EA" : "#1B1A1F"
    readonly property color inkSoft: dark ? Qt.rgba(1, 1, 1, 0.84) : Qt.rgba(0, 0, 0, 0.80)
    readonly property color dim: dark ? Qt.rgba(1, 1, 1, 0.66) : Qt.rgba(0, 0, 0, 0.64)
    readonly property color faint: dark ? Qt.rgba(1, 1, 1, 0.54) : Qt.rgba(0, 0, 0, 0.56)
    readonly property color codeInk: dark ? Qt.rgba(1, 1, 1, 0.78) : Qt.rgba(0, 0, 0, 0.78)

    // The light's gold: text and strokes; a faint fill and an edge for what is live.
    readonly property color accent: dark ? "#F0C27E" : "#8A5A12"
    readonly property color accentFill: dark ? Qt.rgba(0.94, 0.76, 0.49, 0.10) : Qt.rgba(0.54, 0.35, 0.07, 0.08)
    readonly property color accentBorder: dark ? Qt.rgba(0.94, 0.76, 0.49, 0.35) : Qt.rgba(0.54, 0.35, 0.07, 0.35)
    readonly property color danger: "#B3392F"           // white text on it: 5.9:1
    readonly property color error: dark ? "#FF8A80" : "#B3261E"

    // The Home overlay: what darkens (or lightens) the screen behind, top to bottom, and
    // its glass panel. Strong enough that `dim` text reads over white or black content.
    readonly property color scrim: dark ? Qt.rgba(0.016, 0.02, 0.035, 1) : Qt.rgba(0.965, 0.957, 0.94, 1)
    readonly property real scrimTop: dark ? 0.74 : 0.78
    readonly property real scrimMiddle: dark ? 0.80 : 0.84
    readonly property real scrimBottom: dark ? 0.88 : 0.90
    readonly property color panel: dark ? Qt.rgba(0.11, 0.12, 0.16, 0.62) : Qt.rgba(1, 1, 1, 0.74)

    readonly property real readingWidth: 680                 // a conversation's column on wide screens

    // The ground (fades over lists) and the overlay's scrim at a given opacity.
    function fade(alpha) { return Qt.rgba(ground.r, ground.g, ground.b, alpha) }
    function veil(alpha) { return Qt.rgba(scrim.r, scrim.g, scrim.b, alpha) }

    // A command without the shell wrapper Codex adds.
    function command(text) {
        return text.replace(/^\/bin\/(?:ba)?sh -lc '([\s\S]*)'$/, "$1")
    }
}
