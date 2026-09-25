# moto-snapshot: vendor/snapshot (51.0 with the moto codec change; Cargo dependencies vendored).
cd "$SRC/vendor/snapshot"
export CARGO_BUILD_JOBS=${JOBS:-4} CARGO_NET_OFFLINE=true
meson setup build --prefix=/usr -Dprofile=default -Dx11=disabled >/dev/null
meson compile -C build -j"${JOBS:-4}"
DESTDIR="$DESTDIR" meson install -C build >/dev/null
rm -f "$DESTDIR/usr/share/glib-2.0/schemas/gschemas.compiled"
