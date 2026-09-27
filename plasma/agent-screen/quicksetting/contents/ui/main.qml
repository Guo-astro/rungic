// SPDX-License-Identifier: GPL-2.0-or-later
// The assistant's screen on or off (docs/65): rungic-agent-screen turns the host's second output on
// and opens its floating window; with a TV connected the TV shows it instead.

import QtQuick

import org.kde.plasma.plasma5support as P5Support
import org.kde.plasma.private.mobileshell.quicksettingsplugin as QS
import org.kde.plasma.private.mobileshell.state as MobileShellState

QS.QuickSetting {
    id: root

    property bool on: false
    property bool onTv: false
    property bool fullscreen: false
    property bool busy: false
    property string error: ""

    text: "助理屏"
    icon: "video-display"
    enabled: on
    status: {
        if (busy) return on ? "正在关闭…" : "正在打开…";
        if (error) return error;
        if (!on) return "关闭";
        return onTv ? "在电视上" : fullscreen ? "全屏" : "浮窗";
    }

    function run(command) {
        executable.connectSource("/usr/bin/rungic-agent-screen " + command);
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
                result = { error: (data["stderr"] || "rungic-agent-screen 没有返回结果").trim() };
            }
            if (command === "toggle") root.busy = false;
            if (result.error) {
                console.warn("rungic-agent-screen " + command + ": " + result.error);
                root.error = "操作失败";
                return;
            }
            root.on = !!result.enabled;
            root.onTv = result.shown_on === "tv";
            root.fullscreen = result.shown_on === "phone fullscreen";
        }
    }
}
