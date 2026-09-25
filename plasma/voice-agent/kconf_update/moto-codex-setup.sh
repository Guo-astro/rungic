#!/bin/sh
# kconf_update script (moto-voice-agent.upd, Id=moto-codex-v1). Idempotent.
set -eu
codex=$HOME/.codex
mkdir -p "$codex/skills"
[ -e "$codex/skills/moto-phone-desktop" ] || \
    ln -s /usr/share/moto-voice-agent/skills/moto-phone-desktop "$codex/skills/moto-phone-desktop"
config=$codex/config.toml
if ! grep -q '^\[mcp_servers.moto-desktop\]' "$config" 2>/dev/null; then
    cat >> "$config" <<'TOML'

[mcp_servers.moto-desktop]
command = "/usr/bin/moto-cua"
args = ["mcp"]
startup_timeout_sec = 20
tool_timeout_sec = 320
TOML
fi
