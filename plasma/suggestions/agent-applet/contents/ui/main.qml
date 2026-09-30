// SPDX-License-Identifier: GPL-2.0-or-later
import QtQuick
import QtQuick.Layouts
import org.kde.plasma.plasmoid
import org.kde.plasma.core as PlasmaCore
import com.rungic.suggestions

PlasmoidItem {
    id: root
    Plasmoid.backgroundHints: PlasmaCore.Types.NoBackground
    preferredRepresentation: fullRepresentation
    // Home-screen cells touch each other: the card keeps 6 px above and below.
    fullRepresentation: Item {
        Layout.minimumWidth: 160
        Layout.minimumHeight: 90
        Layout.preferredWidth: 340
        Layout.preferredHeight: 100
        AgentWidget { anchors.fill: parent; anchors.topMargin: 6; anchors.bottomMargin: 6 }
    }
}
