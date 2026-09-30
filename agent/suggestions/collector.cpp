// SPDX-License-Identifier: GPL-2.0-or-later
#include "collector.h"
#include "model.h"
#include <KLazyLocalizedString>
#include <QDateTime>
#include <QDir>
#include <QFile>
#include <QProcess>
#include <QStorageInfo>
#include <QRegularExpression>
#include <unistd.h>

namespace Care {
struct Output { QByteArray text; bool ok = false; };
static Output run(const QString &program, const QStringList &args, int timeout = 5000) {
    QProcess p; p.setProcessChannelMode(QProcess::SeparateChannels); p.start(program, args);
    if (!p.waitForFinished(timeout)) { p.kill(); p.waitForFinished(1000); return {}; }
    return {p.readAllStandardOutput().left(1024 * 1024), p.exitStatus() == QProcess::NormalExit && p.exitCode() == 0};
}
static void add(QJsonArray &items, QJsonObject o, const QString &source) { o["source"] = source; items.append(o); }
// The system half runs as root from a timer, outside the desktop session and its language. Texts
// stay untranslated messages (text and arguments; "l10n" for title and body) that the user's
// service renders in the desktop language (Care::localized); title and body hold this process's.
static QJsonObject message(const KLazyLocalizedString &text, const QStringList &args = {}) {
    return {{"text", QString::fromUtf8(text.untranslatedText())}, {"args", QJsonArray::fromStringList(args)}};
}
static QJsonObject localizedObservation(const QString &key, const QJsonObject &title, const QJsonObject &body,
                                        const QString &kind, int severity, const QJsonObject &evidence) {
    auto o = observation(key, translated(title), translated(body), kind, severity, evidence);
    o["l10n"] = QJsonObject{{"title", title}, {"body", body}};
    return o;
}
QStringList runningProcesses() {
    QStringList result;
    for (const auto &pid : QDir("/proc").entryList(QDir::Dirs | QDir::NoDotAndDotDot)) {
        if (pid.isEmpty() || !pid.at(0).isDigit()) continue;
        QFile f("/proc/" + pid + "/comm");
        if (f.open(QIODevice::ReadOnly)) result.append(QString::fromUtf8(f.readAll()).trimmed());
    }
    return result;
}
QJsonObject collectSystem(const QString &kb, const QString &cores) {
    QJsonArray items, sources, coverage;
    const auto now = QDateTime::currentSecsSinceEpoch();
    auto release = readObject("/usr/share/rungic/release.json");
    const auto packages = run("dpkg-query", {"-W", "-f=${binary:Package}\t${Version}\t${db:Status-Status}\n"});
    QJsonObject installed;
    if (packages.ok) for (const auto &line : packages.text.split('\n')) {
        const auto fields = line.split('\t');
        if (fields.size() == 3 && fields[2] == "installed") installed[QString::fromUtf8(fields[0]).section(':', 0, 0)] = QString::fromUtf8(fields[1]);
    }
    QJsonObject groups;
    QDir dir(cores);
    if (dir.exists() && dir.isReadable()) {
        for (const auto &folder : dir.entryList(QDir::Dirs | QDir::NoDotAndDotDot)) {
            const auto path = cores + '/' + folder + "/info.json";
            auto info = readObject(path);
            if (info.isEmpty() || QFileInfo(path).lastModified().toSecsSinceEpoch() < now - 7 * 86400) continue;
            auto signature = info.value("signature").toString();
            if (signature.isEmpty()) continue;
            const auto package = info.value("package").toObject();
            const auto name = package.value("name").toString(info.value("comm").toString("应用"));
            const auto version = package.value("version").toString();
            if (!version.isEmpty() && packages.ok && installed.value(name.section(':', 0, 0)).toString() != version) continue;
            const auto key = signature + ':' + name + ':' + version;
            auto group = groups.value(key).toObject();
            group["signature"] = signature; group["package"] = name; group["version"] = version;
            group["reports"] = group.value("reports").toInt() + 1;
            group["report"] = folder; group["release"] = info.value("release");
            group["signal"] = info.value("signal"); group["process"] = info.value("comm"); groups[key] = group;
        }
        for (auto it = groups.begin(); it != groups.end(); ++it) {
            const auto e = it.value().toObject();
            auto o = localizedObservation("crash:" + it.key(), message(kli18n("%1 quit unexpectedly"), {e.value("package").toString()}),
                message(kli18n("Reports with the same signature kept recently: %1. Agent can look into the cause; the root cause isn't known yet."),
                        {QString::number(e.value("reports").toInt())}), "fault", 1, e);
            o["process"] = e.value("process");
            add(items, o, "crashes");
        }
        sources.append("crashes");
    } else coverage.append(message(kli18n("The crash reports folder can't be read right now.")));

    for (const QString mount : {QString("/"), QString("/home")}) {
        QStorageInfo disk(mount);
        if (!disk.isValid() || !disk.isReady()) continue;
        const auto source = "storage:" + mount; sources.append(source);
        if (disk.bytesAvailable() < 1024LL * 1024 * 1024 && disk.bytesAvailable() * 100 < disk.bytesTotal() * 5) {
            add(items, localizedObservation(source, mount == "/" ? message(kli18n("System storage is almost full")) : message(kli18n("Your storage is almost full")),
                message(kli18n("Low free space can stop files from saving and software from updating. Agent can check what's using it and suggest what to clean up.")), "fault", 2,
                {{"availableBytes", disk.bytesAvailable()}, {"totalBytes", disk.bytesTotal()}, {"mount", mount}}), source);
        }
    }
    const auto audit = run("dpkg", {"--audit"});
    if (audit.ok) {
        sources.append("packages-audit");
        if (!audit.text.trimmed().isEmpty()) add(items, localizedObservation("packages-audit", message(kli18n("A software installation didn't finish")),
            message(kli18n("The package manager reports an unfinished installation. Agent can look for a way to recover first.")), "fault", 1,
            {{"check", "dpkg --audit"}, {"digest", fingerprint(QString::fromUtf8(audit.text))}}), "packages-audit");
    } else coverage.append(message(kli18n("The package integrity check didn't finish.")));

    const auto failed = run("systemctl", {"--failed", "--no-legend", "--plain", "--no-pager"});
    if (failed.ok) {
        sources.append("system-services");
        for (const auto &line : QString::fromUtf8(failed.text).split('\n', Qt::SkipEmptyParts)) {
            const auto unit = line.simplified().section(' ', 0, 0);
            if (!unit.endsWith(".service") || unit.startsWith("rungic-suggestions")) continue;
            add(items, localizedObservation("system-service:" + unit, message(kli18n("A system service needs checking")),
                message(kli18n("%1 failed. Check what it affects and how to recover."), {unit}), "fault", 1,
                {{"unit", unit}, {"state", "failed"}, {"scope", "system"}}), "system-services");
        }
    } else coverage.append(message(kli18n("The system services check didn't finish.")));
    QStringList errors;
    const auto entries = knowledge(kb, &errors);
    if (packages.ok && errors.isEmpty()) {
        sources.append("compatibility");
        for (const auto &v : entries) {
            const auto e = v.toObject(), match = e.value("match").toObject();
            if (e.value("kind") == "policy" || e.value("status") != "verified") continue;
            const auto package = match.value("package").toString(), version = installed.value(package).toString();
            if (!match.value("versions").toArray().contains(version)) continue;
            // Exact optional environment conditions. Missing identity means no match.
            bool fits = true;
            const auto constraints = match.value("environment").toObject();
            for (auto it = constraints.begin(); it != constraints.end(); ++it)
                if (release.value(it.key()) != it.value()) fits = false;
            if (!fits) continue;
            auto o = observation("compat:" + e.value("id").toString() + ':' + version, e.value("title").toString(),
                e.value("explanation").toString(), "optimization", 0,
                {{"package", package}, {"version", version}, {"knowledge", e.value("id")}, {"scope", "版本匹配，需复核本机实际表现"}});
            o["knowledge"] = e.value("id"); o["upstreamProject"] = e.value("upstreamProject");
            add(items, o, "compatibility");
        }
    } else coverage.append(message(kli18n("The compatibility catalog or the package list couldn't be verified.")));
    for (const auto &error : errors) coverage.append(error);
    return {{"schema", 1}, {"generated", now}, {"items", items}, {"sources", sources},
            {"coverage", coverage}, {"release", release}};
}
QJsonObject collectUser() {
    QJsonArray items, sources, coverage;
    const auto failed = run("systemctl", {"--user", "--failed", "--no-legend", "--plain", "--no-pager"});
    if (failed.ok) {
        sources.append("user-services");
        for (const auto &line : QString::fromUtf8(failed.text).split('\n', Qt::SkipEmptyParts)) {
            auto unit = line.simplified().section(' ', 0, 0);
            if (!unit.endsWith(".service") || unit.startsWith("rungic-suggestions")) continue;
            add(items, localizedObservation("service:" + unit, message(kli18n("A background service needs checking")),
                message(kli18n("%1 failed to start. Agent can check whether it affects what you're using."), {unit}), "fault", 1,
                {{"unit", unit}, {"state", "failed"}}), "user-services");
        }
    } else coverage.append(message(kli18n("The user services check isn't available right now.")));
    return {{"items", items}, {"sources", sources}, {"coverage", coverage}};
}
}
