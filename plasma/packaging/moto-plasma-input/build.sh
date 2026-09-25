# moto-plasma-input
R=$SRC/plasma/rime
cmake -S "$R" -B "$R/build" -G Ninja -DCMAKE_BUILD_TYPE=RelWithDebInfo -DCMAKE_INSTALL_PREFIX=/usr \
    -DCMAKE_CXX_FLAGS=-g1
cmake --build "$R/build" -j"${JOBS:-4}"
DESTDIR="$DESTDIR" cmake --install "$R/build"
install -Dm755 "$R/keyboard" "$DESTDIR/usr/libexec/moto-plasma-rime"
install -Dm644 "$R/moto-plasma-rime.desktop" "$DESTDIR/usr/share/applications/moto-plasma-rime.desktop"
python3 "$R/layouts.py" /usr/share/plasma/keyboard/layouts "$DESTDIR/usr/share/moto-rime/plasma/keyboard/layouts"
