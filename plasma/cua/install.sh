#!/bin/sh
# Install moto-cua and moto-clicker (run as root in the container from a copy of
# the repository tree: plasma/cua, vendor/arc-cua and vendor/typesafe-computer-use
# under $1, default the root above this script's directory). Registers the MCP
# server for the desktop user's Codex.
set -eu
src=$(cd "$(dirname "$0")" && pwd)
root=${1:-$(cd "$src/../.." && pwd)}
lib=/usr/local/lib/moto-cua
rm -rf "$lib"
mkdir -p "$lib"
cp -r "$root/vendor/arc-cua/src/arc_cua" "$lib/"
cp -r "$src/moto_cua" "$lib/"
find "$lib" -name __pycache__ -prune -exec rm -rf {} +
install -m755 "$src/moto-cua" /usr/local/bin/moto-cua

# Screen capture helper: KWin grants ScreenShot2 to this executable's desktop file only (docs/64).
cc -O2 -Wall -o /usr/local/libexec/moto-screenshot "$src/screenshot/moto-screenshot.c" \
    $(pkg-config --cflags --libs gio-unix-2.0)
install -m644 "$src/screenshot/moto-screenshot.desktop" /usr/share/applications/dev.moto.screenshot.desktop

# moto-clicker: typesafe-computer-use (goal-level JEV) in its own virtualenv (docs/64). The system
# site packages supply gi, Pillow and onnxruntime; the pins are what was validated on the phone.
clicker=/usr/local/lib/moto-clicker
[ -x "$clicker/venv/bin/python" ] || python3 -m venv --system-site-packages "$clicker/venv"
( [ -r /etc/profile.d/proxy.sh ] && . /etc/profile.d/proxy.sh
  "$clicker/venv/bin/python" -m pip install -q typesafe-sdk==0.6.0 anthropic==1.6.0 openai==2.54.0 rapidocr==3.9.2 )
rm -rf "$clicker/typesafe_computer_use" "$clicker/moto_clicker.py"
cp -r "$root/vendor/typesafe-computer-use/typesafe_computer_use" "$clicker/"
cp "$src/moto_clicker.py" "$clicker/"
find "$clicker" -path "$clicker/venv" -prune -o -name __pycache__ -prune -exec rm -rf {} +
install -m755 "$src/moto-clicker" /usr/local/bin/moto-clicker

# Codex MCP registration for the desktop user (idempotent).
user=${MOTO_USER:-$(getent passwd 1000 | cut -d: -f1)}
home=$(getent passwd "$user" | cut -d: -f6)
config="$home/.codex/config.toml"
if ! grep -q '^\[mcp_servers.moto-desktop\]' "$config" 2>/dev/null; then
    cat >> "$config" <<'TOML'

[mcp_servers.moto-desktop]
command = "/usr/local/bin/moto-cua"
args = ["mcp"]
startup_timeout_sec = 20
tool_timeout_sec = 320
TOML
    chown "$user" "$config"
fi
# Every new RemoteDesktop portal session (each start of this MCP server) popped
# up "Remote control session started" over the top of the windows being
# operated; desktop automation is its only user here (docs/60).
runuser -u "$user" -- env LC_ALL=C.UTF-8 kwriteconfig6 --file xdg-desktop-portal-kde.notifyrc \
    --group Event/remotedesktopstarted --key Action ''
runuser -u "$user" -- env XDG_RUNTIME_DIR="/run/user/$(id -u "$user")" kbuildsycoca6 >/dev/null 2>&1 || true
echo "Installed moto-cua and moto-clicker; restart Codex (moto-voice-agent) to load the MCP server."
