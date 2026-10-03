# The system test image (tools/system_test.py, quality/README.md 分层): the build image with what
# Rungic's Linux system features run on, and an unprivileged user. A headless KWin (--virtual) is the
# compositor; nothing of Android is here: its interfaces are stand-ins of their contracts. A fresh
# Ubuntu rootfs too: tests marked "system-test: as root" install into it (openssh-server: SSH on first install).
ARG BASE
FROM ${BASE}
ARG http_proxy
ARG https_proxy
RUN apt-get update -q && DEBIAN_FRONTEND=noninteractive apt-get install -y -q --no-install-recommends \
        kwin-wayland dbus-daemon dbus-user-session qdbus-qt6 python3-gi gir1.2-gtk-3.0 gir1.2-glib-2.0 \
        cmake qt6-base-dev qt6-base-private-dev qt6-declarative-dev qt6-wayland-dev liblayershellqtinterface-dev \
        plasma-wayland-protocols wayland-protocols libwayland-dev libxkbcommon-dev pkgconf libkf6i18n-dev gettext \
        libkpipewire-dev libegl-dev libgles-dev libdrm-dev \
        qml6-module-qtquick-virtualkeyboard qt6-virtualkeyboard-plugin qml6-module-qtcore qml6-module-qtquick-window \
        qml6-module-qtquick-effects qml6-module-org-kde-kirigami qml6-module-org-kde-pipewire qml6-module-org-kde-layershell \
        fonts-noto-core openssh-server \
    && rm -rf /var/lib/apt/lists/* \
    && useradd -m tester
# wl-clipboard 2.3.0, the release packages/wl-clipboard pins and the phone has (docs/61): the clipboard
# bridge's wl-paste --watch needs ext-data-control, the only data-control KWin 6.6 offers; Ubuntu's
# 2.2.1 has wlroots' only. In /usr/local, first on PATH (tools/system/tests/desktop_clipboard.py).
RUN curl -fsSL -o /tmp/wl-clipboard.tar.gz https://github.com/bugaevc/wl-clipboard/archive/refs/tags/v2.3.0.tar.gz \
    && echo 'b4dc560973f0cd74e02f817ffa2fd44ba645a4f1ea94b7b9614dacc9f895f402  /tmp/wl-clipboard.tar.gz' | sha256sum -c - \
    && tar -xzf /tmp/wl-clipboard.tar.gz -C /tmp \
    && meson setup /tmp/wl-clipboard-build /tmp/wl-clipboard-2.3.0 --prefix=/usr/local >/dev/null \
    && ninja -C /tmp/wl-clipboard-build install >/dev/null \
    && rm -rf /tmp/wl-clipboard*
