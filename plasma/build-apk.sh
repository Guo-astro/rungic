#!/bin/bash
set -euo pipefail
task_root=$(cd "$(dirname "$0")/.." && pwd)
# SDK locations differ per machine; override with RUNGIC_ANDROID_BUILD_TOOLS / RUNGIC_ANDROID_JAR.
task_sdk=${ANDROID_HOME:-$HOME/android-sdk}
task_bt=${RUNGIC_ANDROID_BUILD_TOOLS:-}
[ -n "$task_bt" ] || for task_bt in "$HOME/moto-android-sdk/android-16" $(ls -d "$task_sdk"/build-tools/* 2>/dev/null | sort -V -r); do [ -x "$task_bt/aapt2" ] && break; done
task_jar=${RUNGIC_ANDROID_JAR:-}
[ -n "$task_jar" ] || for task_jar in "$HOME/moto-android-sdk/android-36/android.jar" "$task_sdk/platforms/android-36/android.jar"; do [ -f "$task_jar" ] && break; done
task_out=${RUNGIC_APK_OUT:-$task_root/.work/refs/plasma-mobile-20260923}
# Prebuilt lib/arm64-v8a from the Rust build, or tools/pull_installed_native_libs.py.
task_native=${RUNGIC_NATIVE_LIBS:-$task_root/.work/refs/plasma-mobile-20260923/native-libs}
task_version=$(sed -n 's/.*android:versionName="\([^"]*\)".*/\1/p' "$task_root/plasma/native-apk/AndroidManifest.xml")
task_key=${RUNGIC_APK_KEYSTORE:-$task_root/signing/development/launcher-signing.p12}
task_build=$task_out/apk-build
mkdir -p "$task_build/classes" "$task_build/dex"
task_ocr=$task_build/ocr
rm -rf "$task_ocr" "$task_build/assets"
cp -r "$task_root/plasma/native-apk/assets" "$task_build/assets"
# On-device OCR (docs/64) is optional and off by default (docs/73): its LiteRT runtime and models are
# most of the APK's size, and the Linux side reads text on the CPU (RapidOCR) when the APK has none.
# RUNGIC_APK_OCR=1 builds it in: LiteRT and PP-OCRv6 pinned in provenance/ocr-20260925, and
# librungicocr.so built with the NDK (RUNGIC_ANDROID_NDK, else the newest under $task_sdk/ndk).
if [ "${RUNGIC_APK_OCR:-0}" = 1 ]; then
    task_ndk=${RUNGIC_ANDROID_NDK:-$(ls -d "$task_sdk"/ndk/* 2>/dev/null | sort -V | tail -1)}
    python3 "$task_root/tools/fetch_ocr_assets.py" "$task_ocr"
    mkdir -p "$task_ocr/include/litert/build_common"
    # LiteRT's C API headers from its pinned source (packages/litert, docs/71).
    task_litert=$task_build/litert
    python3 "$task_root/tools/pq.py" source litert --output "$task_litert" >/dev/null
    cp "$task_litert/litert/build_common/config/build_config_gpu.h" "$task_ocr/include/litert/build_common/build_config.h"
    "$task_ndk/toolchains/llvm/prebuilt/linux-x86_64/bin/aarch64-linux-android30-clang++" -std=c++17 -O2 -fPIC -shared \
        -Wall -Wextra -Wno-unused-parameter -I"$task_ocr/include" -I"$task_litert" \
        -o "$task_ocr/lib/arm64-v8a/librungicocr.so" "$task_root"/plasma/native-apk/jni/ocr/{ppocr,jni}.cc \
        -L"$task_ocr/lib/arm64-v8a" -lLiteRt -llog -static-libstdc++ -Wl,--no-undefined
    cp -r "$task_ocr/assets/ocr" "$task_build/assets/ocr"
fi
cd "$task_root/plasma/native-apk"
"$task_bt/aapt2" compile --dir res -o "$task_build/resources.zip"
"$task_bt/aapt2" link -o "$task_build/resources.apk" -I "$task_jar" --manifest AndroidManifest.xml -A "$task_build/assets" -0 tflite "$task_build/resources.zip"
mapfile -t task_sources < <(find src -name '*.java')
javac -encoding UTF-8 -source 8 -target 8 -classpath "$task_jar" -d "$task_build/classes" "${task_sources[@]}"
mapfile -t task_classes < <(find "$task_build/classes" -name '*.class')
"$task_bt/d8" --lib "$task_jar" --min-api 30 --output "$task_build/dex" "${task_classes[@]}"
cp "$task_build/resources.apk" "$task_build/unsigned.apk"
(cd "$task_build/dex" && zip -q "$task_build/unsigned.apk" classes.dex)
(cd "$task_native" && zip -qr "$task_build/unsigned.apk" lib)
[ ! -d "$task_ocr/lib" ] || (cd "$task_ocr" && zip -qr "$task_build/unsigned.apk" lib)
"$task_bt/zipalign" -f 4 "$task_build/unsigned.apk" "$task_build/aligned.apk"
"$task_bt/apksigner" sign --ks "$task_key" --ks-key-alias launcher --ks-pass pass:android --out "$task_out/Rungic-$task_version.apk" "$task_build/aligned.apk"
"$task_bt/apksigner" verify "$task_out/Rungic-$task_version.apk"
