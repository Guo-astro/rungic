// SPDX-License-Identifier: GPL-2.0-or-later
// Cast to a TV from Plasma (docs/58): rungic-cast connects Android's Wi-Fi Display;
// the TV then appears as the session's second screen (CAST-1). A tap opens the TV
// picker (CastPicker): choose a TV, or while casting see it, switch or disconnect.

import QtQuick

import org.kde.plasma.plasma5support as P5Support
import org.kde.plasma.private.mobileshell.state as MobileShellState
import org.kde.plasma.private.mobileshell.quicksettingsplugin as QS

QS.QuickSetting {
    id: root

    // A TV connected (rungic-cast's status). Not "a second screen": the assistant's screen (docs/65)
    // is one too, with or without a TV.
    property bool casting: false
    readonly property int screens: Qt.application.screens.length
    property bool reconnecting: false // the TV dropped the session; rungic-cast-watch is reconnecting
    property string tvName: ""
    property string error: ""
    property int requestSerial: 0
    property var callbacks: ({})

    text: "投屏"
    icon: "video-television"
    enabled: casting || reconnecting || picker.connectingTo !== ""
    settingsCommand: "rungic-cast settings"
    // Short: a tile shows one line.
    status: {
        if (picker.connectingTo) return "正在连接…";
        if (reconnecting) return "电视断开，正在重连…";
        if (error) return error;
        if (casting) return tvName || "已连接";
        return "点按选择电视";
    }

    // Runs rungic-cast; the callback gets its JSON (or {error}). Status results also update the tile.
    function run(command, callback) {
        const serial = ++requestSerial;
        if (callback) callbacks[serial] = callback;
        executable.connectSource("/usr/bin/rungic-cast " + command + " # " + serial);
    }

    function toggle() {
        MobileShellState.ShellDBusClient.closeActionDrawer();
        error = "";
        picker.casting = casting;
        picker.reconnecting = reconnecting;
        picker.open();
    }

    function apply(result) {
        casting = result.active_state === 2;
        tvName = result.active ? result.active.name.replace(/\s*\[.*\]$/, "") : tvName;
        reconnecting = !!result.reconnecting;
        picker.casting = casting;
        picker.reconnecting = reconnecting;
        if (reconnecting) {
            poll.restart();
        } else {
            poll.stop();
        }
    }

    CastPicker {
        id: picker
        tvName: root.tvName
        runner: root.run
        onVisibleChanged: if (!visible) root.run("status")
    }

    // A screen came or went: learn whether a TV is connected, its name, or whether it is being reconnected.
    onScreensChanged: statusDelay.restart()
    Component.onCompleted: run("status")

    Timer {
        id: statusDelay
        interval: 2000
        onTriggered: root.run("status")
    }
    Timer {
        id: poll
        interval: 8000
        onTriggered: if (!root.casting) root.run("status")
    }

    P5Support.DataSource {
        id: executable
        engine: "executable"
        onNewData: (source, data) => {
            disconnectSource(source);
            const serial = Number(source.split(" # ")[1]);
            const callback = root.callbacks[serial];
            delete root.callbacks[serial];
            let result = {};
            try {
                result = JSON.parse(data["stdout"]);
            } catch (e) {
                result = { error: (data["stderr"] || "rungic-cast 没有返回结果").trim() };
            }
            if (result.error) {
                console.warn("rungic-cast: " + result.error);
                if (result.code === "component-missing") root.error = "投屏组件未就绪";
                else if (result.code === "unsupported") root.error = "系统不支持无线投屏";
            } else if (result.active_state !== undefined) {
                root.apply(result);
            }
            if (callback) callback(result);
        }
    }
}
