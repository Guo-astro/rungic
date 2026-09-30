// SPDX-License-Identifier: GPL-2.0-or-later
#pragma once
#include "model.h"
#include "usage.h"
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
    QString AgentUsage();
    void RefreshAgentUsage();
    QString Get(const QString &id);
    QString Act(const QString &id, const QString &action, const QString &json);
    QString Update(const QString &id, const QString &json);
    QString Feedback(const QString &id);
    QString Knowledge();
    void SetVisible(bool visible);
    void Presented(const QString &json, bool opened);
    void Refresh();
    void AgentEvent(const QString &json);
    void NotificationAction(uint notification, const QString &action);
    void NotificationToken(uint notification, const QString &token);
    void NotificationClosed(uint notification, uint reason);
Q_SIGNALS:
    void Changed();
    void UsageChanged();
private:
    bool publish();
    void recover();
    void notify();
    void open(const QString &id, const QString &token = {});
    Care::Model model;
    Care::Usage usage;
    bool usageRefreshing = false;
    qint64 usageAttempt = 0;
    QString feedPath, knowledgePath, statePath;
    QTimer scanTimer;
    bool scanning = false;
    bool notifying = false;
    QJsonArray coverage;
    QSet<QString> visibleClients;
    QHash<uint, QString> notifications;
    QHash<uint, QString> notificationTokens;
};
