// SPDX-License-Identifier: GPL-2.0-or-later
#pragma once
#include "model.h"
#include <QHash>
#include <QList>
#include <QStringList>
namespace Care {
// An agent whose usage the desktop shows, declared by a descriptor file (data, never code;
// docs/research/95): <data dir>/rungic/agent-usage/providers/<id>.json.
struct UsageProvider {
    QString id, name, vendor, file;
    QString service, path, interface, method; // a D-Bus source ...
    QStringList command;                       // ... or a reader run without a shell
    int timeout = 0;                           // ms
    int order = 100;
    bool optional = false;                     // shown only once its source says it is available
    bool dbus() const { return command.isEmpty(); }
};
// Why a descriptor is invalid, or empty (and *out filled) when it is valid.
QString validateUsageProvider(const QJsonObject &descriptor, const QString &fileName, UsageProvider *out = nullptr);
// Descriptors from these directories, lowest precedence first: a later one with the same id replaces
// an earlier one (the user's own directory comes last). Ordered by "order", then id.
QList<UsageProvider> usageProviders(const QStringList &directories, QStringList *errors = nullptr);
// A Codex `thread/tokenUsage/updated` event as the voice agent signalled it before RecordTokens.
QJsonObject codexTokenEvent(const QJsonObject &legacy);

class Usage {
public:
    explicit Usage(QString path);
    void setProviders(const QList<UsageProvider> &providers);
    const QList<UsageProvider> &providers() const { return declared; }
    bool declares(const QString &provider) const;
    // A provider-shaped reply from the provider's source; fields outside the contract are dropped.
    void snapshot(const QString &provider, const QJsonObject &data, qint64 now);
    // The source could not be read: `offline` when it is not running at all.
    void failure(const QString &provider, const QString &message, bool offline = false);
    void identity(const QString &provider, const QString &accountKey);
    // A cumulative per-session count {"accountKey","session","turn","total","last"}; true if it counted.
    bool record(const QString &provider, const QJsonObject &event, qint64 now);
    QJsonObject view(qint64 now) const;
private:
    struct State {
        QString accountKey, problem, status = QStringLiteral("connecting");
        QJsonObject current;
        qint64 refreshed = 0, active = 0;
        bool seen = false, available = true, failed = false;
    };
    QJsonObject provider(const UsageProvider &p, const State &s, qint64 now) const;
    qint64 activeAt(const QString &provider, const State &s) const;
    void save();
    QString path, saveProblem;
    QList<UsageProvider> declared;
    QJsonObject ledger; // provider id -> {"accounts": {account key -> {"turns","days","total","updated"}}}
    QHash<QString, State> states;
};
}
