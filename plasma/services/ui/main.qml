// SPDX-License-Identifier: MIT
// Settings -> Services (docs/83).
import QtQuick
import QtQuick.Controls as QQC2
import QtQuick.Layouts

import org.kde.kcmutils as KCM
import org.kde.kirigami as Kirigami
import org.kde.kirigamiaddons.formcard as FormCard

KCM.SimpleKCM {
    id: root

    title: "系统服务"
    leftPadding: 0
    rightPadding: 0
    topPadding: 0
    bottomPadding: Kirigami.Units.gridUnit

    readonly property var riskText: ({
        remote: "可从网络访问",
        android: "可能影响 Android",
        unknown: "影响未知",
        none: "在本机没有作用"
    })
    readonly property var evidenceText: ({
        recorded: "",
        inferred: "（推测，未实测）",
        unknown: "（原因未记录）"
    })

    function describe(group) {
        return group.status + " · " + riskText[group.risk] + "\n" + group.summary + evidenceText[group.evidence]
            + "\n" + group.units.join("、")
    }

    // Turning on something with a risk asks first; turning off does not.
    function toggle(group, on) {
        if (on && group.warning) {
            confirm.group = group
            confirm.open()
        } else {
            kcm.setEnabled(group.id, on)
        }
    }

    Kirigami.PromptDialog {
        id: confirm
        property var group
        title: group ? "开启 " + group.name + "？" : ""
        subtitle: group ? group.warning : ""
        standardButtons: Kirigami.Dialog.Ok | Kirigami.Dialog.Cancel
        onAccepted: kcm.setEnabled(group.id, true)
        onRejected: kcm.refresh()   // the switch goes back to the real state
    }

    header: QQC2.Control {
        padding: Kirigami.Units.smallSpacing
        visible: kcm.error !== "" || kcm.busy
        contentItem: ColumnLayout {
            Kirigami.InlineMessage {
                Layout.fillWidth: true
                visible: kcm.error !== ""
                type: Kirigami.MessageType.Error
                text: kcm.error
            }
            QQC2.ProgressBar {
                Layout.fillWidth: true
                visible: kcm.busy
                indeterminate: true
            }
        }
    }

    ColumnLayout {
        spacing: 0

        FormCard.FormHeader {
            title: "可选服务"
        }
        FormCard.FormCard {
            Repeater {
                model: kcm.groups.filter(g => g.kind === "optional")
                delegate: ColumnLayout {
                    required property var modelData
                    Layout.fillWidth: true
                    spacing: 0

                    FormCard.FormSwitchDelegate {
                        Layout.fillWidth: true
                        text: modelData.name
                        description: modelData.status + "\n" + modelData.summary
                        checked: modelData.on
                        enabled: !kcm.busy
                        onToggled: root.toggle(modelData, checked)
                    }
                    // SSH: where to connect and what the client should show on the first connection.
                    FormCard.FormTextDelegate {
                        Layout.fillWidth: true
                        visible: modelData.id === "ssh" && modelData.on
                        text: "连接命令"
                        description: kcm.addresses.length
                            ? kcm.addresses.map(a => "ssh " + kcm.userName + "@" + a.split(" ")[0] + "   （" + a.split("  ")[1] + "）").join("\n")
                            : "没有可用的 IPv4 地址"
                        textItem.wrapMode: Text.Wrap
                    }
                    FormCard.FormTextDelegate {
                        Layout.fillWidth: true
                        visible: modelData.id === "ssh" && modelData.on
                        text: "主机密钥指纹（ED25519）"
                        description: kcm.hostKey || "正在生成…"
                        descriptionItem.wrapMode: Text.WrapAnywhere
                    }
                    FormCard.FormTextDelegate {
                        Layout.fillWidth: true
                        visible: modelData.id === "ssh" && modelData.on
                        text: "登录方式"
                        description: "账户密码，或 ~/.ssh/authorized_keys 中的公钥"
                    }
                }
            }
        }

        FormCard.FormHeader {
            title: "默认屏蔽的服务"
        }
        FormCard.FormCard {
            FormCard.FormTextDelegate {
                text: "为什么屏蔽"
                description: "这些服务的功能由 Android 负责，或者在本机没有作用。允许运行只是解除屏蔽：已启用的服务会在下次开机或被调用时运行。关闭会重新屏蔽并立即停止。"
                descriptionItem.wrapMode: Text.Wrap
            }
            Repeater {
                model: kcm.groups.filter(g => g.kind === "masked")
                delegate: FormCard.FormSwitchDelegate {
                    required property var modelData
                    text: modelData.name
                    description: root.describe(modelData)
                    checked: modelData.on
                    enabled: !kcm.busy
                    onToggled: root.toggle(modelData, checked)
                }
            }
        }

        FormCard.FormHeader {
            visible: kcm.otherMasks.length > 0
            title: "其他被屏蔽的服务"
        }
        FormCard.FormCard {
            visible: kcm.otherMasks.length > 0
            Repeater {
                model: kcm.otherMasks
                delegate: FormCard.FormButtonDelegate {
                    required property var modelData
                    text: modelData.unit + (modelData.scope === "user" ? "（用户）" : "")
                    description: "不在 Rungic 的清单里，点按解除屏蔽"
                    enabled: !kcm.busy
                    onClicked: kcm.unmask(modelData.unit, modelData.scope)
                }
            }
        }

        FormCard.FormHeader {
            title: "Ubuntu 自带的屏蔽"
        }
        FormCard.FormCard {
            FormCard.FormTextDelegate {
                text: kcm.distributionMasks.length ? kcm.distributionMasks.join("、") : "无"
                textItem.wrapMode: Text.Wrap
                description: "旧式启动脚本的兼容占位，不是实际运行的服务，不能在这里更改。"
                descriptionItem.wrapMode: Text.Wrap
            }
        }
    }
}
