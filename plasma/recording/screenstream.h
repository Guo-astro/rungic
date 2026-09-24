// SPDX-FileCopyrightText: 2020 Aleix Pol Gonzalez <aleixpol@kde.org>
// SPDX-FileCopyrightText: 2026 Moto Linux integration
// SPDX-License-Identifier: GPL-2.0-or-later
//
// Screen stream request for the recording quick setting (docs/48). Follows
// plasma-workspace's libtaskmanager Screencasting/ScreencastingRequest, whose
// requests always hide the pointer; this one can have KWin draw the pointer into
// the stream, which a recording of an external screen needs.
#pragma once

#include "qwayland-zkde-screencast-unstable-v1.h"

#include <QObject>
#include <QWaylandClientExtensionTemplate>
#include <qqmlregistration.h>

#include <memory>

class ScreenStream : public QObject, public QtWayland::zkde_screencast_stream_unstable_v1
{
    Q_OBJECT
public:
    ~ScreenStream() override;
Q_SIGNALS:
    void created(quint32 node);
    void closed();
    void failed(const QString &error);
protected:
    void zkde_screencast_stream_unstable_v1_created(uint32_t node) override;
    void zkde_screencast_stream_unstable_v1_closed() override;
    void zkde_screencast_stream_unstable_v1_failed(const QString &error) override;
};

class ScreenCasting : public QWaylandClientExtensionTemplate<ScreenCasting>, public QtWayland::zkde_screencast_unstable_v1
{
    Q_OBJECT
public:
    ScreenCasting();
    ~ScreenCasting() override;
    std::unique_ptr<ScreenStream> createOutputStream(const QString &outputName, pointer mode);
};

class ScreenStreamRequest : public QObject
{
    Q_OBJECT
    QML_ELEMENT
    /// Output (screen) name to capture; empty stops the stream.
    Q_PROPERTY(QString outputName READ outputName WRITE setOutputName NOTIFY outputNameChanged)
    /// Draw the pointer into the stream instead of hiding it.
    Q_PROPERTY(bool embedCursor READ embedCursor WRITE setEmbedCursor NOTIFY embedCursorChanged)
    Q_PROPERTY(quint32 nodeId READ nodeId NOTIFY nodeIdChanged)
public:
    explicit ScreenStreamRequest(QObject *parent = nullptr);
    ~ScreenStreamRequest() override;
    QString outputName() const { return m_outputName; }
    void setOutputName(const QString &name);
    bool embedCursor() const { return m_embedCursor; }
    void setEmbedCursor(bool embed);
    quint32 nodeId() const { return m_nodeId; }
Q_SIGNALS:
    void outputNameChanged();
    void embedCursorChanged();
    void nodeIdChanged();
private:
    void restart();
    void setNodeId(quint32 node);
    QString m_outputName;
    bool m_embedCursor = false;
    quint32 m_nodeId = 0;
    std::unique_ptr<ScreenCasting> m_casting;
    std::unique_ptr<ScreenStream> m_stream;
};
