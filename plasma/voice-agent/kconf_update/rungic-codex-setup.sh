#!/bin/sh
# kconf_update script (rungic-voice-agent.upd, Id=rungic-codex-v1). Idempotent.
set -eu
codex=$HOME/.codex
mkdir -p "$codex/skills"
[ -e "$codex/skills/rungic-phone-desktop" ] || \
    ln -s /usr/share/rungic-voice-agent/skills/rungic-phone-desktop "$codex/skills/rungic-phone-desktop"
config=$codex/config.toml
if ! grep -q '^\[mcp_servers.rungic-desktop\]' "$config" 2>/dev/null; then
    cat >> "$config" <<'TOML'

[mcp_servers.rungic-desktop]
command = "/usr/bin/rungic-cua"
args = ["mcp"]
startup_timeout_sec = 20
tool_timeout_sec = 320
TOML
fi
