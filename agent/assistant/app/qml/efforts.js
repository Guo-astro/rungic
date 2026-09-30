// SPDX-License-Identifier: GPL-2.0-or-later
// The words for reasoning efforts (docs/98), shared by the settings and the model page. The
// catalog gives effort ids and English descriptions; the app says them in the desktop's language.
// i18nc is the page's own, passed in as a function (a library has no context to find it in).
.pragma library

function name(i18nc, id) {
    switch (id) {
    case "none": return i18nc("@item reasoning effort", "None")
    case "minimal": return i18nc("@item reasoning effort", "Minimal")
    case "low": return i18nc("@item reasoning effort", "Low")
    case "medium": return i18nc("@item reasoning effort", "Medium")
    case "high": return i18nc("@item reasoning effort", "High")
    case "xhigh": return i18nc("@item reasoning effort", "Extra high")
    case "max": return i18nc("@item reasoning effort", "Max")
    case "ultra": return i18nc("@item reasoning effort", "Ultra")
    default: return id || ""
    }
}

function note(i18nc, effort) {
    switch (effort.id) {
    case "none": case "minimal": return i18nc("@info reasoning effort", "Answers at once, for the simplest requests")
    case "low": return i18nc("@info reasoning effort", "Quick, for everyday tasks on the phone")
    case "medium": return i18nc("@info reasoning effort", "Balances speed and care")
    case "high": return i18nc("@info reasoning effort", "Thinks longer about harder tasks")
    case "xhigh": return i18nc("@info reasoning effort", "Thinks much longer; noticeably slower")
    case "max": return i18nc("@info reasoning effort", "Slow, and uses much more of your plan")
    case "ultra": return i18nc("@info reasoning effort", "The most thorough; only for the rare very hard task")
    default: return effort.description || ""
    }
}
