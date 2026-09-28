# rungic-plasma-config: files under plasma/config mirror the target paths.
cp -a "$SRC/plasma/config/etc" "$SRC/plasma/config/usr" "$DESTDIR/"
for script in "$DESTDIR"/usr/share/kconf_update/*.py "$DESTDIR"/usr/share/kconf_update/*.sh; do
    [ ! -f "$script" ] || chmod 755 "$script"
done
install -Dm644 "$SRC/plasma/dpkg-locales.conf" "$DESTDIR/etc/dpkg/dpkg.cfg.d/zz-rungic-locales"
install -Dm644 "$SRC/plasma/mozilla.sources" "$DESTDIR/etc/apt/sources.list.d/mozilla.sources"
install -Dm644 "$SRC/plasma/mozilla.pref" "$DESTDIR/etc/apt/preferences.d/mozilla"
install -Dm644 "$SRC/plasma/wireplumber-android.conf" "$DESTDIR/etc/wireplumber/wireplumber.conf.d/60-rungic-android.conf"
install -Dm644 "$SRC/plasma/network-manager.conf" "$DESTDIR/etc/dbus-1/system.d/rungic-android-network.conf"
install -Dm644 "$SRC/plasma/bluetooth.conf" "$DESTDIR/etc/dbus-1/system.d/rungic-android-bluetooth.conf"
install -Dm644 "$SRC/plasma/modem-manager.conf" "$DESTDIR/etc/dbus-1/system.d/rungic-android-modem.conf"
install -Dm644 "$SRC/plasma/gpu-env" "$DESTDIR/etc/plasma/gpu-env"
install -Dm644 "$SRC/plasma/pulse.pa" "$DESTDIR/etc/plasma/pulse.pa"
install -Dm755 "$SRC/plasma/policy-rc.d" "$DESTDIR/usr/sbin/policy-rc.d"
# systemd-coredump (for coredumpctl) must never set Android's global core_pattern.
mkdir -p "$DESTDIR/etc/sysctl.d"
ln -s /dev/null "$DESTDIR/etc/sysctl.d/50-coredump.conf"
# Services kept off by default (docs/83): postinst applies each unit's default once, so the
# package does not own the masks and a change made in Settings survives upgrades.
install -Dm644 "$SRC/plasma/services/policy.json" "$DESTDIR/usr/share/rungic/service-policy.json"
