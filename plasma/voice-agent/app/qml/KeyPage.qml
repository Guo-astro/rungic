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
                // A key not tested since the service started is tested now: "可用" is never assumed.
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
            if (e.type === "account") { page.login = e.success ? null : { error: e.error || "登录没有完成" }; AgentClient.request("Setup") }
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
            text: "Codex 用这把密钥调用 OpenAI，按用量计费。"
            wrapMode: Text.Wrap
            font.family: Theme.fontFamily
            font.pixelSize: Theme.bodySize
            color: Theme.text
        }
        Text {
            text: "<a href='https://platform.openai.com/api-keys'>在 OpenAI 平台创建密钥</a> ↗"
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
            text: page.status === "testing" ? "正在测试密钥…"
                : page.status === "ok" ? "密钥可用，已连上 OpenAI。"
                : "这把密钥用不了。检查一下是否复制完整，或在 OpenAI 平台上重新创建一把。" + (page.error ? "（" + page.error + "）" : "")
        }
        Note {
            Layout.fillWidth: true
            text: page.key.store === "file" ? "保存在本机的配置文件里（~/.config/rungic-voice-agent，只有你能读），只发给 OpenAI。"
                : "保存在系统钥匙串里，不会写进文件，也不会发给除 OpenAI 以外的任何地方。"
        }
    }

    Item { implicitHeight: 20 }
    ListGroup {
        Layout.fillWidth: true
        Layout.leftMargin: Theme.groupMargin
        Layout.rightMargin: Theme.groupMargin
        ListRow {
            readonly property bool chatgpt: page.setup.account && page.setup.account.type === "chatgpt"
            text: chatgpt ? "Codex 已用 ChatGPT 账号登录" : "改用 ChatGPT 账号登录"
            subtitle: chatgpt ? (page.setup.account.email || "按 ChatGPT 套餐计费") : "在浏览器里登录，按 ChatGPT 套餐计费"
            accessory: chatgpt ? "" : "chevron"
            onClicked: if (!chatgpt) AgentClient.request("CodexLogin", ["chatgpt"])
        }
        ListRow {
            visible: page.setup.account && page.setup.account.type === "chatgpt" && page.key.set === true
            text: "改用 API Key 登录 Codex"
            subtitle: "Agent 的任务也按这把密钥的用量计费"
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
            text: page.login && page.login.userCode ? "在任意设备打开 <a href='" + page.login.verificationUrl + "'>" + page.login.verificationUrl + "</a>，输入下面的代码：" : ""
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
            text: page.status === "error" && !page.edited ? "重新测试" : page.status === "testing" ? "正在测试…" : "完成"
            enabled: page.status !== "testing"
            onClicked: {
                if (page.status === "error" && !page.edited) { page.status = "testing"; AgentClient.request("TestApiKey") }
                else page.save()
            }
        },
        SecondaryButton {
            Layout.fillWidth: true
            visible: page.key.set === true && !page.edited
            text: "移除密钥"
            negative: true
            onClicked: AgentClient.request("RemoveApiKey")
        }
    ]
}
