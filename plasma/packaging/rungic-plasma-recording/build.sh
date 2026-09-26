# rungic-plasma-recording: the quick setting (its QML module and package), recorder, settings window.
R=$SRC/plasma/recording
cmake -S "$R" -B "$R/build" -DCMAKE_BUILD_TYPE=RelWithDebInfo -DCMAKE_INSTALL_PREFIX=/usr -DKDE_INSTALL_USE_QT_SYS_PATHS=ON -DCMAKE_CXX_FLAGS=-g1
cmake --build "$R/build" -j"${JOBS:-4}"
DESTDIR="$DESTDIR" cmake --install "$R/build"
q=$DESTDIR/usr/share/plasma/quicksettings/com.rungic.quicksetting.record
install -Dm644 "$R/quicksetting/metadata.json" "$q/metadata.json"
install -Dm644 "$R/quicksetting/contents/ui/main.qml" "$q/contents/ui/main.qml"
install -Dm644 "$R/rungic-screen-recording.notifyrc" "$DESTDIR/usr/share/knotifications6/rungic-screen-recording.notifyrc"
install -Dm755 "$R/recorder.py" "$DESTDIR/usr/bin/rungic-screen-recorder"
install -Dm755 "$R/settings.py" "$DESTDIR/usr/bin/rungic-recording-settings"
