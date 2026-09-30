// SPDX-License-Identifier: GPL-2.0-or-later
// D-Bus client of the voice assistant service com.rungic.VoiceAgent (docs/59).
#pragma once

#include <QDBusInterface>
#include <QDBusServiceWatcher>
#include <QObject>
#include <QVariant>
#include <functional>
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
    // A typed message; attachments: JSON [{"path", "name", "kind"}] (docs/87).
    Q_INVOKABLE void sendText(const QString &text, const QString &attachments);
    // Hold released over "To text": what was said, as text (textReady), sent nowhere.
    Q_INVOKABLE void talkToText();
    // "Read aloud": the voice reads this answer out.
    Q_INVOKABLE void readAloud(const QString &text);
    // Settings calls (Setup, SetApiKey, TestApiKey, RemoveApiKey, CodexLogin, InstallCodex,
    // CancelInstall, SetPreferences): the JSON reply comes as replied(method, json).
    Q_INVOKABLE void request(const QString &method, const QVariantList &args = {});
    // Whether this window shows the conversation to the user (docs/89): the voice says less
    // while someone looks. Said again when the service restarts.
    Q_INVOKABLE void setWatching(bool watching);
    // The conversation this window's actions belong to (docs/89). The service keeps one
    // conversation open for everyone: before a press, a message or Read aloud, this one is made the
    // open one, and the action follows only when it is.
    Q_PROPERTY(QString conversation MEMBER m_conversation NOTIFY conversationChanged)

Q_SIGNALS:
    void conversationsListed(const QString &json);
    void conversationOpened(const QString &json);
    void assistantOpened(const QString &json);
    void event(const QString &json);
    void failed(const QString &message);
    void textReady(const QString &json);
    void replied(const QString &method, const QString &json);
    void conversationChanged();

private Q_SLOTS:
    void onEvent(const QString &json);

private:
    void call(const QString &method, const QVariantList &args, void (AgentClient::*reply)(const QString &) = nullptr);
    // `action` once this window's conversation is the service's open one.
    void inConversation(std::function<void()> action);
    // `action` in order: after the actions still waiting for their conversation.
    void inOrder(std::function<void()> action);
    void drain();
    QDBusInterface m_service;
    QDBusServiceWatcher m_watcher;
    bool m_watching = false;
    QString m_conversation;
    bool m_waiting = false;                        // a Use is on its way
    QList<std::function<void()>> m_queue;          // what came meanwhile
};
