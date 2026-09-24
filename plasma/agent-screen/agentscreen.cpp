#include "agentscreen.h"

#include <QCoreApplication>
#include <QGuiApplication>
#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>
#include <QLocalSocket>
#include <QProcess>
#include <QScreen>
#include <QThread>
#include <QWaylandClientExtensionTemplate>
#include <QtGui/qscreen_platform.h>

#include "qwayland-fake-input.h"
#include "qwayland-zkde-screencast-unstable-v1.h"

namespace
{
const QString kSocket = QStringLiteral("/mnt/android-wayland/platform.sock");
// No pointer in the picture: asking for it embedded makes KWin show the pointer, which then sat on the
// phone's own screen as a black square (the host draws its cursor surface without alpha).
constexpr uint kPointerHidden = 1;

// One request on the platform bridge; `timeoutMs` covers a TV connection (up to a minute).
QJsonObject bridge(const QJsonObject &request, int timeoutMs = 3000)
{
    QLocalSocket socket;
    socket.connectToServer(kSocket);
    if (!socket.waitForConnected(1000))
        return {{QStringLiteral("error"), QStringLiteral("platform bridge unavailable")}};
    socket.write(QJsonDocument(request).toJson(QJsonDocument::Compact) + '\n');
    socket.flush();
    QByteArray reply;
    while (!reply.contains('\n') && socket.waitForReadyRead(timeoutMs))
        reply += socket.readAll();
    return QJsonDocument::fromJson(reply.trimmed()).object();
}
}

class ScreencastStream : public QObject, public QtWayland::zkde_screencast_stream_unstable_v1
{
    Q_OBJECT
public:
    explicit ScreencastStream(struct ::zkde_screencast_stream_unstable_v1 *stream)
        : zkde_screencast_stream_unstable_v1(stream)
    {
    }
    ~ScreencastStream() override
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
    ~Screencasting() override
    {
        if (object())
            destroy();
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

#include "agentscreen.moc"

AgentScreen::AgentScreen(QObject *parent)
    : QObject(parent)
    , m_screencasting(std::make_unique<Screencasting>())
    , m_input(std::make_unique<FakeInput>())
{
    connect(qGuiApp, &QGuiApplication::screenAdded, this, &AgentScreen::update);
    connect(qGuiApp, &QGuiApplication::screenRemoved, this, &AgentScreen::update);
    // The phone turning landscape widens its output over the assistant's screen.
    const auto watch = [this](QScreen *screen) {
        connect(screen, &QScreen::geometryChanged, this, [this] { QTimer::singleShot(300, this, &AgentScreen::keepApart); });
    };
    for (QScreen *screen : QGuiApplication::screens())
        watch(screen);
    connect(qGuiApp, &QGuiApplication::screenAdded, this, watch);
    connect(m_screencasting.get(), &Screencasting::activeChanged, this, &AgentScreen::update);
    connect(&m_poll, &QTimer::timeout, this, &AgentScreen::poll);
    m_poll.start(1500);
    poll();
}

AgentScreen::~AgentScreen() = default;

void AgentScreen::setStatus(const QString &status)
{
    if (m_status == status)
        return;
    m_status = status;
    qInfo() << "agent screen:" << status;
    Q_EMIT statusChanged();
}

QScreen *AgentScreen::agentOutput() const
{
    const auto screens = QGuiApplication::screens();
    for (QScreen *screen : screens) {
        if (screen->name().startsWith(QLatin1String("CAST")))
            return screen;
    }
    return nullptr;
}

// Outputs that overlap in KWin's space show the same windows: after the phone turned landscape (360
// -> 800 wide) its home screen appeared inside the assistant's screen. Nothing rearranges the outputs
// then, so move the assistant's screen next to the phone's.
void AgentScreen::keepApart()
{
    QScreen *agent = agentOutput();
    if (!agent)
        return;
    const auto screens = QGuiApplication::screens();
    for (QScreen *screen : screens) {
        if (screen == agent || !screen->geometry().intersects(agent->geometry()))
            continue;
        const QRect phone = screen->geometry();
        const QString position = QStringLiteral("output.%1.position.%2,%3").arg(agent->name()).arg(phone.right() + 1).arg(phone.top());
        qInfo() << "agent screen: overlaps" << screen->name() << "- kscreen-doctor" << position;
        QProcess::startDetached(QStringLiteral("kscreen-doctor"), {position});
        return;
    }
}

void AgentScreen::poll()
{
    const QJsonObject state = bridge({{QStringLiteral("op"), QStringLiteral("agent-screen")}});
    if (state.contains(QStringLiteral("error"))) {
        setStatus(QStringLiteral("error: ") + state.value(QStringLiteral("error")).toString());
        return;
    }
    m_enabled = state.value(QStringLiteral("enabled")).toBool();
    m_onTv = state.value(QStringLiteral("tv")).toBool();
    if (!m_enabled) {  // turned off elsewhere (quick setting, moto-agent-screen off)
        QCoreApplication::quit();
        return;
    }
    update();
}

void AgentScreen::update()
{
    QScreen *output = agentOutput();
    if (!output) {
        stopStream();
        setStatus(QStringLiteral("waiting for the screen"));
        return;
    }
    if (m_onTv) {  // the TV shows it: no recording, the floating window hides
        stopStream();
        setStatus(QStringLiteral("tv"));
        return;
    }
    if (m_stream && m_streamed == output)
        return;
    startStream();
}

void AgentScreen::startStream()
{
    stopStream();
    QScreen *output = agentOutput();
    auto wayland = output ? output->nativeInterface<QNativeInterface::QWaylandScreen>() : nullptr;
    if (!wayland || !m_screencasting->isActive()) {
        setStatus(QStringLiteral("waiting for KWin"));
        return;
    }
    m_stream = std::make_unique<ScreencastStream>(m_screencasting->stream_output(wayland->output(), kPointerHidden));
    m_streamed = output;
    setStatus(QStringLiteral("connecting"));
    connect(m_stream.get(), &ScreencastStream::created, this, [this](uint node) {
        m_nodeId = node;
        Q_EMIT nodeIdChanged();
        setStatus(QStringLiteral("running"));
        // The pointer belongs to the assistant's screen; left on the phone's it shows there.
        if (!m_pointerPlaced) {
            m_pointerPlaced = true;
            pointerMove(0.5, 0.5);
        }
    });
    connect(m_stream.get(), &ScreencastStream::failed, this, [this](const QString &error) {
        setStatus(QStringLiteral("error: ") + error);
        stopStream();
    });
    connect(m_stream.get(), &ScreencastStream::closedByCompositor, this, [this] {
        stopStream();
        QTimer::singleShot(500, this, &AgentScreen::update);
    });
}

void AgentScreen::stopStream()
{
    m_stream.reset();
    m_streamed = nullptr;
    if (m_nodeId) {
        m_nodeId = 0;
        Q_EMIT nodeIdChanged();
    }
}

void AgentScreen::pointerMove(double fx, double fy)
{
    QScreen *output = agentOutput();
    if (!output || !m_input->isActive())
        return;
    if (!m_authenticated) {
        m_input->authenticate(QStringLiteral("Assistant screen"), QStringLiteral("Touches in the floating window"));
        m_authenticated = true;
    }
    const QRect g = output->geometry();
    const double x = g.x() + qBound(0.0, fx, 1.0) * (g.width() - 1);
    const double y = g.y() + qBound(0.0, fy, 1.0) * (g.height() - 1);
    m_input->pointer_motion_absolute(wl_fixed_from_double(x), wl_fixed_from_double(y));
}

void AgentScreen::pointerButton(int button, bool pressed)
{
    if (m_input->isActive())
        m_input->button(uint(button), pressed ? 1 : 0);
}

void AgentScreen::scroll(double dx, double dy)
{
    if (!m_input->isActive())
        return;
    if (dy != 0)
        m_input->axis(0, wl_fixed_from_double(dy));  // vertical
    if (dx != 0)
        m_input->axis(1, wl_fixed_from_double(dx));
}

void AgentScreen::castToTv()
{
    setStatus(QStringLiteral("connecting the TV"));
    // Connecting takes seconds to a minute, off the UI thread; the next poll sees the TV take the screen.
    QThread *worker = QThread::create([] {
        bridge({{QStringLiteral("op"), QStringLiteral("cast")}, {QStringLiteral("args"), QJsonArray{QStringLiteral("connect")}}}, 75000);
    });
    connect(worker, &QThread::finished, worker, &QObject::deleteLater);
    worker->start();
}

void AgentScreen::close()
{
    bridge({{QStringLiteral("op"), QStringLiteral("agent-screen")}, {QStringLiteral("enabled"), false}});
    QCoreApplication::quit();
}
