// SPDX-License-Identifier: GPL-2.0-or-later
#include "service.h"
#include "collector.h"
#include "layout.h"
#include "usage.h"
#include <KLocalizedString>
#include <QCoreApplication>
#include <QDBusConnection>
#include <QDBusConnectionInterface>
#include <QDBusInterface>
#include <QDBusReply>
#include <QDir>
#include <QFile>
#include <QFileInfo>
#include <QJsonDocument>
#include <QLockFile>
#include <QStandardPaths>
#include <cstdio>

int main(int argc, char **argv) {
    QCoreApplication app(argc, argv);
    app.setApplicationName("rungic-suggestions");
    KLocalizedString::setApplicationDomain("rungic-suggestions");
    const auto args = app.arguments();
    if (args.contains("--setup-widget")) {
        if (QDBusConnection::sessionBus().interface()->isServiceRegistered("org.kde.plasmashell")) return 1;
        QStringList launchers;
        for (const auto &id : {"com.rungic.VoiceAssistant.desktop", "firefox.desktop", "org.kde.dolphin.desktop", "org.kde.mobile.plasmasettings.desktop"})
            if (!QStandardPaths::locate(QStandardPaths::GenericDataLocation, QString("applications/") + id).isEmpty()) launchers.append(id);
        return Care::setupWidget(QStandardPaths::writableLocation(QStandardPaths::ConfigLocation) + "/plasma-org.kde.plasma.mobileshell-appletsrc", launchers) ? 0 : 1;
    }
    const auto stateDir = qEnvironmentVariable("RUNGIC_SUGGESTIONS_STATE",
        QStandardPaths::writableLocation(QStandardPaths::GenericDataLocation) + "/rungic-suggestions");
    const auto kb = qEnvironmentVariable("RUNGIC_COMPATIBILITY", "/usr/share/rungic/compatibility/entries");
    const auto feed = qEnvironmentVariable("RUNGIC_SUGGESTIONS_FEED", "/var/lib/rungic-suggestions/observations.json");
    if (args.contains("--collect")) {
        QString error;
        const auto ok = Care::writeObject(feed, Care::collectSystem(kb), &error);
        if (ok) QFile::setPermissions(feed, QFileDevice::ReadOwner | QFileDevice::WriteOwner | QFileDevice::ReadGroup | QFileDevice::ReadOther);
        else fprintf(stderr, "%s\n", qPrintable(error));
        return ok ? 0 : 1;
    }
    if (args.contains("--validate-knowledge")) {
        QStringList errors;
        const auto entries = Care::knowledge(kb, &errors);
        if (entries.isEmpty()) errors.append("knowledge is empty");
        for (const auto &e : errors) fprintf(stderr, "%s\n", qPrintable(e));
        printf("%lld entries\n", qlonglong(entries.size())); return errors.isEmpty() ? 0 : 1;
    }
    if (args.value(1) == "--validate-usage-providers") {
        // Build check for the descriptors a package ships (docs/research/95): every file must load.
        int invalid = 0;
        for (const auto &file : args.mid(2)) {
            const auto problem = Care::validateUsageProvider(Care::readObject(file), QFileInfo(file).fileName());
            if (!problem.isEmpty()) { fprintf(stderr, "%s: %s\n", qPrintable(file), qPrintable(problem)); ++invalid; }
        }
        return invalid || args.size() < 3 ? 1 : 0;
    }
    auto bus = QDBusConnection::sessionBus();
    if (args.contains("--service")) {
        QDir().mkpath(stateDir);
        QLockFile lock(stateDir + "/service.lock");
        if (!lock.tryLock(0)) return 2;
        Suggestions service(stateDir + "/state.json", feed, kb);
        if (!service.ready || !bus.registerService("com.rungic.Suggestions") ||
            !bus.registerObject("/com/rungic/Suggestions", &service, QDBusConnection::ExportAllSlots | QDBusConnection::ExportAllSignals)) return 1;
        return app.exec();
    }
    QDBusInterface service("com.rungic.Suggestions", "/com/rungic/Suggestions", "com.rungic.Suggestions", bus);
    QString method = "List"; QVariantList params;
    const auto command = args.value(1, "list");
    if (command == "get" || command == "feedback") { method = command == "get" ? "Get" : "Feedback"; params = {args.value(2)}; }
    else if (command == "update") { method = "Update"; params = {args.value(2), args.value(3)}; }
    else if (command == "act") { method = "Act"; params = {args.value(2), args.value(3), args.value(4, "{}")}; }
    else if (command == "knowledge") method = "Knowledge";
    else if (command == "usage") method = "AgentUsage";
    else if (command == "refresh") method = "Refresh";
    else if (command != "list") {
        fprintf(stderr, "Usage: rungic-suggestions list|get ID|act ID ACTION [JSON]|update ID JSON|feedback ID|knowledge|usage|refresh\n"); return 2;
    }
    const auto reply = service.callWithArgumentList(QDBus::Block, method, params);
    if (reply.type() == QDBusMessage::ErrorMessage) { fprintf(stderr, "%s\n", qPrintable(reply.errorMessage())); return 1; }
    const auto text = reply.arguments().value(0).toString(); printf("%s\n", qPrintable(text));
    return QJsonDocument::fromJson(text.toUtf8()).object().contains("error") ? 1 : 0;
}
