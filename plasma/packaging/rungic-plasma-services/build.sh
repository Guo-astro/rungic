# rungic-plasma-services: Settings -> Services (the KCM) and its KAuth helper (docs/83).
S=$SRC/plasma/services
cmake -S "$S" -B "$S/build" -DCMAKE_BUILD_TYPE=RelWithDebInfo -DCMAKE_INSTALL_PREFIX=/usr -DKDE_INSTALL_USE_QT_SYS_PATHS=ON -DCMAKE_CXX_FLAGS=-g1
cmake --build "$S/build" -j"${JOBS:-4}"
DESTDIR="$DESTDIR" cmake --install "$S/build"
