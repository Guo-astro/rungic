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
    fullRepresentation: AgentWidget {
        Layout.minimumWidth: 250
        Layout.minimumHeight: 105
        Layout.preferredWidth: 340
        Layout.preferredHeight: 126
    }
}
