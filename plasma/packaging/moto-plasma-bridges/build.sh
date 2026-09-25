# moto-plasma-bridges
install -Dm755 "$SRC/plasma/device-panel.py" "$DESTDIR/usr/bin/moto-platform"
install -Dm644 "$SRC/plasma/dev.moto.Platform.desktop" "$DESTDIR/usr/share/applications/dev.moto.Platform.desktop"
install -Dm755 "$SRC/shared/platform/clipboard.py" "$DESTDIR/usr/bin/moto-clipboard"
install -Dm755 "$SRC/shared/platform/network-manager.py" "$DESTDIR/usr/libexec/moto-android-network"
install -Dm755 "$SRC/shared/media/media-bridge.py" "$DESTDIR/usr/bin/moto-media-bridge"
install -Dm755 "$SRC/shared/media/audio-route.py" "$DESTDIR/usr/bin/moto-audio-route"
mkdir -p "$DESTDIR/usr/bin"
g++ -std=gnu++20 -O2 -g1 -o "$DESTDIR/usr/bin/moto-camera-source" "$SRC/shared/media/camera-source.cpp" \
    $(pkg-config --cflags --libs libpipewire-0.3 json-glib-1.0) -lyuv -pthread
install -Dm644 "$SRC/plasma/moto-plasma-network.service" "$DESTDIR/usr/lib/systemd/system/moto-plasma-network.service"
for unit in moto-plasma-media moto-plasma-clipboard; do
    install -Dm644 "$SRC/plasma/$unit.service" "$DESTDIR/usr/lib/systemd/user/$unit.service"
done
