#!/bin/bash
# Build rungic-cast.jar (classes.dex for app_process) with the SDK used by plasma/build-apk.sh.
set -euo pipefail
root=$(cd "$(dirname "$0")/../../.." && pwd)
sdk=${ANDROID_HOME:-$HOME/android-sdk}
bt=${RUNGIC_ANDROID_BUILD_TOOLS:-$(ls -d "$sdk"/build-tools/* | sort -V | tail -1)}
jar=${RUNGIC_ANDROID_JAR:-$sdk/platforms/android-36/android.jar}
out=${RUNGIC_CAST_OUT:-$root/.work/build/rungic-cast}
rm -rf "$out" && mkdir -p "$out/classes" "$out/dex"
javac -encoding UTF-8 -source 8 -target 8 -classpath "$jar" -d "$out/classes" $(find "$(dirname "$0")/src" -name '*.java')
"$bt/d8" --lib "$jar" --min-api 30 --output "$out/dex" $(find "$out/classes" -name '*.class')
(cd "$out/dex" && zip -q -X ../rungic-cast.jar classes.dex)
echo "$out/rungic-cast.jar"
