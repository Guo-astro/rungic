#!/bin/sh
# kconf_update script (moto.upd, Id=moto-usr-paths-v1): the project's programs moved from
# /usr/local to packages under /usr (docs/61). Point the user's settings that named the
# old paths at the new ones; values the user chose differently are left alone.
set -eu
old=/usr/local/share/applications/moto-plasma-rime.desktop
if [ "$(kreadconfig6 --file kwinrc --group Wayland --key InputMethod)" = "$old" ]; then
    kwriteconfig6 --file kwinrc --group Wayland --key InputMethod /usr/share/applications/moto-plasma-rime.desktop
fi
# A per-user copy of the portal override that started /usr/local/libexec/xdg-desktop-portal-kde;
# the packaged portal carries the change itself now.
dropin=${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user/plasma-xdg-desktop-portal-kde.service.d/moto.conf
if [ -f "$dropin" ] && grep -q '^ExecStart=/usr/local/libexec/xdg-desktop-portal-kde' "$dropin"; then
    rm -f "$dropin"
    rmdir "$(dirname "$dropin")" 2>/dev/null || true
fi
# Codex: the desktop MCP server and the phone-desktop skill moved with the packages.
codex=$HOME/.codex
if [ -f "$codex/config.toml" ]; then
    sed -i 's#^command = "/usr/local/bin/moto-cua"$#command = "/usr/bin/moto-cua"#' "$codex/config.toml"
fi
skill=$codex/skills/moto-phone-desktop
if [ -L "$skill" ] && [ "$(readlink "$skill")" = /usr/local/share/moto-voice-agent/skills/moto-phone-desktop ]; then
    ln -sfn /usr/share/moto-voice-agent/skills/moto-phone-desktop "$skill"
fi
# Units that were enabled for this user only, from their old /etc copies; the packages
# enable them for every user now (systemctl --global).
wants=${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user/plasma-workspace.target.wants
for unit in moto-plasma-display moto-plasma-brightness moto-plasma-media moto-plasma-clipboard; do
    link=$wants/$unit.service
    if [ -L "$link" ] && [ "$(readlink "$link")" = "/etc/systemd/user/$unit.service" ]; then
        rm -f "$link"
    fi
done
