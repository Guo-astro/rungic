// SPDX-License-Identifier: GPL-2.0-or-later
#include "service.h"
#include "collector.h"
#include <KLocalizedString>
#include <QDBusConnection>
#include <QDBusConnectionInterface>
#include <QDBusInterface>
#include <QDBusPendingCallWatcher>
#include <QDBusPendingReply>
#include <QDBusReply>
#include <QDBusVariant>
#include <QDateTime>
#include <QDir>
#include <QFileInfo>
#include <QFutureWatcher>
#include <QJsonDocument>
#include <QProcess>
#include <QProcessEnvironment>
#include <QStandardPaths>
#include <QTimer>
#include <memory>
#include <QUrl>
#include <QtConcurrent>

static QString encoded(const QJsonObject &o) { return QString::fromUtf8(QJsonDocument(o).toJson(QJsonDocument::Compact)); }
static QString failure(const QString &s) { return encoded({{"error", s}}); }
static constexpr auto Voice = "com.rungic.VoiceAgent";
static constexpr auto VoicePath = "/com/rungic/VoiceAgent";

Suggestions::Suggestions(const QString &state, const QString &feed, const QString &kb, QObject *parent)
    : QObject(parent), model(state), usage(QFileInfo(state).absolutePath() + "/agent-usage.json"), feedPath(feed), knowledgePath(kb), statePath(state) {
    QString error;
    ready = model.load(&error);
    if (!ready) { qCritical("%s", qPrintable(error)); return; }
    model.recoverTasks();
    loadUsageProviders(QDateTime::currentSecsSinceEpoch());
    auto bus = QDBusConnection::sessionBus();
    bus.connect(Voice, VoicePath, Voice, "Event", this, SLOT(AgentEvent(QString)));
    bus.connect("org.freedesktop.Notifications", "/org/freedesktop/Notifications", "org.freedesktop.Notifications",
                "ActionInvoked", this, SLOT(NotificationAction(uint,QString)));
    bus.connect("org.freedesktop.Notifications", "/org/freedesktop/Notifications", "org.freedesktop.Notifications",
                "ActivationToken", this, SLOT(NotificationToken(uint,QString)));
    bus.connect("org.freedesktop.Notifications", "/org/freedesktop/Notifications", "org.freedesktop.Notifications",
                "NotificationClosed", this, SLOT(NotificationClosed(uint,uint)));
    connect(bus.interface(), &QDBusConnectionInterface::serviceOwnerChanged, this,
            [this](const QString &name, const QString &, const QString &owner) {
                if (owner.isEmpty()) visibleClients.remove(name);
                for (const auto &p : usage.providers()) {
                    if (!p.dbus() || p.service != name) continue;
                    if (owner.isEmpty()) { usage.failure(p.id, {}, true); Q_EMIT UsageChanged(); }
                    else ProviderChanged(p.id);
                }
                if (name == Voice) {
                    if (owner.isEmpty()) { model.recoverTasks(); publish(); }
                    else recover();
                }
            });
    scanTimer.setInterval(60000);
    connect(&scanTimer, &QTimer::timeout, this, &Suggestions::Refresh);
    scanTimer.start(); QTimer::singleShot(0, this, &Suggestions::Refresh);
}
// Agent usage (docs/research/95): each provider's source is read only while someone looks at the
// usage (AgentUsage calls within the last few minutes), at most every 30 s unless it says it changed.
static constexpr qint64 UsageInterval = 30, UsageWatchWindow = 180, UsageReplyLimit = 1024 * 1024;
void Suggestions::loadUsageProviders(qint64 now) {
    providersLoaded = now;
    QStringList directories;
    const auto override = qEnvironmentVariable("RUNGIC_AGENT_USAGE_PROVIDERS");
    if (!override.isEmpty()) directories = override.split(':', Qt::SkipEmptyParts);
    else {
        // XDG_DATA_DIRS lowest precedence first (/usr/share), the user's own ~/.local/share last.
        const auto locations = QStandardPaths::standardLocations(QStandardPaths::GenericDataLocation);
        for (auto it = locations.crbegin(); it != locations.crend(); ++it) directories.append(*it + "/rungic/agent-usage/providers");
    }
    QStringList errors;
    usage.setProviders(Care::usageProviders(directories, &errors));
    if (errors != usageDescriptorErrors) for (const auto &e : errors) qWarning("agent usage descriptor ignored: %s", qPrintable(e));
    usageDescriptorErrors = errors;
}
QString Suggestions::AgentUsage() {
    RefreshAgentUsage();
    return encoded(usage.view(QDateTime::currentSecsSinceEpoch()));
}
void Suggestions::RefreshAgentUsage() {
    const auto now = QDateTime::currentSecsSinceEpoch();
    usageWatched = now;
    if (now - providersLoaded >= UsageInterval) loadUsageProviders(now); // packages add and remove adapters
    for (const auto &p : usage.providers()) refreshUsage(p, false);
}
void Suggestions::ProviderChanged(const QString &id) {
    if (calledFromDBus()) usagePushers.insert(id);
    for (const auto &p : usage.providers()) {
        if (p.id != id) continue;
        if (QDateTime::currentSecsSinceEpoch() - usageWatched < UsageWatchWindow) refreshUsage(p, true);
        else usageFetches[id].dirty = true; // read first thing when someone looks again
    }
}
void Suggestions::RecordTokens(const QString &provider, const QString &json) {
    if (calledFromDBus()) usagePushers.insert(provider);
    if (usage.record(provider, QJsonDocument::fromJson(json.toUtf8()).object(), QDateTime::currentSecsSinceEpoch())) Q_EMIT UsageChanged();
}
void Suggestions::refreshUsage(const Care::UsageProvider &p, bool force) {
    auto &f = usageFetches[p.id];
    const auto now = QDateTime::currentSecsSinceEpoch();
    if (force) f.dirty = true;
    if (f.running) return; // read again when this one finishes
    if (!f.dirty && now - f.attempt < UsageInterval) return;
    if (now - f.attempt < 2) {
        QTimer::singleShot(2000, this, [this, id = p.id] {
            for (const auto &q : usage.providers()) if (q.id == id) refreshUsage(q, false);
        });
        return;
    }
    f.running = true; f.dirty = false; f.attempt = now;
    readUsage(p);
}
void Suggestions::usageDone(const Care::UsageProvider &p) {
    auto &f = usageFetches[p.id];
    f.running = false;
    Q_EMIT UsageChanged();
    if (f.dirty && QDateTime::currentSecsSinceEpoch() - usageWatched < UsageWatchWindow) refreshUsage(p, false);
}
void Suggestions::accept(const Care::UsageProvider &p, const QByteArray &reply) {
    QJsonParseError error{};
    const auto document = QJsonDocument::fromJson(reply, &error);
    if (error.error != QJsonParseError::NoError || !document.isObject()) usage.failure(p.id, i18n("%1 returned usage that can't be read", p.name));
    else usage.snapshot(p.id, document.object(), QDateTime::currentSecsSinceEpoch());
}
void Suggestions::readUsage(const Care::UsageProvider &p) {
    if (p.dbus()) {
        auto request = QDBusMessage::createMethodCall(p.service, p.path, p.interface, p.method);
        request.setAutoStartService(false); // not running is "offline", not a reason to start an agent
        auto *w = new QDBusPendingCallWatcher(QDBusConnection::sessionBus().asyncCall(request, p.timeout), this);
        connect(w, &QDBusPendingCallWatcher::finished, this, [this, w, p] {
            QDBusPendingReply<QString> reply = *w; w->deleteLater();
            if (!reply.isError()) accept(p, reply.value().toUtf8());
            else if (reply.error().type() == QDBusError::ServiceUnknown || reply.error().name() == "org.freedesktop.DBus.Error.NameHasNoOwner")
                usage.failure(p.id, {}, true);
            else usage.failure(p.id, i18n("%1 usage is unavailable right now; try again later", p.name));
            usageDone(p);
        });
        return;
    }
    // A reader: no shell, no input, bounded output and time.
    auto *process = new QProcess(this);
    process->setProgram(p.command.first());
    process->setArguments(p.command.mid(1));
    process->setStandardInputFile(QProcess::nullDevice());
    process->setStandardErrorFile(QProcess::nullDevice());
    struct Run { QByteArray output; bool done = false, late = false; };
    auto run = std::make_shared<Run>();
    const auto finish = [this, process, p, run](const QString &problem) {
        if (run->done) return;
        run->done = true;
        if (problem.isEmpty()) accept(p, run->output); else usage.failure(p.id, problem);
        process->deleteLater();
        usageDone(p);
    };
    connect(process, &QProcess::readyReadStandardOutput, this, [process, run] {
        run->output += process->readAllStandardOutput();
        if (run->output.size() > UsageReplyLimit) process->kill();
    });
    connect(process, &QProcess::finished, this, [process, p, run, finish](int code, QProcess::ExitStatus status) {
        run->output += process->readAllStandardOutput();
        if (run->late) finish(i18n("The usage reader for %1 didn't answer in time", p.name));
        else if (status != QProcess::NormalExit || code != 0 || run->output.size() > UsageReplyLimit) finish(i18n("The usage reader for %1 failed", p.name));
        else finish({});
    });
    connect(process, &QProcess::errorOccurred, this, [p, finish](QProcess::ProcessError e) {
        if (e == QProcess::FailedToStart) finish(i18n("The usage reader for %1 isn't installed", p.name));
    });
    QTimer::singleShot(p.timeout, process, [process, run] { run->late = true; process->kill(); });
    process->start();
}
QString Suggestions::List() { return encoded({{"items", model.list()}, {"groups", model.groups()}, {"historyGroups", model.groups(true)}, {"coverage", coverage}, {"schema", 2}}); }
QString Suggestions::Get(const QString &id) { return encoded(model.get(id)); }
QString Suggestions::Knowledge() {
    QStringList errors; const auto entries = Care::knowledge(knowledgePath, &errors);
    return encoded({{"entries", entries}, {"errors", QJsonArray::fromStringList(errors)}});
}
void Suggestions::SetVisible(bool visible) {
    if (!calledFromDBus()) return;
    const auto sender = message().service();
    if (visible) visibleClients.insert(sender); else visibleClients.remove(sender);
}
bool Suggestions::publish() {
    QString error;
    if (!model.save(&error)) { qCritical("suggestions save: %s", qPrintable(error)); return false; }
    Q_EMIT Changed(); return true;
}
void Suggestions::Presented(const QString &json, bool opened) {
    bool changed = false;
    for (const auto &v : QJsonDocument::fromJson(json.toUtf8()).array()) {
        const auto r = v.toObject();
        changed |= model.present(r["id"].toString(), r["revision"].toInteger(), opened, QDateTime::currentSecsSinceEpoch());
    }
    if (changed) publish();
}
void Suggestions::recover() {
    for (const auto &v : model.list()) {
        const auto o = v.toObject(), task = o["task"].toObject();
        if (task["state"] != "recovering") continue;
        const auto id = o["id"].toString(), taskId = task["id"].toString();
        auto message = QDBusMessage::createMethodCall(Voice, VoicePath, Voice, "SuggestionTask");
        message.setArguments({id, taskId});
        auto *w = new QDBusPendingCallWatcher(QDBusConnection::sessionBus().asyncCall(message, 5000), this);
        connect(w, &QDBusPendingCallWatcher::finished, this, [this, w, id, taskId] {
            QDBusPendingReply<QString> reply = *w; w->deleteLater();
            if (reply.isError()) return; // Unreachable is not evidence that a task stopped.
            const auto r = QJsonDocument::fromJson(reply.value().toUtf8()).object();
            if (r["state"] == "running") model.taskEvent(id, taskId, {{"type", "started"}, {"conversation", r["conversation"]}}, QDateTime::currentSecsSinceEpoch());
            else {
                const auto now = QDateTime::currentSecsSinceEpoch();
                if (!r["result"].toString().isEmpty()) model.taskEvent(id, taskId, {{"type", "result"}, {"text", r["result"]}}, now);
                const auto state = r["state"].toString();
                const bool terminal = QStringList{"finished", "failed", "stopped"}.contains(state);
                model.taskEvent(id, taskId, {{"type", terminal ? state : QString("interrupted")},
                    {"text", terminal ? r["result"].toString(i18n("Stopped")) : i18n("The earlier task is no longer running. Check the saved result before deciding whether to retry.")}}, now);
            }
            publish();
        });
    }
}
void Suggestions::Refresh() {
    if (scanning) return;
    scanning = true;
    auto *w = new QFutureWatcher<QJsonObject>(this);
    connect(w, &QFutureWatcher<QJsonObject>::finished, this, [this, w] {
        const auto user = w->result(); w->deleteLater();
        const auto now = QDateTime::currentSecsSinceEpoch();
        const auto system = Care::readObject(feedPath);
        coverage = QJsonArray();
        for (const auto &v : user.value("coverage").toArray()) coverage.append(Care::translated(v));
        auto ingest = [this, now](const QJsonObject &batch) {
            QHash<QString, QStringList> present;
            for (const auto &v : batch.value("items").toArray()) {
                const auto o = v.toObject();
                model.observe(Care::localized(o), batch.value("generated").toInteger(now)); present[o.value("source").toString()].append(o.value("id").toString());
            }
            for (const auto &s : batch.value("sources").toArray()) model.reconcile(s.toString(), present.value(s.toString()), now);
        };
        ingest(user);
        if (system.value("schema").toInt() == 1 && now >= system.value("generated").toInteger() && now - system.value("generated").toInteger() < 180) {
            ingest(system);
            for (const auto &v : system.value("coverage").toArray()) coverage.append(Care::translated(v));
            model.due(now);
        } else coverage.append(i18n("System diagnostics haven't updated yet. Existing suggestions are kept; due reminders wait until they do."));
        scanning = false; publish(); recover(); notify();
    });
    w->setFuture(QtConcurrent::run(Care::collectUser));
}
void Suggestions::open(const QString &id, const QString &token) {
    QProcess process;
    auto environment = QProcessEnvironment::systemEnvironment();
    environment.remove("XDG_ACTIVATION_TOKEN");
    if (!token.isEmpty()) environment.insert("XDG_ACTIVATION_TOKEN", token);
    process.setProcessEnvironment(environment);
    process.setProgram("/usr/bin/rungic-voice-assistant");
    process.setArguments({"--suggestion", id});
    process.startDetached();
}
void Suggestions::NotificationToken(uint id, const QString &token) {
    if (notifications.contains(id)) notificationTokens[id] = token;
}
void Suggestions::NotificationClosed(uint id, uint) {
    notifications.remove(id); notificationTokens.remove(id);
}
void Suggestions::NotificationAction(uint id, const QString &action) {
    if (!notifications.contains(id)) return;
    if (action == "default") open(notifications.value(id), notificationTokens.take(id));
    else if (action == "later") Act(notifications.value(id), "later", "{}");
}
void Suggestions::notify() {
    // Per-item, revision-bound presentation receipts replace whole-window suppression.
    if (notifying) return;
    // Ordinary opportunities are delivered by the home feed. Only urgent or user-scheduled
    // work notifies outside it. No inferred "free time", sound or bypass of DND.
    const auto candidate = model.notification(QDateTime::currentSecsSinceEpoch(), false, false);
    if (candidate.isEmpty()) return;
    const auto item = candidate.value("item").toObject();
    const auto id = item.value("id").toString();
    QVariantMap hints{{"desktop-entry", "com.rungic.VoiceAssistant"}, {"suppress-sound", true}, {"urgency", uchar(1)}};
    auto message = QDBusMessage::createMethodCall("org.freedesktop.Notifications", "/org/freedesktop/Notifications",
                                                 "org.freedesktop.Notifications", "Notify");
    message.setArguments({"Agent", uint(0), "dialog-information", item.value("title").toString(),
        i18np("1 suggestion to look at, now or later.", "%1 suggestions to look at, now or later.", candidate.value("ids").toArray().size()),
        QStringList{"default", i18n("View suggestions"), "later", i18n("Later")}, hints, 10000});
    notifying = true;
    auto *w = new QDBusPendingCallWatcher(QDBusConnection::sessionBus().asyncCall(message, 3000), this);
    connect(w, &QDBusPendingCallWatcher::finished, this, [this, w, id, candidate] {
        QDBusPendingReply<uint> reply = *w; w->deleteLater(); notifying = false;
        if (reply.isError()) return;
        notifications[reply.value()] = id;
        model.notifiedReceipts(candidate["receipts"].toArray(), QDateTime::currentSecsSinceEpoch()); publish();
    });
}
QString Suggestions::Act(const QString &id, const QString &action, const QString &json) {
    const auto o = model.get(id);
    if (o.isEmpty()) return failure(i18n("This suggestion no longer exists."));
    auto args = QJsonDocument::fromJson(json.toUtf8()).object();
    if (action == "open") { open(id); return Get(id); }
    if (action == "investigate" || action == "apply") {
        const auto now = QDateTime::currentSecsSinceEpoch();
        const auto begun = model.beginTask(id, action, args["planRevision"].toString(), now);
        if (begun.contains("error")) return encoded(begun);
        const auto taskId = begun["task"].toObject()["id"].toString();
        if (!publish()) {
            model.update(id, {{"task", o["task"]}, {"reminderState", o["reminderState"]}, {"note", o["note"]}});
            return failure(i18n("Couldn't save the task approval, so nothing was started."));
        }
        auto message = QDBusMessage::createMethodCall(Voice, VoicePath, Voice, action == "apply" ? "ApplySuggestion" : "InvestigateSuggestion");
        message.setArguments({id, taskId});
        auto *w = new QDBusPendingCallWatcher(QDBusConnection::sessionBus().asyncCall(message, 120000), this);
        connect(w, &QDBusPendingCallWatcher::finished, this, [this, w, id, taskId] {
            QDBusPendingReply<QString> reply = *w; w->deleteLater();
            const auto r = QJsonDocument::fromJson(reply.value().toUtf8()).object();
            if (reply.isError() || r.contains("error")) {
                model.taskEvent(id, taskId, {{"type", "failed"}, {"text", reply.isError() ? reply.error().message() : r["error"].toString()}}, QDateTime::currentSecsSinceEpoch());
            } else model.taskEvent(id, taskId, {{"type", "started"}, {"conversation", r["conversation"]}}, QDateTime::currentSecsSinceEpoch());
            publish();
        });
        return Get(id);
    }
    if (action == "stop") {
        if (o["state"] != "working") return failure(i18n("No investigation is running."));
        const auto taskId = o["task"].toObject()["id"].toString();
        auto message = QDBusMessage::createMethodCall(Voice, VoicePath, Voice, "StopSuggestion");
        message.setArguments({id, taskId});
        auto *w = new QDBusPendingCallWatcher(QDBusConnection::sessionBus().asyncCall(message, 15000), this);
        connect(w, &QDBusPendingCallWatcher::finished, this, [this, w, id, taskId] {
            QDBusPendingReply<> reply = *w; w->deleteLater();
            if (model.get(id)["task"].toObject()["id"] != taskId) return;
            if (reply.isError()) model.update(id, {{"note", i18n("The stop request wasn't confirmed: %1", reply.error().message())}});
            publish();
        });
        model.update(id, {{"note", i18n("Stop requested. Waiting for Agent to confirm.")}}); publish(); return Get(id);
    }
    if (action == "feedback") return Feedback(id);
    const auto result = model.act(id, action, args, QDateTime::currentSecsSinceEpoch());
    if (!result.contains("error")) publish();
    return encoded(result);
}
void Suggestions::AgentEvent(const QString &json) {
    const auto e = QJsonDocument::fromJson(json.toUtf8()).object();
    // Compatibility for one release (remove after 2026-10): a voice agent from before RecordTokens and
    // ProviderChanged only signals its Codex usage. Once it calls those itself, its events are not read
    // twice; a repeat would be harmless anyway (counts are high-water marks).
    const bool legacy = !usagePushers.contains("codex");
    if (legacy && e["type"] == "usage-changed") { usage.identity("codex", e["accountKey"].toString()); Q_EMIT UsageChanged(); }
    if (e["type"] == "token-usage") {
        if (legacy && usage.record("codex", Care::codexTokenEvent(e), QDateTime::currentSecsSinceEpoch())) Q_EMIT UsageChanged();
        return;
    }
    if (legacy && QStringList{"account", "usage-changed", "agent-started", "agent-finished", "agent-restarted"}.contains(e["type"].toString()))
        ProviderChanged("codex");
    const auto id = e["suggestion"].toString(), taskId = e["suggestionTask"].toString();
    QJsonObject event;
    const auto type = e["type"].toString();
    if (type == "suggestion-started") event = {{"type", "started"}, {"conversation", e["conversation"]}};
    else if (type == "agent-message" && e["final"].toBool()) event = {{"type", "result"}, {"text", e["text"]}};
    else if (type == "task") { event = e; event["type"] = "progress"; }
    else if (type == "agent-finished") event = {{"type", "finished"}};
    else if (type == "task-stopped") event = {{"type", "stopped"}};
    else if (type == "error") event = {{"type", "failed"}, {"text", e["text"]}};
    if (model.taskEvent(id, taskId, event, QDateTime::currentSecsSinceEpoch())) publish();
}
QString Suggestions::Update(const QString &id, const QString &json) {
    const auto input = QJsonDocument::fromJson(json.toUtf8()).object();
    if (model.get(id).isEmpty()) return failure(i18n("This suggestion no longer exists."));
    if (input.contains("taskId") && input["taskId"] != model.get(id)["task"].toObject()["id"])
        return failure(i18n("The task was replaced, so the current record wasn't overwritten."));
    QJsonObject fields;
    for (const auto &key : {"result", "plan", "verification", "rollback", "planStatus", "conclusion", "nextStep", "confidence"}) {
        if (input.contains(key)) fields[key] = input.value(key).toString().left(16000);
    }
    if (input.contains("upstream")) {
        const auto upstream = input.value("upstream").toObject();
        const QUrl url(upstream.value("url").toString());
        const auto status = upstream.value("state").toString();
        if (!QStringList{"not_evaluated", "prepared", "submitted", "review", "merged", "released", "not_applicable"}.contains(status)) return failure(i18n("Invalid upstream status."));
        if (status != "not_evaluated" && status != "prepared" && status != "not_applicable"
            && (url.scheme() != "https" || url.host().isEmpty() || !url.userInfo().isEmpty())) return failure(i18n("This status needs an HTTPS upstream link that can be checked."));
        fields["upstream"] = QJsonObject{{"state", status}, {"url", url.toString()}, {"recordedBy", "local-client"}, {"verification", i18n("Recorded by the maintainer; the upstream wasn't checked automatically.")}};
    }
    // Recording a plan/result never auto-resolves an observed fault or silently applies code.
    if (fields.isEmpty()) return failure(i18n("There is nothing to update in the record."));
    const auto plan = model.updatePlan(id, fields);
    if (plan.contains("error")) return encoded(plan);
    QJsonObject rest{{"updated", QDateTime::currentSecsSinceEpoch()}};
    if (fields.contains("upstream")) rest["upstream"] = fields["upstream"];
    model.update(id, rest); publish(); return Get(id);
}
QString Suggestions::Feedback(const QString &id) {
    const auto o = model.get(id);
    if (o.isEmpty()) return failure(i18n("This suggestion no longer exists."));
    const auto directory = QFileInfo(statePath).absolutePath() + "/feedback/" + id;
    QJsonObject safe;
    const auto e = o.value("evidence").toObject();
    for (const auto &key : {"package", "version", "signature", "signal", "knowledge", "unit"}) if (e.contains(key)) safe[key] = e.value(key);
    const auto project = o.value("upstreamProject").toString();
    const auto rules = Care::readObject(QFileInfo(knowledgePath).absolutePath() + "/upstreams.json").value(project).toObject();
    const QJsonObject report{{"schema", 1}, {"id", id}, {"facts", safe}, {"project", project}, {"policy", rules},
        {"purpose", i18n("Internal feedback material. Add a minimal reproduction, expected and actual results and tests; a maintainer submits it after checking the target project's rules.")},
        {"publicSubmission", false}, {"missing", QJsonArray{i18n("Minimal reproduction"), i18n("Independent verification"), i18n("Maintainer review")}}};
    QString error;
    if (!Care::writeObject(directory + "/facts.json", report, &error)) return failure(error);
    model.update(id, {{"feedback", directory + "/facts.json"}}); publish();
    return encoded({{"path", directory + "/facts.json"}, {"message", i18n("Feedback material was saved on this device. Nothing has been sent.")}});
}
