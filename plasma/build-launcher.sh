#!/bin/sh
# Requires the verified Alpine musl and musl-dev files prepared in .work/refs/.
set -eu
task_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
task_clang=/home/kevinzhow/android-kernel/prebuilts/clang/host/linux-x86/clang-r510928
task_sysroot="$task_root/.work/refs/lxc-install-20260922/staging/sysroot"
cd "$task_root"
"$task_clang/bin/clang" --target=aarch64-linux-musl \
    --sysroot="$task_sysroot" -fuse-ld=lld -static -nostdlib -O2 -Wall -Wextra \
    .work/refs/lxc-install-20260922/staging/sysroot/usr/lib/crt1.o \
    .work/refs/lxc-install-20260922/staging/sysroot/usr/lib/crti.o \
    tools/moto_plasma_enter.c \
    -Lrefs/lxc-install-20260922/staging/sysroot/usr/lib -lc \
    "$task_clang/lib/clang/18/lib/aarch64-unknown-linux-musl/libclang_rt.builtins.a" \
    .work/refs/lxc-install-20260922/staging/sysroot/usr/lib/crtn.o \
    -o .work/refs/plasma-mobile-20260923/moto-plasma-enter
