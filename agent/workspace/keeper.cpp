// rungic-workspace-keeper N: agent workspace N while nobody uses it (docs/research/91, 工作区的生命周期).
//
// Started with the workspace (rungic-workspace) and ending with it. The workspace is quiet when the
// assistant's screen does not show it (the platform bridge), the agent is not at work in it (the
// voice agent's State), and there was no input in it for a while (ext-idle-notify-v1 from its KWin:
// the user's and the agent's input both count, and an app's idle inhibitor holds it off, as a player
// does). Quiet, its apps' slice is frozen (cgroup v2 freezer: no CPU, nothing lost, their memory free
// to be compressed), and thawed the moment one of those changes; whoever needs an app at once
// (the agent's tools, the floating window) thaws it first. Quiet for long, the workspace is closed as
// `rungic-cua close-workspace` does: its apps are asked first, and one that stays (unsaved work)
// keeps the workspace, frozen again, and the user is told once.
//
// RUNGIC_WORKSPACE_FREEZE_S (default 60) and RUNGIC_WORKSPACE_CLOSE_S (default 1800) set the times.
// What it decides goes to stderr, one line a change (rungic-workspace keeps it in keeper.log).
// It also turns the workspace's sound on while the workspace is shown, off while hidden
// (rungic-workspace-sound).
#include <QDBusConnection>
#include <QDBusMessage>
#include <QDateTime>
#include <algorithm>
#include <QFile>
#include <QFileInfo>
#include <QGuiApplication>
#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>
#include <QJsonValue>
#include <QLocalSocket>
#include <QProcess>
#include <QProcessEnvironment>
#include <QTimer>
#include <QWaylandClientExtensionTemplate>
#include <cstdio>
#include <cstring>
#include <functional>
#include <memory>
#include <optional>
#include <unistd.h>
#include <wayland-client.h>

#include "qwayland-ext-idle-notify-v1.h"

class Notifier : public QWaylandClientExtensionTemplate<Notifier>, public QtWayland::ext_idle_notifier_v1
{
public:
    Notifier()
        : QWaylandClientExtensionTemplate<Notifier>(1)
    {
        initialize();
    }
};

class IdleNotification : public QtWayland::ext_idle_notification_v1
{
public:
    explicit IdleNotification(::ext_idle_notification_v1 *object, std::function<void(bool)> changed)
        : QtWayland::ext_idle_notification_v1(object)
        , m_changed(std::move(changed))
    {
    }

protected:
    void ext_idle_notification_v1_idled() override
    {
        m_changed(true);
    }
    void ext_idle_notification_v1_resumed() override
    {
        m_changed(false);
    }

private:
    std::function<void(bool)> m_changed;
};

// The seat to watch: Qt's QWaylandApplication::seat() is the last input's, none before any input.
static wl_seat *bindSeat(wl_display *display)
{
    wl_seat *seat = nullptr;
    static const wl_registry_listener listener = {
        [](void *data, wl_registry *registry, uint32_t name, const char *interface, uint32_t) {
            auto **found = static_cast<wl_seat **>(data);
            if (!*found && std::strcmp(interface, wl_seat_interface.name) == 0) {
                *found = static_cast<wl_seat *>(wl_registry_bind(registry, name, &wl_seat_interface, 1));
            }
        },
        [](void *, wl_registry *, uint32_t) {},
    };
    wl_registry *registry = wl_display_get_registry(display);
    wl_registry_add_listener(registry, &listener, &seat);
    wl_display_roundtrip(display);
    return seat;
}

static void note(const QString &text)
{
    fprintf(stderr, "%s %s\n", qPrintable(QDateTime::currentDateTime().toString(Qt::ISODate)), qPrintable(text));
    fflush(stderr);
}

static int seconds(const char *name, int fallback)
{
    bool ok = false;
    const int value = qEnvironmentVariableIntValue(name, &ok);
    return ok && value > 0 ? value : fallback;
}

class Keeper
{
public:
    explicit Keeper(const QString &slot)
        : m_slot(slot)
        , m_slice(QStringLiteral("app-rungicws%1.slice").arg(slot))
        , m_closeAfter(seconds("RUNGIC_WORKSPACE_CLOSE_S", 1800))
    {
        const QByteArray user = qgetenv("RUNGIC_USER_DBUS_SESSION_BUS_ADDRESS");
        m_userBusAddress = !user.isEmpty() ? QString::fromUtf8(user)
                                           : QStringLiteral("unix:path=%1/bus").arg(qEnvironmentVariable("XDG_RUNTIME_DIR"));
        m_userBus = std::make_unique<QDBusConnection>(QDBusConnection::connectToBus(m_userBusAddress, QStringLiteral("user")));
        // A keeper started again finds its apps as it left them: running is where it starts.
        systemctl(QStringLiteral("thaw"));
    }

    void setInputIdle(bool idle)
    {
        note(idle ? QStringLiteral("no input") : QStringLiteral("input"));
        m_inputIdle = idle;
        check();
    }

    // A headless workspace (KWin's virtual backend, docs/research/97): the Android host has no surface
    // of it, so the app's director would not count it; this tells it the workspace runs, a few seconds
    // apart (an app started again or thawed learns it again). Never waits on a frozen app.
    void announce()
    {
        if (qEnvironmentVariable("RUNGIC_WORKSPACE_BACKEND") != QLatin1String("virtual"))
            return;
        QLocalSocket socket;
        socket.connectToServer(qEnvironmentVariable("RUNGIC_PLATFORM_SOCKET", QStringLiteral("/mnt/android-wayland/platform.sock")));
        if (!socket.waitForConnected(500))
            return;
        socket.write(QJsonDocument(QJsonObject{{QStringLiteral("op"), QStringLiteral("director")},
                                               {QStringLiteral("alive"), m_slot.toInt()}}).toJson(QJsonDocument::Compact) + '\n');
        socket.waitForBytesWritten(500);
        socket.waitForReadyRead(500);
    }

    // A headless workspace shown by the host (TV, fullscreen): its presenter runs; stopped when not.
    void present()
    {
        if (qEnvironmentVariable("RUNGIC_WORKSPACE_BACKEND") != QLatin1String("virtual"))
            return;
        const bool running = m_presenter && m_presenter->state() != QProcess::NotRunning;
        if (m_onHost && !running) {
            // One that ended soon after it started waits longer each time (30 s, doubled up to
            // 5 min): a presenter that keeps failing must not be started every few seconds.
            const qint64 now = QDateTime::currentMSecsSinceEpoch();
            if (m_presenter && m_presenterStarted && now - m_presenterStarted < 20000) {
                m_presenterBackoff = std::clamp<qint64>(m_presenterBackoff * 2, 30000, 300000);
                m_presenterRetry = m_presenterStarted + m_presenterBackoff;
                m_presenterStarted = 0;
                note(QStringLiteral("presenter ended early: again in %1 s").arg(m_presenterBackoff / 1000));
            } else if (m_presenterStarted) {
                m_presenterBackoff = 15000;
                m_presenterStarted = 0;
            }
            if (now < m_presenterRetry)
                return;
            if (!m_presenter) {
                m_presenter = new QProcess;
                m_presenter->setProcessChannelMode(QProcess::ForwardedChannels);
            }
            m_presenter->start(QStringLiteral("/usr/libexec/rungic-workspace-present"), {m_slot});
            m_presenterStarted = now;
            note(QStringLiteral("presenter started"));
        } else if (!m_onHost && running) {
            m_presenter->closeWriteChannel();  // it ends with its stdin
            if (!m_presenter->waitForFinished(2000))
                m_presenter->kill();
            note(QStringLiteral("presenter stopped"));
        }
    }

    void check()
    {
        announce();
        // Being closed (rungic_cua workspace.close): its apps must answer, nothing is frozen.
        const bool closing = QFile::exists(QStringLiteral("%1/rungic-workspace-%2.closing").arg(qEnvironmentVariable("XDG_RUNTIME_DIR"), m_slot));
        const bool isShown = shown();
        present();
        // Heard while shown, but of the TV's director view only the focus.
        const bool isHeard = isShown && m_heard;
        if (!m_soundShown || *m_soundShown != isHeard) {
            // Heard while shown, wherever (the phone's speaker, the TV's while casting): its sink's
            // monitor to the default output (rungic-workspace-sound).
            note(isHeard ? QStringLiteral("shown: sound on") : QStringLiteral("not heard: sound off"));
            QProcess::startDetached(QStringLiteral("rungic-workspace-sound"), {m_slot, isHeard ? QStringLiteral("listen") : QStringLiteral("quiet")});
            m_soundShown = isHeard;
        }
        const bool atWork = m_inputIdle && !closing && !isShown && agentAtWork();
        const bool quiet = m_inputIdle && !closing && !isShown && !atWork;
        const qint64 now = QDateTime::currentSecsSinceEpoch();
        if (m_frozen && !frozenNow()) {
            m_frozen = false; // thawed from outside (the agent's tools, the floating window): frozen again if still quiet
        }
        const QString why = !m_inputIdle ? QStringLiteral("input")
            : closing                    ? QStringLiteral("closing")
            : isShown                    ? QStringLiteral("shown")
                                         : QStringLiteral("agent at work");
        if (quiet != m_wasQuiet) {
            note(quiet ? QStringLiteral("quiet") : QStringLiteral("in use: %1").arg(why));
            m_wasQuiet = quiet;
        }
        if (!quiet) {
            m_quietSince = 0;
            m_closeTried = false;
            m_freezeTried = false;
            if (m_frozen) {
                note(QStringLiteral("thaw: %1").arg(systemctl(QStringLiteral("thaw"))));
                m_frozen = false;
            }
            return;
        }
        if (!m_quietSince) {
            m_quietSince = now;
        }
        if (now - m_quietSince >= m_closeAfter && !m_closeTried && !m_closing) {
            close();
            return;
        }
        if (!m_frozen && !m_closing && !m_freezeTried) {
            // No apps yet (no slice): nothing to freeze; tried once per quiet spell.
            const int status = systemctl(QStringLiteral("freeze"));
            m_frozen = status == 0;
            m_freezeTried = !m_frozen;
            note(QStringLiteral("freeze: %1").arg(status));
        }
    }

private:
    // systemctl and systemd-run on the user's session bus: on this workspace's own bus there is no
    // systemd ("Failed to add reference to unit": freeze asks for one there).
    QProcessEnvironment userEnvironment() const
    {
        QProcessEnvironment env = QProcessEnvironment::systemEnvironment();
        env.insert(QStringLiteral("DBUS_SESSION_BUS_ADDRESS"), m_userBusAddress);
        return env;
    }

    bool frozenNow() const
    {
        const uint uid = getuid();
        QFile events(QStringLiteral("/sys/fs/cgroup/user.slice/user-%1.slice/user@%1.service/app.slice/%2/cgroup.events").arg(uid).arg(m_slice));
        return events.open(QIODevice::ReadOnly) && events.readAll().contains("frozen 1");
    }

    int systemctl(const QString &verb)
    {
        QProcess process;
        process.setProcessEnvironment(userEnvironment());
        process.start(QStringLiteral("systemctl"), {QStringLiteral("--user"), verb, m_slice});
        process.waitForFinished(15000);
        if (process.exitStatus() != QProcess::NormalExit) {
            return -1;
        }
        const QByteArray error = process.readAllStandardError().trimmed();
        if (!error.isEmpty()) {
            note(QString::fromUtf8(error));
        }
        return process.exitCode();
    }

    // The assistant's screen shows this workspace (floating window, fullscreen or TV).
    bool shown()
    {
        QLocalSocket socket;
        socket.connectToServer(qEnvironmentVariable("RUNGIC_PLATFORM_SOCKET", QStringLiteral("/mnt/android-wayland/platform.sock")));
        if (!socket.waitForConnected(2000)) {
            return true; // unknown: as if shown, nothing is frozen on a guess
        }
        socket.write(QJsonDocument(QJsonObject{{QStringLiteral("op"), QStringLiteral("agent-screen")}}).toJson(QJsonDocument::Compact) + '\n');
        QByteArray reply;
        while (!reply.endsWith('\n') && socket.waitForReadyRead(2000)) {
            reply += socket.readAll();
        }
        const QJsonObject state = QJsonDocument::fromJson(reply).object();
        if (state.isEmpty()) {
            return true;
        }
        // The host's own picture of it (the TV, the phone's fullscreen): a headless workspace needs
        // its presenter for that (rungic-workspace-present, docs/research/97 §13).
        m_onHost = false;
        // On the TV: alone, or a tile of its director view (docs/58), where only the focus is heard.
        const QJsonArray onTv = state.value(QStringLiteral("tvShown")).toArray();
        if (onTv.contains(m_slot.toInt())) {
            m_heard = state.value(QStringLiteral("tvHeard")).toInt(-1) == m_slot.toInt();
            m_onHost = true;
            return true;
        }
        m_heard = true;
        if (!state.value(QStringLiteral("enabled")).toBool()) {
            return false;
        }
        // Its own floating window (several workspaces' can be out at once, rungic-agent-screen),
        // in a window or fullscreen there. The director's window shows every workspace running (docs/58); only its focus is heard.
        if (QProcess::execute(QStringLiteral("pgrep"), {QStringLiteral("-f"), QStringLiteral("^/usr/libexec/rungic-agent-screen-window --director")}) == 0) {
            m_heard = state.value(QStringLiteral("directorFocus")).toInt(-1) == m_slot.toInt();
            return true;
        }
        return QProcess::execute(QStringLiteral("pgrep"), {QStringLiteral("-f"), QStringLiteral("^/usr/libexec/rungic-agent-screen-window --workspace %1$").arg(m_slot)}) == 0;
    }

    // An agent is at work in this workspace: one holds it (rungic-workspace-N.busy, rungic_cua.workspace:
    // a runner's empty file until removed, or a sub-agent's desktop tools' record while that process
    // lives and touches it), or the voice agent's State says so.
    bool agentAtWork()
    {
        QFile claim(QStringLiteral("%1/rungic-workspace-%2.busy").arg(qEnvironmentVariable("XDG_RUNTIME_DIR"), m_slot));
        if (claim.open(QIODevice::ReadOnly)) {
            const QByteArray text = claim.readAll().trimmed();
            if (text.isEmpty()) {
                return true;
            }
            const QJsonValue pid = QJsonDocument::fromJson(text).object().value(QStringLiteral("pid"));
            const qint64 age = QFileInfo(claim).lastModified().secsTo(QDateTime::currentDateTime());
            if (!pid.isDouble() || (age < 20 * 60 && QFile::exists(QStringLiteral("/proc/%1").arg(pid.toInteger())))) {
                return true;
            }
        }
        QDBusMessage call = QDBusMessage::createMethodCall(QStringLiteral("com.rungic.VoiceAgent"), QStringLiteral("/com/rungic/VoiceAgent"),
                                                           QStringLiteral("com.rungic.VoiceAgent"), QStringLiteral("State"));
        const QDBusMessage reply = m_userBus->call(call, QDBus::Block, 3000);
        if (reply.type() != QDBusMessage::ReplyMessage || reply.arguments().isEmpty()) {
            return false; // no voice agent: no agent at work
        }
        const QJsonObject state = QJsonDocument::fromJson(reply.arguments().constFirst().toString().toUtf8()).object();
        return state.value(QStringLiteral("agentBusy")).toBool() && QString::number(state.value(QStringLiteral("workspace")).toInt(1)) == m_slot;
    }

    void close()
    {
        note(QStringLiteral("closing after %1 s quiet").arg(m_closeAfter));
        m_closing = true;
        if (m_frozen) {
            systemctl(QStringLiteral("thaw"));
            m_frozen = false;
        }
        auto *process = new QProcess;
        process->setProcessEnvironment(userEnvironment());
        QObject::connect(process, &QProcess::finished, process, [this, process] {
            // Closed: this keeper ends with the workspace. Still open: an app kept it (unsaved work).
            const QByteArray out = process->readAllStandardOutput();
            process->deleteLater();
            m_closing = false;
            m_closeTried = true;
            note(QStringLiteral("close: %1 %2").arg(QString::fromUtf8(out.trimmed()), QString::fromUtf8(process->readAllStandardError().trimmed())));
            const QJsonObject result = QJsonDocument::fromJson(out).object();
            if (!result.value(QStringLiteral("closed")).toBool() && result.contains(QStringLiteral("remaining"))) {
                QProcess::startDetached(QStringLiteral("rungic-user"),
                                        {QStringLiteral("rungic-agent-screen"), QStringLiteral("notify-unsaved"), m_slot,
                                         QString::fromUtf8(QJsonDocument(result).toJson(QJsonDocument::Compact))});
            }
            check();
        });
        // Outside this workspace's unit: its stop would end the closing half-way (it stops this keeper).
        process->start(QStringLiteral("systemd-run"), {QStringLiteral("--user"), QStringLiteral("--wait"), QStringLiteral("--pipe"),
                                                        QStringLiteral("--quiet"), QStringLiteral("--collect"), QStringLiteral("rungic-cua"),
                                                        QStringLiteral("close-workspace"), m_slot});
    }

    const QString m_slot;
    const QString m_slice;
    const int m_closeAfter;
    QString m_userBusAddress;
    std::unique_ptr<QDBusConnection> m_userBus;
    bool m_inputIdle = false;
    bool m_frozen = false;
    bool m_closing = false;
    bool m_closeTried = false;
    bool m_freezeTried = false;
    bool m_wasQuiet = false;
    std::optional<bool> m_soundShown;
    bool m_heard = true;    // shown() found it heard (false: a thumbnail of the TV's director view)
    bool m_onHost = false;  // shown() found the host showing it (the TV)
    QProcess *m_presenter = nullptr;
    qint64 m_presenterStarted = 0, m_presenterRetry = 0, m_presenterBackoff = 15000;
    qint64 m_quietSince = 0;
};

int main(int argc, char *argv[])
{
    qputenv("QT_QPA_PLATFORM", "wayland");
    QGuiApplication app(argc, argv);
    const QString slot = argc > 1 ? QString::fromLocal8Bit(argv[1]) : qEnvironmentVariable("RUNGIC_WORKSPACE", QStringLiteral("1"));
    Keeper keeper(slot);

    wl_display *display = qApp->nativeInterface<QNativeInterface::QWaylandApplication>()->display();
    wl_seat *seat = bindSeat(display);
    Notifier notifier;
    std::unique_ptr<IdleNotification> idle;
    const int freezeAfter = seconds("RUNGIC_WORKSPACE_FREEZE_S", 60);
    auto watch = [&] {
        if (notifier.isActive() && seat && !idle) {
            idle = std::make_unique<IdleNotification>(notifier.get_idle_notification(freezeAfter * 1000, seat),
                                                      [&keeper](bool isIdle) { keeper.setInputIdle(isIdle); });
        }
    };
    QObject::connect(&notifier, &Notifier::activeChanged, &app, watch);
    watch();
    note(QStringLiteral("workspace %1: seat %2, idle notifier %3, freeze after %4 s")
             .arg(slot, seat ? QStringLiteral("bound") : QStringLiteral("missing"),
                  notifier.isActive() ? QStringLiteral("active") : QStringLiteral("pending"))
             .arg(freezeAfter));

    // What the screens show changed (the Android app's "screens" events, platform bridge op
    // "watch"): checked at once, so the sound follows the director's focus without the poll's delay.
    QString screensEpoch;
    qint64 screensSeen = -1;
    std::function<void()> watchScreens;
    watchScreens = [&] {
        auto *socket = new QLocalSocket(&app);
        auto reply = std::make_shared<QByteArray>();
        auto done = std::make_shared<bool>(false);
        const auto retry = [&, socket, done](int delayMs) {
            if (*done)
                return;
            *done = true;
            socket->abort();
            socket->deleteLater();
            QTimer::singleShot(delayMs, &app, watchScreens);
        };
        QObject::connect(socket, &QLocalSocket::connected, socket, [&, socket] {
            QJsonObject request{{QStringLiteral("op"), QStringLiteral("watch")},
                                {QStringLiteral("topics"), QJsonArray{QStringLiteral("screens")}},
                                {QStringLiteral("timeout"), 30000}};
            if (!screensEpoch.isEmpty()) {
                request.insert(QStringLiteral("epoch"), screensEpoch);
                request.insert(QStringLiteral("seen"), QJsonObject{{QStringLiteral("screens"), screensSeen}});
            }
            socket->write(QJsonDocument(request).toJson(QJsonDocument::Compact) + '\n');
        });
        QObject::connect(socket, &QLocalSocket::readyRead, socket, [&, socket, reply, retry] {
            *reply += socket->readAll();
            if (!reply->contains('\n'))
                return;
            const QJsonObject answer = QJsonDocument::fromJson(reply->trimmed()).object();
            if (answer.isEmpty() || answer.contains(QStringLiteral("error"))) {
                retry(5000);
                return;
            }
            screensEpoch = answer.value(QStringLiteral("epoch")).toString();
            screensSeen = answer.value(QStringLiteral("versions")).toObject().value(QStringLiteral("screens")).toInteger();
            if (answer.value(QStringLiteral("changed")).toBool())
                keeper.check();
            retry(0);
        });
        QObject::connect(socket, &QLocalSocket::errorOccurred, socket, [retry](QLocalSocket::LocalSocketError) { retry(5000); });
        socket->connectToServer(qEnvironmentVariable("RUNGIC_PLATFORM_SOCKET", QStringLiteral("/mnt/android-wayland/platform.sock")));
    };
    watchScreens();

    // Shown, hidden, the agent at work or done: polled, a few seconds apart.
    QTimer timer;
    QObject::connect(&timer, &QTimer::timeout, &app, [&keeper] { keeper.check(); });
    timer.start(3000);
    return app.exec();
}
