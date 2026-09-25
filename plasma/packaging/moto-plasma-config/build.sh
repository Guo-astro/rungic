# moto-plasma-config: files under plasma/config mirror the target paths.
cp -a "$SRC/plasma/config/etc" "$SRC/plasma/config/usr" "$DESTDIR/"
chmod 755 "$DESTDIR"/usr/share/kconf_update/*.py "$DESTDIR"/usr/share/kconf_update/*.sh
install -Dm644 "$SRC/plasma/dpkg-locales.conf" "$DESTDIR/etc/dpkg/dpkg.cfg.d/zz-moto-locales"
install -Dm644 "$SRC/plasma/mozilla.sources" "$DESTDIR/etc/apt/sources.list.d/mozilla.sources"
install -Dm644 "$SRC/plasma/mozilla.pref" "$DESTDIR/etc/apt/preferences.d/mozilla"
install -Dm644 "$SRC/plasma/wireplumber-android.conf" "$DESTDIR/etc/wireplumber/wireplumber.conf.d/60-moto-android.conf"
install -Dm644 "$SRC/plasma/network-manager.conf" "$DESTDIR/etc/dbus-1/system.d/moto-android-network.conf"
install -Dm644 "$SRC/plasma/gpu-env" "$DESTDIR/etc/plasma/gpu-env"
install -Dm644 "$SRC/plasma/pulse.pa" "$DESTDIR/etc/plasma/pulse.pa"
install -Dm755 "$SRC/plasma/policy-rc.d" "$DESTDIR/usr/sbin/policy-rc.d"
# systemd-coredump (for coredumpctl) must never set Android's global core_pattern.
mkdir -p "$DESTDIR/etc/sysctl.d"
ln -s /dev/null "$DESTDIR/etc/sysctl.d/50-coredump.conf"
grep -v '^#' "$SRC/plasma/config/systemd-masks.txt" | while read -r scope unit; do
    [ -n "$unit" ] || continue
    mkdir -p "$DESTDIR/etc/systemd/$scope"
    ln -s /dev/null "$DESTDIR/etc/systemd/$scope/$unit"
done
rm -f "$DESTDIR/etc/systemd-masks.txt"
