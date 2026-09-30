// SPDX-License-Identifier: GPL-2.0-or-later
#include "usage.h"
#include <QDateTime>
#include <QFileInfo>
#include <utility>
namespace Care {
Usage::Usage(QString p) : path(std::move(p)) {
    const auto stored = path.isEmpty() ? QJsonObject{} : readObject(path);
    accounts = stored["accounts"].toObject();
    // An account must be verified this session before showing any cached values.
}
void Usage::save() {
    QString error;
    if (!writeObject(path, {{"schema", 1}, {"accounts", accounts}}, &error)) problem = "用量记录未保存：" + error;
}
void Usage::identity(const QString &key) {
    if (key == accountKey) return;
    accountKey = key; current = {}; refreshed = 0; problem.clear();
}
void Usage::snapshot(const QJsonObject &data, qint64 now) {
    identity(data["accountKey"].toString());
    auto next = data;
    if (!data["usageError"].toString().isEmpty()) {
        for (const auto &key : {"rateLimits", "accountUsage"}) if (!next.contains(key)) next[key] = current[key];
    }
    current = next; current.remove("accountKey"); current.remove("tokens");
    problem = data["usageError"].toString(); if (problem.isEmpty()) refreshed = now;
    for (const auto &v : data["tokens"].toArray()) token(v.toObject(), now);
}
void Usage::token(const QJsonObject &event, qint64 now) {
    const auto key = event["accountKey"].toString();
    const auto thread = event["threadId"].toString(), turn = event["turnId"].toString();
    if (key.isEmpty() || thread.isEmpty() || turn.isEmpty()) return;
    const auto total = event["tokenUsage"].toObject()["total"].toObject()["totalTokens"].toInteger(-1);
    if (total < 0) return;
    auto account = accounts.value(key).toObject();
    auto turns = account["turns"].toObject();
    const auto id = fingerprint(thread);
    auto record = turns.value(id).toObject();
    const auto previous = record.isEmpty()
        ? qMax<qint64>(0, total - event["tokenUsage"].toObject()["last"].toObject()["totalTokens"].toInteger())
        : record["tokens"].toInteger();
    if (total <= previous) return; // repeated/sparse/out-of-order cumulative updates
    const auto day = QDateTime::fromSecsSinceEpoch(now).date().toString(Qt::ISODate);
    auto days = account["days"].toObject();
    days[day] = days.value(day).toInteger() + total - previous;
    record["tokens"] = total; turns[id] = record;
    account["turns"] = turns; account["days"] = days;
    account["total"] = account["total"].toInteger() + total - previous;
    account["updated"] = now;
    accounts[key] = account; save();
}
QJsonObject Usage::view(qint64 now) const {
    QJsonObject result = current;
    result["provider"] = "Codex";
    result["updatedAt"] = refreshed;
    result["stale"] = !refreshed || now - refreshed > 180 || !problem.isEmpty();
    result["error"] = problem;
    const auto local = accounts.value(accountKey).toObject();
    result["recordedTokens"] = accountKey.isEmpty() || local.isEmpty() ? QJsonValue(QJsonValue::Null) : local["total"];
    result["todayRecordedTokens"] = accountKey.isEmpty() || local.isEmpty() ? QJsonValue(QJsonValue::Null)
        : QJsonValue(local["days"].toObject().value(QDateTime::fromSecsSinceEpoch(now).date().toString(Qt::ISODate)).toInteger());
    QJsonArray windows;
    const auto limits = current["rateLimits"].toObject();
    auto buckets = limits["rateLimitsByLimitId"].toObject();
    if (buckets.isEmpty() && limits["rateLimits"].isObject()) buckets["codex"] = limits["rateLimits"];
    if (current["authMode"] == "chatgpt") for (auto it = buckets.begin(); it != buckets.end(); ++it) {
        const auto bucket = it.value().toObject();
        for (const auto &field : {"primary", "secondary"}) {
            auto w = bucket[field].toObject();
            if (!w["usedPercent"].isDouble()) continue;
            w["bucket"] = bucket["limitName"].toString(it.key());
            w["expired"] = w["resetsAt"].isDouble() && w["resetsAt"].toInteger() <= now;
            windows.append(w);
        }
    }
    result["windows"] = windows;
    result.remove("rateLimits");
    return result;
}
}
