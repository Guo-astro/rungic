// SPDX-License-Identifier: GPL-2.0-or-later
// One choice among several (docs/102): a row with a radio mark. Like every row that can be tapped
// it darkens while pressed, so a tap is felt before the mark moves; the mark shows the choice.
// States: the row's (normal, pressed, disabled) with the mark's (off, on).
import QtQuick
import com.rungic.design

ListRow {
    id: row
    // `checked` (AbstractButton's): whether this is the chosen one. Not checkable: a tap asks for
    // the choice (clicked), whoever holds it sets `checked`.
    interactive: true
    Accessible.role: Accessible.RadioButton
    Accessible.checkable: true
    Accessible.checked: checked
    leading: RadioMark {
        on: row.checked
        enabled: row.enabled
    }
}
