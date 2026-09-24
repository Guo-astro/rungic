#!/bin/sh
# Install moto-cua (run as root in the container from a copy of the repository
# tree: plasma/cua and vendor/arc-cua side by side under $1, default the parent
# of this script's directory). Registers the MCP server for the desktop user's Codex.
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
echo "Installed moto-cua; restart Codex (moto-voice-agent) to load the MCP server."
