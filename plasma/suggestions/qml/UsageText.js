.pragma library
// Shared by AgentWidget and AgentUsageDetails; `l10n` is the caller's KI18nContext (rungic-suggestions).
// `p` is one provider of AgentUsage schema 2 (docs/research/95), {} while none is known.
function number(l10n, value) { return value === undefined || value === null ? l10n.i18n("no records yet") : Number(value).toLocaleString(Qt.locale(), "f", 0) }
function mode(l10n, p) {
    const a = p.account || {}
    if (!p.id || p.status === "connecting") return l10n.i18n("Connecting")
    return ({"api-key": a.label || "API Key", subscription: a.label || l10n.i18n("Subscription"), none: l10n.i18n("Not signed in")})[a.kind] || l10n.i18n("Not signed in")
}
function status(l10n, p) {
    return ({working: l10n.i18n("Working"), ready: l10n.i18n("Ready"), offline: l10n.i18n("Not connected"), "signed-out": l10n.i18n("Not signed in"), error: l10n.i18n("Unavailable")})[p.status] || l10n.i18n("Connecting")
}
function windowName(l10n, w) {
    const m = w.windowMinutes
    return !m ? l10n.i18n("Usage window") : m >= 1440 ? l10n.i18np("%1-day limit", "%1-day limit", m / 1440) : m >= 60 ? l10n.i18np("%1-hour limit", "%1-hour limit", m / 60) : l10n.i18np("%1-minute limit", "%1-minute limit", m)
}
function reset(l10n, w, now) {
    if (!w.resetsAt) return l10n.i18n("No reset time given")
    const mins = Math.ceil((w.resetsAt - now) / 60)
    if (mins <= 0) return l10n.i18n("Reset time reached, waiting for an update")
    return mins >= 60 ? l10n.i18nc("@info %1 hours and %2 minutes", "Resets in %1 h %2 min", Math.floor(mins / 60), mins % 60) : l10n.i18nc("@info", "Resets in %1 min", mins)
}
function token(l10n, p) { const t = (p.tokens || {}).device; return t === undefined || t === null ? l10n.i18n("No usage recorded yet") : l10n.i18n("%1 tokens recorded on this device", number(l10n, t)) }
