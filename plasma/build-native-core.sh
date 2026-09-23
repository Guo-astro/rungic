#!/bin/bash
set -euo pipefail
task_root=$(cd "$(dirname "$0")/.." && pwd)
task_tools="$task_root/tools/toolchains"
task_native="$task_root/native/plasma"
export PATH="/home/kevinzhow/.cargo/bin:$PATH"
export CARGO_HTTP_PROXY=http://192.168.5.45:6152
export CARGO_TARGET_AARCH64_LINUX_ANDROID_LINKER="$task_tools/android-clang"
export CC_aarch64_linux_android="$task_tools/android-clang"
export CXX_aarch64_linux_android="$task_tools/android-clang++"
export AR_aarch64_linux_android=/home/kevinzhow/android-kernel/prebuilts/clang/host/linux-x86/clang-r510928/bin/llvm-ar
export CARGO_TARGET_DIR="$task_root/.work/build/native-target"
export MOTO_XKBCOMMON_LIB="$task_root/.work/deps/libxkbcommon/build-android/libxkbcommon.so"
export MOTO_JNI_LIBS_DIR="$task_root/.work/refs/plasma-mobile-20260923/native-libs/lib/arm64-v8a"
cargo build --manifest-path "$task_native/Cargo.toml" --locked --lib --release --target aarch64-linux-android --features smithay_android -j8
mkdir -p "$task_root/.work/refs/plasma-mobile-20260923/native-libs/lib/arm64-v8a"
cp "$MOTO_XKBCOMMON_LIB" "$MOTO_JNI_LIBS_DIR/libxkbcommon.so"
cp "$CARGO_TARGET_DIR/aarch64-linux-android/release/libuniffi_winland_core.so" "$task_root/.work/refs/plasma-mobile-20260923/native-libs/lib/arm64-v8a/"
