// SPDX-License-Identifier: GPL-2.0-or-later
// 设置 (docs/87): Codex and the OpenAI API key, voice, appearance, about.
import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as QQC2
import com.rungic.design
import com.rungic.voiceassistant

SettingsFrame {
    id: page
    title: "设置"
    property var setup: ({})
    readonly property var settings: QQC2.ApplicationWindow.window ? QQC2.ApplicationWindow.window.settings : null
    property bool choosingTheme: false

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
            value: !page.setup.codex ? "" : page.codex.installed ? "已安装" : "未安装"
            accessory: "chevron"
            onClicked: page.push("CodexPage.qml")
        }
        ListRow {
            text: "OpenAI API Key"
            value: page.key.set ? page.key.masked : (page.setup.key ? "未设置" : "")
            valueMono: page.key.set === true
            dot: page.setup.key && !page.key.set ? "negative" : ""
            accessory: "chevron"
            onClicked: page.push("KeyPage.qml")
        }
    }

    SectionLabel { Layout.fillWidth: true; text: "语音" }
    ListGroup {
        Layout.fillWidth: true
        Layout.leftMargin: Theme.groupMargin
        Layout.rightMargin: Theme.groupMargin
        ListRow {
            text: "长按 Home 呼出"
            onClicked: homeToggle.toggle()
            trailing: Toggle {
                id: homeToggle
                text: "长按 Home 呼出"
                checked: page.prefs.homeHold !== false
                onToggled: page.prefer("homeHold", checked)
            }
        }
        ListRow {
            text: "朗读回答"
            onClicked: speakToggle.toggle()
            trailing: Toggle {
                id: speakToggle
                text: "朗读回答"
                checked: page.prefs.speak !== false
                onToggled: page.prefer("speak", checked)
            }
        }
        ListRow {
            text: "免提时说完自动发送"
            subtitle: "停顿约 1 秒后发送"
            onClicked: autoToggle.toggle()
            trailing: Toggle {
                id: autoToggle
                text: "免提时说完自动发送"
                checked: page.prefs.handsFreeAutoSend !== false
                onToggled: page.prefer("handsFreeAutoSend", checked)
            }
        }
    }

    SectionLabel { Layout.fillWidth: true; text: "外观" }
    ListGroup {
        Layout.fillWidth: true
        Layout.leftMargin: Theme.groupMargin
        Layout.rightMargin: Theme.groupMargin
        ListRow {
            readonly property var names: ({ system: "跟随系统", light: "浅色", dark: "深色" })
            text: "主题"
            value: page.settings ? names[page.settings.theme] || "跟随系统" : ""
            accessory: "chevron"
            onClicked: page.choosingTheme = !page.choosingTheme
        }
        Repeater {
            model: page.choosingTheme ? [["system", "跟随系统"], ["light", "浅色"], ["dark", "深色"]] : []
            ListRow {
                required property var modelData
                text: modelData[1]
                Accessible.role: Accessible.RadioButton
                leading: RadioMark { on: page.settings && page.settings.theme === modelData[0] }
                onClicked: { page.settings.theme = modelData[0]; page.choosingTheme = false }
            }
        }
    }

    SectionLabel { Layout.fillWidth: true; text: "关于" }
    ListGroup {
        Layout.fillWidth: true
        Layout.leftMargin: Theme.groupMargin
        Layout.rightMargin: Theme.groupMargin
        ListRow { text: "版本"; value: page.setup.version || "" }
        ListRow { text: "隐私说明"; accessory: "chevron"; onClicked: page.push(privacy) }
    }
    Item { implicitHeight: 24 }

    Component {
        id: privacy
        SettingsFrame {
            title: "隐私说明"
            Repeater {
                model: [
                    "你按住说话时，声音才会离开手机：它经你设置的代理发到 OpenAI，由语音模型听懂并回答。松开前滑到 × 取消，这段声音就不会发出。",
                    "Agent 通过 Codex 在这台手机上执行命令、操作应用。它看到的屏幕内容和命令结果会发给 OpenAI 用来决定下一步。",
                    "对话记录只保存在这台手机上（~/.local/share/rungic-voice-agent），删除对话会一并删除记录。",
                    "OpenAI API Key 明文保存在本机的配置文件里（~/.config/rungic-voice-agent，只有你这个用户能读），只用来调用 OpenAI。以你身份运行的程序（包括 Agent）都能读到它。"
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
