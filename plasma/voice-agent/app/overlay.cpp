// SPDX-License-Identifier: GPL-2.0-or-later
#include "overlay.h"

#include <KWindowEffects>
#include <LayerShellQt/Window>
#include <QDBusConnection>
#include <QDBusInterface>
#include <QDBusReply>
#include <QDebug>
#include <QGuiApplication>
#include <QJSEngine>
#include <QPainterPath>
#include <QProcess>
#include <QQuickWindow>
#include <QRegion>
#include <QScreen>
#include <QTimer>

static Overlay *s_instance = nullptr;

Overlay::Overlay(QObject *parent)
    : QObject(parent)
{
}

Overlay *Overlay::instance()
{
    if (!s_instance) {
        s_instance = new Overlay(qApp);
    }
    return s_instance;
}

Overlay *Overlay::create(QQmlEngine *, QJSEngine *)
{
    QJSEngine::setObjectOwnership(instance(), QJSEngine::CppOwnership);
    return instance();
}

void Overlay::setWindow(QQuickWindow *window)
{
    m_window = window;
}

static QScreen *screenNamed(const QString &name)
{
    const auto screens = QGuiApplication::screens();
    for (QScreen *screen : screens) {
        if (screen->name() == name) {
            return screen;
        }
    }
    return QGuiApplication::primaryScreen();
}

void Overlay::present(const QString &screenName)
{
    qInfo() << "overlay: present on" << screenName << (m_window ? "" : "(no window)");
    if (!m_window) {
        return;
    }
    QScreen *screen = screenNamed(screenName);
    if (m_window->isVisible() && m_window->screen() == screen) {
        return;
    }
    // A layer surface is bound to its output when created: moving means mapping again.
    m_window->setVisible(false);
    auto layer = LayerShellQt::Window::get(m_window);
    layer->setScope(QStringLiteral("moto-voice-assistant"));
    layer->setLayer(LayerShellQt::Window::LayerOverlay);
    layer->setAnchors(LayerShellQt::Window::Anchors(LayerShellQt::Window::AnchorTop | LayerShellQt::Window::AnchorBottom
                                                    | LayerShellQt::Window::AnchorLeft | LayerShellQt::Window::AnchorRight));
    layer->setExclusiveZone(-1);   // over the panels; the navigation panel stays touchable (setTouchableHeight)
    layer->setKeyboardInteractivity(LayerShellQt::Window::KeyboardInteractivityNone);
    layer->setScreen(screen);
    m_window->setScreen(screen);
    m_window->setGeometry(screen->geometry());
    m_screen = screen->name();
    loadEffects(true);
    m_window->setVisible(true);
    applyMaterial();
    // The blur protocol is announced when the effect loads; apply again once it is bound.
    QTimer::singleShot(100, this, &Overlay::applyMaterial);
}

void Overlay::conceal()
{
    if (m_window) {
        m_window->setVisible(false);
    }
    loadEffects(false);
}

void Overlay::setCard(const QRectF &rect, qreal radius)
{
    if (rect == m_card && radius == m_radius) {
        return;
    }
    m_card = rect;
    m_radius = radius;
    applyMaterial();
}

void Overlay::setTouchableHeight(int height)
{
    m_touchable = height;
    if (m_window) {
        m_window->setMask(QRegion(0, 0, m_window->width(), qMax(1, height)));
    }
}

void Overlay::applyMaterial()
{
    if (!m_window || !m_window->isVisible()) {
        return;
    }
    if (m_touchable > 0) {
        m_window->setMask(QRegion(0, 0, m_window->width(), m_touchable));
    }
    QPainterPath path;
    path.addRoundedRect(m_card, m_radius, m_radius);
    const QRegion region(path.toFillPolygon().toPolygon());
    // Blur plus the contrast effect's saturation: the frosted, slightly vivid material.
    KWindowEffects::enableBlurBehind(m_window, !m_card.isEmpty(), region);
    KWindowEffects::enableBackgroundContrast(m_window, !m_card.isEmpty(), 0.9, 1.0, 1.6, region);
}

void Overlay::loadEffects(bool on)
{
    // Plasma Mobile does not load blur (docs/65): loaded globally it cost the GPU about 8
    // points with the TV cast (docs/67). Load it while the overlay shows, unless the user had it.
    QDBusInterface effects(QStringLiteral("org.kde.KWin"), QStringLiteral("/Effects"), QStringLiteral("org.kde.kwin.Effects"));
    if (on) {
        for (const QString &name : {QStringLiteral("blur"), QStringLiteral("contrast")}) {
            QDBusReply<bool> loaded = effects.call(QStringLiteral("isEffectLoaded"), name);
            if (loaded.isValid() && !loaded.value()) {
                effects.call(QStringLiteral("loadEffect"), name);
                if (!m_loadedEffects.contains(name)) {
                    m_loadedEffects.append(name);
                }
            }
        }
    } else {
        for (const QString &name : std::as_const(m_loadedEffects)) {
            effects.asyncCall(QStringLiteral("unloadEffect"), name);
        }
        m_loadedEffects.clear();
    }
}

void Overlay::openInApp(const QString &conversation)
{
    QProcess::startDetached(QStringLiteral("moto-voice-assistant"), {QStringLiteral("--conversation"), conversation});
}

void Overlay::Hold(bool pressed, const QString &screen)
{
    qInfo() << "overlay: hold" << pressed << screen;
    Q_EMIT holdRequested(pressed, screen);
}

void Overlay::Show(const QString &screen)
{
    Q_EMIT showRequested(screen);
}

void Overlay::Hide()
{
    Q_EMIT hideRequested();
}
