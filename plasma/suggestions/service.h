// SPDX-License-Identifier: GPL-2.0-or-later
#pragma once
#include "model.h"
#include <QObject>
#include <QDBusContext>
#include <QTimer>
#include <QSet>

class Suggestions : public QObject, protected QDBusContext {
    Q_OBJECT
    Q_CLASSINFO("D-Bus Interface", "com.rungic.Suggestions")
public:
    Suggestions(const QString &state, const QString &feed, const QString &knowledge, QObject *parent = nullptr);
    bool ready = false;
public Q_SLOTS:
    QString List();
    QString Get(const QString &id);
    QString Act(const QString &id, const QString &action, const QString &json);
    QString Update(const QString &id, const QString &json);
    QString Feedback(const QString &id);
    QString Knowledge();
    void SetVisible(bool visible);
    void Refresh();
    void AgentEvent(const QString &json);
    void NotificationAction(uint notification, const QString &action);
Q_SIGNALS:
    void Changed();
private:
    void publish();
    void notify();
    void open(const QString &id);
    Care::Model model;
    QString feedPath, knowledgePath, statePath;
    QTimer scanTimer;
    bool scanning = false;
    QJsonArray coverage;
    QSet<QString> visibleClients;
    QHash<uint, QString> notifications;
};
