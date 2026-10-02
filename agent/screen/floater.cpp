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
    // Mobile's panels. Fullscreen raises it above them (setFullscreen).
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
    // Qt makes a new surface each time the window shows again: its opaque region with it.
    connect(window, &QWindow::visibleChanged, this, [this](bool visible) {
        if (visible && m_opaque)
            applyOpaque();
    });
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

void Floater::setFullscreen(bool fullscreen)
{
    if (!m_window)
        return;
    auto layer = LayerShellQt::Window::get(m_window);
    // Overlay, as Plasma Mobile's panels, and taking the keyboard (Esc leaves): KWin activates a
    // layer surface that starts taking it, and activating raises it above the others of its layer,
    // the panels too (a layer change alone left it under them). The panels see no fullscreen app,
    // so they do not slide away: they are only covered. One window throughout: a second one for
    // fullscreen took ~110 ms to draw the picture the first time, and it was gone meanwhile.
    layer->setLayer(fullscreen ? LayerShellQt::Window::LayerOverlay : LayerShellQt::Window::LayerTop);
    layer->setKeyboardInteractivity(fullscreen ? LayerShellQt::Window::KeyboardInteractivityOnDemand
                                               : LayerShellQt::Window::KeyboardInteractivityNone);
    m_window->requestUpdate();  // the changes go with the next commit
}

void Floater::setOpaque(bool opaque)
{
    m_opaque = opaque;
    applyOpaque();
}

void Floater::applyOpaque()
{
    if (!m_window || !m_window->isVisible())
        return;
    // Qt sets an opaque region only for a window without alpha (its setOpaqueArea is private): ours,
    // on the surface itself. Double-buffered, it goes with the next commit, the next frame's.
    auto native = QGuiApplication::platformNativeInterface();
    auto surface = static_cast<wl_surface *>(native ? native->nativeResourceForWindow("surface", m_window) : nullptr);
    auto wayland = qGuiApp->nativeInterface<QNativeInterface::QWaylandApplication>();
    if (!surface || !wayland || !wayland->compositor())
        return;
    if (m_opaque) {
        // All of it, however large: KWin clips the region to the surface (a turn changes nothing).
        wl_region *region = wl_compositor_create_region(wayland->compositor());
        wl_region_add(region, 0, 0, INT32_MAX, INT32_MAX);
        wl_surface_set_opaque_region(surface, region);
        wl_region_destroy(region);
    } else {
        wl_surface_set_opaque_region(surface, nullptr);
    }
    m_window->requestUpdate();
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
