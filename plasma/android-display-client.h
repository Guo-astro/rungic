// SPDX-License-Identifier: GPL-2.0-or-later
#pragma once

#include <QElapsedTimer>
#include <QFile>
#include <QJsonDocument>
#include <QJsonObject>
#include <QJsonArray>
#include <cerrno>
#include <cstring>
#include <poll.h>
#include <sys/socket.h>
#include <sys/un.h>
#include <unistd.h>

namespace RungicDisplay
{
inline QJsonObject info()
{
    QFile file(QStringLiteral("/mnt/android-wayland/android-display.json"));
    if (!file.open(QIODevice::ReadOnly)) {
        return {};
    }
    return QJsonDocument::fromJson(file.readAll()).object();
}

// Only explicit display changes use IPC; rendering never waits on this socket.
// One total deadline bounds both sending and receiving, including partial I/O.
inline QJsonObject request(QJsonObject value)
{
    const auto failure = [](const QString &message) {
        return QJsonObject{{QStringLiteral("error"), message}};
    };
    const int fd = socket(AF_UNIX, SOCK_STREAM | SOCK_CLOEXEC | SOCK_NONBLOCK, 0);
    if (fd < 0) {
        return failure(QString::fromLocal8Bit(strerror(errno)));
    }
    struct Close { int fd; ~Close() { close(fd); } } closer{fd};
    QElapsedTimer timer;
    timer.start();
    const auto wait = [&](short events) {
        pollfd p{fd, events, 0};
        int result;
        do {
            const int remaining = 500 - int(timer.elapsed());
            if (remaining <= 0) return false;
            result = poll(&p, 1, remaining);
        } while (result < 0 && errno == EINTR);
        return result > 0 && (p.revents & events);
    };
    sockaddr_un address{};
    address.sun_family = AF_UNIX;
    strcpy(address.sun_path, "/mnt/android-wayland/platform.sock");
    if (connect(fd, reinterpret_cast<sockaddr *>(&address), sizeof(address)) < 0) {
        if (errno != EINPROGRESS || !wait(POLLOUT)) {
            return failure(QStringLiteral("Android display connection unavailable"));
        }
        int error = 0;
        socklen_t size = sizeof(error);
        if (getsockopt(fd, SOL_SOCKET, SO_ERROR, &error, &size) < 0 || error) {
            return failure(QStringLiteral("Android display connection failed"));
        }
    }
    value.insert(QStringLiteral("op"), QStringLiteral("display-set"));
    const QByteArray bytes = QJsonDocument(value).toJson(QJsonDocument::Compact) + '\n';
    qsizetype sent = 0;
    while (sent < bytes.size()) {
        if (!wait(POLLOUT)) return failure(QStringLiteral("Android display request timed out"));
        const auto n = send(fd, bytes.constData() + sent, bytes.size() - sent, MSG_NOSIGNAL);
        if (n < 0 && (errno == EAGAIN || errno == EINTR)) continue;
        if (n <= 0) return failure(QStringLiteral("Android display request failed"));
        sent += n;
    }
    QByteArray reply;
    while (!reply.contains('\n') && reply.size() < 16384) {
        if (!wait(POLLIN)) return failure(QStringLiteral("Android display reply timed out"));
        char buffer[4096];
        const auto n = recv(fd, buffer, sizeof(buffer), 0);
        if (n < 0 && (errno == EAGAIN || errno == EINTR)) continue;
        if (n <= 0) break;
        reply.append(buffer, n);
    }
    const QJsonObject result = QJsonDocument::fromJson(reply).object();
    if (result.isEmpty() || (!result.contains(QStringLiteral("error")) && !result.value(QStringLiteral("ok")).toBool())) {
        return failure(QStringLiteral("Invalid Android display reply"));
    }
    return result;
}
}
