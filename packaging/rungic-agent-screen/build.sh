# rungic-agent-screen: desktop mode and the assistant's screen (docs/65, docs/research/91). The
# window's executable holds KWin's screencast and fake-input grants through its desktop files
# (X-KDE-Wayland-Interfaces, matched by executable path).
A=$SRC/agent/screen
# The workspaces (docs/research/91): launcher, input/stream/background helpers, their buses.
W=$SRC/agent/workspace
cmake -S "$W" -B "$W/build" -DCMAKE_BUILD_TYPE=RelWithDebInfo -DCMAKE_INSTALL_PREFIX=/usr -DCMAKE_CXX_FLAGS=-g1
cmake --build "$W/build" -j"${JOBS:-4}"
DESTDIR="$DESTDIR" cmake --install "$W/build"
cmake -S "$A" -B "$A/build" -DCMAKE_BUILD_TYPE=RelWithDebInfo -DCMAKE_INSTALL_PREFIX=/usr -DCMAKE_CXX_FLAGS=-g1
cmake --build "$A/build" -j"${JOBS:-4}"
DESTDIR="$DESTDIR" cmake --install "$A/build"
install -Dm755 "$A/rungic-agent-screen" "$DESTDIR/usr/bin/rungic-agent-screen"
ln -sf rungic-agent-screen "$DESTDIR/usr/bin/rungic-desktop-mode"
for app in AgentScreen DesktopMode; do
    install -Dm644 "$A/com.rungic.$app.desktop" "$DESTDIR/usr/share/applications/com.rungic.$app.desktop"
done
# Its window's catalog and the quick setting's (plasma_<plugin id>) come with cmake --install (po/).
# One tile: desktop mode. The assistant's screen shows itself when the agent works there.
q=$DESTDIR/usr/share/plasma/quicksettings/com.rungic.quicksetting.desktopmode
install -Dm644 "$A/quicksetting/metadata.json" "$q/metadata.json"
install -Dm644 "$A/quicksetting/contents/ui/main.qml" "$q/contents/ui/main.qml"
