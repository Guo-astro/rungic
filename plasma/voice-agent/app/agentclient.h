// SPDX-License-Identifier: GPL-2.0-or-later
// D-Bus client of the voice assistant service com.rungic.VoiceAgent (docs/59).
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
    // Closes it only if it is still the open one ("" closes whatever is open).
    Q_INVOKABLE void closeConversation(const QString &id);
    // The one conversation of the Home button (docs/67); its history comes as assistantOpened.
    Q_INVOKABLE void openAssistant();
    // Home held: talk in the assistant's conversation until releaseTalking().
    Q_INVOKABLE void assistantTalk(const QString &screen);
    // A hold ended: the turn ends, or listening goes on hands-free if nothing was said yet.
    Q_INVOKABLE void releaseTalking();
    // Stop listening and drop what was said (the overlay dismissed while listening).
    Q_INVOKABLE void cancelTalking();
    // Hands-free from the start: the turn ends when speech does.
    Q_INVOKABLE void startListening(const QString &screen);
    Q_INVOKABLE void deleteConversation(const QString &id);
    // The screen the press came from; the reply plays on that side.
    Q_INVOKABLE void startTalking(const QString &screen);
    Q_INVOKABLE void stopTalking();
    Q_INVOKABLE void interrupt();
    Q_INVOKABLE void stopTask();
    Q_INVOKABLE void approve(const QString &id, const QString &decision);
    // Proxied call (docs/63): monitor-on, monitor-off, take-over, hang-up.
    Q_INVOKABLE void callCommand(const QString &command);

Q_SIGNALS:
    void conversationsListed(const QString &json);
    void conversationOpened(const QString &json);
    void assistantOpened(const QString &json);
    void event(const QString &json);
    void failed(const QString &message);

private Q_SLOTS:
    void onEvent(const QString &json);

private:
    void call(const QString &method, const QVariantList &args, void (AgentClient::*reply)(const QString &) = nullptr);
    QDBusInterface m_service;
};
