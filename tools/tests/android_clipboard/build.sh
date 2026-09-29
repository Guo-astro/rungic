#!/bin/bash
# A temporary independent GUI app for tests; never included in product/rootfs/APK builds.
set -euo pipefail
root=$(cd "$(dirname "$0")/../../.." && pwd)
bt=${RUNGIC_ANDROID_BUILD_TOOLS:?set Android build-tools path}
jar=${RUNGIC_ANDROID_JAR:?set android.jar path}
out=$root/.work/tests/android-clipboard
mkdir -p "$out/classes" "$out/dex"
"$bt/aapt2" link -I "$jar" --manifest "$root/tools/tests/android_clipboard/AndroidManifest.xml" -o "$out/app.apk"
javac -source 8 -target 8 -cp "$jar" -d "$out/classes" "$root/tools/tests/android_clipboard/MainActivity.java"
"$bt/d8" --lib "$jar" --min-api 30 --output "$out/dex" "$out"/classes/com/rungic/clipboardtest/*.class
(cd "$out/dex" && zip -q -X "$out/app.apk" classes.dex)
"$bt/zipalign" -f 4 "$out/app.apk" "$out/aligned.apk"
"$bt/apksigner" sign --ks "$root/signing/development/launcher-signing.p12" --ks-key-alias launcher --ks-pass pass:android --out "$out/clipboard-test.apk" "$out/aligned.apk"
