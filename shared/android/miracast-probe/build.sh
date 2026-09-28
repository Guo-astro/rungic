#!/bin/bash
# Build miracast-probe.jar (classes.dex for app_process) — the parked, unfinished
# self-written Wi-Fi Display source experiment (docs/84). Run on the phone as root:
#   CLASSPATH=miracast-probe.jar app_process /system/bin com.rungic.miracast.MiracastProbe <sink> [seconds] [listen MHz] [GO intent]
set -euo pipefail
root=$(cd "$(dirname "$0")/../../.." && pwd)
sdk=${ANDROID_HOME:-$HOME/android-sdk}
bt=${RUNGIC_ANDROID_BUILD_TOOLS:-$(ls -d "$sdk"/build-tools/* | sort -V | tail -1)}
jar=${RUNGIC_ANDROID_JAR:-$sdk/platforms/android-36/android.jar}
out=${RUNGIC_MIRACAST_OUT:-$root/.work/build/miracast-probe}
rm -rf "$out" && mkdir -p "$out/classes" "$out/dex"
javac -encoding UTF-8 -source 8 -target 8 -classpath "$jar" -d "$out/classes" $(find "$(dirname "$0")/src" -name '*.java')
"$bt/d8" --lib "$jar" --min-api 33 --output "$out/dex" $(find "$out/classes" -name '*.class')
(cd "$out/dex" && zip -q -X ../miracast-probe.jar classes.dex)
echo "$out/miracast-probe.jar"
