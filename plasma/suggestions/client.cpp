// SPDX-License-Identifier: GPL-2.0-or-later
#include "client.h"
#include <QDBusConnection>
#include <QDBusInterface>
#include <QDBusPendingCallWatcher>
#include <QDBusPendingReply>
#include <QDateTime>
#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>
#include <QProcess>
#include <QProcessEnvironment>
#include <QGuiApplication>
#include <KWaylandExtras>
#include <KWindowSystem>
#include <QTimer>

static constexpr auto BusName = "com.rungic.Suggestions";
static constexpr auto BusPath = "/com/rungic/Suggestions";
SuggestionsClient::SuggestionsClient(QObject *parent) : QObject(parent),
    m_watcher(BusName, QDBusConnection::sessionBus(), QDBusServiceWatcher::WatchForOwnerChange) {
    QDBusConnection::sessionBus().connect(BusName, BusPath, BusName, "Changed", this, SLOT(onChanged()));
    connect(&m_watcher, &QDBusServiceWatcher::serviceOwnerChanged, this,
        [this](const QString &, const QString &, const QString &owner) {
            if (owner.isEmpty()) { m_error = "建议服务正在重新连接"; Q_EMIT changed(); }
            else { refresh(); watching(m_watching); }
        });
    QTimer::singleShot(0, this, &SuggestionsClient::refresh);
}
void SuggestionsClient::onChanged() { refresh(); }
void SuggestionsClient::call(const QString &method, const QVariantList &args, const QString &id, const QString &action) {
    m_busy = true; Q_EMIT changed();
    auto message = QDBusMessage::createMethodCall(BusName, BusPath, BusName, method);
    message.setArguments(args);
    auto *w = new QDBusPendingCallWatcher(QDBusConnection::sessionBus().asyncCall(message), this);
    connect(w, &QDBusPendingCallWatcher::finished, this, [this, w, method, id, action] {
        QDBusPendingReply<QString> reply = *w; w->deleteLater(); m_busy = false;
        if (reply.isError()) { m_error = reply.error().message(); Q_EMIT changed(); return; }
        const auto result = QJsonDocument::fromJson(reply.value().toUtf8()).object();
        m_error = result.value("error").toString();
        if (method == "List" && m_error.isEmpty()) {
            m_items = result.value("items").toArray().toVariantList(); m_coverage.clear();
            for (const auto &v : result.value("coverage").toArray()) m_coverage.append(v.toString());
        } else Q_EMIT replied(id, action, result.toVariantMap());
        Q_EMIT changed();
    });
}
void SuggestionsClient::refresh() { call("List", {}); }
void SuggestionsClient::scan() {
    auto message = QDBusMessage::createMethodCall(BusName, BusPath, BusName, "Refresh");
    QDBusConnection::sessionBus().asyncCall(message);
}
void SuggestionsClient::act(const QString &id, const QString &action, const QVariantMap &args) {
    call("Act", {id, action, QString::fromUtf8(QJsonDocument(QJsonObject::fromVariantMap(args)).toJson(QJsonDocument::Compact))}, id, action);
}
void SuggestionsClient::launch(const QStringList &arguments) {
    const auto start = [arguments](const QString &token) {
        QProcess process;
        auto environment = QProcessEnvironment::systemEnvironment();
        environment.remove("XDG_ACTIVATION_TOKEN");
        if (!token.isEmpty()) environment.insert("XDG_ACTIVATION_TOKEN", token);
        process.setProcessEnvironment(environment);
        process.setProgram("/usr/bin/rungic-voice-assistant");
        process.setArguments(arguments);
        process.startDetached();
    };
    if (auto *window = QGuiApplication::focusWindow(); window && KWindowSystem::isPlatformWayland())
        KWaylandExtras::xdgActivationToken(window, "com.rungic.VoiceAssistant").then(this, start);
    else start({});
}
void SuggestionsClient::open(const QString &id) { launch({"--suggestion", id}); }
void SuggestionsClient::conversation(const QString &id) { if (!id.isEmpty()) launch({"--conversation", id}); }
void SuggestionsClient::watching(bool visible) {
    m_watching = visible;
    auto message = QDBusMessage::createMethodCall(BusName, BusPath, BusName, "SetVisible");
    message.setArguments({visible}); QDBusConnection::sessionBus().asyncCall(message);
}
double SuggestionsClient::tomorrow(int hour) const {
    return QDateTime(QDate::currentDate().addDays(1), QTime(qBound(0, hour, 23), 0)).toSecsSinceEpoch();
}
