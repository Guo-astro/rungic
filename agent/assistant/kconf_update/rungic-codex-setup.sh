#!/bin/sh
# kconf_update script (rungic-voice-agent.upd, Id=rungic-codex-v1). Idempotent.
set -eu
codex=$HOME/.codex
# The skill itself: rungic-voice-agent copies it to skills/rungic-phone-desktop, the user's to
# edit (the package's is the default; it was a link to it once).
mkdir -p "$codex/skills"
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
