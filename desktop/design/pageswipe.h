// SPDX-License-Identifier: GPL-2.0-or-later
// The swipe back of a page stack (docs/102), as Kirigami's page row has it (ColumnView::
// childMouseEventFilter, KF 6.24): a one-finger drag anywhere on the pages, not only from an
// edge, becomes the swipe once it has gone three times the drag distance to the right before
// going that far up or down; a vertical drag stays the page's own scrolling, and an item that
// keeps its touch grab or has `preventStealing` keeps it. The swipe then takes the touch point
// (the control under the finger is cancelled, not clicked) and reports how far it went; the
// QML side (PageStack.qml) moves the pages and decides by the last movement's direction.
#pragma once

#include <QPointF>
#include <QQuickItem>
#include <qqmlregistration.h>

class QTouchEvent;

class PageSwipe : public QQuickItem
{
    Q_OBJECT
    QML_ELEMENT
    // Whether a swipe can start (the stack has a page to go back to).
    Q_PROPERTY(bool active READ active WRITE setActive NOTIFY activeChanged)
    Q_PROPERTY(bool dragging READ dragging NOTIFY draggingChanged)
public:
    explicit PageSwipe(QQuickItem *parent = nullptr);

    bool active() const { return m_active; }
    void setActive(bool active);
    bool dragging() const { return m_dragging; }

Q_SIGNALS:
    void activeChanged();
    void draggingChanged();
    void started();
    // How far right of where the swipe began, never less than 0.
    void moved(qreal distance);
    // The finger lifted: `forward` is whether its last movement went right.
    void released(qreal distance, bool forward);
    void cancelled();

protected:
    bool childMouseEventFilter(QQuickItem *item, QEvent *event) override;
    void touchEvent(QTouchEvent *event) override;
    void touchUngrabEvent() override;

private:
    bool filter(QQuickItem *item, QTouchEvent *event);
    void reset();

    bool m_active = false;
    bool m_dragging = false;
    bool m_vertical = false;       // went far enough up or down first: the page's scrolling
    bool m_blocked = false;        // the item under the finger keeps its grab
    int m_pointId = -1;
    QPointF m_press;               // scene position
    qreal m_startX = 0;            // scene x where the swipe began
    qreal m_lastX = 0;
    qreal m_lastDelta = 0;
};
