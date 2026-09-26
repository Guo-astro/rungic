#!/bin/sh
# Build the xdg-shell probes (docs/42, docs/60) in the Plasma container:
#   minmax-probe  commits a minimum size above the maximum and reports whether it stays connected
#   size-probe    opens a resizable 400x600 window and prints the compositor's configures
#   idle-probe    holds a zwp_idle_inhibitor_v1 for N seconds (docs/72)
set -eu
out=${1:-.}
xml=/usr/share/wayland-protocols/stable/xdg-shell/xdg-shell.xml
wayland-scanner client-header "$xml" "$out/xdg-shell-client-protocol.h"
wayland-scanner private-code "$xml" "$out/xdg-shell-protocol.c"
for probe in minmax-probe size-probe; do
    cc -O2 -g1 -I"$out" -o "$out/$probe" "$(dirname "$0")/$probe.c" "$out/xdg-shell-protocol.c" -lwayland-client
done
idle=/usr/share/wayland-protocols/unstable/idle-inhibit/idle-inhibit-unstable-v1.xml
wayland-scanner client-header "$idle" "$out/idle-inhibit-unstable-v1-client-protocol.h"
wayland-scanner private-code "$idle" "$out/idle-inhibit-unstable-v1-protocol.c"
cc -O2 -g1 -I"$out" -o "$out/idle-probe" "$(dirname "$0")/idle-probe.c" "$out/idle-inhibit-unstable-v1-protocol.c" \
    "$out/xdg-shell-protocol.c" -lwayland-client
