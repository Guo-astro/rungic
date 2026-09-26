#!/bin/sh
# SPDX-License-Identifier: MIT
# The desktop account across the Rungic rename (docs/70). Before it the home was /home/linux for any
# login, the primary group linux, and the login linux until the first-run account setup chose one.
# Now the home follows the login (/home/<login>; the account setup moves it with the login), the
# group is rungic, and the placeholder login rungic. /home lives on the Android side, outside the
# rootfs snapshot, so a rollback does not take it back:
#   rungic-rebrand-system up     the container init (plasma/init) before any service starts
#   rungic-rebrand-system down   tools/rungic_release.py, with the user's processes stopped, before a
#                                release from before the rename replaces this one
# /home/linux stays as a link to the home until phase D, for absolute paths in application data
# (databases, profiles) that the settings migration (rungic-rebrand-user) does not rewrite.
set -eu
uid=1000
getent passwd $uid >/dev/null || exit 0
login() { getent passwd $uid | cut -d: -f1; }
home() { getent passwd $uid | cut -d: -f6; }
group=$(getent group $uid | cut -d: -f1)
# The login is a placeholder only until the first-run account setup (plasma/account) chose one.
configured=no
grep -q '"configured": *true' /var/lib/moto-host/account.json 2>/dev/null && configured=yes

move_home() {   # to
    from=$(home) to=$1
    [ "$from" != "$to" ] && [ -d "$from" ] && [ ! -L "$from" ] || return 0
    [ ! -L "$to" ] || rm -f "$to"
    [ ! -e "$to" ] || { echo "rungic-rebrand-system: $to exists, the home stays $from" >&2; exit 1; }
    mv "$from" "$to"
    usermod -d "$to" "$(login)"
    echo "home: $from -> $to"
}

rename() {   # kind from to
    case $1 in
    group) [ "$group" = "$2" ] && ! getent group "$3" >/dev/null || return 0; groupmod -n "$3" "$2" ;;
    login) [ "$configured" = no ] && [ "$(login)" = "$2" ] && ! getent passwd "$3" >/dev/null || return 0
           usermod -l "$3" "$2" ;;
    esac
    echo "$1: $2 -> $3"
}

case "${1:-}" in
up)
    rename group linux rungic
    rename login linux rungic
    if [ "$(home)" = /home/linux ]; then
        move_home "/home/$(login)"
        [ -e /home/linux ] || [ -L /home/linux ] || ln -s "$(login)" /home/linux
    fi
    ;;
down)
    [ ! -L /home/linux ] || rm -f /home/linux
    move_home /home/linux
    rename login rungic linux
    rename group rungic linux
    ;;
*)
    echo "usage: rungic-rebrand-system up|down" >&2
    exit 2
    ;;
esac
