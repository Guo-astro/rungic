#!/bin/sh
# kconf_update script (rungic.upd, Id=rungic-firefox-launcher-v1): remove the per-user
# firefox.desktop that plasma/install-firefox-launcher.py wrote (it only redirected Exec to
# the codec wrapper, which rungic-firefox now installs as /usr/bin/firefox). A launcher the
# user wrote is left alone; one the old tool backed up is restored. The marker line and the
# backup name are what that tool wrote, before the Rungic rename (docs/70).
set -eu
dir=${XDG_DATA_HOME:-$HOME/.local/share}/applications
entry=$dir/firefox.desktop
[ -f "$entry" ] || exit 0
head -n1 "$entry" | grep -q '^# Moto: all desktop actions use the private-codec launch wrapper' || exit 0
if [ -f "$dir/firefox.desktop.pre-moto-launcher" ]; then
    mv "$dir/firefox.desktop.pre-moto-launcher" "$entry"
else
    rm -f "$entry"
fi
