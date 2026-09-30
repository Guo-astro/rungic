// SPDX-License-Identifier: GPL-2.0-or-later
// The assistant's overlay (docs/67): a resident layer-shell window that holding the Home
// button brings up. D-Bus com.rungic.VoiceAssistant /Assistant, called by the Plasma Mobile
// navigation panel (plasma-mobile containments/taskpanel, packages/plasma-mobile).
#pragma once

#include <QObject>
#include <QPointer>
#include <QRectF>
#include <qqmlregistration.h>

class QJSEngine;
class QQmlEngine;
class QQuickWindow;

class Overlay : public QObject
{
    Q_OBJECT
    Q_CLASSINFO("D-Bus Interface", "com.rungic.VoiceAssistant.Assistant")
    QML_ELEMENT
    QML_SINGLETON
public:
    // One instance: the D-Bus object and the QML singleton (create()) are the same.
    static Overlay *instance();
    static Overlay *create(QQmlEngine *, QJSEngine *);

    // The window the overlay draws in; set once QML has created it.
    void setWindow(QQuickWindow *window);

    // Maps the window on the named screen (the one Home was held on).
    Q_INVOKABLE void present(const QString &screen);
    Q_INVOKABLE void conceal();
    // The frosted area, in window coordinates: KWin blurs and saturates behind it only.
    Q_INVOKABLE void setCard(const QRectF &rect, qreal radius);
    // Touches below `height` (the navigation panel) go to the shell, not the overlay.
    Q_INVOKABLE void setTouchableHeight(int height);
    Q_INVOKABLE void setTouchableRect(const QRectF &rect);
    Q_INVOKABLE void setKeyboardEnabled(bool enabled);
    // The whole conversation in the app.
    Q_INVOKABLE void openInApp(const QString &conversation);

public Q_SLOTS:
    Q_SCRIPTABLE void Hold(bool pressed, const QString &screen);
    Q_SCRIPTABLE void Show(const QString &screen);
    Q_SCRIPTABLE void Hide();

Q_SIGNALS:
    void holdRequested(bool pressed, const QString &screen);
    void showRequested(const QString &screen);
    void hideRequested();

private:
    explicit Overlay(QObject *parent);
    void applyMaterial();
    void loadEffects(bool on);

    QPointer<QQuickWindow> m_window;
    QString m_screen;
    QRectF m_card;
    qreal m_radius = 0;
    QRectF m_touchable;
    QStringList m_loadedEffects;   // KWin effects this overlay loaded (and unloads)
};
