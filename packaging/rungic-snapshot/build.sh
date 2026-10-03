# rungic-snapshot: packages/snapshot (51.0 with the codec patches, docs/71; Cargo dependencies bundled).
cd "$SRC/upstream/snapshot"
export CARGO_BUILD_JOBS=${JOBS:-4} CARGO_NET_OFFLINE=true
# Kept between builds (rungic_package.sync_script): set up once; meson reconfigures by itself
# when its build files change.
[ -f build/build.ninja ] || meson setup build --prefix=/usr -Dprofile=default -Dx11=disabled >/dev/null
meson compile -C build -j"${JOBS:-4}"
DESTDIR="$DESTDIR" meson install -C build >/dev/null
rm -f "$DESTDIR/usr/share/glib-2.0/schemas/gschemas.compiled"
