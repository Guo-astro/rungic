// The floating window's surface (docs/65): one transparent layer-shell surface over the whole phone
// screen, never taking the keyboard. Everything moves inside it, in QML, so a drag or an animation
// never waits for the compositor to move a surface; the input region is only what is visible (the
// picture, the toolbar, the tab), so touches elsewhere reach the phone as before.
#pragma once

#include <QObject>
#include <QRect>
#include <QVariantList>

class QQuickWindow;

class Floater : public QObject
{
    Q_OBJECT
    Q_PROPERTY(QRect area READ area NOTIFY areaChanged)

public:
    explicit Floater(QObject *parent = nullptr);

    // Must be called before the window is first shown.
    void attach(QQuickWindow *window);
    // The phone's screen, in its logical pixels.
    QRect area() const;
    // Rectangles (x, y, width, height) that take touches; the rest passes through.
    Q_INVOKABLE void setInputRects(const QVariantList &rects);

Q_SIGNALS:
    void areaChanged();

private:
    void fit();

    QQuickWindow *m_window = nullptr;
};
