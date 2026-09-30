S=$SRC/plasma/suggestions
cmake -S "$S" -B "$S/build" -DCMAKE_BUILD_TYPE=RelWithDebInfo -DCMAKE_INSTALL_PREFIX=/usr -DCMAKE_CXX_FLAGS=-g1
cmake --build "$S/build" -j"${JOBS:-4}"
ctest --test-dir "$S/build" --output-on-failure
RUNGIC_COMPATIBILITY="$SRC/compatibility/entries" "$S/build/rungic-suggestions" --validate-knowledge
DESTDIR="$DESTDIR" cmake --install "$S/build"
install -Dm644 "$S/rungic-suggestions.service" "$DESTDIR/usr/lib/systemd/user/rungic-suggestions.service"
install -Dm644 "$S/com.rungic.Suggestions.service" "$DESTDIR/usr/share/dbus-1/services/com.rungic.Suggestions.service"
install -Dm644 "$S/plasma-plasmashell.conf" "$DESTDIR/usr/lib/systemd/user/plasma-plasmashell.service.d/rungic-suggestions.conf"
for unit in rungic-suggestions-collect.service rungic-suggestions-collect.timer; do
    install -Dm644 "$S/$unit" "$DESTDIR/usr/lib/systemd/system/$unit"
done
mkdir -p "$DESTDIR/usr/share/rungic/compatibility"
cp -a "$SRC/compatibility/." "$DESTDIR/usr/share/rungic/compatibility/"

for file in docs/73-reduce-upstream-changes.md docs/90-blender-vulkan-incident.md packages/qt6-multimedia/debian/patches/rungic/pulseaudio-sink-target-latency.patch; do
    install -Dm644 "$SRC/$file" "$DESTDIR/usr/share/rungic/compatibility/$file"
done
