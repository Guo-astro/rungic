// SPDX-License-Identifier: GPL-2.0-or-later
// "Cast to": the TV picker the cast tile opens on the phone screen (docs/58). Scans while
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
    title: i18n("Cast to")

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
            if (result.code === "wifi-unavailable") error = i18n("Turn on Wi-Fi first");
            else if (result.code === "component-missing") error = i18n("Casting isn't ready yet");
            else error = i18n("Search failed. Check Android's cast settings.");
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
                        ? i18n("Couldn't connect to “%1”: the receiver didn't finish joining the network and negotiating. Try again.", name)
                        : i18n("Couldn't connect to “%1”", name);
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
        if (connectingTo) return connectionPhase === "negotiating"
            ? i18np("Negotiating · %1 second", "Negotiating · %1 seconds", elapsedSeconds)
            : i18np("Waiting for the receiver to join the network · %1 second", "Waiting for the receiver to join the network · %1 seconds", elapsedSeconds);
        if (reconnecting) return i18n("TV disconnected, reconnecting…");
        if (casting) return i18n("Casting to %1", current.length ? current[0].name : tvName);
        if (scanning) return i18n("Looking for TVs nearby…");
        if (nothingFound) return i18n("No TVs found nearby");
        return i18n("Search finished");
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
                            text: picker.casting || picker.reconnecting ? i18n("Cast device") : i18n("Cast to")
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
                        text: i18n("Close")
                        Accessible.name: i18n("Close")
                        implicitWidth: Kirigami.Units.gridUnit * 2.75
                        implicitHeight: implicitWidth
                        onClicked: picker.close()
                    }
                }

                SectionLabel { text: i18n("In use"); visible: picker.current.length > 0 }
                Repeater {
                    model: picker.current
                    delegate: ReceiverRow {
                        receiver: modelData
                        subtitle: picker.reconnecting ? i18n("Reconnecting…") : i18n("Casting")
                        emphasized: true
                        enabled: false // nothing to do on the TV in use
                        trailingIcon: picker.reconnecting ? "" : "checkmark"
                        busyIndicator: picker.reconnecting
                    }
                }

                SectionLabel { text: i18n("Last used"); visible: picker.lastUsed.length > 0 }
                Repeater {
                    model: picker.lastUsed
                    delegate: ReceiverRow {
                        receiver: modelData
                        subtitle: picker.connectingTo === modelData.name ? i18n("Connecting… The receiver can take up to two minutes to switch networks")
                            : modelData.busy ? i18n("Busy · In use by another device")
                            : modelData.found ? i18n("Last used · Available")
                            : picker.scanning ? i18n("Last used · Looking…")
                            : picker.casting ? i18n("Last used") : i18n("Last used · Not found yet, you can still try connecting")
                        emphasized: picker.connectingTo === modelData.name
                        busyIndicator: emphasized
                        enabled: !picker.connectingTo && !modelData.busy
                        onActivated: picker.connectTo(modelData)
                    }
                }

                SectionLabel {
                    text: picker.casting || picker.reconnecting ? i18n("Recently found devices") : i18n("Nearby devices")
                    visible: picker.others.length > 0
                }
                Repeater {
                    model: picker.others
                    delegate: ReceiverRow {
                        receiver: modelData
                        subtitle: picker.connectingTo === modelData.name ? i18n("Connecting… The receiver can take up to two minutes to switch networks")
                            : modelData.busy ? i18n("Busy · In use by another device")
                            : modelData.found ? i18n("Available") : i18n("Recently found")
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
                        text: i18n("No TVs found nearby")
                        level: 3
                    }
                }

                Note {
                    visible: !picker.casting && !picker.reconnecting
                    text: picker.nothingFound
                        ? i18n("1. Open screen mirroring on the TV and leave it on the waiting screen\n2. A TV in its screensaver can't be found, so wake it with the remote first\n3. Keep the phone's Wi-Fi on and stay close to the TV")
                        : i18n("Can't find your TV? Leave it on the screen mirroring waiting screen. A TV in its screensaver can't be found.")
                }
                Note {
                    visible: picker.casting || picker.reconnecting
                    text: i18n("You can't search for new TVs while casting. Switching to another TV disconnects the current one first, so the picture pauses for a few seconds until the new TV shows it. Apps open on the desktop keep running.")
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
                        text: i18n("Cancel")
                        onClicked: picker.cancelConnect()
                    }
                    QQC2.Button {
                        Layout.fillWidth: true
                        Layout.preferredHeight: Kirigami.Units.gridUnit * 3
                        visible: !picker.scanning && !picker.connectingTo && !picker.casting && !picker.reconnecting
                        text: i18n("Search again")
                        icon.name: "view-refresh"
                        highlighted: picker.nothingFound
                        onClicked: picker.rescan()
                    }
                    QQC2.Button {
                        Layout.fillWidth: true
                        Layout.preferredHeight: Kirigami.Units.gridUnit * 3
                        visible: (picker.casting || picker.reconnecting) && !picker.connectingTo
                        text: picker.reconnecting ? i18n("Stop reconnecting") : i18n("Stop casting")
                        icon.name: picker.reconnecting ? "dialog-cancel" : "network-disconnect"
                        palette.buttonText: Kirigami.Theme.negativeTextColor
                        onClicked: picker.disconnect()
                    }
                    QQC2.ToolButton {
                        Layout.alignment: Qt.AlignLeft
                        Layout.preferredHeight: Kirigami.Units.gridUnit * 2.75
                        text: i18n("Android cast settings")
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
        Accessible.name: i18nc("@info:whatsthis TV name, then its state", "%1, %2", receiver.name, subtitle)
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
