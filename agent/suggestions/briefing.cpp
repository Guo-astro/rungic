// SPDX-License-Identifier: GPL-2.0-or-later
#include "briefing.h"
#include "model.h"
#include <KLocalizedString>
#include <QDir>
#include <QHash>
#include <QJsonDocument>
#include <QRegularExpression>
#include <algorithm>

namespace Care {
using namespace BriefingLimits;

static const QStringList Kinds{"attention", "issues", "improvement", "result", "followup"};
// What an opened card asks of the Agent beyond presenting the findings. Fixed service text;
// the Agent's own `prompt` goes along only as a quoted note (service.cpp, the voice agent).
static constexpr auto FindingsPrompt = "Present each finding briefly in the chat: what happened, how it affects the user "
    "and what could be done. Then ask the user which of them to look into first.";
static constexpr auto ResultPrompt = "Present the result of the earlier investigation and its suggested next step, then "
    "ask the user what they want to do.";

static QString cleaned(const QString &text) {
    QString s = text;
    for (auto &c : s) {
        const auto category = c.category();
        if (category == QChar::Other_Control || category == QChar::Other_Format || category == QChar::Other_PrivateUse
            || category == QChar::Other_NotAssigned || category == QChar::Separator_Line || category == QChar::Separator_Paragraph)
            c = QLatin1Char(' ');
    }
    return s.simplified();
}
static QString elided(const QString &text, int max) {
    const auto s = cleaned(text);
    return s.size() <= max ? s : s.left(max - 1).trimmed() + QStringLiteral("…");
}
QString redact(const QString &text, int max) {
    QString s = text;
    const auto home = QDir::homePath();
    if (home.size() > 1) s.replace(home, QStringLiteral("~"));
    static const QRegularExpression homes(QStringLiteral(R"((?:~|/home|/root|/var/home|/data/user|/storage/emulated)/[^\s"'<>]*)"));
    static const QRegularExpression mails(QStringLiteral(R"([\w.+-]*@[\w-]+(?:\.[\w-]+)+)"));
    s.replace(homes, QStringLiteral("<private path>"));
    s.replace(mails, QStringLiteral("<email>"));
    return cleaned(s).left(max);
}
static QString encoded(const QJsonValue &v) {
    return QString::fromUtf8(v.isObject() ? QJsonDocument(v.toObject()).toJson(QJsonDocument::Compact)
                                          : QJsonDocument(v.toArray()).toJson(QJsonDocument::Compact));
}
static bool isOpen(const QJsonObject &o) {
    return QStringList{"new", "attention", "working", "snoozed"}.contains(o["state"].toString());
}
// Fallback and service cards only cover what needs the user: new findings and waiting results.
static bool pending(const QJsonObject &o) { return o["state"] == "new" || o["state"] == "attention"; }
static int bucket(int reports) {
    int b = 0;
    for (int threshold : {3, 10, 30, 100}) if (reports >= threshold) ++b;
    return b;
}
static QHash<QString, QJsonObject> byId(const QJsonArray &items) {
    QHash<QString, QJsonObject> result;
    for (const auto &v : items) result.insert(v.toObject()["id"].toString(), v.toObject());
    return result;
}

Briefing::Briefing(QString p) : path(std::move(p)) {}
bool Briefing::load() {
    const auto data = readObject(path);
    if (data["schema"].toInt() == 1) state = data;
    curating = false;
    return true;
}
bool Briefing::save(QString *error) const {
    if (path.isEmpty()) return true;
    auto data = state; data["schema"] = 1;
    return writeObject(path, data, error);
}
QString Briefing::material(const QJsonObject &o) {
    const auto task = o["task"].toObject();
    const QJsonObject m{{"delivery", o["deliveryRevision"]}, {"issue", o["issueState"]},
        {"reports", bucket(o["evidence"].toObject()["reports"].toInt())},
        {"review", task["needsReview"].toBool() ? task["id"].toString("review") : QString()}};
    return fingerprint(encoded(m));
}
QJsonObject Briefing::digest(const QJsonArray &items) {
    QJsonObject d;
    for (const auto &v : items) d[v.toObject()["id"].toString()] = material(v.toObject());
    return d;
}

QJsonArray Briefing::validate(const QJsonValue &output, const QJsonArray &items, QStringList *dropped) {
    QJsonArray result;
    const auto known = byId(items);
    const auto drop = [dropped](const QString &why) { if (dropped) dropped->append(why); };
    if (!output.isObject() || !output.toObject()["cards"].isArray()) { drop("output"); return result; }
    QSet<QString> topics;
    for (const auto &v : output.toObject()["cards"].toArray()) {
        if (result.size() >= MaxCards) { drop("count"); continue; }
        const auto c = v.toObject();
        const auto title = cleaned(c["title"].toString()), body = cleaned(c["body"].toString());
        const auto kind = c["kind"].toString();
        const auto action = c["action"].toObject();
        const auto label = cleaned(action["label"].toString()), prompt = cleaned(action["prompt"].toString());
        if (!v.isObject() || title.isEmpty() || title.size() > TitleMax || body.isEmpty() || body.size() > BodyMax) { drop("text"); continue; }
        if (!Kinds.contains(kind)) { drop("kind"); continue; }
        const auto priority = c["priority"].toDouble(-1);
        if (!c["priority"].isDouble() || priority < 0 || priority > 100 || priority != int(priority)) { drop("priority"); continue; }
        if (label.isEmpty() || label.size() > LabelMax || !action["prompt"].isString() || prompt.size() > PromptMax) { drop("action"); continue; }
        const auto refsIn = c["refs"].toArray();
        QStringList refs; bool bad = refsIn.isEmpty() || refsIn.size() > MaxRefs;
        for (const auto &r : refsIn) {
            if (!r.isString() || !known.contains(r.toString())) { bad = true; break; }
            if (!refs.contains(r.toString())) refs.append(r.toString());
        }
        if (bad) { drop("refs"); continue; }
        auto sorted = refs; sorted.sort();
        const auto topic = kind + ':' + sorted.join(',');
        if (topics.contains(topic)) { drop("duplicate"); continue; }
        topics.insert(topic);
        // Only these fields, rebuilt: nothing else of the model's output is kept.
        result.append(QJsonObject{{"id", "agent:" + fingerprint(topic)}, {"title", title}, {"body", body}, {"kind", kind},
            {"priority", int(priority)}, {"refs", QJsonArray::fromStringList(refs)},
            {"action", QJsonObject{{"label", label}, {"prompt", prompt}}},
            {"notify", c["notify"].toBool(false)}, {"origin", "agent"}});
    }
    return result;
}

QJsonArray Briefing::fallbackCards(const QJsonArray &items) {
    QJsonArray cards;
    QList<QJsonObject> findings, results;
    for (const auto &v : items) {
        const auto o = v.toObject();
        if (o["state"] == "attention") results.append(o);
        else if (o["state"] == "new") findings.append(o);
    }
    if (!findings.isEmpty()) {
        QStringList refs, names; bool severe = false;
        for (const auto &o : findings) {
            if (refs.size() < MaxRefs) refs.append(o["id"].toString());
            severe |= o["severity"].toInt() >= 2;
            const auto name = cleaned(o["displayTitle"].toString(o["title"].toString()));
            if (!name.isEmpty() && !names.contains(name)) names.append(name);
        }
        const int n = findings.size();
        QString title, body, label;
        if (n == 1) {
            title = elided(findings[0]["displayTitle"].toString(findings[0]["title"].toString()), TitleMax);
            body = elided(findings[0]["summary"].toString(findings[0]["body"].toString()), BodyMax);
            label = i18nc("@action suggestion card", "Ask Agent about it");
        } else {
            title = i18ncp("@title suggestion card", "%1 finding to look at", "%1 findings to look at", n);
            // As many names as fit, the rest left out.
            for (int shown = qMin<int>(3, names.size()); shown >= 0; --shown) {
                body = shown ? i18nc("@info suggestion card, %1 lists a few findings", "Including %1. Agent can go through them with you.", names.mid(0, shown).join(i18nc("list separator", ", ")))
                             : i18nc("@info suggestion card", "Agent can go through them with you and tell you which ones matter.");
                if (body.size() <= BodyMax) break;
            }
            body = elided(body, BodyMax);
            label = i18nc("@action suggestion card", "Go through them with Agent");
        }
        if (body.isEmpty()) body = i18nc("@info suggestion card", "Agent can look into it with you.");
        refs.sort();
        cards.append(QJsonObject{{"id", "fallback:findings:" + fingerprint(refs.join(','))}, {"title", title}, {"body", body},
            {"kind", severe ? "attention" : "issues"}, {"priority", severe ? 70 : 60}, {"refs", QJsonArray::fromStringList(refs)},
            {"action", QJsonObject{{"label", label}, {"prompt", FindingsPrompt}}}, {"notify", false}, {"origin", "service"}});
    }
    for (const auto &o : results) {
        if (cards.size() >= MaxCards) break;
        const auto name = cleaned(o["displayTitle"].toString(o["title"].toString()));
        auto body = elided(o["summary"].toString(), BodyMax);
        if (body.isEmpty()) body = i18nc("@info suggestion card", "Agent finished looking into this. See what it found.");
        const auto id = o["id"].toString();
        cards.append(QJsonObject{{"id", "fallback:result:" + fingerprint(id + ':' + o["task"].toObject()["id"].toString())},
            {"title", elided(i18nc("@title suggestion card, %1 is what was investigated", "Result: %1", name), TitleMax)},
            {"body", body}, {"kind", "result"}, {"priority", 80}, {"refs", QJsonArray{id}},
            {"action", QJsonObject{{"label", i18nc("@action suggestion card", "See the result")}, {"prompt", ResultPrompt}}},
            {"notify", false}, {"origin", "service"}});
    }
    return cards;
}

bool Briefing::observe(const QJsonArray &items, qint64 now) {
    const auto d = digest(items), seen = state["seen"].toObject();
    // Dismissals end with a material change of their record.
    auto dismissed = state["dismissed"].toObject();
    for (const auto &ref : dismissed.keys()) if (dismissed[ref] != d[ref]) dismissed.remove(ref);
    state["dismissed"] = dismissed;
    if (d == seen) return false;
    bool urgent = false;
    const auto known = byId(items);
    for (auto it = d.begin(); it != d.end(); ++it) {
        if (seen[it.key()] == it.value()) continue;
        const auto o = known.value(it.key());
        urgent |= o["task"].toObject()["needsReview"].toBool() || (o["severity"].toInt() >= 2 && o["issueState"] == "observed");
    }
    state["seen"] = d;
    state["lastChange"] = now;
    if (!state["pendingSince"].toInteger()) state["pendingSince"] = now;
    if (urgent) state["urgent"] = true;
    return true;
}
static QList<qint64> recent(const QJsonArray &attempts, qint64 now) {
    QList<qint64> result;
    for (const auto &v : attempts) if (v.toInteger() > now - 86400 && v.toInteger() <= now) result.append(v.toInteger());
    std::sort(result.begin(), result.end());
    return result;
}
bool Briefing::capped(qint64 now) const { return recent(state["attempts"].toArray(), now).size() >= DailyCap; }
qint64 Briefing::nextRun(qint64 now) const {
    if (!state["pendingSince"].toInteger()) return 0;
    qint64 at = state["lastChange"].toInteger() + Debounce;
    if (const auto last = state["lastAttempt"].toInteger())
        at = qMax(at, last + (state["urgent"].toBool() ? MinIntervalUrgent : MinInterval));
    const auto attempts = recent(state["attempts"].toArray(), now);
    if (attempts.size() >= DailyCap) at = qMax(at, attempts[attempts.size() - DailyCap] + 86400);
    return at;
}

QJsonObject Briefing::redacted(const QJsonObject &o, const QJsonObject &dismissed) {
    const auto e = o["evidence"].toObject(), task = o["task"].toObject();
    QJsonObject r{{"id", o["id"]}, {"group", o["groupId"]}, {"kind", redact(o["kind"].toString(), 30)},
        {"source", redact(o["source"].toString(), 60)}, {"title", redact(o["displayTitle"].toString(o["title"].toString()), 120)},
        {"state", o["state"]}, {"severity", o["severity"].toInt()}, {"firstSeen", o["created"].toInteger()},
        {"lastSeen", o["lastObserved"].toInteger()}, {"dismissedByUser", dismissed.contains(o["id"].toString())}};
    for (const auto &key : {"package", "version", "signature", "signal", "unit", "process", "knowledge", "mount", "state", "scope"})
        if (e[key].isString() && !e[key].toString().isEmpty()) r[QStringLiteral("evidence_") + key] = redact(e[key].toString(), 80);
    for (const auto &key : {"reports", "availableBytes", "totalBytes"}) if (e[key].isDouble()) r[QStringLiteral("evidence_") + key] = e[key];
    static const QList<std::pair<QString, int>> texts{{"conclusion", 220}, {"nextStep", 100}, {"confidence", 20}, {"planStatus", 30}};
    for (const auto &[key, max] : texts)
        if (!o[key].toString().isEmpty()) r[key] = redact(o[key].toString(), max);
    if (!task.isEmpty()) r["task"] = QJsonObject{{"state", task["state"].toString("idle")}, {"mode", task["mode"].toString()},
                                                  {"resultWaitingForUser", task["needsReview"].toBool()}};
    if (o["upstream"].toObject()["state"].isString()) r["upstream"] = o["upstream"].toObject()["state"];
    return r;
}
QJsonObject Briefing::input(const QJsonArray &items, qint64 now) const {
    QJsonArray records; int omitted = 0;
    const auto dismissed = state["dismissed"].toObject();
    for (const auto &v : items) {
        const auto o = v.toObject();
        const bool resolved = o["state"] == "resolved" && now - o["updated"].toInteger() < ResolvedShown;
        if (!isOpen(o) && !resolved) continue;
        if (records.size() >= InputItems) { ++omitted; continue; }
        records.append(redacted(o, dismissed));
    }
    QJsonArray current;
    for (const auto &v : state["cards"].toArray()) {
        const auto c = v.toObject();
        current.append(QJsonObject{{"title", redact(c["title"].toString(), TitleMax)}, {"kind", c["kind"]}, {"refs", c["refs"]}});
    }
    return {{"schema", 1}, {"now", now}, {"items", records}, {"omitted", omitted}, {"currentCards", current},
            {"feedback", feedback(now)},
            {"limits", QJsonObject{{"maxCards", MaxCards}, {"titleMax", TitleMax}, {"bodyMax", BodyMax}, {"labelMax", LabelMax},
                                   {"promptMax", PromptMax}, {"maxRefs", MaxRefs}, {"kinds", QJsonArray::fromStringList(Kinds)}}}};
}
void Briefing::begin(const QJsonArray &items, qint64 now) {
    curating = true;
    auto attempts = QJsonArray();
    for (auto t : recent(state["attempts"].toArray(), now)) attempts.append(t);
    attempts.append(now);
    state["attempts"] = attempts; state["lastAttempt"] = now;
    state["pendingSince"] = 0; state["urgent"] = false;
    state["pendingBasis"] = digest(items);
    state["seen"] = state["pendingBasis"];
}
bool Briefing::applyAgent(const QJsonValue &output, const QJsonArray &items, qint64 now, QStringList *dropped) {
    curating = false;
    const auto cards = validate(output, items, dropped);
    if (!output.isObject() || !output.toObject()["cards"].isArray() || (cards.isEmpty() && !output.toObject()["cards"].toArray().isEmpty()))
        return false;
    const auto basis = state.contains("pendingBasis") ? state.take("pendingBasis").toObject() : digest(items);
    state["basis"] = basis; state["basisRevision"] = fingerprint(encoded(basis));
    state["cards"] = cards; state["source"] = "agent"; state["generatedAt"] = now; state["error"] = QString();
    state["revision"] = state["revision"].toInteger() + 1;
    return true;
}
void Briefing::applyFallback(const QJsonArray &items, qint64 now, const QString &error) {
    curating = false;
    state.remove("pendingBasis");
    const auto basis = digest(items);
    state["basis"] = basis; state["basisRevision"] = fingerprint(encoded(basis));
    state["cards"] = fallbackCards(items); state["source"] = "fallback"; state["generatedAt"] = now; state["error"] = error;
    state["revision"] = state["revision"].toInteger() + 1;
}

QJsonArray Briefing::cards(const QJsonArray &items) const {
    const auto known = byId(items);
    QList<QJsonObject> list;
    if (source() == "agent") {
        for (const auto &v : state["cards"].toArray()) {
            auto c = v.toObject(); QJsonArray refs;
            for (const auto &r : c["refs"].toArray()) if (known.contains(r.toString())) refs.append(r);
            if (refs.isEmpty()) continue;
            c["refs"] = refs; list.append(c);
        }
        // What the curator hasn't seen yet shows as the deterministic cards until it has.
        const auto basis = state["basis"].toObject();
        QJsonArray unseen;
        for (const auto &v : items) {
            const auto o = v.toObject();
            if (pending(o) && basis[o["id"].toString()] != material(o)) unseen.append(o);
        }
        for (const auto &v : fallbackCards(unseen)) list.append(v.toObject());
    } else {
        for (const auto &v : fallbackCards(items)) list.append(v.toObject());
    }
    const auto dismissed = state["dismissed"].toObject();
    QJsonArray result;
    std::stable_sort(list.begin(), list.end(), [](const auto &a, const auto &b) { return a["priority"].toInt() > b["priority"].toInt(); });
    for (auto c : list) {
        bool hidden = true;
        for (const auto &r : c["refs"].toArray())
            if (dismissed[r.toString()].toString() != material(known.value(r.toString()))) hidden = false;
        if (hidden || result.size() >= MaxCards) continue;
        c["count"] = c["refs"].toArray().size();
        result.append(c);
    }
    return result;
}
QJsonObject Briefing::card(const QString &id, const QJsonArray &items) const {
    for (const auto &v : cards(items)) if (v.toObject()["id"] == id) return v.toObject();
    return {};
}
QJsonObject Briefing::view(const QJsonArray &items, bool background, qint64 now) const {
    QJsonArray cards;
    for (const auto &v : this->cards(items)) {
        auto c = v.toObject(); auto action = c["action"].toObject(); action.remove("prompt");
        c["action"] = action; cards.append(c);   // the Agent's note for the conversation isn't UI text
    }
    return {{"revision", state["revision"].toInteger()}, {"generatedAt", state["generatedAt"].toInteger()},
            {"source", source().isEmpty() ? QStringLiteral("fallback") : source()}, {"basisRevision", state["basisRevision"].toString()},
            {"cards", cards}, {"curating", curating}, {"error", state["error"].toString()},
            {"backgroundCuration", background}, {"pending", state["pendingSince"].toInteger() > 0},
            {"nextCuration", background ? nextRun(now) : 0}};
}
void Briefing::remember(const QJsonObject &card, const QString &action, qint64 now) {
    auto list = feedback(now);
    list.append(QJsonObject{{"at", now}, {"action", action}, {"kind", card["kind"]},
        {"title", redact(card["title"].toString(), TitleMax)}, {"refs", card["refs"]}});
    while (list.size() > FeedbackKept) list.removeFirst();
    state["feedback"] = list;
}
bool Briefing::dismiss(const QString &id, const QJsonArray &items, qint64 now) {
    const auto c = card(id, items);
    if (c.isEmpty()) return false;
    const auto known = byId(items);
    auto dismissed = state["dismissed"].toObject();
    for (const auto &r : c["refs"].toArray()) dismissed[r.toString()] = material(known.value(r.toString()));
    state["dismissed"] = dismissed;
    remember(c, "dismissed", now);
    return true;
}
bool Briefing::opened(const QString &id, const QJsonArray &items, qint64 now) {
    const auto c = card(id, items);
    if (c.isEmpty()) return false;
    remember(c, "opened", now);
    return true;
}
QJsonArray Briefing::feedback(qint64 now) const {
    QJsonArray result;
    for (const auto &v : state["feedback"].toArray())
        if (now - v.toObject()["at"].toInteger() < FeedbackDays * 86400) result.append(v);
    return result;
}
}
