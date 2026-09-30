# rungic-plasma-diagnostics
D=$SRC/system/diagnostics
for tool in rungic-a11y rungic-fs-audit rungic-integrity rungic-crash-symbols; do
    install -Dm755 "$D/$tool" "$DESTDIR/usr/bin/$tool"
done
install -Dm755 "$D/rungic-coredump-collect" "$DESTDIR/usr/libexec/rungic-coredump-collect"
install -Dm644 "$D/rungic-local-config.json" "$DESTDIR/usr/share/rungic/local-config.json"
install -Dm644 "$D/rungic-coredump.path" "$DESTDIR/usr/lib/systemd/system/rungic-coredump.path"
install -Dm644 "$D/rungic-coredump.service" "$DESTDIR/usr/lib/systemd/system/rungic-coredump.service"
install -Dm644 "$D/rungic-coredump.tmpfiles" "$DESTDIR/usr/lib/tmpfiles.d/rungic-coredump.conf"
install -Dm644 "$D/60-rungic-core.conf" "$DESTDIR/usr/lib/systemd/system.conf.d/60-rungic-core.conf"
install -Dm644 "$D/60-rungic-core.conf" "$DESTDIR/usr/lib/systemd/user.conf.d/60-rungic-core.conf"
install -Dm644 "$D/sys-kernel-tracing.conf" "$DESTDIR/usr/lib/systemd/system/sys-kernel-tracing.mount.d/60-rungic.conf"
# Probes and the compositor benchmark.
B=$DESTDIR/usr/bin
mkdir -p "$B"
gl="$(pkg-config --cflags --libs gbm egl glesv2)"
cc -O2 -g1 -o "$B/rungic-gpu-probe" "$SRC/shared/graphics/gpu-probe.c" $gl
cc -O2 -g1 -I"$SRC/shared/graphics" $(pkg-config --cflags libdrm) -o "$B/rungic-gpu-ahb-probe" "$SRC/desktop/gpu-ahb-probe.c" $gl
qt="$(pkg-config --cflags --libs Qt6Gui Qt6Qml)"
g++ -O2 -g1 -std=c++20 -fPIC -o "$B/rungic-input-probe" "$D/probes/input-probe.cpp" $qt
g++ -O2 -g1 -std=c++20 -fPIC -o "$B/screen-probe" "$D/probes/screen-probe.cpp" $(pkg-config --cflags --libs Qt6Gui)
g++ -O2 -g1 -std=c++20 -fPIC -o "$B/apps-probe" "$D/probes/apps-probe.cpp" $(pkg-config --cflags --libs Qt6Core) \
    -I/usr/include/KF6/KService -I/usr/include/KF6/KCoreAddons -lKF6Service -lKF6CoreAddons
sh "$SRC/desktop/bench/compbench/build.sh" "$SRC/desktop/bench/compbench/build" >/dev/null
install -m755 "$SRC/desktop/bench/compbench/build/compbench" "$B/rungic-compbench"
# Wayland protocol probes (docs/42, docs/60, docs/72); the idle probe backs acceptance idle.inhibit.
W=$(mktemp -d)
sh "$D/wayland-probes/build.sh" "$W" >/dev/null
for probe in idle minmax size; do
    install -m755 "$W/$probe-probe" "$B/rungic-$probe-probe"
done
rm -rf "$W"
