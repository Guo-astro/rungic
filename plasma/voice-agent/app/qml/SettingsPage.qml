// SPDX-License-Identifier: GPL-2.0-or-later
// Settings (docs/87): Codex and the OpenAI API key, voice, appearance, about.
import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as QQC2
import com.rungic.design
import com.rungic.voiceassistant

SettingsFrame {
    id: page
    title: i18nc("@title", "Settings")
    property var setup: ({})
    readonly property var settings: QQC2.ApplicationWindow.window ? QQC2.ApplicationWindow.window.settings : null
    property bool choosingTheme: false
    readonly property var themeNames: [["system", i18nc("@item the app's theme", "System")], ["light", i18nc("@item the app's theme", "Light")],
                                       ["dark", i18nc("@item the app's theme", "Dark")]]

    Component.onCompleted: AgentClient.request("Setup")
    onVisibleChanged: if (visible) AgentClient.request("Setup")
    Connections {
        target: AgentClient
        function onReplied(method, json) { if (method === "Setup") page.setup = JSON.parse(json) }
    }
    readonly property var codex: setup.codex || {}
    readonly property var key: setup.key || {}
    readonly property var prefs: setup.preferences || {}
    function prefer(name, value) {
        const p = Object.assign({}, prefs)
        p[name] = value
        setup = Object.assign({}, setup, { preferences: p })
        AgentClient.request("SetPreferences", [JSON.stringify(p)])
    }

    SectionLabel { Layout.fillWidth: true; text: "Codex" }
    ListGroup {
        Layout.fillWidth: true
        Layout.leftMargin: Theme.groupMargin
        Layout.rightMargin: Theme.groupMargin
        ListRow {
            text: "Codex"
            dot: page.setup.codex ? (page.codex.installed ? "positive" : "negative") : ""
            value: !page.setup.codex ? "" : page.codex.installed ? i18nc("@info Codex", "Installed") : i18nc("@info Codex", "Not installed")
            accessory: "chevron"
            onClicked: page.push("CodexPage.qml")
        }
        ListRow {
            text: "OpenAI API Key"
            value: page.key.set ? page.key.masked : (page.setup.key ? i18nc("@info the API key", "Not set") : "")
            valueMono: page.key.set === true
            dot: page.setup.key && !page.key.set ? "negative" : ""
            accessory: "chevron"
            onClicked: page.push("KeyPage.qml")
        }
    }

    SectionLabel { Layout.fillWidth: true; text: i18nc("@title:group", "Voice") }
    ListGroup {
        Layout.fillWidth: true
        Layout.leftMargin: Theme.groupMargin
        Layout.rightMargin: Theme.groupMargin
        ListRow {
            text: i18nc("@option:check", "Hold Home to open")
            onClicked: homeToggle.toggle()
            trailing: Toggle {
                id: homeToggle
                text: i18nc("@option:check", "Hold Home to open")
                checked: page.prefs.homeHold !== false
                onToggled: page.prefer("homeHold", checked)
            }
        }
        ListRow {
            text: i18nc("@option:check", "Read answers aloud")
            onClicked: speakToggle.toggle()
            trailing: Toggle {
                id: speakToggle
                text: i18nc("@option:check", "Read answers aloud")
                checked: page.prefs.speak !== false
                onToggled: page.prefer("speak", checked)
            }
        }
        ListRow {
            text: i18nc("@option:check", "Auto-send in hands-free mode")
            subtitle: i18nc("@info", "Sends after a pause of about a second")
            onClicked: autoToggle.toggle()
            trailing: Toggle {
                id: autoToggle
                text: i18nc("@option:check", "Auto-send in hands-free mode")
                checked: page.prefs.handsFreeAutoSend !== false
                onToggled: page.prefer("handsFreeAutoSend", checked)
            }
        }
    }

    SectionLabel { Layout.fillWidth: true; text: i18nc("@title:group", "Appearance") }
    ListGroup {
        Layout.fillWidth: true
        Layout.leftMargin: Theme.groupMargin
        Layout.rightMargin: Theme.groupMargin
        ListRow {
            readonly property var names: ({ system: page.themeNames[0][1], light: page.themeNames[1][1], dark: page.themeNames[2][1] })
            text: i18nc("@label", "Theme")
            value: page.settings ? names[page.settings.theme] || names.system : ""
            accessory: "chevron"
            onClicked: page.choosingTheme = !page.choosingTheme
        }
        Repeater {
            model: page.choosingTheme ? page.themeNames : []
            ListRow {
                required property var modelData
                text: modelData[1]
                Accessible.role: Accessible.RadioButton
                leading: RadioMark { on: page.settings && page.settings.theme === modelData[0] }
                onClicked: { page.settings.theme = modelData[0]; page.choosingTheme = false }
            }
        }
    }

    SectionLabel { Layout.fillWidth: true; text: i18nc("@title:group", "About") }
    ListGroup {
        Layout.fillWidth: true
        Layout.leftMargin: Theme.groupMargin
        Layout.rightMargin: Theme.groupMargin
        ListRow { text: i18nc("@label", "Version"); value: page.setup.version || "" }
        ListRow { text: i18nc("@action:button", "Privacy"); accessory: "chevron"; onClicked: page.push(privacy) }
    }
    Item { implicitHeight: 24 }

    Component {
        id: privacy
        SettingsFrame {
            title: i18nc("@title", "Privacy")
            Repeater {
                model: [
                    i18nc("@info privacy", "Your voice leaves the phone only while you hold to talk: it goes through the proxy you set up to OpenAI, where a voice model understands it and answers. Slide onto × before you let go to cancel, and it is never sent."),
                    i18nc("@info privacy", "The Agent runs commands and uses apps on this phone through Codex. What it sees on the screen and the results of its commands are sent to OpenAI to decide the next step."),
                    i18nc("@info privacy; %1 is a folder", "Conversations are kept only on this phone (%1). Deleting a conversation deletes its history too.",
                          "~/.local/share/rungic-voice-agent"),
                    i18nc("@info privacy; %1 is a folder", "Your OpenAI API key is kept in plain text in a config file on this phone (%1, readable only by your user) and is used only to call OpenAI. Programs running as you, including the Agent, can read it.",
                          "~/.config/rungic-voice-agent")
                ]
                Text {
                    required property string modelData
                    Layout.fillWidth: true
                    Layout.leftMargin: Theme.gutter
                    Layout.rightMargin: Theme.gutter
                    Layout.topMargin: 12
                    text: modelData
                    wrapMode: Text.Wrap
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.bodySize
                    lineHeight: Theme.bodyLine
                    lineHeightMode: Text.FixedHeight
                    color: Theme.text
                }
            }
        }
    }
}
