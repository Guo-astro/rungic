// SPDX-License-Identifier: GPL-2.0-or-later
#include "pageswipe.h"

#include <QGuiApplication>
#include <QStyleHints>
#include <QTouchEvent>
#include <cmath>

PageSwipe::PageSwipe(QQuickItem *parent)
    : QQuickItem(parent)
{
    setAcceptTouchEvents(true);
    setFiltersChildMouseEvents(true);
}

void PageSwipe::setActive(bool active)
{
    if (active == m_active)
        return;
    m_active = active;
    if (!active && m_dragging) {
        reset();                    // first: the ungrab below must find no swipe to cancel again
        ungrabTouchPoints();
        Q_EMIT cancelled();
    }
    Q_EMIT activeChanged();
}

void PageSwipe::reset()
{
    const bool was = m_dragging;
    m_dragging = m_vertical = m_blocked = false;
    m_pointId = -1;
    m_lastDelta = 0;
    if (was)
        Q_EMIT draggingChanged();
}

bool PageSwipe::childMouseEventFilter(QQuickItem *item, QEvent *event)
{
    switch (event->type()) {
    case QEvent::TouchBegin:
    case QEvent::TouchUpdate:
    case QEvent::TouchEnd:
    case QEvent::TouchCancel:
        return filter(item, static_cast<QTouchEvent *>(event));
    default:
        return QQuickItem::childMouseEventFilter(item, event);
    }
}

void PageSwipe::touchEvent(QTouchEvent *event)
{
    // Touches on the pages' empty parts, and every touch once the swipe holds the point.
    if (filter(this, event) || event->type() == QEvent::TouchBegin)
        event->accept();
    else
        event->ignore();
}

void PageSwipe::touchUngrabEvent()
{
    if (m_dragging) {
        reset();
        Q_EMIT cancelled();
    }
}

bool PageSwipe::filter(QQuickItem *item, QTouchEvent *event)
{
    if (!m_active)
        return false;
    const qreal threshold = QGuiApplication::styleHints()->startDragDistance() * 3;
    switch (event->type()) {
    case QEvent::TouchBegin: {
        reset();
        if (event->pointCount() != 1)
            return false;
        const QEventPoint &point = event->points().first();
        m_pointId = point.id();
        m_press = point.scenePosition();
        m_blocked = item != this && (item->keepTouchGrab() || item->property("preventStealing").toBool());
        return false;
    }
    case QEvent::TouchUpdate: {
        if (m_pointId < 0)
            return false;
        if (event->pointCount() != 1) {
            if (m_dragging) {
                reset();
                ungrabTouchPoints();
                Q_EMIT cancelled();
            }
            return false;
        }
        const QEventPoint &point = event->points().first();
        if (point.id() != m_pointId)
            return false;
        const QPointF pos = point.scenePosition();
        if (!m_dragging) {
            if (m_blocked || m_vertical)
                return false;
            if (std::abs(pos.y() - m_press.y()) > threshold) {
                m_vertical = true;
                return false;
            }
            if (item != this && (item->keepTouchGrab() || item->property("preventStealing").toBool()))
                return false;
            if (pos.x() - m_press.x() <= threshold)
                return false;
            // From here on the finger is the swipe's: the control under it is cancelled.
            m_dragging = true;
            m_startX = m_lastX = pos.x();
            grabTouchPoints({m_pointId});
            Q_EMIT draggingChanged();
            Q_EMIT started();
            return true;
        }
        m_lastDelta = pos.x() - m_lastX;
        m_lastX = pos.x();
        Q_EMIT moved(std::max<qreal>(0, pos.x() - m_startX));
        return true;
    }
    case QEvent::TouchEnd:
    case QEvent::TouchCancel: {
        if (!m_dragging) {
            reset();
            return false;
        }
        const qreal distance = std::max<qreal>(0, m_lastX - m_startX);
        const bool forward = m_lastDelta >= 0;
        const bool cancel = event->type() == QEvent::TouchCancel;
        reset();
        ungrabTouchPoints();
        if (cancel)
            Q_EMIT cancelled();
        else
            Q_EMIT released(distance, forward);
        return true;
    }
    default:
        return false;
    }
}
