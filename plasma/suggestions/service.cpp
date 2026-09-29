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
#include <QUrl>
#include <QtConcurrent>

static QString encoded(const QJsonObject &o) { return QString::fromUtf8(QJsonDocument(o).toJson(QJsonDocument::Compact)); }
static QString failure(const QString &s) { return encoded({{"error", s}}); }
static constexpr auto Voice = "com.rungic.VoiceAgent";
static constexpr auto VoicePath = "/com/rungic/VoiceAgent";

Suggestions::Suggestions(const QString &state, const QString &feed, const QString &kb, QObject *parent)
    : QObject(parent), model(state), feedPath(feed), knowledgePath(kb), statePath(state) {
    QString error;
    ready = model.load(&error);
    if (!ready) { qCritical("%s", qPrintable(error)); return; }
    model.recoverTasks();
    auto bus = QDBusConnection::sessionBus();
    bus.connect(Voice, VoicePath, Voice, "Event", this, SLOT(AgentEvent(QString)));
    bus.connect("org.freedesktop.Notifications", "/org/freedesktop/Notifications", "org.freedesktop.Notifications",
                "ActionInvoked", this, SLOT(NotificationAction(uint,QString)));
    connect(bus.interface(), &QDBusConnectionInterface::serviceOwnerChanged, this,
            [this](const QString &name, const QString &, const QString &owner) { if (owner.isEmpty()) visibleClients.remove(name); });
    scanTimer.setInterval(60000);
    connect(&scanTimer, &QTimer::timeout, this, &Suggestions::Refresh);
    scanTimer.start(); QTimer::singleShot(0, this, &Suggestions::Refresh);
}
QString Suggestions::List() { return encoded({{"items", model.list()}, {"coverage", coverage}, {"schema", 1}}); }
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
void Suggestions::publish() {
    QString error;
    if (!model.save(&error)) qCritical("suggestions save: %s", qPrintable(error));
    Q_EMIT Changed();
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
                model.observe(o, now); present[o.value("source").toString()].append(o.value("id").toString());
            }
            for (const auto &s : batch.value("sources").toArray()) model.reconcile(s.toString(), present.value(s.toString()), now);
        };
        ingest(user);
        if (system.value("schema").toInt() == 1 && now - system.value("generated").toInteger() < 180) {
            ingest(system);
            for (const auto &v : system.value("coverage").toArray()) coverage.append(v);
            model.due(now, Care::runningProcesses());
        } else coverage.append("系统诊断尚未更新，保留已有建议；暂不触发过期提醒");
        scanning = false; publish(); notify();
    });
    w->setFuture(QtConcurrent::run(Care::collectUser));
}
void Suggestions::open(const QString &id) {
    QProcess::startDetached("/usr/bin/rungic-voice-assistant", {"--suggestion", id});
}
void Suggestions::NotificationAction(uint id, const QString &action) {
    if (!notifications.contains(id)) return;
    if (action == "default") open(notifications.value(id));
    else if (action == "later") Act(notifications.value(id), "later", "{}");
}
void Suggestions::notify() {
    // A visible home feed/page is already the delivery surface; never double-notify it.
    if (!visibleClients.isEmpty()) return;
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
    auto *w = new QDBusPendingCallWatcher(QDBusConnection::sessionBus().asyncCall(message, 3000), this);
    connect(w, &QDBusPendingCallWatcher::finished, this, [this, w, id, candidate] {
        QDBusPendingReply<uint> reply = *w; w->deleteLater();
        if (reply.isError()) return;
        notifications[reply.value()] = id;
        QStringList ids; for (const auto &v : candidate.value("ids").toArray()) ids.append(v.toString());
        model.notified(ids, QDateTime::currentSecsSinceEpoch()); publish();
    });
}
QString Suggestions::Act(const QString &id, const QString &action, const QString &json) {
    const auto o = model.get(id);
    if (o.isEmpty()) return failure("建议已不存在");
    auto args = QJsonDocument::fromJson(json.toUtf8()).object();
    if (action == "open") { open(id); return Get(id); }
    if (action == "investigate" || action == "apply") {
        if (o.value("state") == "resolved") return failure("问题已消失，请先刷新建议");
        if (o.value("state") == "working") return failure("Agent 已在处理这条建议");
        // The service rechecks the source's age before starting a task on an old card.
        if (QDateTime::currentSecsSinceEpoch() - o.value("lastObserved").toInteger() > 180)
            return failure("诊断信息已过期，请刷新后重试");
        if (action == "apply" && (o.value("plan").toString().isEmpty() || o.value("verification").toString().isEmpty()
                                 || o.value("rollback").toString().isEmpty()))
            return failure("需要先准备具体方案、验证与回退办法");
        model.update(id, {{"state", "working"}, {"note", "正在连接 Agent"}, {"notified", true}}); publish();
        auto message = QDBusMessage::createMethodCall(Voice, VoicePath, Voice, action == "apply" ? "ApplySuggestion" : "InvestigateSuggestion");
        message.setArguments({id});
        auto *w = new QDBusPendingCallWatcher(QDBusConnection::sessionBus().asyncCall(message, 120000), this);
        connect(w, &QDBusPendingCallWatcher::finished, this, [this, w, id] {
            QDBusPendingReply<QString> reply = *w; w->deleteLater();
            auto r = QJsonDocument::fromJson(reply.value().toUtf8()).object();
            if (reply.isError() || r.contains("error")) {
                model.update(id, {{"state", "attention"}, {"note", reply.isError() ? reply.error().message() : r.value("error")}});
            } else {
                model.update(id, {{"conversation", r.value("conversation")}});
            }
            publish();
        });
        return Get(id);
    }
    if (action == "stop") {
        if (o.value("state") != "working") return failure("当前没有正在运行的调查");
        auto message = QDBusMessage::createMethodCall(Voice, VoicePath, Voice, "StopSuggestion");
        message.setArguments({id}); QDBusConnection::sessionBus().asyncCall(message);
        model.update(id, {{"note", "已请求停止，等待 Agent 确认"}}); publish(); return Get(id);
    }
    if (action == "feedback") return Feedback(id);
    const auto result = model.act(id, action, args, QDateTime::currentSecsSinceEpoch());
    if (!result.contains("error")) publish();
    return encoded(result);
}
void Suggestions::AgentEvent(const QString &json) {
    const auto e = QJsonDocument::fromJson(json.toUtf8()).object();
    const auto conversation = e.value("conversation").toString();
    if (conversation.isEmpty()) return;
    if (e.value("type") == "suggestion-started") {
        model.update(e.value("suggestion").toString(), {{"conversation", conversation}, {"note", "Agent 正在检查原因"}});
        publish(); return;
    }
    for (const auto &v : model.list()) {
        const auto o = v.toObject();
        if (o.value("conversation").toString() != conversation) continue;
        if (e.value("type") == "agent-started" && o.value("state") != "resolved")
            model.update(o.value("id").toString(), {{"state", "working"}, {"note", "Agent 正在继续处理"}});
        if (model.get(o.value("id").toString()).value("state") != "working") continue;
        QJsonObject fields;
        if (e.value("type") == "agent-message" && e.value("final").toBool()) fields["result"] = e.value("text").toString().left(12000);
        if (e.value("type") == "task") fields["progress"] = e;
        if (e.value("type") == "agent-finished" || e.value("type") == "task-stopped" || e.value("type") == "error") {
            fields["state"] = "attention";
            fields["note"] = e.value("type") == "agent-finished" ? "调查已结束，查看结果与下一步" : "处理已停止，可查看原对话继续";
            fields["notified"] = false;
            fields["scheduled"] = true; // Completion of work the user explicitly requested.
        }
        if (!fields.isEmpty()) { model.update(o.value("id").toString(), fields); publish(); }
    }
}
QString Suggestions::Update(const QString &id, const QString &json) {
    const auto input = QJsonDocument::fromJson(json.toUtf8()).object();
    if (model.get(id).isEmpty()) return failure("建议已不存在");
    QJsonObject fields;
    for (const auto &key : {"result", "plan", "verification", "rollback"}) {
        if (input.contains(key)) fields[key] = input.value(key).toString().left(16000);
    }
    if (input.contains("upstream")) {
        const auto upstream = input.value("upstream").toObject();
        const QUrl url(upstream.value("url").toString());
        const auto status = upstream.value("state").toString();
        if (!QStringList{"not_evaluated", "prepared", "submitted", "review", "merged", "released", "not_applicable"}.contains(status)) return failure("无效的上游状态");
        if (status != "not_evaluated" && status != "prepared" && status != "not_applicable"
            && (url.scheme() != "https" || url.host().isEmpty() || !url.userInfo().isEmpty())) return failure("该状态需要可核对的 HTTPS 上游链接");
        fields["upstream"] = QJsonObject{{"state", status}, {"url", url.toString()}, {"verifiedBy", "maintainer"}};
    }
    // Recording a plan/result never auto-resolves an observed fault or silently applies code.
    if (fields.isEmpty()) return failure("没有可更新的处理记录");
    fields["updated"] = QDateTime::currentSecsSinceEpoch(); model.update(id, fields); publish(); return Get(id);
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
