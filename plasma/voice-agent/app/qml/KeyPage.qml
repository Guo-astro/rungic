// SPDX-License-Identifier: GPL-2.0-or-later
// OpenAI API Key (docs/87): what it is for, the key (hidden unless revealed), whether it
// works, where it is kept; signing Codex in with a ChatGPT account instead.
import QtQuick
import QtQuick.Layouts
import com.rungic.design
import com.rungic.voiceassistant

SettingsFrame {
    id: page
    title: "OpenAI API Key"
    property var setup: ({})
    property string status: ""                // "" | testing | ok | error
    property string error: ""
    property bool edited: false
    property var login: null                  // a ChatGPT device-code sign-in under way
    readonly property var key: setup.key || {}

    Component.onCompleted: AgentClient.request("Setup")
    Connections {
        target: AgentClient
        function onReplied(method, json) {
            const r = JSON.parse(json)
            if (method === "Setup") {
                page.setup = r
                if (!page.edited) field.text = r.key && r.key.set ? r.key.masked : ""
                // A key not tested since the service started is tested now: "works" is never assumed.
                if (r.key && r.key.set && !page.status) {
                    if (r.key.working === true) page.status = "ok"
                    else { page.status = "testing"; AgentClient.request("TestApiKey") }
                }
            } else if (method === "SetApiKey" || method === "TestApiKey") {
                page.status = r.ok ? "ok" : "error"
                page.error = r.error || ""
                if (r.ok) { page.edited = false; AgentClient.request("Setup") }
            } else if (method === "RemoveApiKey") {
                page.status = ""
                page.edited = false
                AgentClient.request("Setup")
            } else if (method === "CodexLogin") {
                page.login = r.error ? { error: r.error } : r
            }
        }
        function onEvent(json) {
            const e = JSON.parse(json)
            if (e.type === "account") { page.login = e.success ? null : { error: e.error || i18nc("@info", "The sign-in didn't finish") }; AgentClient.request("Setup") }
        }
    }

    function save() {
        if (!edited || !field.text.trim()) { back(); return }
        status = "testing"
        AgentClient.request("SetApiKey", [field.text.trim()])
    }

    ColumnLayout {
        Layout.fillWidth: true
        Layout.leftMargin: Theme.gutter
        Layout.rightMargin: Theme.gutter
        Layout.topMargin: 12
        spacing: 12
        Text {
            Layout.fillWidth: true
            text: i18nc("@info", "Codex uses this key to call OpenAI. You're billed for what you use.")
            wrapMode: Text.Wrap
            font.family: Theme.fontFamily
            font.pixelSize: Theme.bodySize
            color: Theme.text
        }
        Text {
            text: i18nc("@info a link; keep the markup", "<a href='%1'>Create a key on the OpenAI platform</a> ↗", "https://platform.openai.com/api-keys")
            textFormat: Text.StyledText
            linkColor: Theme.link
            font.family: Theme.fontFamily
            font.pixelSize: Theme.metaSize
            color: Theme.link
            onLinkActivated: link => Qt.openUrlExternally(link)
        }
        Text {
            Layout.topMargin: 8
            text: "API Key"
            font.family: Theme.fontFamily
            font.pixelSize: Theme.labelSize
            color: Theme.dim
        }
        SecretField {
            id: field
            Layout.fillWidth: true
            accessibleName: "OpenAI API Key"
            placeholderText: "sk-…"
            error: page.status === "error"
            input.onTextEdited: { page.edited = true; if (page.status === "error") page.status = "" }
            // A saved key shows masked; editing starts from empty.
            input.onActiveFocusChanged: if (input.activeFocus && !page.edited && page.key.set) field.text = ""
        }
        Note {
            Layout.fillWidth: true
            visible: page.status !== ""
            tone: page.status === "ok" ? "positive" : page.status === "error" ? "negative" : ""
            text: page.status === "testing" ? i18nc("@info:status", "Testing the key…")
                : page.status === "ok" ? i18nc("@info:status", "The key works. Connected to OpenAI.")
                : page.error ? i18nc("@info:status %1 is the error", "This key doesn't work. Check that you copied all of it, or create a new one on the OpenAI platform. (%1)", page.error)
                : i18nc("@info:status", "This key doesn't work. Check that you copied all of it, or create a new one on the OpenAI platform.")
        }
        Note {
            Layout.fillWidth: true
            text: i18nc("@info %1 is a folder", "Kept in plain text in a config file on this phone (%1, readable only by your user) and sent only to OpenAI.",
                        "~/.config/rungic-voice-agent")
        }
    }

    Item { implicitHeight: 20 }
    ListGroup {
        Layout.fillWidth: true
        Layout.leftMargin: Theme.groupMargin
        Layout.rightMargin: Theme.groupMargin
        ListRow {
            readonly property bool chatgpt: page.setup.account && page.setup.account.type === "chatgpt"
            text: chatgpt ? i18nc("@info", "Codex is signed in with ChatGPT") : i18nc("@action:button", "Sign in with ChatGPT instead")
            subtitle: chatgpt ? (page.setup.account.email || i18nc("@info", "Billed to your ChatGPT plan"))
                : i18nc("@info", "Sign in with your browser. Billed to your ChatGPT plan.")
            accessory: chatgpt ? "" : "chevron"
            onClicked: if (!chatgpt) AgentClient.request("CodexLogin", ["chatgpt"])
        }
        ListRow {
            visible: page.setup.account && page.setup.account.type === "chatgpt" && page.key.set === true
            text: i18nc("@action:button", "Sign Codex in with the API key instead")
            subtitle: i18nc("@info", "The Agent's tasks are then billed to this key too")
            accessory: "chevron"
            onClicked: AgentClient.request("CodexLogin", ["apiKey"])
        }
    }
    // A device-code sign-in: the code to enter on the page it names.
    ColumnLayout {
        Layout.fillWidth: true
        Layout.margins: Theme.gutter
        visible: page.login !== null
        spacing: 8
        Note {
            Layout.fillWidth: true
            visible: page.login && page.login.error
            tone: "negative"
            text: page.login && page.login.error ? page.login.error : ""
        }
        Text {
            Layout.fillWidth: true
            visible: page.login && page.login.userCode
            text: page.login && page.login.userCode
                ? i18nc("@info a link; keep the markup", "On any device, open <a href='%1'>%1</a> and enter this code:", page.login.verificationUrl) : ""
            textFormat: Text.StyledText
            linkColor: Theme.link
            wrapMode: Text.Wrap
            font.family: Theme.fontFamily
            font.pixelSize: Theme.metaSize
            color: Theme.text
            onLinkActivated: link => Qt.openUrlExternally(link)
        }
        Text {
            visible: page.login && page.login.userCode
            text: page.login ? page.login.userCode || "" : ""
            font.family: Theme.monoFamily
            font.pixelSize: 28
            font.weight: Font.DemiBold
            color: Theme.text
        }
    }

    footer: [
        PrimaryButton {
            Layout.fillWidth: true
            text: page.status === "error" && !page.edited ? i18nc("@action:button", "Test again")
                : page.status === "testing" ? i18nc("@action:button", "Testing…") : i18nc("@action:button", "Done")
            enabled: page.status !== "testing"
            onClicked: {
                if (page.status === "error" && !page.edited) { page.status = "testing"; AgentClient.request("TestApiKey") }
                else page.save()
            }
        },
        SecondaryButton {
            Layout.fillWidth: true
            visible: page.key.set === true && !page.edited
            text: i18nc("@action:button", "Remove key")
            negative: true
            onClicked: AgentClient.request("RemoveApiKey")
        }
    ]
}
