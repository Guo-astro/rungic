// SPDX-License-Identifier: GPL-2.0-or-later
#include "claude_code.h"
#include "model.h"
#include <KLocalizedString>
#include <QDateTime>
#include <QDir>
#include <QDirIterator>
#include <QElapsedTimer>
#include <QFile>
#include <QFileInfo>
#include <QHash>
#include <QJsonArray>
#include <QJsonDocument>
#include <QSaveFile>
#include <QSet>
#include <QStandardPaths>
#include <algorithm>

namespace Care::ClaudeCode {
namespace {
constexpr qint64 LimitsFresh = 3600;  // statusline rate limits older than this are not shown
constexpr qint64 WorkingWithin = 90;  // a response this recent: a turn is (probably) still running
qint64 whole(const QJsonValue &v) { return v.isDouble() && v.toDouble() >= 0 && v.toDouble() < 9e15 ? qint64(v.toDouble()) : 0; }
QJsonObject load(const QString &path, qint64 limit) {
    QFile f(path);
    if (!f.open(QIODevice::ReadOnly) || f.size() > limit) return {};
    return QJsonDocument::fromJson(f.readAll()).object();
}
bool store(const QString &path, const QJsonObject &o, QString *error) {
    QDir().mkpath(QFileInfo(path).absolutePath());
    QSaveFile f(path);
    if (!f.open(QIODevice::WriteOnly)) { *error = f.errorString(); return false; }
    f.setPermissions(QFileDevice::ReadOwner | QFileDevice::WriteOwner);
    const auto bytes = QJsonDocument(o).toJson(QJsonDocument::Compact);
    if (f.write(bytes) != bytes.size() || !f.commit()) { *error = f.errorString(); return false; }
    return true;
}
QString projects(const QString &root) { return root.endsWith("/projects") ? root : root + "/projects"; }
}

Paths defaults() {
    QStringList roots;
    // Documented: CLAUDE_CONFIG_DIR is one directory replacing ~/.claude. A comma-separated list is
    // ccusage's convention for several; accepted the same way. Without it: ~/.claude and, for
    // versions that used XDG_CONFIG_HOME (changelog 1.0.28), ~/.config/claude.
    const auto configured = qEnvironmentVariable("CLAUDE_CONFIG_DIR");
    if (!configured.isEmpty()) {
        for (const auto &part : configured.split(',', Qt::SkipEmptyParts)) if (!part.trimmed().isEmpty()) roots.append(part.trimmed());
    } else roots = {QDir::homePath() + "/.claude", QStandardPaths::writableLocation(QStandardPaths::GenericConfigLocation) + "/claude"};
    const auto data = QStandardPaths::writableLocation(QStandardPaths::GenericDataLocation) + "/rungic/agent-usage";
    return {roots, data + "/claude-code-ledger.json", data + "/claude-code-statusline.json"};
}

qint64 lineTokens(const QJsonObject &line) {
    const auto usage = line["message"].toObject()["usage"].toObject();
    if (usage.isEmpty()) return 0;
    auto writes = whole(usage["cache_creation_input_tokens"]);
    const auto split = usage["cache_creation"].toObject();
    if (split.contains("ephemeral_5m_input_tokens") || split.contains("ephemeral_1h_input_tokens"))
        writes = whole(split["ephemeral_5m_input_tokens"]) + whole(split["ephemeral_1h_input_tokens"]);
    // As ccusage counts a message: everything the request processed, cache included.
    return whole(usage["input_tokens"]) + whole(usage["output_tokens"]) + writes + whole(usage["cache_read_input_tokens"]);
}

QJsonObject read(const Paths &paths, qint64 now, qint64 budgetMs) {
    auto ledger = load(paths.ledger, 256 * 1024 * 1024);
    const auto files = ledger["files"].toObject();
    // Counted messages: fingerprint -> [local day, tokens]. Kept as a list: tens of thousands of them.
    struct Entry { QString day; qint64 tokens = 0; };
    QHash<QString, Entry> entries;
    for (const auto &v : ledger["entries"].toArray()) {
        const auto e = v.toArray();
        if (e.size() == 3) entries.insert(e[0].toString(), {e[1].toString(), whole(e[2])});
    }
    auto latest = whole(ledger["latest"]);
    auto model = ledger["model"].toString();
    QStringList found;
    bool any = false;
    for (const auto &root : paths.roots) {
        if (!QFileInfo(projects(root)).isDir()) continue;
        any = true;
        // Sessions, their subagents/ and set-aside copies: a copy's messages are the same messages.
        QDirIterator it(projects(root), {"*.jsonl"}, QDir::Files, QDirIterator::Subdirectories);
        while (it.hasNext()) found.append(QFileInfo(it.next()).canonicalFilePath());
    }
    const auto statusline = load(paths.statusline, 64 * 1024);
    if (!any && statusline.isEmpty()) return {{"available", false}}; // Claude Code isn't used here
    found.removeAll(QString()); // broken links
    found.removeDuplicates();
    std::sort(found.begin(), found.end());
    QElapsedTimer timer; timer.start();
    bool unfinished = false;
    QJsonObject kept;
    for (const auto &path : found) {
        const QFileInfo info(path);
        auto offset = whole(files[path].toObject()["offset"]);
        if (info.size() < offset) offset = 0; // rewritten: its messages are deduplicated below
        if (info.size() > offset && timer.elapsed() < budgetMs) {
            QFile f(path);
            if (f.open(QIODevice::ReadOnly) && f.seek(offset)) {
                while (!f.atEnd()) {
                    if (timer.elapsed() >= budgetMs) break;
                    const auto line = f.readLine();
                    if (!line.endsWith('\n')) break; // still being written: next time
                    offset += line.size();
                    if (!line.contains("\"usage\"")) continue;
                    const auto o = QJsonDocument::fromJson(line).object();
                    const auto tokens = lineTokens(o);
                    const auto message = o["message"].toObject();
                    const auto stamp = QDateTime::fromString(o["timestamp"].toString(), Qt::ISODateWithMs);
                    if (tokens <= 0 || !stamp.isValid()) continue;
                    // One API response can be written to several files (resumed and forked sessions):
                    // counted once, as ccusage does, by message id and request id.
                    const auto id = message["id"].toString(), request = o["requestId"].toString();
                    const auto key = fingerprint(!id.isEmpty() && !request.isEmpty() ? id + '|' + request
                        : id + '|' + o["sessionId"].toString() + '|' + o["timestamp"].toString() + '|' + o["uuid"].toString());
                    const auto previous = entries.constFind(key);
                    if (previous == entries.constEnd() || previous->tokens < tokens)
                        entries.insert(key, {stamp.toLocalTime().date().toString(Qt::ISODate), tokens});
                    const auto at = stamp.toSecsSinceEpoch();
                    if (at >= latest) {
                        latest = at;
                        if (message["model"].isString() && !message["model"].toString().startsWith('<')) model = message["model"].toString().left(128);
                    }
                }
            }
        }
        if (info.size() > offset && timer.elapsed() >= budgetMs) unfinished = true;
        kept[path] = QJsonObject{{"offset", offset}};
    }
    const auto today = QDateTime::fromSecsSinceEpoch(now).date().toString(Qt::ISODate);
    qint64 device = 0, daily = 0;
    QJsonArray list;
    for (auto it = entries.constBegin(); it != entries.constEnd(); ++it) {
        list.append(QJsonArray{it.key(), it->day, it->tokens});
        device += it->tokens;
        if (it->day == today) daily += it->tokens;
    }
    QString error;
    const bool saved = store(paths.ledger, {{"schema", 1}, {"files", kept}, {"entries", list}, {"latest", latest}, {"model", model}}, &error);
    QJsonObject out{{"status", latest && now - latest <= WorkingWithin ? "working" : "ready"}, {"lastActive", latest}};
    if (any) out["tokens"] = QJsonObject{{"device", device}, {"today", daily}};
    const auto limits = statusline["rateLimits"].toObject();
    const auto limitsAt = whole(statusline["limitsAt"]);
    if (!limits.isEmpty() && now - limitsAt <= LimitsFresh) {
        // rate_limits exist only for claude.ai Pro and Max subscribers (statusline documentation).
        out["account"] = QJsonObject{{"kind", "subscription"}, {"label", "Claude"}, {"plan", ""}};
        QJsonArray list;
        for (const auto &[name, minutes] : {std::pair{"five_hour", 300}, std::pair{"seven_day", 10080}}) {
            const auto w = limits[name].toObject();
            if (w.isEmpty()) continue;
            list.append(QJsonObject{{"id", QString("claude-code.") + name}, {"label", "Claude"}, {"windowMinutes", minutes},
                                    {"usedPercent", w["usedPercent"]}, {"resetsAt", w["resetsAt"]}});
        }
        out["limits"] = list;
    }
    out["model"] = whole(statusline["receivedAt"]) >= latest && !statusline["model"].toString().isEmpty() ? statusline["model"].toString() : model;
    if (unfinished) out["error"] = i18n("Still reading the Claude Code history; the counts aren't complete yet");
    if (!saved) out["error"] = i18n("The Claude Code usage record wasn't saved: %1", error);
    return out;
}

QString statusline(const QByteArray &input, const Paths &paths, qint64 now) {
    const auto in = QJsonDocument::fromJson(input).object();
    if (in.isEmpty()) return {};
    auto kept = load(paths.statusline, 64 * 1024);
    kept["schema"] = 1;
    kept["receivedAt"] = now;
    kept["version"] = in["version"].toString().left(32);
    const auto model = in["model"].toObject();
    kept["model"] = model["id"].toString().left(128);
    kept["modelName"] = model["display_name"].toString().left(64);
    // Documented fields only (Claude Code >= 2.1.80): percentages 0-100, resets in epoch seconds.
    // They come after a session's first response; a window Claude Code dropped has reset.
    if (in["rate_limits"].isObject()) {
        const auto limits = in["rate_limits"].toObject();
        QJsonObject windows;
        for (const auto *name : {"five_hour", "seven_day"}) {
            const auto w = limits[name].toObject();
            const auto used = w["used_percentage"];
            if (!used.isDouble() || used.toDouble() < 0 || used.toDouble() > 100) continue; // cf. claude-code#52326
            windows[name] = QJsonObject{{"usedPercent", used.toDouble()},
                                        {"resetsAt", whole(w["resets_at"]) ? QJsonValue(whole(w["resets_at"])) : QJsonValue(QJsonValue::Null)}};
        }
        kept["rateLimits"] = windows;
        kept["limitsAt"] = now;
    }
    QString error;
    store(paths.statusline, kept, &error);
    QString line = kept["modelName"].toString();
    const auto windows = kept["rateLimits"].toObject();
    for (const auto &[name, label] : {std::pair{"five_hour", "5h"}, std::pair{"seven_day", "7d"}}) {
        if (!windows.contains(name)) continue;
        if (!line.isEmpty()) line += QStringLiteral(" · ");
        line += QStringLiteral("%1 %2%").arg(label).arg(qRound(windows[name].toObject()["usedPercent"].toDouble()));
    }
    return line;
}
}
