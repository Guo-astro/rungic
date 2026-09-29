// SPDX-License-Identifier: GPL-2.0-or-later
#include "model.h"
#include <QCryptographicHash>
#include <QDateTime>
#include <QDir>
#include <QFile>
#include <QFileInfo>
#include <QJsonDocument>
#include <QSaveFile>
#include <QSet>
#include <QUuid>
#include <algorithm>

namespace Care {
QJsonObject readObject(const QString &path) {
    QFile f(path);
    if (!f.open(QIODevice::ReadOnly) || f.size() > 4 * 1024 * 1024) return {};
    return QJsonDocument::fromJson(f.readAll()).object();
}
bool writeObject(const QString &path, const QJsonObject &object, QString *error) {
    QDir().mkpath(QFileInfo(path).absolutePath());
    QSaveFile f(path);
    if (!f.open(QIODevice::WriteOnly)) { if (error) *error = f.errorString(); return false; }
    f.setPermissions(QFileDevice::ReadOwner | QFileDevice::WriteOwner);
    const auto bytes = QJsonDocument(object).toJson();
    if (f.write(bytes) != bytes.size() || !f.commit()) { if (error) *error = f.errorString(); return false; }
    return true;
}
QString fingerprint(const QString &text) {
    return QString::fromLatin1(QCryptographicHash::hash(text.toUtf8(), QCryptographicHash::Sha256).toHex().left(24));
}
QString validateKnowledge(const QJsonObject &e) {
    for (const auto &key : {"id", "title", "kind", "status", "explanation", "reviewed"})
        if (e.value(key).toString().isEmpty()) return QStringLiteral("missing %1").arg(key);
    if (e.value("schema").toInt() != 1 || e.value("evidence").toArray().isEmpty()) return "schema/evidence";
    const auto match = e.value("match").toObject();
    if (match.value("package").toString().isEmpty() ||
        (e.value("kind") != "policy" && match.value("versions").toArray().isEmpty())) return "match needs exact package versions";
    if (!QStringList{"policy", "issue", "optimization"}.contains(e.value("kind").toString())) return "kind";
    if (!QStringList{"verified", "research", "superseded"}.contains(e.value("status").toString())) return "status";
    // Knowledge is data, never an executable repair recipe.
    for (const auto &key : {"command", "shell", "script", "exec"}) if (e.contains(key)) return "executable knowledge is forbidden";
    return {};
}
QJsonArray knowledge(const QString &directory, QStringList *errors) {
    QJsonArray result;
    QSet<QString> ids;
    for (const auto &file : QDir(directory).entryList({"*.json"}, QDir::Files, QDir::Name)) {
        auto e = readObject(directory + '/' + file);
        auto error = validateKnowledge(e);
        if (ids.contains(e.value("id").toString())) error = "duplicate id";
        if (!error.isEmpty()) { if (errors) errors->append(file + ": " + error); continue; }
        ids.insert(e.value("id").toString()); result.append(e);
    }
    return result;
}
QJsonObject observation(const QString &key, const QString &title, const QString &body,
                        const QString &kind, int severity, const QJsonObject &evidence) {
    return {{"id", fingerprint(key)}, {"key", key}, {"title", title}, {"body", body},
            {"kind", kind}, {"severity", severity}, {"evidence", evidence}};
}
static bool activeTask(const QJsonObject &o) {
    return QStringList{"running", "recovering"}.contains(o["task"].toObject()["state"].toString());
}
static QString evidenceRevision(const QJsonObject &o) {
    return fingerprint(QString::fromUtf8(QJsonDocument(o["evidence"].toObject()).toJson(QJsonDocument::Compact)));
}
static QString revision(const QJsonObject &o) {
    QJsonObject plan;
    for (const auto &key : {"plan", "verification", "rollback", "planStatus", "planEvidence"}) plan[key] = o[key];
    plan["currentEvidence"] = evidenceRevision(o);
    return fingerprint(QString::fromUtf8(QJsonDocument(plan).toJson(QJsonDocument::Compact)));
}
static void nextDelivery(QJsonObject &o, const QString &reason) {
    o["deliveryRevision"] = o["deliveryRevision"].toInteger() + 1;
    o["deliveryReason"] = reason;
}
static QJsonObject projected(QJsonObject o) {
    if (o.isEmpty()) return o;
    const auto task = o["task"].toObject();
    QString state = "new";
    if (activeTask(o)) state = "working";
    else if (o["reminderState"] == "dismissed") state = "dismissed";
    else if (o["reminderState"] == "snoozed") state = "snoozed";
    else if (task["needsReview"].toBool()) state = "attention";
    else if (o["issueState"] == "absent") state = "resolved";
    o["state"] = state; // Compatibility/view projection only; never the task authority.
    o["planRevision"] = revision(o);
    o["canApply"] = o["issueState"] == "observed" && !activeTask(o) && o["planStatus"] == "ready"
        && o["planEvidence"] == evidenceRevision(o) && !o["plan"].toString().trimmed().isEmpty()
        && !o["verification"].toString().trimmed().isEmpty() && !o["rollback"].toString().trimmed().isEmpty();
    o["notified"] = o["notifiedRevision"].toInteger() >= o["deliveryRevision"].toInteger();
    o["seen"] = o["openedRevision"].toInteger() >= o["deliveryRevision"].toInteger();
    return o;
}
Model::Model(QString p) : path(std::move(p)) {}
bool Model::load(QString *error) {
    if (!QFile::exists(path)) return true;
    const auto data = readObject(path);
    const int schema = data["schema"].toInt();
    if ((schema != 1 && schema != 2) || !data["items"].isObject()) {
        if (error) *error = "建议记录损坏或版本不支持，已保留原文件";
        return false;
    }
    items = data["items"].toObject(); settings = data["settings"].toObject();
    lastDigest = data["lastDigest"].toInteger();
    if (schema == 1) {
        if (!QFile::exists(path + ".schema1-backup") && !QFile::copy(path, path + ".schema1-backup")) {
            if (error) *error = "无法备份原建议记录，未迁移"; return false;
        }
        for (const auto &id : items.keys()) {
            auto o = items[id].toObject(); const auto state = o["state"].toString();
            o["issueState"] = state == "resolved" ? "absent" : "observed";
            o["task"] = QJsonObject{{"state", state == "working" ? "recovering" : "idle"},
                {"needsReview", state == "attention"}, {"conversation", o["conversation"]}};
            o["reminderState"] = state == "dismissed" || state == "snoozed" ? state : "none";
            o["planStatus"] = "needs_investigation"; // Legacy prose is not an executable plan.
            o["deliveryRevision"] = 1;
            o["deliveryReason"] = o["scheduled"].toBool() ? "reminder" : "discovery";
            if (o["notified"].toBool()) o["notifiedRevision"] = 1;
            if (o["seen"].toBool()) o["openedRevision"] = 1;
            if (o.contains("condition")) {
                o.remove("condition"); o["note"] = "原应用退出条件无法可靠核验，已保留待处理，请重新选择提醒时间";
            }
            o.remove("state"); o.remove("notified"); o.remove("seen"); o.remove("scheduled");
            items[id] = o;
        }
    }
    return true;
}
bool Model::save(QString *error) const {
    return writeObject(path, {{"schema", 2}, {"items", items}, {"settings", settings}, {"lastDigest", lastDigest}}, error);
}
QJsonObject Model::get(const QString &id) const { return projected(items[id].toObject()); }
QJsonArray Model::list() const {
    QList<QJsonObject> sorted;
    for (auto it = items.begin(); it != items.end(); ++it) sorted.append(projected(it.value().toObject()));
    std::sort(sorted.begin(), sorted.end(), [](const auto &a, const auto &b) {
        auto rank = [](const auto &o) {
            const auto state = o["state"].toString();
            if (state == "resolved") return -100;
            if (state == "dismissed") return -90;
            if (state == "snoozed") return -10;
            if (o["severity"].toInt() >= 2) return 30;
            if (state == "attention") return 20;
            if (state == "working") return 10;
            return o["severity"].toInt();
        };
        if (rank(a) != rank(b)) return rank(a) > rank(b);
        if (a["updated"] != b["updated"]) return a["updated"].toInteger() > b["updated"].toInteger();
        return a["id"].toString() < b["id"].toString();
    });
    QJsonArray result; for (const auto &o : sorted) result.append(o); return result;
}
bool Model::observe(QJsonObject incoming, qint64 now) {
    const auto id = incoming["id"].toString(); if (id.isEmpty()) return false;
    auto o = items[id].toObject(); const bool fresh = o.isEmpty(), recurrent = o["issueState"] == "absent";
    bool changed = fresh || recurrent;
    const int severity = o["severity"].toInt();
    // Observations can update evidence, never user choices, task state or plans.
    for (const auto &key : {"id", "key", "title", "body", "kind", "severity", "evidence", "source", "process", "knowledge", "upstreamProject", "application"}) {
        if (!incoming.contains(key)) continue;
        if (o[key] != incoming[key]) changed = true;
        o[key] = incoming[key];
    }
    o["lastObserved"] = now; o["issueState"] = "observed";
    if (fresh) {
        o["created"] = now; o["task"] = QJsonObject{{"state", "idle"}};
        o["reminderState"] = "none"; o["planStatus"] = "needs_investigation";
        o["upstream"] = QJsonObject{{"state", "not_evaluated"}};
        nextDelivery(o, "discovery");
    } else if (recurrent || o["severity"].toInt() > severity) {
        // A user's mute survives disappearance and recurrence of the same issue.
        nextDelivery(o, "discovery");
        if (recurrent) o["note"] = "问题再次出现，保留此前记录与提醒选择";
    }
    if (changed) o["updated"] = now;
    items[id] = o; return changed;
}
void Model::reconcile(const QString &source, const QStringList &present, qint64 now) {
    for (const auto &id : items.keys()) {
        auto o = items[id].toObject();
        if (o["source"] != source || present.contains(id) || o["issueState"] == "absent") continue;
        o["issueState"] = "absent";
        o["issueNote"] = "复查不再匹配此项；不代表根因已确认修复";
        if (!activeTask(o) && !o["task"].toObject()["needsReview"].toBool()) o["note"] = o["issueNote"];
        if (!o["task"].toObject()["needsReview"].toBool()) {
            if (o["reminderState"] == "snoozed") o["reminderState"] = "none";
            o.remove("remindAt"); o.remove("condition");
        }
        o["updated"] = now;
        items[id] = o;
    }
}
bool Model::update(const QString &id, const QJsonObject &fields) {
    auto o = items[id].toObject(); if (o.isEmpty()) return false;
    for (auto it = fields.begin(); it != fields.end(); ++it) {
        if (QStringList{"state", "notified", "seen", "scheduled", "planRevision", "canApply"}.contains(it.key())) continue;
        o[it.key()] = it.value();
    }
    items[id] = o; return true;
}
QJsonObject Model::updatePlan(const QString &id, const QJsonObject &fields) {
    auto o = items[id].toObject();
    if (o.isEmpty()) return {{"error", "建议已不存在"}};
    bool planChanged = false;
    for (const auto &key : {"plan", "verification", "rollback", "planStatus"}) if (fields.contains(key)) planChanged = true;
    auto status = fields["planStatus"].toString("needs_investigation");
    if (!QStringList{"needs_investigation", "unavailable", "ready"}.contains(status)) return {{"error", "无效的方案状态"}};
    for (const auto &key : {"result", "plan", "verification", "rollback"})
        if (fields.contains(key)) o[key] = fields[key].toString().left(16000);
    if (planChanged) {
        if (status == "ready" && (o["plan"].toString().trimmed().isEmpty() || o["verification"].toString().trimmed().isEmpty() || o["rollback"].toString().trimmed().isEmpty()))
            return {{"error", "可应用方案必须包含具体变更、验证及回退办法"}};
        o["planStatus"] = status; o["planEvidence"] = evidenceRevision(o);
    }
    items[id] = o; return get(id);
}
QJsonObject Model::beginTask(const QString &id, const QString &mode, const QString &approvedRevision, qint64 now) {
    auto o = get(id);
    if (o.isEmpty() || o["issueState"] != "observed") return {{"error", "当前证据不再匹配，请先复查"}};
    if (activeTask(o)) return {{"error", "该建议已有任务，先查看进度或停止"}};
    if (now - o["lastObserved"].toInteger() > 180 || now < o["lastObserved"].toInteger()) return {{"error", "诊断信息已过期，请刷新后重试"}};
    if (mode == "apply" && (!o["canApply"].toBool() || approvedRevision.isEmpty() || approvedRevision != o["planRevision"].toString()))
        return {{"error", "方案或适用证据已变化，请重新查看并确认当前方案"}};
    QJsonObject task{{"id", QUuid::createUuid().toString(QUuid::WithoutBraces)}, {"state", "running"}, {"mode", mode}, {"started", now}};
    if (mode == "apply") {
        QJsonObject snapshot;
        for (const auto &key : {"plan", "verification", "rollback", "planRevision", "evidence"}) snapshot[key] = o[key];
        task["approvedPlan"] = snapshot;
    }
    update(id, {{"task", task}, {"reminderState", "none"}, {"note", "正在连接 Agent"}, {"updated", now}});
    return get(id);
}
bool Model::taskEvent(const QString &id, const QString &taskId, const QJsonObject &event, qint64 now) {
    auto o = items[id].toObject(); auto task = o["task"].toObject();
    if (taskId.isEmpty() || task["id"] != taskId || !activeTask(o)) return false;
    const auto type = event["type"].toString();
    if (type == "started") {
        task["state"] = "running"; task["conversation"] = event["conversation"];
        o["conversation"] = event["conversation"]; o["note"] = "Agent 正在处理";
    } else if (type == "result") o["result"] = event["text"].toString().left(16000);
    else if (type == "progress") o["progress"] = event;
    else if (QStringList{"finished", "failed", "stopped", "interrupted"}.contains(type)) {
        task["state"] = type; task["finished"] = now; task["needsReview"] = true;
        o["note"] = type == "finished" ? "处理已结束，查看结果与下一步" : event["text"].toString("处理已停止，可查看原对话");
        if (type == "failed") o["result"] = event["text"];
        nextDelivery(o, "task");
    } else return false;
    o["task"] = task; o["updated"] = now; items[id] = o; return true;
}
QJsonObject Model::act(const QString &id, const QString &action, const QJsonObject &args, qint64 now) {
    auto o = items[id].toObject();
    if (o.isEmpty()) return {{"error", "建议已不存在"}};
    if (action == "seen" || action == "displayed") {
        present(id, args["revision"].toInteger(), action == "seen", now); return get(id);
    }
    if (activeTask(o)) return {{"error", "请先停止正在进行的处理"}};
    if (action == "closed") return {{"error", "缺少可靠的应用实例身份，请选择时间提醒"}};
    if (action == "later" || action == "snooze") {
        if (o["issueState"] == "absent" && !o["task"].toObject()["needsReview"].toBool()) return {{"error", "该项已归档"}};
        o.remove("remindAt"); o.remove("condition");
        o["reminderState"] = "snoozed"; o["note"] = "保留在建议中，随时可以继续";
        if (action == "snooze") {
            const auto at = args["at"].toInteger();
            if (at <= now || at > now + 366LL * 86400) return {{"error", "请选择未来一年内的提醒时间"}};
            o["remindAt"] = at; o["note"] = QDateTime::fromSecsSinceEpoch(at).toString("M月d日 HH:mm") + " 提醒";
        }
    } else if (action == "reviewed" && o["issueState"] == "absent") {
        auto task = o["task"].toObject(); task["needsReview"] = false; o["task"] = task;
        o["reminderState"] = "none"; o["note"] = o["issueNote"];
    } else if (action == "dismiss") {
        o["reminderState"] = "dismissed"; o.remove("remindAt"); o.remove("condition"); o["note"] = "已停止提醒，可随时恢复";
    } else if (action == "restore") {
        o["reminderState"] = "none"; o.remove("remindAt"); o.remove("condition"); o["note"] = "已恢复到建议列表";
    } else return {{"error", "不支持的操作"}};
    o["notifiedRevision"] = o["deliveryRevision"];
    o["updated"] = now; items[id] = o; return get(id);
}
QStringList Model::due(qint64 now, const QStringList &) {
    QStringList result;
    for (const auto &id : items.keys()) {
        auto o = items[id].toObject();
        if (o["reminderState"] != "snoozed" || activeTask(o)) continue;
        // A fresh root batch doesn't establish freshness of every individual source.
        const bool resultReminder = o["task"].toObject()["needsReview"].toBool();
        if (!resultReminder && (o["issueState"] != "observed" || now - o["lastObserved"].toInteger() > 180 || now < o["lastObserved"].toInteger())) continue;
        const auto at = o["remindAt"].toInteger();
        if (at > 0 && at <= now) {
            o["reminderState"] = "none"; o["note"] = "已到你约定的处理时间";
            nextDelivery(o, resultReminder ? "task" : "reminder"); o.remove("remindAt");
            items[id] = o; result.append(id);
        }
    }
    return result;
}
bool Model::present(const QString &id, qint64 revision, bool opened, qint64 now) {
    auto o = items[id].toObject();
    if (o.isEmpty() || revision != o["deliveryRevision"].toInteger()) return false;
    const auto key = opened ? "openedRevision" : "displayedRevision";
    if (o[key].toInteger() >= revision) return false;
    o[key] = revision; o[opened ? "openedAt" : "displayedAt"] = now;
    items[id] = o; return true;
}
QJsonObject Model::notification(qint64 now, bool safe, bool inhibited) {
    if (inhibited || !settings["notifications"].toBool(true)) return {};
    QJsonArray ids, receipts;
    QJsonObject first;
    for (const auto &v : list()) {
        const auto o = v.toObject(); const auto state = o["state"].toString();
        if (state != "new" && state != "attention") continue;
        const auto r = o["deliveryRevision"].toInteger();
        if (qMax(o["displayedRevision"].toInteger(), qMax(o["openedRevision"].toInteger(), o["notifiedRevision"].toInteger())) >= r) continue;
        const bool task = o["deliveryReason"] == "task", scheduled = task || o["deliveryReason"] == "reminder";
        if (!task && (now - o["lastObserved"].toInteger() > 180 || now < o["lastObserved"].toInteger())) continue;
        if (!safe && o["severity"].toInt() < 2 && !scheduled) continue;
        if (!scheduled && o["severity"].toInt() < 2 && now - lastDigest < 86400) continue;
        ids.append(o["id"]); receipts.append(QJsonObject{{"id", o["id"]}, {"revision", r}});
        if (first.isEmpty()) first = o;
    }
    if (ids.isEmpty()) return {};
    return {{"ids", ids}, {"receipts", receipts}, {"item", first}};
}
void Model::notified(const QStringList &ids, qint64 now) {
    QJsonArray receipts;
    for (const auto &id : ids) receipts.append(QJsonObject{{"id", id}, {"revision", get(id)["deliveryRevision"]}});
    notifiedReceipts(receipts, now);
}
void Model::notifiedReceipts(const QJsonArray &receipts, qint64 now) {
    for (const auto &v : receipts) {
        const auto receipt = v.toObject(); const auto id = receipt["id"].toString(); auto o = items[id].toObject();
        if (o.isEmpty() || o["deliveryRevision"] != receipt["revision"]) continue;
        if (o["severity"].toInt() < 2 && o["deliveryReason"] == "discovery") lastDigest = now;
        o["notifiedRevision"] = receipt["revision"]; o["notifiedAt"] = now; items[id] = o;
    }
}
void Model::recoverTasks() {
    for (const auto &id : items.keys()) {
        auto o = items[id].toObject();
        if (activeTask(o)) {
            auto task = o["task"].toObject(); task["state"] = "recovering";
            // Old running tasks predate task IDs: preserve results, never invent a live task.
            if (task["id"].toString().isEmpty()) { task["state"] = "interrupted"; task["needsReview"] = true; }
            o["task"] = task; o["note"] = "正在核对原任务进度"; items[id] = o;
        }
    }
}
}
