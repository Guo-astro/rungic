// SPDX-License-Identifier: GPL-2.0-or-later
#include "agentclient.h"

#include <QDBusConnection>
#include <QDBusPendingCallWatcher>
#include <QDBusPendingReply>
#include <QJsonArray>
#include <QJsonDocument>

static const QString Service = QStringLiteral("com.rungic.VoiceAgent");
static const QString Path = QStringLiteral("/com/rungic/VoiceAgent");

AgentClient::AgentClient(QObject *parent)
    : QObject(parent)
    , m_service(Service, Path, Service, QDBusConnection::sessionBus())
    , m_watcher(Service, QDBusConnection::sessionBus(), QDBusServiceWatcher::WatchForRegistration)
{
    // Opening a conversation starts Codex and a realtime session; allow for it.
    m_service.setTimeout(120000);
    QDBusConnection::sessionBus().connect(Service, Path, Service, QStringLiteral("Event"), this, SLOT(onEvent(QString)));
    // The service started again (restarted or crashed, docs/87): what it had open is gone, a
    // running turn with it. Said as agent-restarted, so the pages open their conversation again.
    connect(&m_watcher, &QDBusServiceWatcher::serviceRegistered, this, [this]() {
        if (m_watching)
            call(QStringLiteral("SetWatching"), {true});
        Q_EMIT event(QStringLiteral("{\"type\":\"agent-restarted\"}"));
    });
}

void AgentClient::call(const QString &method, const QVariantList &args, void (AgentClient::*reply)(const QString &))
{
    auto *watcher = new QDBusPendingCallWatcher(m_service.asyncCallWithArgumentList(method, args), this);
    connect(watcher, &QDBusPendingCallWatcher::finished, this, [this, watcher, reply, method]() {
        watcher->deleteLater();
        if (watcher->isError()) {
            Q_EMIT failed(method + QStringLiteral(": ") + watcher->error().message());
            return;
        }
        if (reply) {
            QDBusPendingReply<QString> result = *watcher;
            (this->*reply)(result.value());
        }
    });
}

void AgentClient::listConversations() { call(QStringLiteral("ListConversations"), {}, &AgentClient::conversationsListed); }
void AgentClient::openConversation(const QString &id) { call(QStringLiteral("OpenConversation"), {id}, &AgentClient::conversationOpened); }
void AgentClient::closeConversation(const QString &id) { call(QStringLiteral("CloseConversation"), {id}); }
void AgentClient::openAssistant() { call(QStringLiteral("OpenAssistant"), {}, &AgentClient::assistantOpened); }
void AgentClient::assistantTalk(const QString &screen) { call(QStringLiteral("AssistantTalk"), {screen}); }
void AgentClient::releaseTalking() { inOrder([this] { call(QStringLiteral("ReleaseTalking"), {}); }); }
void AgentClient::cancelTalking() { inOrder([this] { call(QStringLiteral("CancelTalking"), {}); }); }
void AgentClient::startListening(const QString &screen)
{
    inConversation([this, screen] { call(QStringLiteral("StartListening"), {screen}); });
}
void AgentClient::deleteConversation(const QString &id) { call(QStringLiteral("DeleteConversation"), {id}); }
void AgentClient::startTalking(const QString &screen)
{
    inConversation([this, screen] { call(QStringLiteral("StartTalking"), {screen}); });
}
void AgentClient::stopTalking() { inOrder([this] { call(QStringLiteral("StopTalking"), {}); }); }
void AgentClient::interrupt() { call(QStringLiteral("Interrupt"), {}); }
void AgentClient::stopTask() { call(QStringLiteral("StopTask"), {}); }
void AgentClient::approve(const QString &id, const QString &decision) { call(QStringLiteral("Approve"), {id, decision}); }
void AgentClient::callCommand(const QString &command) { call(QStringLiteral("CallCommand"), {command}); }
void AgentClient::sendText(const QString &text, const QString &attachments)
{
    inConversation([this, text, attachments] { call(QStringLiteral("SendText"), {text, attachments}); });
}
void AgentClient::talkToText() { inOrder([this] { call(QStringLiteral("TalkToText"), {}, &AgentClient::textReady); }); }
void AgentClient::readAloud(const QString &text)
{
    inConversation([this, text] { call(QStringLiteral("ReadAloud"), {text}); });
}

void AgentClient::inConversation(std::function<void()> action)
{
    if (m_waiting) {
        m_queue.append([this, action] { inConversation(action); });
        return;
    }
    if (m_conversation.isEmpty()) {
        action();
        return;
    }
    // In order: the service runs every call on a thread of its own, so the action waits for the
    // reply, and what comes meanwhile (the release of a short press) waits behind it.
    m_waiting = true;
    auto *watcher = new QDBusPendingCallWatcher(m_service.asyncCall(QStringLiteral("Use"), m_conversation), this);
    connect(watcher, &QDBusPendingCallWatcher::finished, this, [this, watcher, action]() {
        watcher->deleteLater();
        if (watcher->isError())
            Q_EMIT failed(QStringLiteral("Use: ") + watcher->error().message());
        action();
        m_waiting = false;
        drain();
    });
}

void AgentClient::inOrder(std::function<void()> action)
{
    if (m_waiting)
        m_queue.append(action);
    else
        action();
}

void AgentClient::drain()
{
    while (!m_waiting && !m_queue.isEmpty())
        m_queue.takeFirst()();
}
void AgentClient::request(const QString &method, const QVariantList &args)
{
    auto *watcher = new QDBusPendingCallWatcher(m_service.asyncCallWithArgumentList(method, args), this);
    connect(watcher, &QDBusPendingCallWatcher::finished, this, [this, watcher, method]() {
        watcher->deleteLater();
        if (watcher->isError()) {
            Q_EMIT replied(method, QStringLiteral("{\"error\":%1}").arg(QString::fromUtf8(QJsonDocument(QJsonArray{watcher->error().message()}).toJson(QJsonDocument::Compact)).mid(1).chopped(1)));
            return;
        }
        QDBusPendingReply<QString> result = *watcher;
        Q_EMIT replied(method, result.value().isEmpty() ? QStringLiteral("{}") : result.value());
    });
}
void AgentClient::onEvent(const QString &json) { Q_EMIT event(json); }
void AgentClient::setWatching(bool watching)
{
    if (watching == m_watching)
        return;
    m_watching = watching;
    call(QStringLiteral("SetWatching"), {watching});
}
