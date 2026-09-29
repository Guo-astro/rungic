// SPDX-License-Identifier: GPL-2.0-or-later
// The state gallery (docs/87): every control of the design system in every state it has,
// forced with `forcedState`, so states are checked side by side (light and dark) instead of
// by pressing things on the phone. rungic-design-gallery [--theme light|dark] [--section NAME].
import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as QQC2
import com.rungic.design

QQC2.ApplicationWindow {
    id: gallery
    property string initialTheme: "system"
    property string section: ""                 // show only these sections, comma-separated (screenshots)
    visible: true
    width: 390
    height: 844
    title: "Rungic 设计系统 · 状态"
    color: Theme.background
    Component.onCompleted: Theme.mode = initialTheme

    readonly property var buttonStates: ["normal", "pressed", "checked", "disabled"]

    Flickable {
        anchors.fill: parent
        contentHeight: column.implicitHeight + 40
        clip: true
        ColumnLayout {
            id: column
            x: 16
            width: parent.width - 32
            spacing: 6
            RowLayout {
                Layout.topMargin: 12
                Text {
                    Layout.fillWidth: true
                    text: "状态 · " + (Theme.dark ? "深色" : "浅色")
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.headingSize
                    font.weight: Font.DemiBold
                    color: Theme.text
                }
                PillButton { text: Theme.dark ? "浅色" : "深色"; onClicked: Theme.mode = Theme.dark ? "light" : "dark" }
            }

            Section {
                name: "Icon colours"
                Repeater {
                    model: ["#ffffff", "strongInk", "#ff3333", "#000000"]
                    Variant {
                        label: modelData
                        Rectangle {
                            width: 44; height: 44; radius: 22; color: modelData === "strongInk" ? Theme.strong : "#232629"
                            Icon { anchors.centerIn: parent; name: "send"; color: modelData === "strongInk" ? Theme.strongInk : modelData }
                        }
                    }
                }
                Variant { label: "strongInk=" + Theme.strongInk; Item { width: 1; height: 1 } }
            }
            Section {
                name: "IconButton"
                Repeater {
                    model: gallery.buttonStates
                    Variant { label: modelData; IconButton { iconName: "keyboard"; text: "键盘"; forcedState: modelData } }
                }
                Repeater {
                    model: gallery.buttonStates
                    Variant { label: "small " + modelData; IconButton { small: true; iconName: "copy"; text: "复制"; forcedState: modelData } }
                }
            }
            Section {
                name: "CircleButton"
                Repeater {
                    model: ["normal", "pressed", "disabled"]
                    Variant { label: "stop " + modelData; CircleButton { iconName: "stop"; text: "停止"; forcedState: modelData } }
                }
                Repeater {
                    model: ["normal", "pressed", "disabled"]
                    Variant { label: "send " + modelData; CircleButton { iconName: "send"; text: "发送"; forcedState: modelData } }
                }
            }
            Section {
                name: "PillButton"
                Repeater {
                    model: gallery.buttonStates
                    Variant { label: modelData; PillButton { iconName: "headset"; text: "旁听"; forcedState: modelData } }
                }
                Repeater {
                    model: gallery.buttonStates
                    Variant { label: "negative " + modelData; PillButton { iconName: "hang-up"; text: "挂断"; negative: true; forcedState: modelData } }
                }
            }
            Section {
                name: "PrimaryButton"
                wide: true
                Repeater {
                    model: ["normal", "pressed", "disabled", "busy"]
                    Variant { label: modelData; wide: true; PrimaryButton { width: 300; iconName: "download"; text: "安装 Codex"; forcedState: modelData } }
                }
            }
            Section {
                name: "SecondaryButton"
                wide: true
                Repeater {
                    model: ["normal", "pressed", "disabled"]
                    Variant { label: modelData; wide: true; SecondaryButton { width: 300; text: "移除密钥"; negative: true; forcedState: modelData } }
                }
            }
            Section {
                name: "NavItem"
                wide: true
                Repeater {
                    model: ["normal", "pressed", "current", "disabled"]
                    Variant { label: modelData; wide: true; NavItem { width: 300; iconName: "settings"; text: "设置"; forcedState: modelData } }
                }
            }
            Section {
                name: "ListRow"
                wide: true
                Repeater {
                    model: ["normal", "pressed", "disabled"]
                    Variant {
                        label: modelData
                        wide: true
                        ListGroup {
                            width: 300
                            ListRow { text: "Codex"; value: "已安装"; dot: "positive"; accessory: "chevron"; forcedState: modelData }
                            ListRow { text: "API Key"; value: "sk-…3f9a"; valueMono: true; accessory: "chevron"; forcedState: modelData }
                        }
                    }
                }
            }
            Section {
                name: "Toggle"
                Repeater {
                    model: ["off", "on", "pressed-off", "pressed-on", "disabled-off", "disabled-on"]
                    Variant { label: modelData; Toggle { text: "开关"; forcedState: modelData } }
                }
            }
            Section {
                name: "RadioMark"
                Repeater {
                    model: ["off", "on", "disabled-off", "disabled-on"]
                    Variant { label: modelData; RadioMark { forcedState: modelData } }
                }
            }
            Section {
                name: "Tile"
                Repeater {
                    model: ["normal", "pressed", "disabled"]
                    Variant { label: modelData; Rectangle { width: 104; height: 96; color: Theme.side; Tile { anchors.fill: parent; anchors.margins: 6; iconName: "image"; text: "照片"; forcedState: modelData } } }
                }
            }
            Section {
                name: "MetaButton"
                Repeater {
                    model: ["collapsed", "expanded", "pressed"]
                    Variant { label: modelData; MetaButton { text: "已处理 2 步"; forcedState: modelData } }
                }
            }
            Section {
                name: "HoldTarget"
                Repeater {
                    model: ["idle", "active"]
                    Variant { label: "cancel " + modelData; HoldTarget { iconName: "close"; text: "取消"; forcedState: modelData } }
                }
                Repeater {
                    model: ["idle", "active"]
                    Variant { label: "text " + modelData; HoldTarget { iconName: "text"; text: "转文字"; edit: true; forcedState: modelData } }
                }
            }
            Section {
                name: "VoiceBar"
                wide: true
                Repeater {
                    model: ["idle", "pressed", "hot", "cancel", "handsFree", "disabled"]
                    Variant {
                        label: modelData
                        wide: true
                        VoiceBar {
                            id: vb
                            width: 330
                            forcedState: modelData
                            IconButton { iconName: "plus"; text: "添加"; tint: vb.ink; visible: vb.visualState === "idle" || vb.visualState === "pressed" || vb.visualState === "disabled" }
                            Wave {
                                visible: vb.visualState === "hot" || vb.visualState === "cancel" || vb.visualState === "handsFree"
                                Layout.fillWidth: true
                                Layout.leftMargin: 10
                                bars: 24
                                color: vb.ink
                                active: vb.visualState !== "cancel"
                                clip: true
                            }
                            Text {
                                visible: vb.visualState === "idle" || vb.visualState === "pressed" || vb.visualState === "disabled"
                                Layout.fillWidth: true
                                horizontalAlignment: Text.AlignHCenter
                                text: "按住说话"
                                font.family: Theme.fontFamily
                                font.pixelSize: Theme.bodySize
                                font.weight: Font.DemiBold
                                color: vb.ink
                            }
                            CircleButton { visible: vb.visualState === "handsFree"; iconName: "stop"; text: "停止聆听" }
                            IconButton { iconName: "keyboard"; text: "键盘"; tint: vb.ink; visible: vb.visualState === "idle" || vb.visualState === "pressed" || vb.visualState === "disabled" }
                        }
                    }
                }
            }
            Section {
                name: "SecretField"
                wide: true
                Repeater {
                    model: ["normal", "focused", "error", "disabled"]
                    Variant { label: modelData; wide: true; SecretField { width: 300; text: "sk-proj-xxxxxxxx3f9a"; forcedState: modelData } }
                }
            }
            Section {
                name: "Note"
                wide: true
                Repeater {
                    model: ["", "positive", "negative"]
                    Variant { label: modelData || "plain"; wide: true; Note { width: 300; tone: modelData; text: "密钥可用，已连上 OpenAI。" } }
                }
            }
            Section {
                name: "Progress · BusyRing · ShineText"
                wide: true
                Variant { label: "progress"; wide: true; Progress { width: 300 } }
                Variant { label: "busy ring"; BusyRing {} }
                Variant { label: "shine"; wide: true; ShineText { width: 300; text: "正在处理 · 12 秒 · 在微信里搜索联系人" } }
            }
        }
    }

    // A titled run of variants.
    component Section: ColumnLayout {
        id: sectionBox
        property string name
        property bool wide: false
        default property alias variants: flow.data
        Layout.fillWidth: true
        Layout.topMargin: 14
        visible: gallery.section === "" || gallery.section.split(",").indexOf(name) >= 0
        spacing: 8
        Text {
            text: sectionBox.name
            font.family: Theme.monoFamily
            font.pixelSize: Theme.labelSize
            color: Theme.dim
        }
        Flow {
            id: flow
            Layout.fillWidth: true
            spacing: 12
        }
    }
    // One state: the control above its state's name.
    component Variant: Column {
        property string label
        property bool wide: false
        spacing: 4
        Text {
            text: parent.label
            font.family: Theme.monoFamily
            font.pixelSize: 11
            color: Theme.faint
        }
    }
}
