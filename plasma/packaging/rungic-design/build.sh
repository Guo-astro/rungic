# rungic-design
D=$SRC/plasma/design
cmake -S "$D" -B "$D/build" -DCMAKE_BUILD_TYPE=RelWithDebInfo -DCMAKE_INSTALL_PREFIX=/usr -DCMAKE_CXX_FLAGS=-g1
cmake --build "$D/build" -j"${JOBS:-4}"
DESTDIR="$DESTDIR" cmake --install "$D/build"
