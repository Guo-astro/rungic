# rungic-agent-screen. The window's executable holds KWin's screencast and fake-input grants through
# com.rungic.AgentScreen.desktop (X-KDE-Wayland-Interfaces, matched by executable path).
A=$SRC/plasma/agent-screen
cmake -S "$A" -B "$A/build" -DCMAKE_BUILD_TYPE=RelWithDebInfo -DCMAKE_INSTALL_PREFIX=/usr -DCMAKE_CXX_FLAGS=-g1
cmake --build "$A/build" -j"${JOBS:-4}"
DESTDIR="$DESTDIR" cmake --install "$A/build"
install -Dm755 "$A/rungic-agent-screen" "$DESTDIR/usr/bin/rungic-agent-screen"
install -Dm644 "$A/com.rungic.AgentScreen.desktop" "$DESTDIR/usr/share/applications/com.rungic.AgentScreen.desktop"
q=$DESTDIR/usr/share/plasma/quicksettings/com.rungic.quicksetting.agentscreen
install -Dm644 "$A/quicksetting/metadata.json" "$q/metadata.json"
install -Dm644 "$A/quicksetting/contents/ui/main.qml" "$q/contents/ui/main.qml"
