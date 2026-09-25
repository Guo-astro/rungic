# moto-plasma-session
P=$SRC/plasma
install -Dm755 "$P/init" "$DESTDIR/usr/sbin/moto-plasma-init"
install -Dm755 "$P/session" "$DESTDIR/usr/libexec/moto-plasma-session"
install -Dm755 "$P/shared-storage" "$DESTDIR/usr/libexec/moto-plasma-shared"
install -Dm755 "$P/kwin" "$DESTDIR/usr/libexec/moto-plasma-kwin"
install -Dm755 "$P/desktop-action.py" "$DESTDIR/usr/libexec/moto-plasma-desktop-action"
install -Dm755 "$P/display.py" "$DESTDIR/usr/libexec/moto-plasma-display"
install -Dm755 "$P/brightness.py" "$DESTDIR/usr/libexec/moto-plasma-brightness"
install -Dm644 "$P/power-policy.py" "$DESTDIR/usr/libexec/moto-power-policy.py"
install -Dm755 "$P/account/setup.py" "$DESTDIR/usr/libexec/moto-plasma-account-setup"
install -Dm644 "$P/account/moto-account.desktop" "$DESTDIR/usr/share/applications/moto-account.desktop"
install -Dm755 "$P/user-exec" "$DESTDIR/usr/bin/moto-plasma-user-exec"
mkdir -p "$DESTDIR/usr/bin"
g++ -O2 -std=c++20 -fPIC -o "$DESTDIR/usr/bin/moto-plasma-screen-metrics" "$P/screen-metrics.cpp" \
    $(pkg-config --cflags --libs Qt6Gui)
for unit in moto-plasma-session moto-plasma-shared; do
    install -Dm644 "$P/$unit.service" "$DESTDIR/usr/lib/systemd/system/$unit.service"
done
for unit in moto-plasma-display moto-plasma-brightness; do
    install -Dm644 "$P/$unit.service" "$DESTDIR/usr/lib/systemd/user/$unit.service"
done
install -Dm644 "$P/kwin-override.conf" "$DESTDIR/usr/lib/systemd/user/plasma-kwin_wayland.service.d/moto.conf"
install -Dm644 "$P/pulse-override.conf" "$DESTDIR/usr/lib/systemd/user/pulseaudio.service.d/moto.conf"
