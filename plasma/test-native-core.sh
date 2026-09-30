#!/bin/bash
# Unit tests of the host compositor (packages/android-host): they need Android (oboe, NDK), so they are
# built for aarch64-linux-android and run on the phone over adb, then removed (docs/72).
set -euo pipefail
task_root=$(cd "$(dirname "$0")/.." && pwd)
task_tools="$task_root/tools/toolchains"
export PYTHONPYCACHEPREFIX=${PYTHONPYCACHEPREFIX:-$task_root/.work/cache/pycache}
task_native=$(python3 "$task_root/tools/prepare_android_host.py")
export PATH="$HOME/.cargo/bin:$PATH"
task_ndk=$(ls -d "${ANDROID_HOME:-$HOME/android-sdk}"/ndk/*/toolchains/llvm/prebuilt/linux-x86_64 | sort -V | tail -1)
export RUNGIC_ANDROID_CLANG="$task_ndk/bin/clang" RUNGIC_ANDROID_CLANGXX="$task_ndk/bin/clang++" RUNGIC_ANDROID_SYSROOT="$task_ndk/sysroot"
export CARGO_TARGET_AARCH64_LINUX_ANDROID_LINKER="$task_tools/android-clang"
export CC_aarch64_linux_android="$task_tools/android-clang" CXX_aarch64_linux_android="$task_tools/android-clang++"
export AR_aarch64_linux_android="$task_ndk/bin/llvm-ar"
export CARGO_TARGET_DIR="$task_root/.work/build/native-target"
export RUNGIC_JNI_LIBS_DIR="$task_root/.work/refs/plasma-mobile-20260923/native-libs/lib/arm64-v8a"
export RUNGIC_XKBCOMMON_LIB="$RUNGIC_JNI_LIBS_DIR/libxkbcommon.so"
binary=$(cargo test --manifest-path "$task_native/Cargo.toml" --locked --lib --release \
    --target aarch64-linux-android --features smithay_android --no-run --message-format=json \
  | python3 -c "import json,sys; [print(m['executable']) for m in map(json.loads, sys.stdin) if m.get('reason')=='compiler-artifact' and m.get('executable') and m['target']['name']=='uniffi_winland_core']")
dir=/data/local/tmp/winland-tests.$$
adb shell mkdir -p "$dir"
adb push -q "$binary" "$dir/tests"
adb push -q "$RUNGIC_XKBCOMMON_LIB" "$dir/"
adb shell "cd $dir && LD_LIBRARY_PATH=$dir ./tests --test-threads 1 $*; status=\$?; rm -rf $dir; exit \$status"
