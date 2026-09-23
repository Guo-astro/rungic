#!/bin/bash
set -euo pipefail
task_root=$(cd "$(dirname "$0")/.." && pwd)
# SDK locations differ per machine; override with MOTO_ANDROID_BUILD_TOOLS / MOTO_ANDROID_JAR.
task_sdk=${ANDROID_HOME:-$HOME/android-sdk}
task_bt=${MOTO_ANDROID_BUILD_TOOLS:-}
[ -n "$task_bt" ] || for task_bt in "$HOME/moto-android-sdk/android-16" $(ls -d "$task_sdk"/build-tools/* 2>/dev/null | sort -V -r); do [ -x "$task_bt/aapt2" ] && break; done
task_jar=${MOTO_ANDROID_JAR:-}
[ -n "$task_jar" ] || for task_jar in "$HOME/moto-android-sdk/android-36/android.jar" "$task_sdk/platforms/android-36/android.jar"; do [ -f "$task_jar" ] && break; done
task_out=${MOTO_APK_OUT:-$task_root/.work/refs/plasma-mobile-20260923}
# Prebuilt lib/arm64-v8a from the Rust build, or tools/pull_installed_native_libs.py.
task_native=${MOTO_NATIVE_LIBS:-$task_root/.work/refs/plasma-mobile-20260923/native-libs}
task_version=$(sed -n 's/.*android:versionName="\([^"]*\)".*/\1/p' "$task_root/plasma/native-apk/AndroidManifest.xml")
task_key=${MOTO_APK_KEYSTORE:-$task_root/signing/development/launcher-signing.p12}
task_build=$task_out/apk-build
mkdir -p "$task_build/classes" "$task_build/dex"
cd "$task_root/plasma/native-apk"
"$task_bt/aapt2" compile --dir res -o "$task_build/resources.zip"
"$task_bt/aapt2" link -o "$task_build/resources.apk" -I "$task_jar" --manifest AndroidManifest.xml -A assets "$task_build/resources.zip"
mapfile -t task_sources < <(find src -name '*.java')
javac -encoding UTF-8 -source 8 -target 8 -classpath "$task_jar" -d "$task_build/classes" "${task_sources[@]}"
mapfile -t task_classes < <(find "$task_build/classes" -name '*.class')
"$task_bt/d8" --lib "$task_jar" --min-api 30 --output "$task_build/dex" "${task_classes[@]}"
cp "$task_build/resources.apk" "$task_build/unsigned.apk"
(cd "$task_build/dex" && zip -q "$task_build/unsigned.apk" classes.dex)
(cd "$task_native" && zip -qr "$task_build/unsigned.apk" lib)
"$task_bt/zipalign" -f 4 "$task_build/unsigned.apk" "$task_build/aligned.apk"
"$task_bt/apksigner" sign --ks "$task_key" --ks-key-alias launcher --ks-pass pass:android --out "$task_out/Plasma-Mobile-$task_version.apk" "$task_build/aligned.apk"
"$task_bt/apksigner" verify "$task_out/Plasma-Mobile-$task_version.apk"
