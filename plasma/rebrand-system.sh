#!/bin/sh
# SPDX-License-Identifier: MIT
# The desktop account across the Rungic rename (docs/70): home /home/linux -> /home/rungic, its
# primary group linux -> rungic, and the placeholder login linux -> rungic (a login chosen at the
# first-run account setup stays). /home lives on the Android side, outside the rootfs snapshot, so
# a rollback does not take it back:
#   rungic-rebrand-system up     the container init (plasma/init) before any service starts
#   rungic-rebrand-system down   tools/rungic_release.py, with the user's processes stopped, before a
#                                release from before the rename replaces this one
# /home/linux stays as a link to the new home until phase D, for absolute paths in application
# data (databases, profiles) that the settings migration (rungic-rebrand-user) does not rewrite.
set -eu
uid=1000
entry=$(getent passwd $uid) || exit 0
login=${entry%%:*}
home=$(echo "$entry" | cut -d: -f6)
group=$(getent group $uid | cut -d: -f1)
# The login is a placeholder only until the first-run account setup (plasma/account) chose one.
configured=no
grep -q '"configured": *true' /var/lib/moto-host/account.json 2>/dev/null && configured=yes

rename_account() {   # from to
    from=$1 to=$2
    if [ "$home" = "/home/$from" ] && [ -d "/home/$from" ] && [ ! -L "/home/$from" ]; then
        [ ! -L "/home/$to" ] || rm -f "/home/$to"
        [ ! -e "/home/$to" ] || { echo "rungic-rebrand-system: /home/$to exists, /home/$from stays" >&2; exit 1; }
        mv "/home/$from" "/home/$to"
        usermod -d "/home/$to" "$login"
        echo "home: /home/$from -> /home/$to"
    fi
    if [ "$group" = "$from" ] && ! getent group "$to" >/dev/null; then
        groupmod -n "$to" "$from"
        echo "group: $from -> $to"
    fi
    if [ "$configured" = no ] && [ "$login" = "$from" ] && ! getent passwd "$to" >/dev/null; then
        usermod -l "$to" "$from"
        echo "placeholder login: $from -> $to"
    fi
}

case "${1:-}" in
up)
    rename_account linux rungic
    [ -e /home/linux ] || [ ! -d /home/rungic ] || ln -s rungic /home/linux
    ;;
down)
    [ ! -L /home/linux ] || rm -f /home/linux
    rename_account rungic linux
    ;;
*)
    echo "usage: rungic-rebrand-system up|down" >&2
    exit 2
    ;;
esac
