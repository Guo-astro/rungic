#!/bin/sh
# Run inside the Ubuntu 26.04 ARM64 container with the archived FFmpeg 8.1.2 tree.
set -eu
cd /root/moto-codec-build/ffmpeg-8.1.2
cp ../ffmpeg-moto-codec.c libavcodec/moto_codec.c
cp ../codec-client.h libavcodec/moto-codec-client.h
python3 - <<'PY'
from pathlib import Path
import re
names=['h264_moto_auto_encoder','hevc_moto_auto_encoder','h264_moto_decoder','hevc_moto_decoder','vp9_moto_decoder','h264_moto_encoder','hevc_moto_encoder']
p=Path('libavcodec/allcodecs.c');s=p.read_text()
for name in names:
 s=re.sub(r'^extern const FFCodec ff_'+name+r';\n','',s,flags=re.M)
marker='extern const FFCodec ff_a64multi_encoder;'
assert s.count(marker)==1
s=s.replace(marker,'\n'.join('extern const FFCodec ff_'+name+';' for name in names)+'\n\n'+marker);p.write_text(s)
p=Path('libavcodec/Makefile');s=p.read_text()
for name in names:
 s=re.sub(r'^OBJS-\$\(CONFIG_'+name.upper()+r'\).*\n','',s,flags=re.M)
s+='\n'+''.join('OBJS-$(CONFIG_'+name.upper()+') += moto_codec.o\n' for name in names);p.write_text(s)
# This private library exposes x264 explicitly as the software fallback. The
# auto encoder must remain eligible for Firefox's CPU-frame encoder API on
# Alpine builds whose MOZ_FFVPX_AUDIOONLY excludes remote hardware encoding.
p=Path('libavcodec/libx264.c');s=p.read_text();s=s.replace('.p.name           = "libx264",','.p.name           = "libx264_sw",');p.write_text(s)
PY
./configure --prefix=/usr/local/lib/moto-codec/ffmpeg --enable-shared --disable-static \
 --disable-doc --disable-debug --disable-autodetect --disable-network --disable-devices \
 --enable-gpl --enable-libx264 --enable-libx265 --enable-libvpx --enable-libopus --enable-libdav1d \
 --extra-ldflags='-L/usr/local/lib/moto-codec -Wl,-rpath,/usr/local/lib/moto-codec' \
 --extra-libs='-lmotocodec -pthread'
make -j2
make install
