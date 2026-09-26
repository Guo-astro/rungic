# rungic-plasma-bridges
install -Dm755 "$SRC/plasma/device-panel.py" "$DESTDIR/usr/bin/rungic-platform"
install -Dm644 "$SRC/plasma/com.rungic.Platform.desktop" "$DESTDIR/usr/share/applications/com.rungic.Platform.desktop"
install -Dm755 "$SRC/shared/platform/clipboard.py" "$DESTDIR/usr/bin/rungic-clipboard"
install -Dm755 "$SRC/shared/platform/network-manager.py" "$DESTDIR/usr/libexec/rungic-android-network"
install -Dm755 "$SRC/shared/media/media-bridge.py" "$DESTDIR/usr/bin/rungic-media-bridge"
install -Dm755 "$SRC/shared/media/audio-route.py" "$DESTDIR/usr/bin/rungic-audio-route"
mkdir -p "$DESTDIR/usr/bin"
g++ -std=gnu++20 -O2 -g1 -o "$DESTDIR/usr/bin/rungic-camera-source" "$SRC/shared/media/camera-source.cpp" \
    $(pkg-config --cflags --libs libpipewire-0.3 json-glib-1.0) -lyuv -pthread
install -Dm644 "$SRC/plasma/rungic-plasma-network.service" "$DESTDIR/usr/lib/systemd/system/rungic-plasma-network.service"
for unit in rungic-plasma-media rungic-plasma-clipboard; do
    install -Dm644 "$SRC/plasma/$unit.service" "$DESTDIR/usr/lib/systemd/user/$unit.service"
done
