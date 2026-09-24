// SPDX-License-Identifier: GPL-2.0-or-later
// D-Bus client of the voice assistant service dev.moto.VoiceAgent (docs/59).
#pragma once

#include <QDBusInterface>
#include <QObject>
#include <QVariant>
#include <qqmlregistration.h>

class AgentClient : public QObject
{
    Q_OBJECT
    QML_ELEMENT
    QML_SINGLETON
public:
    explicit AgentClient(QObject *parent = nullptr);

    // JSON strings are parsed on the QML side.
    Q_INVOKABLE void listConversations();
    Q_INVOKABLE void openConversation(const QString &id);
    Q_INVOKABLE void closeConversation();
    Q_INVOKABLE void deleteConversation(const QString &id);
    // The screen the press came from; the reply plays on that side.
    Q_INVOKABLE void startTalking(const QString &screen);
    Q_INVOKABLE void stopTalking();
    Q_INVOKABLE void interrupt();
    Q_INVOKABLE void stopTask();
    Q_INVOKABLE void approve(const QString &id, const QString &decision);

Q_SIGNALS:
    void conversationsListed(const QString &json);
    void conversationOpened(const QString &json);
    void event(const QString &json);
    void failed(const QString &message);

private Q_SLOTS:
    void onEvent(const QString &json);

private:
    void call(const QString &method, const QVariantList &args, void (AgentClient::*reply)(const QString &) = nullptr);
    QDBusInterface m_service;
};
