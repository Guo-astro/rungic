// SPDX-License-Identifier: GPL-2.0-or-later
#pragma once
#include <QObject>
#include <QVariantList>
#include <QDBusServiceWatcher>
#include <QtQml/qqmlregistration.h>

class SuggestionsClient : public QObject {
    Q_OBJECT
    QML_ELEMENT
    Q_PROPERTY(QVariantList items READ items NOTIFY changed)
    Q_PROPERTY(QStringList coverage READ coverage NOTIFY changed)
    Q_PROPERTY(QString error READ error NOTIFY changed)
    Q_PROPERTY(bool busy READ busy NOTIFY changed)
public:
    explicit SuggestionsClient(QObject *parent = nullptr);
    QVariantList items() const { return m_items; }
    QStringList coverage() const { return m_coverage; }
    QString error() const { return m_error; }
    bool busy() const { return m_busy; }
    Q_INVOKABLE void act(const QString &id, const QString &action, const QVariantMap &args = {});
    Q_INVOKABLE void refresh();
    Q_INVOKABLE void scan();
    Q_INVOKABLE void open(const QString &id = {});
    Q_INVOKABLE void conversation(const QString &id);
    Q_INVOKABLE void watching(bool visible);
    Q_INVOKABLE double tomorrow(int hour = 10) const;
Q_SIGNALS:
    void changed();
    void replied(const QString &id, const QString &action, const QVariantMap &result);
private:
    Q_SLOT void onChanged();
    void call(const QString &method, const QVariantList &args, const QString &id = {}, const QString &action = {});
    void launch(const QStringList &arguments);
    QVariantList m_items;
    QStringList m_coverage;
    QString m_error;
    bool m_busy = false;
    bool m_watching = false;
    QDBusServiceWatcher m_watcher;
};
