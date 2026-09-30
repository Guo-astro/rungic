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
Model::Model(QString p) : path(std::move(p)) {}
bool Model::load(QString *error) {
    if (!QFile::exists(path)) return true;
    const auto data = readObject(path);
    if (data.value("schema").toInt() != 1 || !data.value("items").isObject()) {
        if (error) *error = "建议记录损坏，已保留原文件";
        return false;
    }
    items = data.value("items").toObject(); settings = data.value("settings").toObject();
    lastDigest = data.value("lastDigest").toInteger(); return true;
}
bool Model::save(QString *error) const {
    return writeObject(path, {{"schema", 1}, {"items", items}, {"settings", settings}, {"lastDigest", lastDigest}}, error);
}
QJsonObject Model::get(const QString &id) const { return items.value(id).toObject(); }
QJsonArray Model::list() const {
    QList<QJsonObject> sorted;
    for (auto it = items.begin(); it != items.end(); ++it) sorted.append(it.value().toObject());
    std::sort(sorted.begin(), sorted.end(), [](const auto &a, const auto &b) {
        auto rank = [](const auto &o) {
            const auto state = o.value("state").toString();
            if (state == "resolved") return -100;
            if (state == "dismissed") return -90;
            if (state == "snoozed") return -10;
            return o.value("severity").toInt();
        };
        if (rank(a) != rank(b)) return rank(a) > rank(b);
        return a.value("updated").toInteger() > b.value("updated").toInteger();
    });
    QJsonArray result; for (const auto &o : sorted) result.append(o); return result;
}
bool Model::observe(QJsonObject incoming, qint64 now) {
    const auto id = incoming.value("id").toString();
    if (id.isEmpty()) return false;
    auto old = get(id);
    const bool fresh = old.isEmpty();
    const bool recurrent = old.value("state").toString() == "resolved";
    bool changed = fresh || recurrent;
    for (auto it = incoming.begin(); it != incoming.end(); ++it) {
        if (old.value(it.key()) != it.value()) changed = true;
        old.insert(it.key(), it.value());
    }
    old["lastObserved"] = now;
    if (fresh) {
        old["created"] = now; old["state"] = "new"; old["notified"] = false;
        old["upstream"] = QJsonObject{{"state", "not_evaluated"}};
    } else if (recurrent) {
        old["state"] = "new"; old["notified"] = false;
        old["note"] = "问题再次出现，保留了此前处理记录";
    }
    // Repeated samples and changed counts don't undo mute or snooze.
    if (changed) old["updated"] = now;
    items[id] = old;
    return changed;
}
void Model::reconcile(const QString &source, const QStringList &present, qint64 now) {
    for (const auto &id : items.keys()) {
        auto o = get(id);
        if (o.value("source").toString() != source || present.contains(id)) continue;
        if (o.value("state").toString() == "resolved") continue;
        o["state"] = "resolved"; o["note"] = "复查不再匹配此项，已归档；不代表根因已确认修复";
        o["updated"] = now; o.remove("remindAt"); o.remove("condition");
        items[id] = o;
    }
}
bool Model::update(const QString &id, const QJsonObject &fields) {
    auto o = get(id); if (o.isEmpty()) return false;
    for (auto it = fields.begin(); it != fields.end(); ++it) o[it.key()] = it.value();
    items[id] = o; return true;
}
QJsonObject Model::act(const QString &id, const QString &action, const QJsonObject &args, qint64 now) {
    auto o = get(id);
    auto fail = [](QString s) { return QJsonObject{{"error", s}}; };
    if (o.isEmpty()) return fail("建议已不存在");
    const auto state = o.value("state").toString();
    if (action == "seen") { o["seen"] = true; }
    else if (action == "later" || action == "snooze" || action == "closed") {
        if (state == "working" || state == "resolved") return fail("当前状态不适合安排提醒");
        o.remove("remindAt"); o.remove("condition"); o["notified"] = true;
        o["state"] = "snoozed"; o["note"] = "保留在建议中，随时可以继续";
        if (action == "snooze") {
            const auto at = args.value("at").toInteger();
            if (at <= now || at > now + 366LL * 86400) return fail("请选择未来一年内的提醒时间");
            o["remindAt"] = at;
            o["note"] = QDateTime::fromSecsSinceEpoch(at).toString("M月d日 HH:mm") + " 提醒";
        } else if (action == "closed") {
            auto process = o.value("process").toString();
            if (process.isEmpty()) return fail("无法可靠识别此应用的退出，请选择时间提醒");
            o["condition"] = process; o["note"] = "等待应用关闭后提醒";
        }
    } else if (action == "dismiss") {
        if (state == "working") return fail("请先停止正在进行的处理");
        o["state"] = "dismissed"; o["notified"] = true;
        o.remove("remindAt"); o.remove("condition"); o["note"] = "已停止提醒，可随时恢复";
    } else if (action == "restore") {
        if (state == "working" || state == "resolved") return fail("当前状态无需恢复");
        o["state"] = "new"; o["notified"] = true;
        o.remove("remindAt"); o.remove("condition"); o["note"] = "已恢复到建议列表";
    } else return fail("不支持的操作");
    o["updated"] = now; items[id] = o; return o;
}
QStringList Model::due(qint64 now, const QStringList &runningApps) {
    QStringList result;
    for (const auto &id : items.keys()) {
        auto o = get(id);
        if (o.value("state").toString() != "snoozed") continue;
        const auto at = o.value("remindAt").toInteger();
        const auto app = o.value("condition").toString();
        if ((at > 0 && at <= now) || (!app.isEmpty() && !runningApps.contains(app))) {
            o["state"] = "new"; o["notified"] = false; o["scheduled"] = true;
            o["note"] = "已到你约定的处理时间";
            o.remove("remindAt"); o.remove("condition");
            items[id] = o; result.append(id);
        }
    }
    return result;
}
QJsonObject Model::notification(qint64 now, bool safe, bool inhibited) {
    if (inhibited || !settings.value("notifications").toBool(true)) return {};
    QStringList ids;
    for (const auto &v : list()) {
        auto o = v.toObject(); const auto state = o.value("state").toString();
        if ((state != "new" && state != "attention") || o.value("notified").toBool()) continue;
        // Without reliable context, stay in the widget/list; urgent errors can notify normally.
        if (!safe && o.value("severity").toInt() < 2 && !o.value("scheduled").toBool()) continue;
        if (!o.value("scheduled").toBool() && o.value("severity").toInt() < 2 && now - lastDigest < 86400) continue;
        ids.append(o.value("id").toString());
    }
    if (ids.isEmpty()) return {};
    return {{"ids", QJsonArray::fromStringList(ids)}, {"item", get(ids.first())}};
}
void Model::notified(const QStringList &ids, qint64 now) {
    for (const auto &id : ids) {
        auto o = get(id);
        if (o.value("severity").toInt() < 2 && !o.value("scheduled").toBool()) lastDigest = now;
        o["notified"] = true; o["notifiedAt"] = now; o.remove("scheduled"); items[id] = o;
    }
}
void Model::recoverTasks() {
    for (const auto &id : items.keys()) {
        auto o = get(id);
        if (o.value("state").toString() == "working") {
            o["state"] = "attention"; o["note"] = "服务重新连接，请查看原对话确认处理进度";
            o["notified"] = true; items[id] = o;
        }
    }
}
}
