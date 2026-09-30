# rungic-cast
install -Dm755 "$SRC/plasma/cast/rungic-cast" "$DESTDIR/usr/bin/rungic-cast"
q=$DESTDIR/usr/share/plasma/quicksettings/com.rungic.quicksetting.cast
install -Dm644 "$SRC/plasma/cast/quicksetting/metadata.json" "$q/metadata.json"
install -Dm644 "$SRC/plasma/cast/quicksetting/contents/ui/main.qml" "$q/contents/ui/main.qml"
install -Dm644 "$SRC/plasma/cast/quicksetting/contents/ui/CastPicker.qml" "$q/contents/ui/CastPicker.qml"
# The quick setting's catalog: Plasma Mobile loads it under the domain plasma_<plugin id>.
for po in "$SRC"/plasma/cast/po/*/*.po; do
    lang=$(basename "$(dirname "$po")")
    mkdir -p "$DESTDIR/usr/share/locale/$lang/LC_MESSAGES"
    msgfmt -c --check-format -o "$DESTDIR/usr/share/locale/$lang/LC_MESSAGES/$(basename "$po" .po).mo" "$po"
done
