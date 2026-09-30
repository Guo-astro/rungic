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

    title: i18nc("@title", "Services")
    leftPadding: 0
    rightPadding: 0
    topPadding: 0
    bottomPadding: Kirigami.Units.gridUnit

    readonly property var riskText: ({
        remote: i18nc("@info risk of a service", "Reachable from the network"),
        android: i18nc("@info risk of a service", "May affect Android"),
        unknown: i18nc("@info risk of a service", "Unknown impact"),
        none: i18nc("@info risk of a service", "No use on this device")
    })
    readonly property var evidenceText: ({
        recorded: "",
        inferred: i18nc("@info appended to a service's reason", " (inferred, not tested)"),
        unknown: i18nc("@info appended to a service's reason", " (reason not recorded)")
    })

    function describe(group) {
        return group.status + " · " + riskText[group.risk] + "\n" + group.summary + evidenceText[group.evidence]
            + "\n" + group.units.join(i18nc("@info separator between unit names", ", "))
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
        // On the window: inside the scrolling page it is centred in the whole (long) content.
        parent: QQC2.Overlay.overlay
        title: group ? i18nc("@title:window", "Turn on %1?", group.name) : ""
        subtitle: group ? group.warning : ""
        standardButtons: Kirigami.Dialog.Ok | Kirigami.Dialog.Cancel
        onAccepted: kcm.setEnabled(group.id, true)
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
            title: i18nc("@title:group", "Optional services")
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
                        onClicked: {
                            root.toggle(modelData, checked)
                            // The switch shows the real state, which refresh() reports once the change
                            // is made (or cancelled); the click must not leave it detached from it.
                            checked = Qt.binding(() => modelData.on)
                        }
                    }
                    // SSH: where to connect and what the client should show on the first connection.
                    FormCard.FormTextDelegate {
                        Layout.fillWidth: true
                        visible: modelData.id === "ssh" && modelData.on
                        text: i18nc("@label", "Command to connect")
                        description: kcm.addresses.length
                            ? kcm.addresses.map(a => i18nc("@info %1 an ssh command, %2 its network interface", "%1   (%2)",
                                                           "ssh " + kcm.userName + "@" + a.split(" ")[0], a.split("  ")[1])).join("\n")
                            : i18nc("@info", "No IPv4 address available")
                        textItem.wrapMode: Text.Wrap
                    }
                    FormCard.FormTextDelegate {
                        Layout.fillWidth: true
                        visible: modelData.id === "ssh" && modelData.on
                        text: i18nc("@label", "Host key fingerprint (ED25519)")
                        description: kcm.hostKey || i18nc("@info the host key", "Generating…")
                        descriptionItem.wrapMode: Text.WrapAnywhere
                    }
                    FormCard.FormTextDelegate {
                        Layout.fillWidth: true
                        visible: modelData.id === "ssh" && modelData.on
                        text: i18nc("@label", "Sign-in methods")
                        description: i18nc("@info", "Your account password, or a public key in ~/.ssh/authorized_keys")
                    }
                }
            }
        }

        FormCard.FormHeader {
            title: i18nc("@title:group", "Services masked by default")
        }
        FormCard.FormCard {
            FormCard.FormTextDelegate {
                text: i18nc("@label", "Why they are masked")
                description: i18nc("@info", "Android does what these services would do, or they have no use on this device. Allowing one only removes its mask: if it is enabled, it runs at the next boot or when something calls it. Turning it off masks it again and stops it at once.")
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
                    onClicked: {
                        root.toggle(modelData, checked)
                        // The switch shows the real state, which refresh() reports once the change is
                        // made (or cancelled); the click must not leave it detached from it.
                        checked = Qt.binding(() => modelData.on)
                    }
                }
            }
        }

        FormCard.FormHeader {
            visible: kcm.otherMasks.length > 0
            title: i18nc("@title:group", "Other masked services")
        }
        FormCard.FormCard {
            visible: kcm.otherMasks.length > 0
            Repeater {
                model: kcm.otherMasks
                delegate: FormCard.FormButtonDelegate {
                    required property var modelData
                    text: modelData.scope === "user" ? i18nc("@item a systemd user service", "%1 (user)", modelData.unit) : modelData.unit
                    description: i18nc("@info", "Not on Rungic's list. Tap to unmask.")
                    enabled: !kcm.busy
                    onClicked: kcm.unmask(modelData.unit, modelData.scope)
                }
            }
        }

        FormCard.FormHeader {
            title: i18nc("@title:group", "Masked by Ubuntu")
        }
        FormCard.FormCard {
            FormCard.FormTextDelegate {
                text: kcm.distributionMasks.length ? kcm.distributionMasks.join(i18nc("@info separator between unit names", ", ")) : i18nc("@info no masks", "None")
                textItem.wrapMode: Text.Wrap
                description: i18nc("@info", "Placeholders for old init scripts, not services that actually run. They can't be changed here.")
                descriptionItem.wrapMode: Text.Wrap
            }
        }
    }
}
