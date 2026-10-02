// The floating window's surface (docs/65): one transparent layer-shell surface over the whole phone
// screen, never taking the keyboard. Everything moves inside it, in QML, so a drag or an animation
// never waits for the compositor to move a surface; the input region is only what is visible (the
// picture, the toolbar, the tab), so touches elsewhere reach the phone as before.
#pragma once

#include <QObject>
#include <QRect>
#include <QVariantList>

class QQuickWindow;
class QWindow;

class Floater : public QObject
{
    Q_OBJECT
    Q_PROPERTY(QRect area READ area NOTIFY areaChanged)
    // A TV shows the user's KWin's cast output (CAST-n): computer mode on it (docs/research/97 §19.5).
    Q_PROPERTY(bool castPresent READ castPresent NOTIFY areaChanged)

public:
    explicit Floater(QObject *parent = nullptr);

    // Must be called before the window is first shown.
    void attach(QQuickWindow *window);
    // The phone's screen, in its logical pixels.
    QRect area() const;
    // Rectangles (x, y, width, height) that take touches; the rest passes through.
    Q_INVOKABLE void setInputRects(const QVariantList &rects);
    // Fullscreen (docs/research/97 §17.2): this surface in the overlay layer, taking the keyboard,
    // above the shell's panels; back in the top layer, without the keyboard, after.
    Q_INVOKABLE void setFullscreen(bool fullscreen);
    // Fullscreen arrived (docs/research/97 §20): the surface opaque all over, so the phone's KWin
    // draws nothing under it (an ARGB surface without an opaque region counts as see-through, and
    // all of Plasma Mobile was composited under it every frame). Off before it is see-through again.
    Q_INVOKABLE void setOpaque(bool opaque);
    bool castPresent() const;
    // Before it is first shown: `window` a layer surface over the whole cast output, in the overlay
    // layer (above the desktop shell the phone's KWin puts there), taking the keyboard when clicked.
    // False when there is no cast output.
    Q_INVOKABLE bool placeOnCast(QWindow *window);

Q_SIGNALS:
    void areaChanged();

private:
    void fit();
    void applyOpaque();

    QQuickWindow *m_window = nullptr;
    bool m_opaque = false;
};
