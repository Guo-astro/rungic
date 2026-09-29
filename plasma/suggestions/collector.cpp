// SPDX-License-Identifier: GPL-2.0-or-later
#include "collector.h"
#include "model.h"
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
            auto o = observation("crash:" + it.key(), e.value("package").toString() + " 出现意外退出",
                QString("最近保留了 %1 份相同签名的报告。可以让 Agent 检查原因，尚未确定根因。").arg(e.value("reports").toInt()), "fault", 1, e);
            o["process"] = e.value("process");
            add(items, o, "crashes");
        }
        sources.append("crashes");
    } else coverage.append("崩溃目录暂不可读");

    for (const QString mount : {QString("/"), QString("/home")}) {
        QStorageInfo disk(mount);
        if (!disk.isValid() || !disk.isReady()) continue;
        const auto source = "storage:" + mount; sources.append(source);
        if (disk.bytesAvailable() < 1024LL * 1024 * 1024 && disk.bytesAvailable() * 100 < disk.bytesTotal() * 5) {
            add(items, observation(source, mount == "/" ? "系统存储空间不足" : "用户存储空间不足",
                "剩余空间不足，可能影响保存或软件更新。可以检查占用并准备清理建议。", "fault", 2,
                {{"availableBytes", disk.bytesAvailable()}, {"totalBytes", disk.bytesTotal()}, {"mount", mount}}), source);
        }
    }
    const auto audit = run("dpkg", {"--audit"});
    if (audit.ok) {
        sources.append("packages-audit");
        if (!audit.text.trimmed().isEmpty()) add(items, observation("packages-audit", "软件安装尚未完整结束",
            "软件包管理器报告了未完成的安装状态。Agent 可以先检查恢复办法。", "fault", 1,
            {{"check", "dpkg --audit"}, {"digest", fingerprint(QString::fromUtf8(audit.text))}}), "packages-audit");
    } else coverage.append("软件包完整性检查未完成");

    const auto failed = run("systemctl", {"--failed", "--no-legend", "--plain", "--no-pager"});
    if (failed.ok) {
        sources.append("system-services");
        for (const auto &line : QString::fromUtf8(failed.text).split('\n', Qt::SkipEmptyParts)) {
            const auto unit = line.simplified().section(' ', 0, 0);
            if (!unit.endsWith(".service") || unit.startsWith("rungic-suggestions")) continue;
            add(items, observation("system-service:" + unit, "系统服务需要检查", unit + " 运行失败，可以先检查影响与恢复办法。", "fault", 1,
                {{"unit", unit}, {"state", "failed"}, {"scope", "system"}}), "system-services");
        }
    } else coverage.append("系统服务检查未完成");
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
    } else coverage.append("兼容性目录或软件清单未完成校验");
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
            add(items, observation("service:" + unit, "后台服务需要检查",
                unit + " 启动失败，可以让 Agent 查看它是否影响正在使用的功能。", "fault", 1,
                {{"unit", unit}, {"state", "failed"}}), "user-services");
        }
    } else coverage.append("用户服务检查暂不可用");
    return {{"items", items}, {"sources", sources}, {"coverage", coverage}};
}
}
