# rungic-firefox
install -Dm755 "$SRC/plasma/firefox" "$DESTDIR/usr/bin/firefox"
cp -a "$SRC/plasma/firefox-mobile/usr" "$DESTDIR/"
install -Dm644 "$SRC/plasma/firefox-policies.json" "$DESTDIR/usr/lib/firefox/distribution/policies.json"
install -Dm644 "$SRC/plasma/firefox-codec-prefs.js" "$DESTDIR/usr/lib/firefox/defaults/pref/rungic-codec.js"
# Firefox loads FFmpeg from its own directory first: the private build with the moto codecs.
for lib in libavcodec.so.62 libavutil.so.60 libswresample.so.6 libswscale.so.9; do
    ln -s "/usr/lib/rungic-codec/ffmpeg/lib/$lib" "$DESTDIR/usr/lib/firefox/$lib"
done
