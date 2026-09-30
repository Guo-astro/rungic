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
        Layout.minimumWidth: 250
        Layout.minimumHeight: 190
        Layout.preferredWidth: 340
        Layout.preferredHeight: 340
        SuggestionsWidget { anchors.fill: parent; anchors.topMargin: 6; anchors.bottomMargin: 6 }
    }
}
