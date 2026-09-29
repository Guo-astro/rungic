// SPDX-License-Identifier: GPL-2.0-or-later
// Codex (docs/87): ready (version, sign-in, where credentials are kept, the config file),
// not installed (how to install it), or installing (steps and output).
import QtQuick
import QtQuick.Layouts
import com.rungic.design
import com.rungic.voiceassistant

SettingsFrame {
    id: page
    title: install.running ? "安装 Codex" : "Codex"
    property var setup: ({})
    readonly property var codex: setup.codex || {}
    property string method: "package"
    // The installation under way: InstallCodex events.
    QtObject {
        id: install
        property bool running: false
        property string step: ""
        property string log: ""
        property string error: ""
    }
    readonly property var steps: [["download", "下载安装程序"], ["install", "安装 Codex"], ["check", "检查能否运行"], ["connect", "连接 OpenAI"]]
    function stepIndex(name) { return steps.findIndex(s => s[0] === name) }

    Component.onCompleted: AgentClient.request("Setup")
    Connections {
        target: AgentClient
        function onReplied(method, json) { if (method === "Setup") page.setup = JSON.parse(json) }
        function onEvent(json) {
            const e = JSON.parse(json)
            if (e.type !== "install") return
            if (e.line) install.log = (install.log + e.line + "\n").split("\n").slice(-40).join("\n")
            if (e.step) install.step = e.step
            if (e.state === "done" || e.state === "failed" || e.state === "cancelled") {
                install.running = false
                install.error = e.state === "failed" ? (e.error || "安装没有完成") : ""
                AgentClient.request("Setup")
            }
        }
    }

    // ---- ready or not ---------------------------------------------------------------
    ColumnLayout {
        Layout.fillWidth: true
        visible: !install.running && page.setup.codex !== undefined
        spacing: 0
        ColumnLayout {
            Layout.fillWidth: true
            Layout.topMargin: 20
            Layout.leftMargin: 32
            Layout.rightMargin: 32
            spacing: 10
            Rectangle {
                Layout.alignment: Qt.AlignHCenter
                Layout.preferredWidth: 72
                Layout.preferredHeight: 72
                radius: 36
                color: Theme.fill
                Icon {
                    anchors.centerIn: parent
                    name: page.codex.installed ? "check" : "terminal"
                    color: page.codex.installed ? Theme.positive : Theme.text
                    implicitWidth: 32
                    implicitHeight: 32
                }
            }
            Text {
                Layout.alignment: Qt.AlignHCenter
                text: page.codex.installed ? (page.codex.runs === false ? "Codex 运行不了" : "Codex 已就绪") : "还没有安装 Codex"
                font.family: Theme.fontFamily
                font.pixelSize: Theme.heroSize
                font.weight: Font.DemiBold
                color: Theme.text
            }
            Text {
                Layout.fillWidth: true
                horizontalAlignment: Text.AlignHCenter
                text: page.codex.installed ? "Agent 用它在手机上执行命令、操作应用。"
                    : "Agent 靠 Codex 在手机上执行命令、操作应用。装好后就能让它替你做事。"
                wrapMode: Text.Wrap
                font.family: Theme.fontFamily
                font.pixelSize: Theme.metaSize
                color: Theme.dim
            }
            Note {
                Layout.fillWidth: true
                visible: install.error !== ""
                tone: "negative"
                text: install.error
            }
        }
        Item { implicitHeight: 20 }

        // Installed.
        ListGroup {
            Layout.fillWidth: true
            Layout.leftMargin: Theme.groupMargin
            Layout.rightMargin: Theme.groupMargin
            visible: page.codex.installed === true
            ListRow { text: "版本"; value: page.codex.version || "" }
            ListRow {
                text: "登录方式"
                value: !page.setup.account ? "未登录" : page.setup.account.type === "apiKey" ? "API Key" : "ChatGPT 账号"
                accessory: "chevron"
                onClicked: page.push("KeyPage.qml")
            }
            ListRow {
                text: "凭据保存在"
                value: page.setup.credentials === "keyring" ? "系统钥匙串" : "本机文件"
            }
            ListRow {
                text: "配置文件"
                value: "~/.codex/config.toml"
                valueMono: true
                accessory: "external"
                onClicked: Qt.openUrlExternally("file://" + page.setup.home + "/.codex/config.toml")
            }
        }
        Item { implicitHeight: 20; visible: page.codex.installed === true }
        ListGroup {
            Layout.fillWidth: true
            Layout.leftMargin: Theme.groupMargin
            Layout.rightMargin: Theme.groupMargin
            visible: page.codex.installed === true
            ListRow { text: "重新检测"; interactive: true; onClicked: AgentClient.request("Setup") }
        }

        // Not installed: how.
        SectionLabel { Layout.fillWidth: true; text: "安装方式"; visible: page.codex.installed === false }
        ListGroup {
            Layout.fillWidth: true
            Layout.leftMargin: Theme.groupMargin
            Layout.rightMargin: Theme.groupMargin
            visible: page.codex.installed === false
            Accessible.role: Accessible.List
            Accessible.name: "安装方式"
            ListRow {
                text: "系统软件包（推荐）"
                subtitle: "apt install rungic-codex · 与系统一起更新"
                interactive: true
                leading: RadioMark { on: page.method === "package" }
                onClicked: page.method = "package"
            }
            ListRow {
                text: "官方安装脚本"
                subtitle: "curl -fsSL https://chatgpt.com/codex/install.sh | sh"
                interactive: true
                leading: RadioMark { on: page.method === "script" }
                onClicked: page.method = "script"
            }
        }
    }

    // ---- installing -------------------------------------------------------------------
    ColumnLayout {
        Layout.fillWidth: true
        Layout.leftMargin: Theme.gutter
        Layout.rightMargin: Theme.gutter
        Layout.topMargin: 16
        visible: install.running
        spacing: 12
        ShineText { Layout.fillWidth: true; pixelSize: Theme.heroSize; text: "正在安装 Codex…" }
        Progress { Layout.fillWidth: true }
        Text { text: "大约还要 1 分钟，可以先离开这页"; font.family: Theme.fontFamily; font.pixelSize: Theme.labelSize; color: Theme.dim }
    }
    Item { implicitHeight: 16; visible: install.running }
    ListGroup {
        Layout.fillWidth: true
        Layout.leftMargin: Theme.groupMargin
        Layout.rightMargin: Theme.groupMargin
        visible: install.running
        Repeater {
            model: page.steps
            ListRow {
                required property var modelData
                required property int index
                readonly property int at: page.stepIndex(install.step)
                text: modelData[1]
                leading: Item {
                    implicitWidth: 20
                    implicitHeight: 20
                    BusyRing { anchors.fill: parent; visible: index === at }
                    Icon {
                        anchors.fill: parent
                        visible: index !== at
                        name: index < at ? "check" : "chevron"
                        color: index < at ? Theme.positive : Theme.dim
                    }
                }
            }
        }
    }
    SectionLabel { Layout.fillWidth: true; text: "详细输出"; visible: install.running && install.log !== "" }
    Text {
        Layout.fillWidth: true
        Layout.leftMargin: Theme.groupMargin
        Layout.rightMargin: Theme.groupMargin
        visible: install.running && install.log !== ""
        padding: 14
        text: install.log.trim()
        wrapMode: Text.WrapAnywhere
        font.family: Theme.monoFamily
        font.pixelSize: 12
        lineHeight: 19
        lineHeightMode: Text.FixedHeight
        color: Theme.dim
        Rectangle { anchors.fill: parent; z: -1; radius: Theme.radiusInput; color: Theme.fill }
    }
    Item { implicitHeight: 20 }

    footer: [
        PrimaryButton {
            Layout.fillWidth: true
            visible: page.codex.installed === false && !install.running
            iconName: "download"
            text: "安装 Codex"
            onClicked: {
                install.running = true
                install.error = ""
                install.log = ""
                install.step = "download"
                AgentClient.request("InstallCodex", [page.method])
            }
        },
        SecondaryButton {
            Layout.fillWidth: true
            visible: page.codex.installed === false && !install.running
            text: "稍后再说"
            onClicked: page.back()
        },
        SecondaryButton {
            Layout.fillWidth: true
            visible: install.running
            text: "取消安装"
            onClicked: AgentClient.request("CancelInstall")
        }
    ]
}
