// SPDX-License-Identifier: GPL-2.0-or-later
// The assistant's screen on or off (docs/65): moto-agent-screen turns the host's second output on
// and opens its floating window; with a TV connected the TV shows it instead.

import QtQuick

import org.kde.plasma.plasma5support as P5Support
import org.kde.plasma.private.mobileshell.quicksettingsplugin as QS

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
        executable.connectSource("/usr/bin/moto-agent-screen " + command);
    }

    function toggle() {
        if (busy) return;
        error = "";
        busy = true;
        run("toggle");
    }

    Component.onCompleted: run("ensure")
    // The screen is also turned on by the assistant and off from its window: keep the tile current,
    // and bring its floating window back if it went away while the screen stayed on.
    Timer {
        interval: 4000
        repeat: true
        running: true
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
                result = { error: (data["stderr"] || "moto-agent-screen 没有返回结果").trim() };
            }
            if (command === "toggle") root.busy = false;
            if (result.error) {
                console.warn("moto-agent-screen " + command + ": " + result.error);
                root.error = "操作失败";
                return;
            }
            root.on = !!result.enabled;
            root.onTv = result.shown_on === "tv";
            root.fullscreen = result.shown_on === "phone fullscreen";
        }
    }
}
