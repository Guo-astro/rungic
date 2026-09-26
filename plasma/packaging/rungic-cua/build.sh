# rungic-cua
C=$SRC/plasma/cua
lib=$DESTDIR/usr/lib/rungic-cua
mkdir -p "$lib"
cp -r "$SRC/upstream/arc-cua/src/arc_cua" "$C/rungic_cua" "$lib/"
install -Dm755 "$C/rungic-cua" "$DESTDIR/usr/bin/rungic-cua"
# KWin grants ScreenShot2 to this executable's desktop file only (docs/64).
mkdir -p "$DESTDIR/usr/libexec"
cc -O2 -g1 -Wall -o "$DESTDIR/usr/libexec/rungic-screenshot" "$C/screenshot/rungic-screenshot.c" \
    $(pkg-config --cflags --libs gio-unix-2.0)
install -Dm644 "$C/screenshot/rungic-screenshot.desktop" "$DESTDIR/usr/share/applications/com.rungic.screenshot.desktop"
# rungic-clicker: typesafe-computer-use in its own venv; the system site packages supply gi,
# Pillow and onnxruntime. The pins are what was validated on the phone (docs/64).
clicker=$DESTDIR/usr/lib/rungic-clicker
python3 -m venv --system-site-packages "$clicker/venv"
( [ -r /etc/profile.d/proxy.sh ] && . /etc/profile.d/proxy.sh
  "$clicker/venv/bin/python" -m pip install -q --no-compile --disable-pip-version-check \
      typesafe-sdk==0.6.0 anthropic==1.6.0 openai==2.54.0 rapidocr==3.9.2 )
# The venv was made under DESTDIR: point its scripts and config at the installed path.
grep -rlI --null "$DESTDIR" "$clicker/venv" | xargs -0 -r sed -i "s#$DESTDIR##g"
find "$clicker" -name __pycache__ -prune -exec rm -rf {} +
cp -r "$SRC/upstream/typesafe-computer-use/typesafe_computer_use" "$clicker/"
install -m644 "$C/rungic_clicker.py" "$clicker/rungic_clicker.py"
install -Dm755 "$C/rungic-clicker" "$DESTDIR/usr/bin/rungic-clicker"
find "$DESTDIR" -name __pycache__ -prune -exec rm -rf {} +
