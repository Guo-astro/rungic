// SPDX-License-Identifier: GPL-2.0-or-later
// A setting that is on or off (docs/102): a row with a switch. The whole row switches it, and
// darkens while pressed as every row that can be tapped does; the switch's knob widens with it.
// States: the row's (normal, pressed, disabled) with the switch's (off, on).
import QtQuick
import com.rungic.design

ListRow {
    id: row
    // `checked` (AbstractButton's) is the setting; a tap on the row flips it (checkable).
    // The user switched it: `checked` is the new state.
    signal switched(bool checked)
    checkable: true
    interactive: true
    Accessible.role: Accessible.CheckBox
    Accessible.checkable: true
    Accessible.checked: checked
    Connections { target: row; function onToggled() { row.switched(row.checked) } }
    trailing: Toggle {
        text: row.text
        checked: row.checked
        enabled: row.enabled
        // Pressing the row presses the switch too; the row owns the tap.
        forcedState: row.visualState === "pressed" ? (row.checked ? "pressed-on" : "pressed-off") : ""
        onToggled: { row.checked = checked; row.switched(checked) }
    }
}
