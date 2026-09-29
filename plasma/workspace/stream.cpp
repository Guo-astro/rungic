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
#include <QGuiApplication>
#include <QScreen>
#include <QSocketNotifier>
#include <QStringList>
#include <QWaylandClientExtensionTemplate>
#include <QtGui/qscreen_platform.h>
#include <iostream>
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
    bool authenticated = false;
    std::unique_ptr<Stream> stream;
    constexpr uint embedded = 2;    // the pointer drawn into the picture

    auto start = [&]() {
        QScreen *screen = QGuiApplication::primaryScreen();
        auto wayland = screen ? screen->nativeInterface<QNativeInterface::QWaylandScreen>() : nullptr;
        if (stream || !wayland || !screencasting.isActive()) {
            return;
        }
        stream = std::make_unique<Stream>(screencasting.stream_output(wayland->output(), embedded));
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
    auto command = [&](const QStringList &words) {
        if (words.isEmpty() || !input.isActive()) {
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
