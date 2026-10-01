#!/bin/sh
# team-run N ROLE: one member of the Flappy Bird team (docs/research/91): `codex exec` with its commands
# and its desktop tools in agent workspace N, the role's prompt, the log in the run directory.
set -eu
N=$1 ROLE=$2
P=$HOME/Projects/flappy-team
R=$HOME/Projects/flappy-team-run
runtime=${XDG_RUNTIME_DIR:-/run/user/$(id -u)}
state=$HOME/.local/state/rungic-workspaces/$N
systemctl --user start --no-block rungic-workspace@$N.service
i=0; while [ $i -lt 100 ] && ! { [ -s "$state/bus" ] && [ -S "$runtime/wayland-ws-$N" ]; }; do sleep 0.2; i=$((i+1)); done
# Its tools must not take the user's assistant screen over (show_workspace): three would fight for it.
touch "$runtime/rungic-agent-screen-dismissed-$N"
# An agent at work here (rungic-agent-screen busy_marker): its keeper neither freezes nor closes it, its
# window's close button only hides it. Gone when this member ends.
touch "$runtime/rungic-workspace-$N.busy"
trap 'rm -f "$runtime/rungic-workspace-$N.busy"' EXIT
# The workspace's environment as a TOML inline table, for the MCP server and the shell (Codex starts
# MCP servers with a few variables only), as the voice agent's thread_settings() does.
envtoml=$(rungic-workspace-env "$N" python3 -c '
import json, os
keys = ["WAYLAND_DISPLAY", "DBUS_SESSION_BUS_ADDRESS", "RUNGIC_WORKSPACE", "QT_QPA_PLATFORM", "XDG_SESSION_TYPE",
        "XDG_CURRENT_DESKTOP", "PLASMA_INTEGRATION_USE_PORTAL", "KDE_FULL_SESSION", "KDE_SESSION_VERSION", "DISPLAY",
        "PULSE_SINK", "RUNGIC_USER_WAYLAND_DISPLAY", "RUNGIC_USER_DBUS_SESSION_BUS_ADDRESS",
        "RUNGIC_USER_PLASMA_INTEGRATION_USE_PORTAL", "RUNGIC_USER_QT_QPA_PLATFORMTHEME"]
env = {k: os.environ[k] for k in keys if k in os.environ}
env["QT_QPA_PLATFORMTHEME"] = ""
print("{" + ", ".join(f"{k} = {json.dumps(v)}" for k, v in env.items()) + "}")')
echo "$envtoml" > "$R/$ROLE.env"
prompt=$(cat "$R/prompt-common.md" "$R/prompt-$ROLE.md")
echo "== $(date -Is) start: workspace $N, role $ROLE" >> "$R/$ROLE.log"
rungic-workspace-env "$N" codex exec --dangerously-bypass-approvals-and-sandbox --skip-git-repo-check -C "$P" -c model_reasoning_effort=medium \
    -c "mcp_servers.rungic-desktop.env=$envtoml" -c "shell_environment_policy.set=$envtoml" \
    "$prompt" >> "$R/$ROLE.log" 2>&1
echo "== $(date -Is) end: $?" >> "$R/$ROLE.log"
