// SPDX-FileCopyrightText: 2022-2025 Devin Lin <devin@kde.org>
// SPDX-License-Identifier: LGPL-2.0-or-later

import QtQuick
import QtQuick.Window

import org.kde.plasma.private.mobileshell.state as MobileShellState
import org.kde.plasma.quicksetting.record
import org.kde.plasma.private.mobileshell.quicksettingsplugin as QS

QS.QuickSetting {
    id: root

    text: RecordUtil.quickSettingText
    status: RecordUtil.quickSettingStatus
    icon: "camera-video-symbolic"
    enabled: RecordUtil.isRecording
    available: true
    settingsCommand: "/usr/bin/moto-recording-settings"

    // Screens to capture, this (the phone's) screen first: one KWin stream and
    // one file per screen, so a cast TV is recorded together with the phone.
    property var captureScreens: []
    property var nodes: ({})
    property bool startRecordingRequest: false

    function captureLabel(name, index) {
        if (name === Screen.name) {
            return "手机";
        }
        return root.captureScreens.length > 2 ? "外屏 " + index : "外屏";
    }

    function stopCapture() {
        root.startRecordingRequest = false;
        startTimer.stop();
        root.captureScreens = [];
        root.nodes = {};
    }

    function tryStart(force) {
        if (!root.startRecordingRequest) {
            return;
        }
        const screens = [];
        for (let i = 0; i < root.captureScreens.length; i++) {
            const name = root.captureScreens[i];
            const node = root.nodes[name] || 0;
            if (node > 0) {
                screens.push({ node: node, label: captureLabel(name, i) });
            } else if (!force || i === 0) {
                // Wait for every stream; after the timeout the phone's is still required.
                return;
            }
        }
        root.startRecordingRequest = false;
        startTimer.stop();
        if (RecordUtil.startRecordingScreens(screens)) {
            MobileShellState.ShellDBusClient.closeActionDrawer();
        } else {
            stopCapture();
        }
    }

    Connections {
        target: RecordUtil
        function onIsRecordingChanged() {
            if (!RecordUtil.isRecording) root.stopCapture();
        }
    }

    function toggle() {
        if (RecordUtil.isRecording) {
            RecordUtil.stopRecording();
        } else {
            const names = [Screen.name];
            const screens = Qt.application.screens;
            for (let i = 0; i < screens.length; i++) {
                if (screens[i].name !== Screen.name) {
                    names.push(screens[i].name);
                }
            }
            root.nodes = {};
            root.startRecordingRequest = true;
            root.captureScreens = names;
            startTimer.restart();
        }
    }

    // Start with the streams that exist if a screen does not deliver one.
    Timer {
        id: startTimer
        interval: 3000
        onTriggered: root.tryStart(true)
    }

    Instantiator {
        model: root.captureScreens
        // External screens are recorded with the pointer drawn in (the phone
        // has none in touch mode); TaskManager.ScreencastingRequest always hides it.
        delegate: ScreenStreamRequest {
            required property string modelData
            outputName: modelData
            embedCursor: modelData !== root.captureScreens[0]
            onNodeIdChanged: {
                if (nodeId > 0) {
                    const nodes = root.nodes;
                    nodes[modelData] = nodeId;
                    root.nodes = nodes;
                    root.tryStart(false);
                }
            }
        }
    }
}
