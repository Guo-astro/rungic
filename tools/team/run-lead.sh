#!/bin/sh
# Codex as the lead (docs/research/91 §12): one request, the team practice from the desktop skill (team.md).
R=~/Projects/flappy-lead-run
mkdir -p $R
systemctl --user start rungic-workspace@1.service
sleep 3
env=$(rungic-workspace-env 1 env | grep -E '^(WAYLAND_DISPLAY|DBUS_SESSION_BUS_ADDRESS|RUNGIC_WORKSPACE|DISPLAY|PULSE_SINK|XDG_CURRENT_DESKTOP|QT_QPA_PLATFORM|RUNGIC_USER_[A-Z_]*)=' \
      | sed 's/\\/\\\\/g; s/"/\\"/g; s/^\([^=]*\)=\(.*\)$/\1="\2"/' | paste -sd, -)
echo "== $(date -Iseconds) start" > $R/lead.log
cd ~ && rungic-workspace-env 1 codex exec --dangerously-bypass-approvals-and-sandbox --skip-git-repo-check -C ~ \
  -c model_reasoning_effort=medium \
  -c tools.update_plan.enabled=true \
  -c "mcp_servers.rungic-desktop.env={$env}" \
  -c "shell_environment_policy.set={$env}" \
  "$(cat $R/request.txt)" >> $R/lead.log 2>&1
echo "== $(date -Iseconds) end: $?" >> $R/lead.log
