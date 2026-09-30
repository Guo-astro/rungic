// SPDX-License-Identifier: GPL-2.0-or-later
#include "service.h"
#include "collector.h"
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
                if (name == Voice) {
                    if (owner.isEmpty()) { model.recoverTasks(); publish(); }
                    else recover();
                }
            });
    scanTimer.setInterval(60000);
    connect(&scanTimer, &QTimer::timeout, this, &Suggestions::Refresh);
    scanTimer.start(); QTimer::singleShot(0, this, &Suggestions::Refresh);
}
QString Suggestions::AgentUsage() {
    RefreshAgentUsage();
    return encoded(usage.view(QDateTime::currentSecsSinceEpoch()));
}
void Suggestions::RefreshAgentUsage() {
    const auto now = QDateTime::currentSecsSinceEpoch();
    if (usageRefreshing || now - usageAttempt < 30) return;
    usageRefreshing = true; usageAttempt = now;
    auto request = QDBusMessage::createMethodCall(Voice, VoicePath, Voice, "Usage");
    auto *w = new QDBusPendingCallWatcher(QDBusConnection::sessionBus().asyncCall(request, 35000), this);
    connect(w, &QDBusPendingCallWatcher::finished, this, [this, w] {
        QDBusPendingReply<QString> reply = *w; w->deleteLater(); usageRefreshing = false;
        if (reply.isError()) usage.error("Agent 用量暂时不可用，稍后重试");
        else usage.snapshot(QJsonDocument::fromJson(reply.value().toUtf8()).object(), QDateTime::currentSecsSinceEpoch());
        Q_EMIT UsageChanged();
    });
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
                    {"text", terminal ? r["result"].toString("处理已停止") : QString("原任务已不在运行，请查看已保存结果后决定是否重试")}}, now);
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
        coverage = user.value("coverage").toArray();
        auto ingest = [this, now](const QJsonObject &batch) {
            QHash<QString, QStringList> present;
            for (const auto &v : batch.value("items").toArray()) {
                const auto o = v.toObject();
                model.observe(o, batch.value("generated").toInteger(now)); present[o.value("source").toString()].append(o.value("id").toString());
            }
            for (const auto &s : batch.value("sources").toArray()) model.reconcile(s.toString(), present.value(s.toString()), now);
        };
        ingest(user);
        if (system.value("schema").toInt() == 1 && now >= system.value("generated").toInteger() && now - system.value("generated").toInteger() < 180) {
            ingest(system);
            for (const auto &v : system.value("coverage").toArray()) coverage.append(v);
            model.due(now);
        } else coverage.append("系统诊断尚未更新，保留已有建议；暂不触发过期提醒");
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
        QString("有 %1 项建议可查看，也可以稍后处理。").arg(candidate.value("ids").toArray().size()),
        QStringList{"default", "查看建议", "later", "稍后"}, hints, 10000});
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
    if (o.isEmpty()) return failure("建议已不存在");
    auto args = QJsonDocument::fromJson(json.toUtf8()).object();
    if (action == "open") { open(id); return Get(id); }
    if (action == "investigate" || action == "apply") {
        const auto now = QDateTime::currentSecsSinceEpoch();
        const auto begun = model.beginTask(id, action, args["planRevision"].toString(), now);
        if (begun.contains("error")) return encoded(begun);
        const auto taskId = begun["task"].toObject()["id"].toString();
        if (!publish()) {
            model.update(id, {{"task", o["task"]}, {"reminderState", o["reminderState"]}, {"note", o["note"]}});
            return failure("无法保存任务授权，未开始执行");
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
        if (o["state"] != "working") return failure("当前没有正在运行的调查");
        const auto taskId = o["task"].toObject()["id"].toString();
        auto message = QDBusMessage::createMethodCall(Voice, VoicePath, Voice, "StopSuggestion");
        message.setArguments({id, taskId});
        auto *w = new QDBusPendingCallWatcher(QDBusConnection::sessionBus().asyncCall(message, 15000), this);
        connect(w, &QDBusPendingCallWatcher::finished, this, [this, w, id, taskId] {
            QDBusPendingReply<> reply = *w; w->deleteLater();
            if (model.get(id)["task"].toObject()["id"] != taskId) return;
            if (reply.isError()) model.update(id, {{"note", "停止请求未确认：" + reply.error().message()}});
            publish();
        });
        model.update(id, {{"note", "已请求停止，等待 Agent 确认"}}); publish(); return Get(id);
    }
    if (action == "feedback") return Feedback(id);
    const auto result = model.act(id, action, args, QDateTime::currentSecsSinceEpoch());
    if (!result.contains("error")) publish();
    return encoded(result);
}
void Suggestions::AgentEvent(const QString &json) {
    const auto e = QJsonDocument::fromJson(json.toUtf8()).object();
    if (e["type"] == "usage-changed") { usage.identity(e["accountKey"].toString()); Q_EMIT UsageChanged(); }
    if (e["type"] == "token-usage") {
        usage.token(e, QDateTime::currentSecsSinceEpoch()); Q_EMIT UsageChanged(); return;
    }
    if (QStringList{"account", "usage-changed", "agent-started", "agent-finished", "agent-restarted"}.contains(e["type"].toString())) {
        usageAttempt = 0; RefreshAgentUsage();
    }
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
    if (model.get(id).isEmpty()) return failure("建议已不存在");
    if (input.contains("taskId") && input["taskId"] != model.get(id)["task"].toObject()["id"])
        return failure("任务已被替代，未覆盖当前记录");
    QJsonObject fields;
    for (const auto &key : {"result", "plan", "verification", "rollback", "planStatus", "conclusion", "nextStep", "confidence"}) {
        if (input.contains(key)) fields[key] = input.value(key).toString().left(16000);
    }
    if (input.contains("upstream")) {
        const auto upstream = input.value("upstream").toObject();
        const QUrl url(upstream.value("url").toString());
        const auto status = upstream.value("state").toString();
        if (!QStringList{"not_evaluated", "prepared", "submitted", "review", "merged", "released", "not_applicable"}.contains(status)) return failure("无效的上游状态");
        if (status != "not_evaluated" && status != "prepared" && status != "not_applicable"
            && (url.scheme() != "https" || url.host().isEmpty() || !url.userInfo().isEmpty())) return failure("该状态需要可核对的 HTTPS 上游链接");
        fields["upstream"] = QJsonObject{{"state", status}, {"url", url.toString()}, {"recordedBy", "local-client"}, {"verification", "维护端记录，未自动核验远端"}};
    }
    // Recording a plan/result never auto-resolves an observed fault or silently applies code.
    if (fields.isEmpty()) return failure("没有可更新的处理记录");
    const auto plan = model.updatePlan(id, fields);
    if (plan.contains("error")) return encoded(plan);
    QJsonObject rest{{"updated", QDateTime::currentSecsSinceEpoch()}};
    if (fields.contains("upstream")) rest["upstream"] = fields["upstream"];
    model.update(id, rest); publish(); return Get(id);
}
QString Suggestions::Feedback(const QString &id) {
    const auto o = model.get(id);
    if (o.isEmpty()) return failure("建议已不存在");
    const auto directory = QFileInfo(statePath).absolutePath() + "/feedback/" + id;
    QJsonObject safe;
    const auto e = o.value("evidence").toObject();
    for (const auto &key : {"package", "version", "signature", "signal", "knowledge", "unit"}) if (e.contains(key)) safe[key] = e.value(key);
    const auto project = o.value("upstreamProject").toString();
    const auto rules = Care::readObject(QFileInfo(knowledgePath).absolutePath() + "/upstreams.json").value(project).toObject();
    const QJsonObject report{{"schema", 1}, {"id", id}, {"facts", safe}, {"project", project}, {"policy", rules},
        {"purpose", "内部反馈准备材料；需补充最小复现、预期/实际结果和测试，核对目标项目规则后由维护者提交"},
        {"publicSubmission", false}, {"missing", QJsonArray{"最小复现", "独立验证", "维护者审阅"}}};
    QString error;
    if (!Care::writeObject(directory + "/facts.json", report, &error)) return failure(error);
    model.update(id, {{"feedback", directory + "/facts.json"}}); publish();
    return encoded({{"path", directory + "/facts.json"}, {"message", "已生成本地反馈材料，尚未对外发送"}});
}
