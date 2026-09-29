// SPDX-License-Identifier: GPL-2.0-or-later
// "投屏到": the TV picker the cast tile opens on the phone screen (docs/58). Scans while
// open, merges each TV's Wi-Fi Display entries (rungic-cast "receivers") and connects the
// TV tapped. While casting it shows the TV in use, the TVs seen lately (Android cannot
// scan during a session) and disconnects; tapping another TV switches to it.

import QtQuick
import QtQuick.Controls as QQC2
import QtQuick.Layouts
import QtQuick.Window

import org.kde.kirigami as Kirigami
import org.kde.layershell 1.0 as LayerShell

Window {
    id: picker

    // Set by the tile.
    property bool casting: false
    property bool reconnecting: false
    property string tvName: ""
    // The tile's rungic-cast runner: run(command, callback(result)).
    property var runner

    // Receivers by name, as rungic-cast reports them; "found" marks those this picker's scans saw.
    property var receivers: []
    property bool scanning: false
    property int scanRounds: 0
    property string connectingTo: ""
    property string error: ""
    property int generation: 0
    property string connectionPhase: ""
    property int elapsedSeconds: 0
    readonly property int maxRounds: 5

    // The phone's own screen: TVs and the assistant's screen are CAST-n outputs.
    screen: {
        const screens = Qt.application.screens;
        for (let i = 0; i < screens.length; i++) {
            if (!screens[i].name.startsWith("CAST-")) return screens[i];
        }
        return screens[0];
    }
    width: screen ? screen.width : 360
    height: screen ? screen.height : 800
    visible: false
    color: "transparent"
    title: "投屏到"

    LayerShell.Window.scope: "rungic-cast-picker"
    LayerShell.Window.anchors: LayerShell.Window.AnchorTop | LayerShell.Window.AnchorBottom
                               | LayerShell.Window.AnchorLeft | LayerShell.Window.AnchorRight
    LayerShell.Window.layer: LayerShell.Window.LayerOverlay
    LayerShell.Window.exclusionZone: -1
    LayerShell.Window.keyboardInteractivity: LayerShell.Window.KeyboardInteractivityOnDemand

    function open() {
        error = "";
        // Preserve an in-flight request when the sheet is reopened.
        receivers = [];
        visible = true;
        runner("status", merge);
        if (!casting && !reconnecting && !connectingTo) rescan();
    }

    function close() {
        visible = false;
        scanning = false;
        scanRounds = 0;
    }

    function rescan() {
        error = "";
        scanRounds = 0;
        scanning = true;
        for (const r of receivers) r.found = false;
        receivers = receivers.slice();
        scanOnce();
    }

    function scanOnce() {
        if (!visible || !scanning || connectingTo) return;
        runner("scan 6", result => {
            if (!visible) return;
            merge(result, true);
            scanRounds++;
            // Keep looking a while even after a TV shows: a second TV may take longer.
            if (result.error || scanRounds >= maxRounds) scanning = false;
            else scanOnce();
        });
    }

    // Merge a rungic-cast result into the list; a scan's available receivers become "found".
    function merge(result, fromScan) {
        if (result.error) {
            if (result.code === "wifi-unavailable") error = "请先开启 Wi-Fi";
            else if (result.code === "component-missing") error = "投屏组件未就绪";
            else error = "搜索失败，可在 Android 投屏设置中查看";
            return;
        }
        if (result.connection) { connectionPhase = result.connection.phase; elapsedSeconds = result.connection.elapsed_seconds; }
        if (!result.receivers) return;
        const previous = {};
        for (const r of receivers) previous[r.name] = r;
        const next = [];
        for (const r of result.receivers) {
            const old = previous[r.name];
            const found = (fromScan && r.available) || (old ? old.found : false);
            next.push({
                name: r.name, address: r.address, active: r.active, last: r.last,
                busy: fromScan && r.available && !r.can_connect ? true : (old ? old.busy && !(fromScan && r.can_connect) : false),
                found: found,
                recent: r.seen_ms_ago !== null && r.seen_ms_ago !== undefined
            });
            delete previous[r.name];
        }
        for (const name in previous) next.push(previous[name]);
        receivers = next;
    }

    function connectTo(receiver) {
        if (connectingTo || receiver.active) return;
        scanning = false;
        error = "";
        connectingTo = receiver.name;
        cancelled = false; connectionPhase = "waiting-receiver"; elapsedSeconds = 0;
        const request = ++generation;
        runner("connect '" + receiver.name.replace(/'/g, "'\\''") + "'", result => {
            if (request !== generation) return;
            const name = connectingTo;
            connectingTo = "";
            if (result.error) {
                // A cancel (disconnect) ends the connect with an error too: say nothing then.
                if (result.code !== "cancelled" && visible && !cancelled) {
                    error = result.code === "timeout"
                        ? "没有连上“" + name + "”，接收端未能完成网络连接和协商，请重试"
                        : "连接“" + name + "”失败";
                }
                cancelled = false;
                return;
            }
            close();
        });
    }

    property bool cancelled: false
    function cancelConnect() {
        cancelled = true; generation++;
        connectingTo = "";
        runner("disconnect", merge);
    }

    function disconnect() {
        generation++; connectingTo = "";
        runner("disconnect", () => {});
        close();
    }

    readonly property var lastUsed: receivers.filter(r => r.last && !r.active)
    readonly property var current: receivers.filter(r => r.active)
    // Nearby: found by this picker's scans; while casting, those seen lately.
    readonly property var others: receivers.filter(r => !r.last && !r.active && (r.found || ((casting || reconnecting) && r.recent)))
    readonly property bool nothingFound: !scanning && !connectingTo && !casting && !reconnecting
                                         && receivers.filter(r => r.found).length === 0

    readonly property string statusLine: {
        if (connectingTo) return (connectionPhase === "negotiating" ? "正在协商" : "等待接收端联网") + " · " + elapsedSeconds + " 秒";
        if (reconnecting) return "电视断开，正在重连…";
        if (casting) return "正在投屏到 " + (current.length ? current[0].name : tvName);
        if (scanning) return "正在搜索附近的电视…";
        if (nothingFound) return "附近没有找到电视";
        return "搜索已结束";
    }

    Timer {
        interval: 2000; repeat: true
        running: picker.visible && (!!picker.connectingTo)
        onTriggered: picker.runner("status", picker.merge)
    }

    // Background shaded toward the text colour: fills that stay visible in light and dark schemes.
    function tint(amount) {
        return Kirigami.ColorUtils.linearInterpolation(Kirigami.Theme.backgroundColor, Kirigami.Theme.textColor, amount);
    }

    Kirigami.Theme.colorSet: Kirigami.Theme.View
    Kirigami.Theme.inherit: false

    // Dimmed desktop; a tap outside the sheet closes it.
    Rectangle {
        anchors.fill: parent
        color: Qt.rgba(0, 0, 0, 0.55)
        MouseArea {
            anchors.fill: parent
            onClicked: picker.close()
        }
    }

    Rectangle {
        id: sheet
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        height: Math.min(column.implicitHeight + Kirigami.Units.gridUnit * 1.5, parent.height * 0.85)
        radius: Kirigami.Units.gridUnit * 1.5
        color: Kirigami.Theme.backgroundColor
        // Square bottom corners.
        Rectangle {
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.bottom: parent.bottom
            height: parent.radius
            color: parent.color
        }
        MouseArea { anchors.fill: parent } // taps on the sheet stay in it

        Flickable {
            anchors.fill: parent
            contentHeight: column.implicitHeight
            clip: true
            boundsBehavior: Flickable.StopAtBounds

            ColumnLayout {
                id: column
                width: parent.width
                spacing: 0

                Rectangle {
                    Layout.alignment: Qt.AlignHCenter
                    Layout.topMargin: Kirigami.Units.smallSpacing * 2
                    Layout.preferredWidth: Kirigami.Units.gridUnit * 2.25
                    Layout.preferredHeight: 4
                    radius: 2
                    color: Kirigami.ColorUtils.linearInterpolation(Kirigami.Theme.backgroundColor, Kirigami.Theme.textColor, 0.25)
                }

                RowLayout {
                    Layout.fillWidth: true
                    Layout.leftMargin: Kirigami.Units.gridUnit * 1.25
                    Layout.rightMargin: Kirigami.Units.gridUnit * 0.75
                    Layout.topMargin: Kirigami.Units.smallSpacing * 2
                    spacing: Kirigami.Units.gridUnit * 0.75

                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: Kirigami.Units.smallSpacing
                        Kirigami.Heading {
                            text: picker.casting || picker.reconnecting ? "投屏设备" : "投屏到"
                            level: 2
                            font.weight: Font.Bold
                        }
                        RowLayout {
                            spacing: Kirigami.Units.smallSpacing * 1.5
                            QQC2.BusyIndicator {
                                visible: picker.scanning || picker.reconnecting
                                running: visible
                                Layout.preferredWidth: Kirigami.Units.iconSizes.small
                                Layout.preferredHeight: Kirigami.Units.iconSizes.small
                                padding: 0
                            }
                            QQC2.Label {
                                Layout.fillWidth: true
                                text: picker.statusLine
                                color: picker.reconnecting ? Kirigami.Theme.neutralTextColor : Kirigami.Theme.disabledTextColor
                                elide: Text.ElideRight
                            }
                        }
                    }
                    QQC2.ToolButton {
                        icon.name: "window-close-symbolic"
                        display: QQC2.AbstractButton.IconOnly
                        text: "关闭"
                        Accessible.name: "关闭"
                        implicitWidth: Kirigami.Units.gridUnit * 2.75
                        implicitHeight: implicitWidth
                        onClicked: picker.close()
                    }
                }

                SectionLabel { text: "正在使用"; visible: picker.current.length > 0 }
                Repeater {
                    model: picker.current
                    delegate: ReceiverRow {
                        receiver: modelData
                        subtitle: picker.reconnecting ? "正在重连…" : "正在投屏"
                        emphasized: true
                        enabled: false // nothing to do on the TV in use
                        trailingIcon: picker.reconnecting ? "" : "checkmark"
                        busyIndicator: picker.reconnecting
                    }
                }

                SectionLabel { text: "上次使用"; visible: picker.lastUsed.length > 0 }
                Repeater {
                    model: picker.lastUsed
                    delegate: ReceiverRow {
                        receiver: modelData
                        subtitle: picker.connectingTo === modelData.name ? "正在连接…接收端切换网络可能需要两分钟"
                            : modelData.busy ? "忙碌中 · 正被其他设备使用"
                            : modelData.found ? "上次使用 · 可连接"
                            : picker.scanning ? "上次使用 · 正在查找…"
                            : picker.casting ? "上次使用" : "上次使用 · 暂未找到，仍可尝试连接"
                        emphasized: picker.connectingTo === modelData.name
                        busyIndicator: emphasized
                        enabled: !picker.connectingTo && !modelData.busy
                        onActivated: picker.connectTo(modelData)
                    }
                }

                SectionLabel {
                    text: picker.casting || picker.reconnecting ? "最近发现的设备" : "附近的设备"
                    visible: picker.others.length > 0
                }
                Repeater {
                    model: picker.others
                    delegate: ReceiverRow {
                        receiver: modelData
                        subtitle: picker.connectingTo === modelData.name ? "正在连接…接收端切换网络可能需要两分钟"
                            : modelData.busy ? "忙碌中 · 正被其他设备使用"
                            : modelData.found ? "可连接" : "最近发现"
                        emphasized: picker.connectingTo === modelData.name
                        busyIndicator: emphasized
                        enabled: !picker.connectingTo && !modelData.busy
                        onActivated: picker.connectTo(modelData)
                    }
                }

                // Nothing found: what to check.
                ColumnLayout {
                    visible: picker.nothingFound && picker.lastUsed.length === 0
                    Layout.fillWidth: true
                    Layout.topMargin: Kirigami.Units.gridUnit
                    spacing: Kirigami.Units.gridUnit * 0.5
                    Kirigami.Icon {
                        Layout.alignment: Qt.AlignHCenter
                        source: "video-television"
                        implicitWidth: Kirigami.Units.iconSizes.huge
                        implicitHeight: implicitWidth
                        color: Kirigami.Theme.disabledTextColor
                    }
                    Kirigami.Heading {
                        Layout.alignment: Qt.AlignHCenter
                        text: "附近没有找到电视"
                        level: 3
                    }
                }

                Note {
                    visible: !picker.casting && !picker.reconnecting
                    text: picker.nothingFound
                        ? "1. 在电视上打开“无线投屏”，停在等待连接的画面\n2. 电视进入屏保后无法被搜到，先按遥控器唤醒\n3. 手机的 Wi-Fi 保持打开，并尽量靠近电视"
                        : "找不到电视？请让电视停在“无线投屏”的等待画面，电视进入屏保后无法被搜到。"
                }
                Note {
                    visible: picker.casting || picker.reconnecting
                    text: "投屏时无法搜索新电视。换到另一台电视时，会先断开当前电视，新电视出现画面前会中断几秒，桌面上打开的应用不受影响。"
                }

                QQC2.Label {
                    visible: picker.error !== ""
                    Layout.fillWidth: true
                    Layout.leftMargin: Kirigami.Units.gridUnit * 1.25
                    Layout.rightMargin: Kirigami.Units.gridUnit * 1.25
                    Layout.topMargin: Kirigami.Units.gridUnit * 0.75
                    text: picker.error
                    color: Kirigami.Theme.negativeTextColor
                    wrapMode: Text.Wrap
                }

                // Actions.
                ColumnLayout {
                    Layout.fillWidth: true
                    Layout.leftMargin: Kirigami.Units.gridUnit * 1.25
                    Layout.rightMargin: Kirigami.Units.gridUnit * 1.25
                    Layout.topMargin: Kirigami.Units.gridUnit * 0.75
                    spacing: Kirigami.Units.smallSpacing

                    QQC2.Button {
                        Layout.fillWidth: true
                        Layout.preferredHeight: Kirigami.Units.gridUnit * 3
                        visible: picker.connectingTo !== ""
                        text: "取消连接"
                        onClicked: picker.cancelConnect()
                    }
                    QQC2.Button {
                        Layout.fillWidth: true
                        Layout.preferredHeight: Kirigami.Units.gridUnit * 3
                        visible: !picker.scanning && !picker.connectingTo && !picker.casting && !picker.reconnecting
                        text: "重新搜索"
                        icon.name: "view-refresh"
                        highlighted: picker.nothingFound
                        onClicked: picker.rescan()
                    }
                    QQC2.Button {
                        Layout.fillWidth: true
                        Layout.preferredHeight: Kirigami.Units.gridUnit * 3
                        visible: (picker.casting || picker.reconnecting) && !picker.connectingTo
                        text: picker.reconnecting ? "停止重连" : "断开投屏"
                        icon.name: picker.reconnecting ? "dialog-cancel" : "network-disconnect"
                        palette.buttonText: Kirigami.Theme.negativeTextColor
                        onClicked: picker.disconnect()
                    }
                    QQC2.ToolButton {
                        Layout.alignment: Qt.AlignLeft
                        Layout.preferredHeight: Kirigami.Units.gridUnit * 2.75
                        text: "Android 投屏设置"
                        icon.name: "external-link-symbolic"
                        onClicked: {
                            picker.runner("settings", () => {});
                            picker.close();
                        }
                    }
                }
            }
        }
    }

    component SectionLabel: QQC2.Label {
        Layout.fillWidth: true
        Layout.leftMargin: Kirigami.Units.gridUnit * 1.25
        Layout.topMargin: Kirigami.Units.gridUnit * 0.75
        Layout.bottomMargin: Kirigami.Units.smallSpacing
        font.weight: Font.Medium
        color: Kirigami.Theme.disabledTextColor
    }

    component Note: QQC2.Label {
        Layout.fillWidth: true
        Layout.leftMargin: Kirigami.Units.gridUnit * 1.25
        Layout.rightMargin: Kirigami.Units.gridUnit * 1.25
        Layout.topMargin: Kirigami.Units.gridUnit * 0.75
        padding: Kirigami.Units.gridUnit * 0.75
        wrapMode: Text.Wrap
        lineHeight: 1.3
        background: Rectangle {
            radius: Kirigami.Units.gridUnit * 0.75
            color: picker.tint(0.05)
        }
    }

    component ReceiverRow: QQC2.ItemDelegate {
        id: row
        property var receiver
        property string subtitle
        // The TV in use or being connected: its badge in the accent colour (not the whole row,
        // which would leave the pressed state nothing to show).
        property bool emphasized: false
        property string trailingIcon: enabled && !emphasized ? "go-next-symbolic" : ""
        property bool busyIndicator: false
        signal activated()

        Layout.fillWidth: true
        implicitHeight: Kirigami.Units.gridUnit * 4.25
        leftPadding: Kirigami.Units.gridUnit * 1.25
        rightPadding: Kirigami.Units.gridUnit * 1.25
        Accessible.name: receiver.name + "，" + subtitle
        onClicked: activated()

        contentItem: RowLayout {
            spacing: Kirigami.Units.gridUnit * 0.875
            Rectangle {
                Layout.preferredWidth: Kirigami.Units.gridUnit * 2.75
                Layout.preferredHeight: Layout.preferredWidth
                radius: width / 2
                color: row.emphasized ? Kirigami.Theme.highlightColor : picker.tint(0.08)
                Kirigami.Icon {
                    anchors.centerIn: parent
                    source: "video-television"
                    implicitWidth: Kirigami.Units.iconSizes.smallMedium
                    implicitHeight: implicitWidth
                    color: row.emphasized ? Kirigami.Theme.highlightedTextColor : Kirigami.Theme.textColor
                    opacity: row.enabled || row.emphasized ? 1 : 0.6
                }
            }
            ColumnLayout {
                Layout.fillWidth: true
                spacing: 2
                QQC2.Label {
                    Layout.fillWidth: true
                    text: row.receiver.name
                    font.weight: Font.Medium
                    color: Kirigami.Theme.textColor // also on the inert row of the TV in use
                    elide: Text.ElideRight
                    opacity: row.enabled || row.emphasized ? 1 : 0.6
                }
                QQC2.Label {
                    Layout.fillWidth: true
                    text: row.subtitle
                    font: Kirigami.Theme.smallFont
                    color: row.emphasized || (row.receiver.last && row.enabled) ? Kirigami.Theme.linkColor : Kirigami.Theme.disabledTextColor
                    wrapMode: Text.Wrap
                }
            }
            QQC2.BusyIndicator {
                visible: row.busyIndicator
                running: visible
                Layout.preferredWidth: Kirigami.Units.iconSizes.smallMedium
                Layout.preferredHeight: Layout.preferredWidth
                padding: 0
            }
            Kirigami.Icon {
                visible: row.trailingIcon !== "" && !row.busyIndicator
                source: row.trailingIcon
                implicitWidth: Kirigami.Units.iconSizes.small
                implicitHeight: implicitWidth
                color: row.emphasized ? Kirigami.Theme.linkColor : Kirigami.Theme.disabledTextColor
            }
        }
    }
}
