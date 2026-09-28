# rungic-cast
install -Dm755 "$SRC/plasma/cast/rungic-cast" "$DESTDIR/usr/bin/rungic-cast"
q=$DESTDIR/usr/share/plasma/quicksettings/com.rungic.quicksetting.cast
install -Dm644 "$SRC/plasma/cast/quicksetting/metadata.json" "$q/metadata.json"
install -Dm644 "$SRC/plasma/cast/quicksetting/contents/ui/main.qml" "$q/contents/ui/main.qml"
install -Dm644 "$SRC/plasma/cast/quicksetting/contents/ui/CastPicker.qml" "$q/contents/ui/CastPicker.qml"
