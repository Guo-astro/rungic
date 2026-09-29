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

class Model {
public:
    explicit Model(QString path);
    bool load(QString *error = nullptr);
    bool save(QString *error = nullptr) const;
    QJsonObject get(const QString &id) const;
    QJsonArray list() const;
    bool observe(QJsonObject item, qint64 now);
    void reconcile(const QString &source, const QStringList &present, qint64 now);
    QJsonObject act(const QString &id, const QString &action, const QJsonObject &args, qint64 now);
    bool update(const QString &id, const QJsonObject &fields);
    QStringList due(qint64 now, const QStringList &runningApps = {});
    QJsonObject notification(qint64 now, bool safe, bool inhibited);
    void notified(const QStringList &ids, qint64 now);
    void recoverTasks();
    QJsonObject settings;
private:
    QString path;
    QJsonObject items;
    qint64 lastDigest = 0;
};
}
