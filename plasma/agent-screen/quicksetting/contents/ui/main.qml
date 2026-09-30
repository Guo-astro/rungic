// SPDX-License-Identifier: GPL-2.0-or-later
// Desktop mode on or off (docs/65, docs/research/91): rungic-desktop-mode gives the user's desktop
// a second output, a full desktop, and opens its floating window; a TV or fullscreen may show it
// instead. The assistant's screen has no tile: it shows itself when the agent works there.

import QtQuick

import org.kde.plasma.plasma5support as P5Support
import org.kde.plasma.private.mobileshell.quicksettingsplugin as QS
import org.kde.plasma.private.mobileshell.state as MobileShellState

QS.QuickSetting {
    id: root

    readonly property string program: "rungic-desktop-mode"

    property bool on: false
    property bool onTv: false
    property bool fullscreen: false
    property bool busy: false
    property string error: ""

    text: i18nc("@title quick setting", "Desktop Mode")
    icon: "computer"
    enabled: on
    status: {
        if (busy) return on ? i18nc("@info:status", "Turning off…") : i18nc("@info:status", "Turning on…");
        if (error) return error;
        if (!on) return i18nc("@info:status desktop mode is off", "Off");
        return onTv ? i18nc("@info:status shown on the TV", "On the TV") : fullscreen ? i18nc("@info:status", "Full screen") : i18nc("@info:status shown in a floating window", "Floating window");
    }

    function run(command) {
        executable.connectSource("/usr/bin/" + program + " " + command);
    }

    function toggle() {
        if (busy) return;
        error = "";
        busy = true;
        run("toggle");
    }

    Component.onCompleted: run("ensure")
    // The screen is also turned on by the assistant and off from its window, and its output comes
    // and goes with it: ask then, often only while the control centre shows the tile, and while the
    // screen is on now and then to bring its floating window back if it went away. Every 4 s at all
    // times it started a Python process for nothing (docs/49).
    readonly property int screens: Qt.application.screens.length
    readonly property bool shown: MobileShellState.ShellDBusClient.isActionDrawerOpen
    onScreensChanged: if (!busy) run("ensure")
    onShownChanged: if (shown && !busy) run("ensure")
    Timer {
        interval: root.shown ? 2000 : 15000
        repeat: true
        running: root.shown || root.on
        onTriggered: if (!root.busy) root.run("ensure")
    }

    P5Support.DataSource {
        id: executable
        engine: "executable"
        onNewData: (source, data) => {
            disconnectSource(source);
            const command = source.split(" ")[1];
            let result = {};
            try {
                result = JSON.parse(data["stdout"]);
            } catch (e) {
                result = { error: (data["stderr"] || root.program + " returned no result").trim() };
            }
            if (command === "toggle") root.busy = false;
            if (result.error) {
                console.warn(root.program + " " + command + ": " + result.error);
                root.error = i18nc("@info:status", "Something went wrong");
                return;
            }
            root.on = !!result.enabled;
            root.onTv = result.shown_on === "tv";
            root.fullscreen = result.shown_on === "phone fullscreen";
        }
    }
}
