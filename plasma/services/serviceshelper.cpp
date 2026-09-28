// SPDX-License-Identifier: MIT
// KAuth helper of Settings -> Services (docs/83): turns a group of service-policy.json on or off,
// or removes one existing mask in /etc/systemd. It runs as root and acts only on unit names it reads
// from the installed policy or finds as a mask there, never on other names the caller sends.

#include <KAuth/ActionReply>
#include <KAuth/HelperSupport>

#include <QFile>
#include <QFileInfo>
#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>
#include <QProcess>
#include <QRegularExpression>

using namespace Qt::StringLiterals;

namespace
{
const auto POLICY = u"/usr/share/rungic/service-policy.json"_s;

KAuth::ActionReply failure(const QString &message)
{
    auto reply = KAuth::ActionReply::HelperErrorReply();
    reply.setErrorDescription(message);
    return reply;
}

// systemctl with the arguments; an empty string on success, else its message.
QString systemctl(const QStringList &args)
{
    QProcess process;
    process.setProcessChannelMode(QProcess::MergedChannels);
    process.start(u"systemctl"_s, args);
    if (!process.waitForFinished(60000)) {
        process.kill();
        return u"systemctl %1: timed out"_s.arg(args.join(u' '));
    }
    if (process.exitStatus() != QProcess::NormalExit || process.exitCode() != 0) {
        const auto output = QString::fromUtf8(process.readAll()).trimmed();
        return u"systemctl %1: %2"_s.arg(args.join(u' '), output.isEmpty() ? u"failed"_s : output);
    }
    return {};
}

QStringList strings(const QJsonValue &value)
{
    QStringList result;
    for (const auto &item : value.toArray()) {
        result << item.toString();
    }
    return result;
}
}

class ServicesHelper : public QObject
{
    Q_OBJECT
public Q_SLOTS:
    KAuth::ActionReply set(const QVariantMap &args);
    KAuth::ActionReply unmask(const QVariantMap &args);
};

// args: group (an id in the policy), enabled (bool). A 'masked' group is unmasked or masked (and
// stopped); a 'disabled' group has its 'start' units enabled and started, or all its units
// disabled and stopped.
KAuth::ActionReply ServicesHelper::set(const QVariantMap &args)
{
    QFile file(POLICY);
    if (!file.open(QIODevice::ReadOnly)) {
        return failure(u"cannot read %1"_s.arg(POLICY));
    }
    const auto id = args.value(u"group"_s).toString();
    const bool enabled = args.value(u"enabled"_s).toBool();
    QJsonObject group;
    for (const auto &value : QJsonDocument::fromJson(file.readAll()).object().value(u"groups"_s).toArray()) {
        if (value.toObject().value(u"id"_s).toString() == id) {
            group = value.toObject();
        }
    }
    if (group.isEmpty()) {
        return failure(u"no service group %1"_s.arg(id));
    }
    const auto system = strings(group.value(u"system"_s));
    const auto user = strings(group.value(u"user"_s));
    QString error;
    if (group.value(u"default"_s).toString() == u"disabled") {
        if (!system.isEmpty()) {
            error = enabled ? systemctl(QStringList{u"enable"_s, u"--now"_s, u"--"_s} + strings(group.value(u"start"_s)))
                            : systemctl(QStringList{u"disable"_s, u"--now"_s, u"--"_s} + system);
        }
        if (error.isEmpty() && !user.isEmpty()) {
            error = systemctl(QStringList{u"--global"_s, enabled ? u"enable"_s : u"disable"_s, u"--"_s} + user);
        }
    } else {
        if (!system.isEmpty()) {
            error = enabled ? systemctl(QStringList{u"unmask"_s, u"--"_s} + system)
                            : systemctl(QStringList{u"mask"_s, u"--now"_s, u"--"_s} + system);
        }
        if (error.isEmpty() && !user.isEmpty()) {
            // Running user managers reload on the caller's side (it runs as the user).
            error = systemctl(QStringList{u"--global"_s, enabled ? u"unmask"_s : u"mask"_s, u"--"_s} + user);
        }
    }
    return error.isEmpty() ? KAuth::ActionReply::SuccessReply() : failure(error);
}

// args: unit, scope ("system" or "user"). Only an existing mask in /etc/systemd/<scope>.
KAuth::ActionReply ServicesHelper::unmask(const QVariantMap &args)
{
    static const QRegularExpression name(u"^[A-Za-z0-9:_.@\\-]+\\.(service|socket|target|path|timer|mount)$"_s);
    const auto unit = args.value(u"unit"_s).toString();
    const auto scope = args.value(u"scope"_s).toString();
    if (!name.match(unit).hasMatch() || (scope != u"system" && scope != u"user")) {
        return failure(u"invalid unit %1 (%2)"_s.arg(unit, scope));
    }
    const QFileInfo link(u"/etc/systemd/%1/%2"_s.arg(scope, unit));
    if (!link.isSymLink() || link.symLinkTarget() != u"/dev/null") {
        return failure(u"%1 is not masked in /etc/systemd/%2"_s.arg(unit, scope));
    }
    const auto error = scope == u"system" ? systemctl({u"unmask"_s, u"--"_s, unit}) : systemctl({u"--global"_s, u"unmask"_s, u"--"_s, unit});
    return error.isEmpty() ? KAuth::ActionReply::SuccessReply() : failure(error);
}

KAUTH_HELPER_MAIN("com.rungic.services", ServicesHelper)

#include "serviceshelper.moc"
