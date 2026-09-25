# moto-cast
install -Dm755 "$SRC/plasma/cast/moto-cast" "$DESTDIR/usr/bin/moto-cast"
q=$DESTDIR/usr/share/plasma/quicksettings/dev.moto.quicksetting.cast
install -Dm644 "$SRC/plasma/cast/quicksetting/metadata.json" "$q/metadata.json"
install -Dm644 "$SRC/plasma/cast/quicksetting/contents/ui/main.qml" "$q/contents/ui/main.qml"
