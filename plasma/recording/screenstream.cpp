// SPDX-FileCopyrightText: 2020 Aleix Pol Gonzalez <aleixpol@kde.org>
// SPDX-FileCopyrightText: 2026 Rungic
// SPDX-License-Identifier: GPL-2.0-or-later
#include "screenstream.h"

#include <QDebug>
#include <QGuiApplication>
#include <QScreen>
#include <qpa/qplatformnativeinterface.h>

ScreenStream::~ScreenStream()
{
    if (isInitialized()) {
        close();
    }
}

void ScreenStream::zkde_screencast_stream_unstable_v1_created(uint32_t node)
{
    Q_EMIT created(node);
}

void ScreenStream::zkde_screencast_stream_unstable_v1_closed()
{
    Q_EMIT closed();
}

void ScreenStream::zkde_screencast_stream_unstable_v1_failed(const QString &error)
{
    Q_EMIT failed(error);
}

ScreenCasting::ScreenCasting()
    : QWaylandClientExtensionTemplate<ScreenCasting>(ZKDE_SCREENCAST_UNSTABLE_V1_STREAM_REGION_SINCE_VERSION)
{
    initialize();
    if (!isInitialized()) {
        qWarning() << "zkde_screencast_unstable_v1 unavailable (X-KDE-Wayland-Interfaces of the client)";
    }
}

ScreenCasting::~ScreenCasting()
{
    if (isActive()) {
        destroy();
    }
}

std::unique_ptr<ScreenStream> ScreenCasting::createOutputStream(const QString &outputName, pointer mode)
{
    if (!isActive()) {
        return nullptr;
    }
    wl_output *output = nullptr;
    for (QScreen *screen : qGuiApp->screens()) {
        if (screen->name() == outputName) {
            output = static_cast<wl_output *>(QGuiApplication::platformNativeInterface()->nativeResourceForScreen("output", screen));
        }
    }
    if (!output) {
        return nullptr;
    }
    auto stream = std::make_unique<ScreenStream>();
    stream->init(stream_output(output, mode));
    return stream;
}

ScreenStreamRequest::ScreenStreamRequest(QObject *parent)
    : QObject(parent)
{
}

ScreenStreamRequest::~ScreenStreamRequest() = default;

void ScreenStreamRequest::setOutputName(const QString &name)
{
    if (m_outputName == name) {
        return;
    }
    m_outputName = name;
    Q_EMIT outputNameChanged();
    restart();
}

void ScreenStreamRequest::setEmbedCursor(bool embed)
{
    if (m_embedCursor == embed) {
        return;
    }
    m_embedCursor = embed;
    Q_EMIT embedCursorChanged();
    restart();
}

void ScreenStreamRequest::restart()
{
    m_stream.reset();
    setNodeId(0);
    if (m_outputName.isEmpty()) {
        return;
    }
    if (!m_casting) {
        m_casting = std::make_unique<ScreenCasting>();
    }
    m_stream = m_casting->createOutputStream(m_outputName,
                                             m_embedCursor ? ScreenCasting::pointer_embedded : ScreenCasting::pointer_hidden);
    if (!m_stream) {
        qWarning() << "cannot request a screen stream for" << m_outputName;
        return;
    }
    connect(m_stream.get(), &ScreenStream::created, this, &ScreenStreamRequest::setNodeId);
    connect(m_stream.get(), &ScreenStream::closed, this, [this]() {
        setNodeId(0);
    });
    connect(m_stream.get(), &ScreenStream::failed, this, [this](const QString &error) {
        qWarning() << "screen stream for" << m_outputName << "failed:" << error;
    });
}

void ScreenStreamRequest::setNodeId(quint32 node)
{
    if (m_nodeId != node) {
        m_nodeId = node;
        Q_EMIT nodeIdChanged();
    }
}
