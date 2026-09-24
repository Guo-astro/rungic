#include "floater.h"

#include <LayerShellQt/Window>
#include <QGuiApplication>
#include <QQuickWindow>
#include <QRegion>
#include <QScreen>

namespace
{
// The phone's panel, never the assistant's screen (CAST-n) or another external one.
QScreen *phoneScreen()
{
    const auto screens = QGuiApplication::screens();
    for (QScreen *screen : screens) {
        if (!screen->name().startsWith(QLatin1String("Virtual-")) && !screen->name().startsWith(QLatin1String("CAST")))
            return screen;
    }
    return QGuiApplication::primaryScreen();
}
}

Floater::Floater(QObject *parent)
    : QObject(parent)
{
    connect(qGuiApp, &QGuiApplication::screenAdded, this, &Floater::areaChanged);
    connect(qGuiApp, &QGuiApplication::screenRemoved, this, &Floater::areaChanged);
    // The phone turned (fullscreen is landscape): the area is the new size.
    const auto watch = [this](QScreen *screen) { connect(screen, &QScreen::geometryChanged, this, &Floater::areaChanged); };
    for (QScreen *screen : QGuiApplication::screens())
        watch(screen);
    connect(qGuiApp, &QGuiApplication::screenAdded, this, watch);
    connect(this, &Floater::areaChanged, this, &Floater::fit);
}

void Floater::attach(QQuickWindow *window)
{
    m_window = window;
    auto layer = LayerShellQt::Window::get(window);
    layer->setScope(QStringLiteral("moto-agent-screen"));
    // Top: above apps and panels, below the shell's overlays (control center, lock screen, OSDs).
    layer->setLayer(LayerShellQt::Window::LayerTop);
    layer->setAnchors(LayerShellQt::Window::Anchors(LayerShellQt::Window::AnchorTop | LayerShellQt::Window::AnchorBottom
                                                    | LayerShellQt::Window::AnchorLeft | LayerShellQt::Window::AnchorRight));
    layer->setKeyboardInteractivity(LayerShellQt::Window::KeyboardInteractivityNone);
    layer->setExclusiveZone(-1);  // over panels instead of being pushed between them
    layer->setWantsToBeOnActiveScreen(false);
    layer->setScreen(phoneScreen());
    window->setScreen(phoneScreen());
    window->setColor(Qt::transparent);
    fit();
    window->setMask(QRegion(0, 0, 1, 1));  // nothing takes touches until QML says what is visible
}

QRect Floater::area() const
{
    QScreen *screen = phoneScreen();
    return screen ? QRect(QPoint(0, 0), screen->size()) : QRect();
}

void Floater::fit()
{
    if (m_window && area().isValid())
        m_window->resize(area().size());
}

void Floater::setInputRects(const QVariantList &rects)
{
    if (!m_window)
        return;
    QRegion region;
    for (const QVariant &rect : rects)
        region += rect.toRectF().toAlignedRect();
    // An empty mask means "everywhere" to Qt: keep one pixel instead when nothing is shown.
    m_window->setMask(region.isEmpty() ? QRegion(0, 0, 1, 1) : region);
}

void Floater::setupOverlay(QQuickWindow *window)
{
    auto layer = LayerShellQt::Window::get(window);
    layer->setScope(QStringLiteral("moto-agent-screen-fullscreen"));
    layer->setLayer(LayerShellQt::Window::LayerOverlay);
    layer->setAnchors(LayerShellQt::Window::Anchors(LayerShellQt::Window::AnchorTop | LayerShellQt::Window::AnchorBottom
                                                    | LayerShellQt::Window::AnchorLeft | LayerShellQt::Window::AnchorRight));
    layer->setKeyboardInteractivity(LayerShellQt::Window::KeyboardInteractivityNone);
    layer->setExclusiveZone(-1);
    layer->setWantsToBeOnActiveScreen(false);
    layer->setScreen(phoneScreen());
    window->setScreen(phoneScreen());
    window->resize(area().size());
}
