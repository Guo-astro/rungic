#!/bin/sh
# Build a root "enter" program (tools/rungic_*_enter.c) as a static Android executable with the NDK:
#   tools/build_enter.sh plasma|lxc|docker    -> .work/build/android/rungic-NAME-enter
# The program pivots into a Linux runtime before it execs, so its own C library does not matter;
# RUNGIC_ANDROID_NDK overrides the newest NDK under $ANDROID_HOME.
set -eu
task_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
name=${1:?usage: build_enter.sh plasma|lxc|docker}
task_ndk=${RUNGIC_ANDROID_NDK:-$(ls -d "${ANDROID_HOME:-$HOME/android-sdk}"/ndk/* 2>/dev/null | sort -V | tail -1)}
[ -d "$task_ndk" ] || { echo 'No Android NDK: set RUNGIC_ANDROID_NDK' >&2; exit 1; }
mkdir -p "$task_root/.work/build/android"
"$task_ndk/toolchains/llvm/prebuilt/linux-x86_64/bin/aarch64-linux-android30-clang" -static -s -O2 -Wall -Wextra -Werror \
    "$task_root/tools/rungic_${name}_enter.c" -o "$task_root/.work/build/android/rungic-$name-enter"
echo "$task_root/.work/build/android/rungic-$name-enter"
