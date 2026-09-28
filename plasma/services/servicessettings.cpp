// SPDX-License-Identifier: MIT
// Settings -> Services (docs/83): the services the container keeps off (service-policy.json), why,
// and their current state; turning one on or off goes through the KAuth helper
// (serviceshelper.cpp). Masks that are not in the policy are listed too: Ubuntu's own in /usr/lib
// (read-only) and any made in /etc (can be removed).

#include <KAuth/Action>
#include <KAuth/ExecuteJob>
#include <KPluginFactory>
#include <KQuickConfigModule>
#include <KUser>

#include <QDir>
#include <QFile>
#include <QFileInfo>
#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>
#include <QNetworkInterface>
#include <QProcess>
#include <QSet>
#include <QTimer>

using namespace Qt::StringLiterals;

namespace
{
const auto POLICY = u"/usr/share/rungic/service-policy.json"_s;

bool isMask(const QString &path)
{
    const QFileInfo info(path);
    return info.isSymLink() && info.symLinkTarget() == u"/dev/null";
}

QStringList strings(const QJsonValue &value)
{
    QStringList result;
    for (const auto &item : value.toArray()) {
        result << item.toString();
    }
    return result;
}

QString run(const QString &program, const QStringList &args)
{
    QProcess process;
    process.start(program, args);
    process.waitForFinished(10000);
    return QString::fromUtf8(process.readAllStandardOutput());
}

// systemctl show for the units: {unit: {property: value}}, in one call per scope.
QHash<QString, QHash<QString, QString>> show(const QStringList &units, bool user)
{
    QHash<QString, QHash<QString, QString>> result;
    if (units.isEmpty()) {
        return result;
    }
    QStringList args;
    if (user) {
        args << u"--user"_s;
    }
    args << u"show"_s << u"--property=Id,LoadState,ActiveState,UnitFileState"_s << u"--"_s << units;
    // One block per unit, in the order given, separated by an empty line.
    const auto blocks = run(u"systemctl"_s, args).split(u"\n\n"_s, Qt::SkipEmptyParts);
    for (int i = 0; i < blocks.size() && i < units.size(); ++i) {
        QHash<QString, QString> properties;
        for (const auto &line : blocks[i].split(u'\n', Qt::SkipEmptyParts)) {
            properties.insert(line.section(u'=', 0, 0), line.section(u'=', 1));
        }
        result.insert(units[i], properties);
    }
    return result;
}

QStringList masksIn(const QString &directory)
{
    QStringList result;
    for (const auto &info : QDir(directory).entryInfoList(QDir::Files | QDir::System | QDir::NoDotAndDotDot, QDir::Name)) {
        if (isMask(info.filePath())) {
            result << info.fileName();
        }
    }
    return result;
}
}

class ServicesSettings : public KQuickConfigModule
{
    Q_OBJECT
    Q_PROPERTY(QVariantList groups MEMBER m_groups NOTIFY changed)
    Q_PROPERTY(QStringList distributionMasks MEMBER m_distributionMasks NOTIFY changed)
    Q_PROPERTY(QVariantList otherMasks MEMBER m_otherMasks NOTIFY changed)
    Q_PROPERTY(QStringList addresses MEMBER m_addresses NOTIFY changed)
    Q_PROPERTY(QString userName MEMBER m_userName CONSTANT)
    Q_PROPERTY(QString hostKey MEMBER m_hostKey NOTIFY changed)
    Q_PROPERTY(bool busy MEMBER m_busy NOTIFY busyChanged)
    Q_PROPERTY(QString error MEMBER m_error NOTIFY errorChanged)

public:
    ServicesSettings(QObject *parent, const KPluginMetaData &data)
        : KQuickConfigModule(parent, data)
        , m_userName(KUser().loginName())
    {
        setButtons(NoAdditionalButton);
        refresh();
    }

    Q_INVOKABLE void refresh()
    {
        QFile file(POLICY);
        QJsonArray policy;
        if (file.open(QIODevice::ReadOnly)) {
            policy = QJsonDocument::fromJson(file.readAll()).object().value(u"groups"_s).toArray();
        } else {
            setError(u"找不到服务清单 %1"_s.arg(POLICY));
        }
        QStringList systemUnits, userUnits;
        QSet<QString> listed;
        for (const auto &value : policy) {
            const auto group = value.toObject();
            for (const auto &unit : strings(group.value(u"system"_s))) {
                systemUnits << unit;
                listed.insert(u"system/"_s + unit);
            }
            for (const auto &unit : strings(group.value(u"user"_s))) {
                userUnits << unit;
                listed.insert(u"user/"_s + unit);
            }
        }
        const auto systemState = show(systemUnits, false);
        const auto userState = show(userUnits, true);

        m_groups.clear();
        for (const auto &value : policy) {
            const auto group = value.toObject();
            const bool disabledKind = group.value(u"default"_s).toString() == u"disabled";
            const auto start = strings(group.value(u"start"_s));
            int masked = 0, total = 0, active = 0, enabled = 0, missing = 0;
            QStringList units;
            for (const auto &scope : {u"system"_s, u"user"_s}) {
                for (const auto &unit : strings(group.value(scope))) {
                    const auto state = scope == u"system" ? systemState.value(unit) : userState.value(unit);
                    ++total;
                    units << (scope == u"user" ? unit + u"（用户）"_s : unit);
                    if (isMask(u"/etc/systemd/%1/%2"_s.arg(scope, unit))) {
                        ++masked;
                    }
                    if (state.value(u"LoadState"_s) == u"not-found") {
                        ++missing;
                    }
                    if (state.value(u"ActiveState"_s) == u"active") {
                        ++active;
                    }
                    if ((start.isEmpty() || start.contains(unit)) && state.value(u"UnitFileState"_s).startsWith(u"enabled"_s)) {
                        ++enabled;
                    }
                }
            }
            QString status;
            bool on;
            if (disabledKind) {
                on = enabled > 0 && masked == 0;
                status = masked ? u"已屏蔽"_s : active ? u"运行中"_s : on ? u"已开启，未运行"_s : u"已关闭"_s;
            } else {
                on = masked == 0;
                status = masked == total ? u"已屏蔽"_s
                    : masked                ? u"部分屏蔽"_s
                    : missing == total      ? u"已允许（未安装）"_s
                    : active                ? u"已允许，运行中"_s
                                            : u"已允许，未运行"_s;
            }
            m_groups << QVariantMap{
                {u"id"_s, group.value(u"id"_s).toString()},
                {u"name"_s, group.value(u"name"_s).toString()},
                {u"summary"_s, group.value(u"summary"_s).toString()},
                {u"warning"_s, group.value(u"warning"_s).toString()},
                {u"risk"_s, group.value(u"risk"_s).toString()},
                {u"evidence"_s, group.value(u"evidence"_s).toString()},
                {u"kind"_s, disabledKind ? u"optional"_s : u"masked"_s},
                {u"units"_s, units},
                {u"on"_s, on},
                {u"status"_s, status},
            };
        }

        m_distributionMasks = masksIn(u"/usr/lib/systemd/system"_s);
        for (const auto &unit : masksIn(u"/usr/lib/systemd/user"_s)) {
            m_distributionMasks << unit + u"（用户）"_s;
        }
        m_otherMasks.clear();
        for (const auto &scope : {u"system"_s, u"user"_s}) {
            for (const auto &unit : masksIn(u"/etc/systemd/"_s + scope)) {
                if (!listed.contains(scope + u'/' + unit)) {
                    m_otherMasks << QVariantMap{{u"unit"_s, unit}, {u"scope"_s, scope}};
                }
            }
        }

        m_addresses.clear();
        for (const auto &interface : QNetworkInterface::allInterfaces()) {
            const auto flags = interface.flags();
            if (!(flags & QNetworkInterface::IsUp) || !(flags & QNetworkInterface::IsRunning) || (flags & QNetworkInterface::IsLoopBack)) {
                continue;
            }
            for (const auto &entry : interface.addressEntries()) {
                if (entry.ip().protocol() == QAbstractSocket::IPv4Protocol) {
                    m_addresses << u"%1  %2"_s.arg(entry.ip().toString(), interface.name());
                }
            }
        }
        // "256 SHA256:... root@host (ED25519)": what an SSH client shows on the first connection.
        m_hostKey.clear();
        const auto key = u"/etc/ssh/ssh_host_ed25519_key.pub"_s;
        if (QFile::exists(key)) {
            m_hostKey = run(u"ssh-keygen"_s, {u"-l"_s, u"-f"_s, key}).section(u' ', 1, 1);
        }
        Q_EMIT changed();
    }

    Q_INVOKABLE void setEnabled(const QString &group, bool enabled)
    {
        bool user = false;
        for (const auto &value : std::as_const(m_groups)) {
            const auto map = value.toMap();
            if (map.value(u"id"_s) == group) {
                const auto units = map.value(u"units"_s).toStringList();
                user = std::any_of(units.cbegin(), units.cend(), [](const QString &unit) {
                    return unit.endsWith(u"（用户）"_s);
                });
            }
        }
        execute(u"com.rungic.services.set"_s, {{u"group"_s, group}, {u"enabled"_s, enabled}}, user);
    }

    Q_INVOKABLE void unmask(const QString &unit, const QString &scope)
    {
        execute(u"com.rungic.services.unmask"_s, {{u"unit"_s, unit}, {u"scope"_s, scope}}, scope == u"user");
    }

Q_SIGNALS:
    void changed();
    void busyChanged();
    void errorChanged();

private:
    void setError(const QString &error)
    {
        m_error = error;
        Q_EMIT errorChanged();
    }

    void execute(const QString &name, const QVariantMap &args, bool userUnits)
    {
        KAuth::Action action(name);
        action.setHelperId(u"com.rungic.services"_s);
        action.setArguments(args);
        auto *job = action.execute();
        m_busy = true;
        Q_EMIT busyChanged();
        setError({});
        connect(job, &KJob::result, this, [this, job, userUnits] {
            if (job->error() && job->error() != KAuth::ActionReply::UserCancelledError) {
                setError(job->errorText().isEmpty() ? job->errorString() : job->errorText());
            }
            if (userUnits) {
                // The helper changed /etc/systemd/user; this user's manager loads it again.
                run(u"systemctl"_s, {u"--user"_s, u"daemon-reload"_s});
            }
            m_busy = false;
            Q_EMIT busyChanged();
            refresh();
            // sshd-keygen runs next to ssh.socket: the host key can appear a moment later.
            QTimer::singleShot(2000, this, &ServicesSettings::refresh);
        });
        job->start();
    }

    QVariantList m_groups;
    QStringList m_distributionMasks;
    QVariantList m_otherMasks;
    QStringList m_addresses;
    QString m_userName;
    QString m_hostKey;
    bool m_busy = false;
    QString m_error;
};

K_PLUGIN_CLASS_WITH_JSON(ServicesSettings, "kcm_rungic_services.json")

#include "servicessettings.moc"
