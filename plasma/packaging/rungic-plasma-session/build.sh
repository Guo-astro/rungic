# rungic-plasma-session
P=$SRC/plasma
install -Dm755 "$P/init" "$DESTDIR/usr/sbin/rungic-plasma-init"
install -Dm755 "$P/session" "$DESTDIR/usr/libexec/rungic-plasma-session"
install -Dm755 "$P/shared-storage" "$DESTDIR/usr/libexec/rungic-plasma-shared"
install -Dm755 "$P/kwin" "$DESTDIR/usr/libexec/rungic-plasma-kwin"
install -Dm755 "$P/desktop-action.py" "$DESTDIR/usr/libexec/rungic-plasma-desktop-action"
install -Dm755 "$P/display.py" "$DESTDIR/usr/libexec/rungic-plasma-display"
install -Dm755 "$P/brightness.py" "$DESTDIR/usr/libexec/rungic-plasma-brightness"
install -Dm644 "$P/power-policy.py" "$DESTDIR/usr/libexec/rungic-power-policy.py"
install -Dm755 "$P/account/setup.py" "$DESTDIR/usr/libexec/rungic-plasma-account-setup"
install -Dm644 "$P/account/rungic-account.desktop" "$DESTDIR/usr/share/applications/rungic-account.desktop"
install -Dm755 "$P/user-exec" "$DESTDIR/usr/bin/rungic-plasma-user-exec"
install -Dm755 "$P/rebrand-user.py" "$DESTDIR/usr/libexec/rungic-rebrand-user"
mkdir -p "$DESTDIR/usr/bin"
g++ -O2 -g1 -std=c++20 -fPIC -o "$DESTDIR/usr/bin/rungic-plasma-screen-metrics" "$P/screen-metrics.cpp" \
    $(pkg-config --cflags --libs Qt6Gui)
for unit in rungic-plasma-session rungic-plasma-shared; do
    install -Dm644 "$P/$unit.service" "$DESTDIR/usr/lib/systemd/system/$unit.service"
done
for unit in rungic-plasma-display rungic-plasma-brightness; do
    install -Dm644 "$P/$unit.service" "$DESTDIR/usr/lib/systemd/user/$unit.service"
done
install -Dm644 "$P/kwin-override.conf" "$DESTDIR/usr/lib/systemd/user/plasma-kwin_wayland.service.d/rungic.conf"
install -Dm644 "$P/pulse-override.conf" "$DESTDIR/usr/lib/systemd/user/pulseaudio.service.d/rungic.conf"
