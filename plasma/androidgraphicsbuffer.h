// SPDX-License-Identifier: GPL-2.0-or-later
// Android AHardwareBuffer lease protocol shared with the Android native APK backend.
#pragma once

#include "core/graphicsbuffer.h"
#include "core/graphicsbufferallocator.h"
#include <drm_fourcc.h>
#include <sys/socket.h>
#include <sys/time.h>
#include <sys/un.h>
#include <unistd.h>
#include <cstring>

namespace KWin
{
class AndroidGraphicsBuffer final : public GraphicsBuffer
{
public:
    AndroidGraphicsBuffer(DmaBufAttributes &&attributes, FileDescriptor &&lease)
        : m_attributes(std::move(attributes)), m_lease(std::move(lease)) {}
    QSize size() const override { return {m_attributes.width, m_attributes.height}; }
    bool hasAlphaChannel() const override { return alphaChannelFromDrmFormat(m_attributes.format); }
    const DmaBufAttributes *dmabufAttributes() const override { return &m_attributes; }

private:
    DmaBufAttributes m_attributes;
    FileDescriptor m_lease; // Keep the Android native handle alive until release.
};

static GraphicsBuffer *allocateAndroidBuffer(const QByteArray &path, const GraphicsBufferOptions &options)
{
    const int width = options.size.width(), height = options.size.height();
    if (options.software || width <= 0 || height <= 0 || width > 4096 || height > 4096 || int64_t(width) * height > 4194304) {
        return nullptr;
    }
    if (!options.modifiers.isEmpty() && !options.modifiers.contains(DRM_FORMAT_MOD_LINEAR) && !options.modifiers.contains(DRM_FORMAT_MOD_INVALID)) {
        return nullptr;
    }
    switch (options.format) {
    case DRM_FORMAT_ARGB8888:
    case DRM_FORMAT_XRGB8888:
    case DRM_FORMAT_ABGR8888:
    case DRM_FORMAT_XBGR8888:
        break;
    default:
        return nullptr;
    }
    sockaddr_un address{};
    address.sun_family = AF_UNIX;
    if (path.isEmpty() || path.size() >= sizeof(address.sun_path)) {
        return nullptr;
    }
    std::memcpy(address.sun_path, path.constData(), path.size());
    FileDescriptor lease(socket(AF_UNIX, SOCK_STREAM | SOCK_CLOEXEC, 0));
    if (!lease.isValid()) {
        return nullptr;
    }
    timeval timeout{.tv_sec = 3, .tv_usec = 0};
    setsockopt(lease.get(), SOL_SOCKET, SO_RCVTIMEO, &timeout, sizeof(timeout));
    setsockopt(lease.get(), SOL_SOCKET, SO_SNDTIMEO, &timeout, sizeof(timeout));
    if (connect(lease.get(), reinterpret_cast<sockaddr *>(&address), sizeof(address)) < 0) {
        return nullptr;
    }
    // Both endpoints are little-endian ARM64; this is protocol v1.
    uint32_t request[]{0x4d475055, uint32_t(width), uint32_t(height), options.format};
    if (send(lease.get(), request, sizeof(request), MSG_NOSIGNAL) != sizeof(request)) {
        return nullptr;
    }
    uint32_t reply[3]{};
    iovec iov{.iov_base = reply, .iov_len = sizeof(reply)};
    alignas(cmsghdr) char control[CMSG_SPACE(8 * sizeof(int))]{};
    msghdr message{};
    message.msg_iov = &iov;
    message.msg_iovlen = 1;
    message.msg_control = control;
    message.msg_controllen = sizeof(control);
    const auto length = recvmsg(lease.get(), &message, MSG_WAITALL | MSG_CMSG_CLOEXEC);
    std::vector<FileDescriptor> received;
    for (cmsghdr *c = CMSG_FIRSTHDR(&message); c; c = CMSG_NXTHDR(&message, c)) {
        if (c->cmsg_level == SOL_SOCKET && c->cmsg_type == SCM_RIGHTS && c->cmsg_len >= CMSG_LEN(0)) {
            const size_t count = (c->cmsg_len - CMSG_LEN(0)) / sizeof(int);
            for (size_t i = 0; i < count; ++i) {
                int fd;
                std::memcpy(&fd, CMSG_DATA(c) + i * sizeof(int), sizeof(int));
                received.emplace_back(fd);
            }
        }
    }
    if (length != sizeof(reply) || (message.msg_flags & (MSG_CTRUNC | MSG_TRUNC)) || received.size() != 1 ||
        reply[0] != 0x4d475055 || reply[2] != options.format || reply[1] < uint32_t(width) * 4 || reply[1] > 65536) {
        return nullptr;
    }
    DmaBufAttributes attributes;
    attributes.planeCount = 1;
    attributes.width = width;
    attributes.height = height;
    attributes.format = options.format;
    attributes.modifier = DRM_FORMAT_MOD_LINEAR;
    attributes.fd[0] = std::move(received.front());
    attributes.pitch[0] = reply[1];
    return new AndroidGraphicsBuffer(std::move(attributes), std::move(lease));
}
}
