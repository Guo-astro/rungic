// SPDX-License-Identifier: GPL-2.0-or-later
#pragma once
#include <QJsonArray>
#include <QJsonObject>
#include <QString>

namespace Care {
QJsonObject readObject(const QString &path);
bool writeObject(const QString &path, const QJsonObject &object, QString *error = nullptr);
QString fingerprint(const QString &text);
QString validateKnowledge(const QJsonObject &entry);
QJsonArray knowledge(const QString &directory, QStringList *errors = nullptr);
QJsonObject observation(const QString &key, const QString &title, const QString &body,
                        const QString &kind, int severity, const QJsonObject &evidence);
// A message recorded untranslated ({"text", "args"}) in the reader's language; other values as they are.
QString translated(const QJsonValue &message);
// An observation with its "l10n" messages rendered into title and body.
QJsonObject localized(QJsonObject observation);

class Model {
public:
    explicit Model(QString path);
    bool load(QString *error = nullptr);
    bool save(QString *error = nullptr) const;
    QJsonObject get(const QString &id) const;
    QJsonArray list() const;
    QJsonArray groups(bool history = false) const;
    bool observe(QJsonObject item, qint64 now);
    void reconcile(const QString &source, const QStringList &present, qint64 now);
    QJsonObject act(const QString &id, const QString &action, const QJsonObject &args, qint64 now);
    bool update(const QString &id, const QJsonObject &fields);
    QStringList due(qint64 now, const QStringList &runningApps = {});
    QJsonObject notification(qint64 now, bool safe, bool inhibited);
    void notified(const QStringList &ids, qint64 now);
    void recoverTasks();
    QJsonObject updatePlan(const QString &id, const QJsonObject &fields);
    QJsonObject beginTask(const QString &id, const QString &mode, const QString &approvedRevision, qint64 now);
    bool taskEvent(const QString &id, const QString &taskId, const QJsonObject &event, qint64 now);
    bool present(const QString &id, qint64 revision, bool opened, qint64 now);
    void notifiedReceipts(const QJsonArray &receipts, qint64 now);
    QJsonObject settings;
private:
    QString path;
    QJsonObject items;
    qint64 lastDigest = 0;
};
}
