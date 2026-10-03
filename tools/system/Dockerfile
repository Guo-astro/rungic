# The system test image (tools/system_test.py, quality/README.md 分层): the build image with what
# Rungic's Linux system features run on, and an unprivileged user. A headless KWin (--virtual) is the
# compositor; nothing of Android is here: its interfaces are stand-ins of their contracts. A fresh
# Ubuntu rootfs too: tests marked "system-test: as root" install into it (openssh-server: SSH on first install).
# The AT-SPI bus and its GObject binding: rungic-a11y drives applications by their controls' names.
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
        at-spi2-core gir1.2-atspi-2.0 qml6-module-qtquick-controls qml6-module-qtquick-layouts \
    && rm -rf /var/lib/apt/lists/* \
    && useradd -m tester
