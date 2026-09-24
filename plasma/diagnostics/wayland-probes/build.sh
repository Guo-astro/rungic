#!/bin/sh
# Build the xdg-shell probes (docs/42, docs/60) in the Plasma container:
#   minmax-probe  commits a minimum size above the maximum and reports whether it stays connected
#   size-probe    opens a resizable 400x600 window and prints the compositor's configures
set -eu
out=${1:-.}
xml=/usr/share/wayland-protocols/stable/xdg-shell/xdg-shell.xml
wayland-scanner client-header "$xml" "$out/xdg-shell-client-protocol.h"
wayland-scanner private-code "$xml" "$out/xdg-shell-protocol.c"
for probe in minmax-probe size-probe; do
    cc -O2 -I"$out" -o "$out/$probe" "$(dirname "$0")/$probe.c" "$out/xdg-shell-protocol.c" -lwayland-client
done
