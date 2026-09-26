# moto-codec
M=$SRC/shared/media
lib=$DESTDIR/usr/lib/moto-codec
mkdir -p "$lib" "$DESTDIR/usr/lib/aarch64-linux-gnu/gstreamer-1.0"
cc -O2 -g1 -fPIC -shared -pthread -Wl,-soname,libmotocodec.so -o "$lib/libmotocodec.so" "$M/codec-client.c"
cc -O2 -g1 -fPIC -shared -o "$DESTDIR/usr/lib/aarch64-linux-gnu/gstreamer-1.0/libgstmotocodec.so" "$M/gst-moto-codec.c" \
    $(pkg-config --cflags --libs gstreamer-video-1.0) -L"$lib" -lmotocodec -Wl,-rpath,/usr/lib/moto-codec
# Private FFmpeg (packages/ffmpeg: the release with the codec registration patches, docs/71).
cd "$SRC/upstream/ffmpeg"
./configure --prefix=/usr/lib/moto-codec/ffmpeg --enable-shared --disable-static \
 --disable-doc --disable-autodetect --disable-network --disable-devices \
 --enable-gpl --enable-libx264 --enable-libx265 --enable-libvpx --enable-libopus --enable-libdav1d \
 --extra-cflags=-g1 --extra-ldflags="-L$lib -Wl,-rpath,/usr/lib/moto-codec:/usr/lib/moto-codec/ffmpeg/lib" \
 --extra-libs='-lmotocodec -pthread' >/dev/null
make -j"${JOBS:-4}" >/dev/null
make install DESTDIR="$DESTDIR" >/dev/null
rm -rf "$DESTDIR/usr/lib/moto-codec/ffmpeg/include" "$DESTDIR/usr/lib/moto-codec/ffmpeg/lib/pkgconfig" \
       "$DESTDIR/usr/lib/moto-codec/ffmpeg/share"
