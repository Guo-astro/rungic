#!/bin/bash
set -euo pipefail
task_root=$(cd "$(dirname "$0")/.." && pwd)
task_tools="$task_root/tools/toolchains"
task_native="$task_root/native/plasma"
export PATH="$HOME/.cargo/bin:$PATH"
# The project proxy (AGENTS.md); MOTO_PROXY= builds without it on machines that cannot reach it.
task_proxy=${MOTO_PROXY-http://192.168.5.45:6152}
[ -z "$task_proxy" ] || export CARGO_HTTP_PROXY="$task_proxy"
# Toolchain: the kernel-tree clang where present, else the newest SDK NDK.
if [ -z "${MOTO_ANDROID_CLANG:-}" ] && [ ! -x /home/kevinzhow/android-kernel/prebuilts/clang/host/linux-x86/clang-r510928/bin/clang ]; then
  task_ndk=$(ls -d "${ANDROID_HOME:-$HOME/android-sdk}"/ndk/*/toolchains/llvm/prebuilt/linux-x86_64 2>/dev/null | sort -V | tail -1)
  [ -n "$task_ndk" ] || { echo 'No Android clang: set MOTO_ANDROID_CLANG/MOTO_ANDROID_SYSROOT or install an NDK' >&2; exit 1; }
  export MOTO_ANDROID_CLANG="$task_ndk/bin/clang" MOTO_ANDROID_CLANGXX="$task_ndk/bin/clang++" MOTO_ANDROID_SYSROOT="$task_ndk/sysroot"
  task_ar="$task_ndk/bin/llvm-ar"
fi
export CARGO_TARGET_AARCH64_LINUX_ANDROID_LINKER="$task_tools/android-clang"
export CC_aarch64_linux_android="$task_tools/android-clang"
export CXX_aarch64_linux_android="$task_tools/android-clang++"
export AR_aarch64_linux_android=${task_ar:-/home/kevinzhow/android-kernel/prebuilts/clang/host/linux-x86/clang-r510928/bin/llvm-ar}
export CARGO_TARGET_DIR="$task_root/.work/build/native-target"
export MOTO_JNI_LIBS_DIR="$task_root/.work/refs/plasma-mobile-20260923/native-libs/lib/arm64-v8a"
# Local Android build of libxkbcommon, else the copy shipped in the installed APK
# (tools/pull_installed_native_libs.py).
export MOTO_XKBCOMMON_LIB=${MOTO_XKBCOMMON_LIB:-$task_root/.work/deps/libxkbcommon/build-android/libxkbcommon.so}
[ -s "$MOTO_XKBCOMMON_LIB" ] || MOTO_XKBCOMMON_LIB="$MOTO_JNI_LIBS_DIR/libxkbcommon.so"
cargo build --manifest-path "$task_native/Cargo.toml" --locked --lib --release --target aarch64-linux-android --features smithay_android -j8
mkdir -p "$task_root/.work/refs/plasma-mobile-20260923/native-libs/lib/arm64-v8a"
[ "$MOTO_XKBCOMMON_LIB" -ef "$MOTO_JNI_LIBS_DIR/libxkbcommon.so" ] || cp "$MOTO_XKBCOMMON_LIB" "$MOTO_JNI_LIBS_DIR/libxkbcommon.so"
cp "$CARGO_TARGET_DIR/aarch64-linux-android/release/libuniffi_winland_core.so" "$task_root/.work/refs/plasma-mobile-20260923/native-libs/lib/arm64-v8a/"
