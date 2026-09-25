# moto-plasma-diagnostics
D=$SRC/plasma/diagnostics
for tool in moto-a11y moto-fs-audit moto-integrity moto-crash-symbols; do
    install -Dm755 "$D/$tool" "$DESTDIR/usr/bin/$tool"
done
install -Dm755 "$D/moto-coredump-collect" "$DESTDIR/usr/libexec/moto-coredump-collect"
install -Dm644 "$D/moto-local-config.json" "$DESTDIR/usr/share/moto/local-config.json"
install -Dm644 "$D/moto-coredump.path" "$DESTDIR/usr/lib/systemd/system/moto-coredump.path"
install -Dm644 "$D/moto-coredump.service" "$DESTDIR/usr/lib/systemd/system/moto-coredump.service"
install -Dm644 "$D/moto-coredump.tmpfiles" "$DESTDIR/usr/lib/tmpfiles.d/moto-coredump.conf"
install -Dm644 "$D/60-moto-core.conf" "$DESTDIR/usr/lib/systemd/system.conf.d/60-moto-core.conf"
install -Dm644 "$D/60-moto-core.conf" "$DESTDIR/usr/lib/systemd/user.conf.d/60-moto-core.conf"
install -Dm644 "$D/sys-kernel-tracing.conf" "$DESTDIR/usr/lib/systemd/system/sys-kernel-tracing.mount.d/60-moto.conf"
# Probes and the compositor benchmark.
B=$DESTDIR/usr/bin
mkdir -p "$B"
gl="$(pkg-config --cflags --libs gbm egl glesv2)"
cc -O2 -g1 -o "$B/moto-gpu-probe" "$SRC/shared/graphics/gpu-probe.c" $gl
cc -O2 -g1 -I"$SRC/shared/graphics" $(pkg-config --cflags libdrm) -o "$B/moto-gpu-ahb-probe" "$SRC/plasma/gpu-ahb-probe.c" $gl
qt="$(pkg-config --cflags --libs Qt6Gui Qt6Qml)"
g++ -O2 -g1 -std=c++20 -fPIC -o "$B/moto-input-probe" "$D/probes/input-probe.cpp" $qt
g++ -O2 -g1 -std=c++20 -fPIC -o "$B/screen-probe" "$D/probes/screen-probe.cpp" $(pkg-config --cflags --libs Qt6Gui)
g++ -O2 -g1 -std=c++20 -fPIC -o "$B/apps-probe" "$D/probes/apps-probe.cpp" $(pkg-config --cflags --libs Qt6Core) \
    -I/usr/include/KF6/KService -I/usr/include/KF6/KCoreAddons -lKF6Service -lKF6CoreAddons
sh "$SRC/plasma/bench/compbench/build.sh" "$SRC/plasma/bench/compbench/build" >/dev/null
install -m755 "$SRC/plasma/bench/compbench/build/compbench" "$B/moto-compbench"
    "$B"/apps-probe "$B"/moto-compbench
