// SPDX-License-Identifier: GPL-2.0-or-later
// Cast to a TV from Plasma (docs/58): moto-cast connects Android's Wi-Fi Display;
// the TV then appears as the session's second screen (CAST-1).

import QtQuick

import org.kde.plasma.plasma5support as P5Support
import org.kde.plasma.private.mobileshell.quicksettingsplugin as QS

QS.QuickSetting {
    id: root

    // A TV connected (moto-cast's status). Not "a second screen": the assistant's screen (docs/65)
    // is one too, with or without a TV.
    property bool casting: false
    readonly property int screens: Qt.application.screens.length
    property string busy: ""          // "connect" or "disconnect" while moto-cast runs
    property bool reconnecting: false // the TV dropped the session; moto-cast-watch is reconnecting
    property string tvName: ""
    property string error: ""

    text: "投屏"
    icon: "video-television"
    enabled: casting || busy === "connect" || reconnecting
    settingsCommand: "plasma-open-settings kcm_kscreen"
    // Short: a tile shows one line.
    status: {
        if (busy === "connect") return "正在连接…";
        if (busy === "disconnect") return "正在断开…";
        if (reconnecting) return "电视断开，正在重连…";
        if (error) return error;
        if (casting) return tvName || "已连接";
        return "未连接";
    }

    function run(command) {
        executable.connectSource("/usr/local/bin/moto-cast " + command);
    }

    function toggle() {
        if (busy) return;
        error = "";
        busy = casting || reconnecting ? "disconnect" : "connect";
        run(busy);
    }

    function apply(result) {
        casting = !!result.active;
        tvName = result.active ? result.active.name.replace(/\[.*\]$/, "") : tvName;
        reconnecting = !!result.reconnecting;
        if (reconnecting) {
            poll.restart();
        } else {
            poll.stop();
        }
    }

    // A screen came or went: learn whether a TV is connected, its name, or whether it is being reconnected.
    onScreensChanged: statusDelay.restart()
    Component.onCompleted: run("status")

    Timer {
        id: statusDelay
        interval: 2000
        onTriggered: if (!root.busy) root.run("status")
    }
    Timer {
        id: poll
        interval: 8000
        onTriggered: if (!root.busy && !root.casting) root.run("status")
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
                result = { error: (data["stderr"] || "moto-cast 没有返回结果").trim() };
            }
            if (command === root.busy) root.busy = "";
            if (result.error) {
                console.warn("moto-cast " + command + ": " + result.error);
                root.error = command === "connect" ? "没有连上电视" : "操作失败";
            } else {
                root.apply(result);
            }
        }
    }
}
