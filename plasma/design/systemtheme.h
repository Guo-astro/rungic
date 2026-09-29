// SPDX-License-Identifier: GPL-2.0-or-later
// Whether the system's colours are dark or light (docs/59, docs/87): Rungic apps and the Home
// overlay follow it with their own dark and light looks. Read from KDE's kdeglobals
// (the window background), watched for changes; Qt's colour scheme hint also triggers
// a re-read. The app sets its own palette, so its palette cannot tell.
#pragma once

#include <KConfigWatcher>
#include <QObject>
#include <qqmlregistration.h>

class QJSEngine;
class QQmlEngine;

class SystemTheme : public QObject
{
    Q_OBJECT
    QML_ELEMENT
    QML_SINGLETON
    Q_PROPERTY(bool dark READ dark NOTIFY darkChanged)
public:
    static SystemTheme *instance();
    static SystemTheme *create(QQmlEngine *, QJSEngine *);
    bool dark() const;

Q_SIGNALS:
    void darkChanged();

private:
    explicit SystemTheme(QObject *parent);
    void update();

    bool m_dark = true;
    KConfigWatcher::Ptr m_watcher;
};
