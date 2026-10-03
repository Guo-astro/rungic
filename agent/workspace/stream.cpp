// rungic-workspace-stream: a live picture of an agent workspace (docs/research/91).
//
// The assistant screen's floating window lives in the phone's KWin and cannot record another
// compositor; this helper connects to the workspace's KWin ($WAYLAND_DISPLAY), records its
// output through zkde_screencast (granted by its desktop file) with the pointer drawn in, so
// the user sees where the agent points, and prints "node <PipeWire node id>" on stdout. The
// stream lives while this process does (stdin closed or killed: it ends).
//
// The window's touches come back on stdin, one a line, into the workspace through its
// fake-input protocol (granted by the same desktop file):
//   pointer FX FY     pointer to that point of the output (fractions 0..1)
//   button CODE 0|1   Linux button code, released or pressed
//   axis 0|1 VALUE    vertical or horizontal scroll, in pointer axis units
//   key CODE 0|1      Linux key code, released or pressed (the phone's keyboard: Enter, Backspace...)
//   text BASE64       text typed on the phone, committed to the focused field as an input method
//                     does (KWin's VirtualKeyboard.commitText on the workspace's bus)
//
// --pointer-hidden (the independent desktop, workspace 0, docs/research/97 §19): the picture
// without the pointer, the user's touches being the pointer there; `pointer-stream on` adds a
// second picture with the pointer drawn in (fullscreen's touchpad mode), printed as
// "pointer-node <id>", and `pointer-stream off` ends it ("pointer-node 0"). `tv-stream on|off`
// likewise a picture of its own for the TV ("tv-node <id>").
//
// "prompting 1" while polkit's prompt waits in the workspace for its user (polkit-kde-agent's
// delegate on the workspace's bus shows the prompts of its apps there, docs/research/97 §21), and
// "prompting 0" once it is answered: the floating window says so.
#include <QDBusConnection>
#include <QDBusConnectionInterface>
#include <QDBusMessage>
#include <QDBusPendingCallWatcher>
#include <QDBusServiceWatcher>
#include <QDBusVariant>
#include <QGuiApplication>
#include <QScreen>
#include <QSocketNotifier>
#include <QStringList>
#include <QWaylandClientExtensionTemplate>
#include <QtGui/qscreen_platform.h>
#include <iostream>
#include <map>
#include <memory>
#include <unistd.h>

#include "qwayland-fake-input.h"
#include "qwayland-zkde-screencast-unstable-v1.h"

class Stream : public QObject, public QtWayland::zkde_screencast_stream_unstable_v1
{
    Q_OBJECT
public:
    explicit Stream(struct ::zkde_screencast_stream_unstable_v1 *stream)
        : zkde_screencast_stream_unstable_v1(stream)
    {
    }
    ~Stream() override
    {
        if (object())
            close();
    }
Q_SIGNALS:
    void created(uint node);
    void failed(const QString &error);
    void closedByCompositor();

protected:
    void zkde_screencast_stream_unstable_v1_created(uint32_t node) override { Q_EMIT created(node); }
    void zkde_screencast_stream_unstable_v1_failed(const QString &error) override { Q_EMIT failed(error); }
    void zkde_screencast_stream_unstable_v1_closed() override { Q_EMIT closedByCompositor(); }
};

// The delegate's Prompting on this workspace's bus, printed when it changes.
class PromptWatch : public QObject
{
    Q_OBJECT
public:
    PromptWatch()
    {
        const QString service = QStringLiteral("org.kde.polkit-kde-authentication-agent-1");
        const QString path = QStringLiteral("/org/kde/Polkit1AuthAgent/Delegate");
        QDBusConnection bus = QDBusConnection::sessionBus();
        bus.connect(service, path, QStringLiteral("org.kde.Polkit1AuthAgent.Delegate"), QStringLiteral("PromptingChanged"), this,
                    SLOT(changed(bool)));
        auto *watcher = new QDBusServiceWatcher(service, bus, QDBusServiceWatcher::WatchForUnregistration, this);
        connect(watcher, &QDBusServiceWatcher::serviceUnregistered, this, [this] {
            changed(false);
        });
        // Already waiting when this started (the window opened after the prompt); never starts it.
        if (bus.interface() && bus.interface()->isServiceRegistered(service)) {
            QDBusMessage get = QDBusMessage::createMethodCall(service, path, QStringLiteral("org.freedesktop.DBus.Properties"), QStringLiteral("Get"));
            get << QStringLiteral("org.kde.Polkit1AuthAgent.Delegate") << QStringLiteral("Prompting");
            auto *pending = new QDBusPendingCallWatcher(bus.asyncCall(get), this);
            connect(pending, &QDBusPendingCallWatcher::finished, this, [this](QDBusPendingCallWatcher *call) {
                call->deleteLater();
                const QDBusMessage reply = call->reply();
                if (reply.type() == QDBusMessage::ReplyMessage && !reply.arguments().isEmpty())
                    changed(qvariant_cast<QDBusVariant>(reply.arguments().first()).variant().toBool());
            });
        }
    }

public Q_SLOTS:
    void changed(bool prompting)
    {
        if (prompting == m_prompting)
            return;
        m_prompting = prompting;
        std::cout << "prompting " << (prompting ? 1 : 0) << std::endl;
    }

private:
    bool m_prompting = false;
};

class Screencasting : public QWaylandClientExtensionTemplate<Screencasting>, public QtWayland::zkde_screencast_unstable_v1
{
public:
    Screencasting()
        : QWaylandClientExtensionTemplate<Screencasting>(1)
    {
        initialize();
    }
};

class FakeInput : public QWaylandClientExtensionTemplate<FakeInput>, public QtWayland::org_kde_kwin_fake_input
{
public:
    FakeInput()
        : QWaylandClientExtensionTemplate<FakeInput>(4)
    {
        initialize();
    }
};

int main(int argc, char *argv[])
{
    qputenv("QT_QPA_PLATFORM", "wayland");
    QGuiApplication app(argc, argv);
    QGuiApplication::setDesktopFileName(QStringLiteral("com.rungic.WorkspaceStream"));
    Screencasting screencasting;
    FakeInput input;
    PromptWatch prompts;
    bool authenticated = false;
    std::unique_ptr<Stream> stream;
    constexpr uint hidden = 1, embedded = 2;    // the pointer left out of the picture, or drawn in
    const bool pointerHidden = app.arguments().contains(QStringLiteral("--pointer-hidden"));

    auto start = [&]() {
        QScreen *screen = QGuiApplication::primaryScreen();
        auto wayland = screen ? screen->nativeInterface<QNativeInterface::QWaylandScreen>() : nullptr;
        if (stream || !wayland || !screencasting.isActive()) {
            return;
        }
        stream = std::make_unique<Stream>(screencasting.stream_output(wayland->output(), pointerHidden ? hidden : embedded));
        QObject::connect(stream.get(), &Stream::created, &app, [](uint node) {
            std::cout << "node " << node << std::endl;
        });
        QObject::connect(stream.get(), &Stream::failed, &app, [](const QString &error) {
            std::cout << "error " << error.toStdString() << std::endl;
            QCoreApplication::exit(1);
        });
        QObject::connect(stream.get(), &Stream::closedByCompositor, &app, [] {
            QCoreApplication::exit(0);
        });
    };
    QObject::connect(&screencasting, &Screencasting::activeChanged, &app, start);
    QObject::connect(&app, &QGuiApplication::primaryScreenChanged, &app, start);
    start();
    // Other pictures of the same output, beside the first (no flash of black while one starts):
    // "pointer" with the pointer drawn in (fullscreen's touchpad mode), "tv" a fresh one for the TV
    // (a newly connected consumer of a running stream gets no frame until the screen changes: the
    // TV stayed black for up to a minute, until the clock turned; a new stream starts with one).
    std::map<std::string, std::unique_ptr<Stream>> extra;
    auto picture = [&](const std::string &name, bool on) {
        QScreen *screen = QGuiApplication::primaryScreen();
        auto wayland = screen ? screen->nativeInterface<QNativeInterface::QWaylandScreen>() : nullptr;
        auto &slot = extra[name];
        if (!on || !wayland || !screencasting.isActive()) {
            if (slot) {
                slot.reset();
                std::cout << name << "-node 0" << std::endl;
            }
            return;
        }
        if (slot) {
            return;
        }
        slot = std::make_unique<Stream>(screencasting.stream_output(wayland->output(), name == "pointer" ? embedded : hidden));
        QObject::connect(slot.get(), &Stream::created, &app, [name](uint node) {
            std::cout << name << "-node " << node << std::endl;
        });
        // Gone: the others stay. Not deleted inside its own signal.
        const auto gone = [&extra, &app, name, stream = slot.get()] {
            QMetaObject::invokeMethod(&app, [&extra, name, stream] {
                auto &current = extra[name];
                if (current.get() == stream) {
                    current.reset();
                    std::cout << name << "-node 0" << std::endl;
                }
            }, Qt::QueuedConnection);
        };
        QObject::connect(slot.get(), &Stream::failed, &app, gone);
        QObject::connect(slot.get(), &Stream::closedByCompositor, &app, gone);
    };
    auto command = [&](const QStringList &words) {
        if (words.isEmpty()) {
            return;
        }
        if ((words[0] == QLatin1String("pointer-stream") || words[0] == QLatin1String("tv-stream")) && words.size() == 2) {
            picture(words[0] == QLatin1String("pointer-stream") ? "pointer" : "tv", words[1] == QLatin1String("on"));
            return;
        }
        if (words[0] == QLatin1String("text") && words.size() == 2) {
            // As an input method commits it (text-input v1/v2/v3, else key events): any language.
            QDBusMessage call = QDBusMessage::createMethodCall(QStringLiteral("org.kde.KWin"), QStringLiteral("/VirtualKeyboard"),
                                                               QStringLiteral("org.kde.kwin.VirtualKeyboard"), QStringLiteral("commitText"));
            call << QString::fromUtf8(QByteArray::fromBase64(words[1].toLatin1()));
            QDBusConnection::sessionBus().send(call);
            return;
        }
        if (!input.isActive()) {
            return;
        }
        if (!authenticated) {
            input.authenticate(QStringLiteral("Assistant screen"), QStringLiteral("Touches in the floating window"));
            authenticated = true;
        }
        if (words[0] == QLatin1String("pointer") && words.size() == 3) {
            QScreen *screen = QGuiApplication::primaryScreen();
            if (!screen) {
                return;
            }
            const QRect g = screen->geometry();
            const double x = g.x() + qBound(0.0, words[1].toDouble(), 1.0) * (g.width() - 1);
            const double y = g.y() + qBound(0.0, words[2].toDouble(), 1.0) * (g.height() - 1);
            input.pointer_motion_absolute(wl_fixed_from_double(x), wl_fixed_from_double(y));
        } else if (words[0] == QLatin1String("button") && words.size() == 3) {
            input.button(words[1].toUInt(), words[2].toUInt());
        } else if (words[0] == QLatin1String("axis") && words.size() == 3) {
            input.axis(words[1].toUInt(), wl_fixed_from_double(words[2].toDouble()));
        } else if (words[0] == QLatin1String("key") && words.size() == 3) {
            input.keyboard_key(words[1].toUInt(), words[2].toUInt());
        }
    };
    QByteArray pending;
    QSocketNotifier commands(STDIN_FILENO, QSocketNotifier::Read);
    QObject::connect(&commands, &QSocketNotifier::activated, &app, [&]() {
        char buffer[512];
        const ssize_t n = read(STDIN_FILENO, buffer, sizeof buffer);
        if (n <= 0) {
            QCoreApplication::quit();
            return;
        }
        pending.append(buffer, n);
        qsizetype end;
        while ((end = pending.indexOf('\n')) >= 0) {
            command(QString::fromUtf8(pending.left(end)).split(QLatin1Char(' '), Qt::SkipEmptyParts));
            pending.remove(0, end + 1);
        }
    });
    return app.exec();
}

#include "stream.moc"
