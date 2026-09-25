// SPDX-License-Identifier: GPL-2.0-or-later
#include "agentclient.h"

#include <QDBusConnection>
#include <QDBusPendingCallWatcher>
#include <QDBusPendingReply>

static const QString Service = QStringLiteral("dev.moto.VoiceAgent");
static const QString Path = QStringLiteral("/dev/moto/VoiceAgent");

AgentClient::AgentClient(QObject *parent)
    : QObject(parent)
    , m_service(Service, Path, Service, QDBusConnection::sessionBus())
{
    // Opening a conversation starts Codex and a realtime session; allow for it.
    m_service.setTimeout(120000);
    QDBusConnection::sessionBus().connect(Service, Path, Service, QStringLiteral("Event"), this, SLOT(onEvent(QString)));
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
void AgentClient::releaseTalking() { call(QStringLiteral("ReleaseTalking"), {}); }
void AgentClient::cancelTalking() { call(QStringLiteral("CancelTalking"), {}); }
void AgentClient::startListening(const QString &screen) { call(QStringLiteral("StartListening"), {screen}); }
void AgentClient::deleteConversation(const QString &id) { call(QStringLiteral("DeleteConversation"), {id}); }
void AgentClient::startTalking(const QString &screen) { call(QStringLiteral("StartTalking"), {screen}); }
void AgentClient::stopTalking() { call(QStringLiteral("StopTalking"), {}); }
void AgentClient::interrupt() { call(QStringLiteral("Interrupt"), {}); }
void AgentClient::stopTask() { call(QStringLiteral("StopTask"), {}); }
void AgentClient::approve(const QString &id, const QString &decision) { call(QStringLiteral("Approve"), {id, decision}); }
void AgentClient::callCommand(const QString &command) { call(QStringLiteral("CallCommand"), {command}); }
void AgentClient::onEvent(const QString &json) { Q_EMIT event(json); }
