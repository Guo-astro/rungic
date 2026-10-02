#include "floater.h"

#include <LayerShellQt/Window>
#include <QGuiApplication>
#include <QQuickWindow>
#include <QRegion>
#include <QScreen>
#include <climits>
#include <qpa/qplatformnativeinterface.h>
#include <wayland-client.h>

namespace
{
// The phone's panel, never the assistant's screen (CAST-n) or another external one.
QScreen *castScreen()
{
    const auto screens = QGuiApplication::screens();
    for (QScreen *screen : screens) {
        if (screen->name().startsWith(QLatin1String("CAST")))
            return screen;
    }
    return nullptr;
}

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
    layer->setScope(QStringLiteral("rungic-agent-screen"));
    // Top: above apps, below the shell's overlays (control center, lock screen, OSDs) and Plasma
    // Mobile's panels. Fullscreen is another window (showFullscreen).
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

void Floater::showFullscreen(QWindow *window)
{
    if (!window)
        return;
    // Not a layer surface in the overlay layer, as it was (§17.2): there it was above everything
    // the shell and KWin put over a fullscreen app, and what appeared later went under it (§21).
    // Qt asks for fullscreen before the first commit, so the first configure is the whole screen.
    window->setScreen(phoneScreen());
    window->showFullScreen();
}

void Floater::setOpaque(QWindow *window, bool opaque)
{
    if (!window || !window->isVisible())
        return;
    // Qt sets an opaque region only for a window without alpha (its setOpaqueArea is private): ours,
    // on the surface itself. Double-buffered, it goes with the next commit, the next frame's.
    auto native = QGuiApplication::platformNativeInterface();
    auto surface = static_cast<wl_surface *>(native ? native->nativeResourceForWindow("surface", window) : nullptr);
    auto wayland = qGuiApp->nativeInterface<QNativeInterface::QWaylandApplication>();
    if (!surface || !wayland || !wayland->compositor())
        return;
    if (opaque) {
        // All of it, however large: KWin clips the region to the surface.
        wl_region *region = wl_compositor_create_region(wayland->compositor());
        wl_region_add(region, 0, 0, INT32_MAX, INT32_MAX);
        wl_surface_set_opaque_region(surface, region);
        wl_region_destroy(region);
    } else {
        wl_surface_set_opaque_region(surface, nullptr);
    }
    window->requestUpdate();
}

bool Floater::castPresent() const
{
    return castScreen() != nullptr;
}

bool Floater::placeOnCast(QWindow *window)
{
    QScreen *cast = castScreen();
    if (!window || !cast)
        return false;
    auto layer = LayerShellQt::Window::get(window);
    layer->setScope(QStringLiteral("rungic-agent-screen-tv"));
    layer->setLayer(LayerShellQt::Window::LayerOverlay);
    layer->setAnchors(LayerShellQt::Window::Anchors(LayerShellQt::Window::AnchorTop | LayerShellQt::Window::AnchorBottom
                                                    | LayerShellQt::Window::AnchorLeft | LayerShellQt::Window::AnchorRight));
    layer->setKeyboardInteractivity(LayerShellQt::Window::KeyboardInteractivityOnDemand);
    layer->setExclusiveZone(-1);
    layer->setWantsToBeOnActiveScreen(false);
    layer->setScreen(cast);
    window->setScreen(cast);
    window->resize(cast->size());
    return true;
}
