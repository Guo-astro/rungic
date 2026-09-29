// SPDX-License-Identifier: GPL-2.0-or-later
// Rungic's design tokens (docs/87): quiet like a chat app. Flat grounds, no cards or
// shadows; Breeze's neutrals only, blue for links and focus. Two looks, dark and light,
// following the system (SystemTheme) unless `mode` says otherwise. Every text colour
// reads at 4.5:1 or better on the grounds it is meant for (WCAG AA).
pragma Singleton
import QtQuick
import com.rungic.design

QtObject {
    id: theme

    // "system" | "light" | "dark": an app's own choice (its settings), else the system's.
    property string mode: "system"
    readonly property bool dark: mode === "dark" || (mode === "system" && SystemTheme.dark)

    // Grounds, from the page outwards.
    readonly property color background: dark ? "#141618" : "#ffffff"     // pages, sheets
    readonly property color side: dark ? "#1b1d20" : "#f7f7f7"           // side panels, keyboard and attach panels
    readonly property color fill: dark ? "#232629" : "#f2f3f4"           // fields, the user's bubbles, list groups
    readonly property color fill2: dark ? "#2e3134" : "#e8e9ea"          // pressed fills, tracks, handles
    readonly property color line: dark ? "#2c2f32" : "#e3e4e5"           // hairlines, outlined buttons

    // Text.
    readonly property color text: dark ? "#fcfcfc" : "#232629"
    readonly property color dim: dark ? "#a1a9b1" : "#5f6b77"            // secondary text, placeholders
    readonly property color faint: dark ? "#7b848c" : "#8a939c"          // decoration only, never text on fills
    // The strong fill (send, talk, primary buttons, a switch on) and what sits on it. Not
    // "onStrong": QML takes a name of "on" and a capital as a signal handler, and that token
    // stayed black (the state gallery caught the black icons on the strong fill).
    readonly property color strong: dark ? "#fcfcfc" : "#232629"
    readonly property color strongInk: dark ? "#141618" : "#ffffff"
    readonly property color link: dark ? "#3daee9" : "#2272a8"
    readonly property color negative: dark ? "#e0606d" : "#bf3445"
    readonly property color positive: dark ? "#3ec57a" : "#1b7a44"
    readonly property color scrim: dark ? Qt.rgba(0, 0, 0, 0.55) : Qt.rgba(0, 0, 0, 0.32)

    // Type (px). Body 16/26; the rest follow the design (docs/87).
    readonly property string fontFamily: Qt.application.font.family
    readonly property string monoFamily: "Noto Sans Mono"
    readonly property int bodySize: 16
    readonly property int bodyLine: 26
    readonly property int titleSize: 16          // top bar title, weight 600
    readonly property int headingSize: 24        // empty-state heading, weight 600
    readonly property int heroSize: 20           // status headings in settings
    readonly property int liveSize: 20           // the live transcript while holding
    readonly property int metaSize: 14           // "已处理 2 步", buttons
    readonly property int labelSize: 13          // group labels, subtitles, notes
    readonly property int footSize: 12           // the hint under the composer

    // Sizes and radii (px).
    readonly property int touch: 44              // the smallest target
    readonly property int topBar: 52
    readonly property int field: 56              // the composer's bar
    readonly property int row: 52                // a settings row
    readonly property int drawerWidth: 320
    readonly property int readingWidth: 680      // a conversation's column on wide screens
    readonly property int radiusField: 28
    readonly property int radiusPill: 22
    readonly property int radiusGroup: 16
    readonly property int radiusInput: 14
    readonly property int radiusItem: 10
    readonly property int radiusSheet: 20
    readonly property int gutter: 20             // page side margin
    readonly property int groupMargin: 16

    // Motion: short and eased out; nothing moves when the system asks for less.
    readonly property int quick: 100
    readonly property int normal: 200
    readonly property int slide: 250
    readonly property var easing: [0.33, 1, 0.68, 1, 1, 1]   // cubic-bezier(0.33, 1, 0.68, 1)

    // A colour at an opacity.
    function alpha(c, a) { return Qt.rgba(c.r, c.g, c.b, a) }
}
