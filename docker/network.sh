#!/system/bin/sh
# Android policy-routing adapter for this Docker installation.
set -eu
export PATH=/product/bin:/system/bin:/system/xbin:/vendor/bin
BASE=/data/adb/moto-docker
CIDR=172.30.0.0/16
FWD=MOTO_DOCKER_FWD
NAT=MOTO_DOCKER_NAT

case ${1:-up} in
    up|ensure)
        route=$(ip -4 route get 1.1.1.1)
        wan=$(printf '%s\n' "$route" | awk '{for(i=1;i<NF;i++) if($i=="dev") {print $(i+1); exit}}')
        table=$(printf '%s\n' "$route" | awk '{for(i=1;i<NF;i++) if($i=="table") {print $(i+1); exit}}')
        [ -n "$table" ] || table=main
        case "$wan:$table" in *[!a-zA-Z0-9_.:-]*|:*) echo 'Invalid uplink' >&2; exit 1;; esac
        if [ "${1:-up}" = ensure ] &&
           [ "$(cat "$BASE/network.interface" 2>/dev/null)" = "$wan" ] &&
           [ "$(cat "$BASE/network.table" 2>/dev/null)" = "$table" ] &&
           [ "$(cat /proc/sys/net/ipv4/ip_forward)" = 1 ] &&
           ip -4 rule show | grep -q "9000:.*to $CIDR lookup main" &&
           ip -4 rule show | grep -q "9010:.*from $CIDR lookup $table" &&
           iptables -w 5 -C FORWARD -j "$FWD" 2>/dev/null &&
           iptables -w 5 -t nat -C POSTROUTING -j "$NAT" 2>/dev/null; then
            exit 0
        fi
        if [ ! -e "$BASE/ip-forward.before" ]; then
            cat /proc/sys/net/ipv4/ip_forward > "$BASE/ip-forward.before"
        fi
        echo 1 > /proc/sys/net/ipv4/ip_forward
        # These priorities and selectors belong exclusively to this adapter.
        ip -4 rule show | grep -q "9000:.*to $CIDR lookup main" ||
            ip -4 rule add pref 9000 to "$CIDR" lookup main
        if ! ip -4 rule show | grep -q "9010:.*from $CIDR lookup $table"; then
            old_table=$(cat "$BASE/network.table" 2>/dev/null || true)
            if [ -n "$old_table" ]; then
                ip -4 rule del pref 9010 from "$CIDR" lookup "$old_table" 2>/dev/null || true
            fi
            ip -4 rule add pref 9010 from "$CIDR" lookup "$table"
        fi
        printf '%s\n' "$table" > "$BASE/network.table"
        iptables -w 5 -N "$FWD" 2>/dev/null || true
        iptables -w 5 -F "$FWD"
        iptables -w 5 -A "$FWD" -s "$CIDR" -o "$wan" -j ACCEPT
        iptables -w 5 -A "$FWD" -d "$CIDR" -i "$wan" -m conntrack --ctstate RELATED,ESTABLISHED -j ACCEPT
        iptables -w 5 -C FORWARD -j "$FWD" 2>/dev/null || iptables -w 5 -I FORWARD 1 -j "$FWD"
        iptables -w 5 -t nat -N "$NAT" 2>/dev/null || true
        iptables -w 5 -t nat -F "$NAT"
        iptables -w 5 -t nat -A "$NAT" -s "$CIDR" -o "$wan" -j MASQUERADE
        iptables -w 5 -t nat -C POSTROUTING -j "$NAT" 2>/dev/null ||
            iptables -w 5 -t nat -I POSTROUTING 1 -j "$NAT"
        printf '%s\n' "$wan" > "$BASE/network.interface"
        echo "Docker uplink: $wan (table $table)"
        ;;
    down)
        iptables -w 5 -D FORWARD -j "$FWD" 2>/dev/null || true
        iptables -w 5 -F "$FWD" 2>/dev/null || true
        iptables -w 5 -X "$FWD" 2>/dev/null || true
        iptables -w 5 -t nat -D POSTROUTING -j "$NAT" 2>/dev/null || true
        iptables -w 5 -t nat -F "$NAT" 2>/dev/null || true
        iptables -w 5 -t nat -X "$NAT" 2>/dev/null || true
        ip -4 rule del pref 9000 to "$CIDR" lookup main 2>/dev/null || true
        table=$(cat "$BASE/network.table" 2>/dev/null || true)
        if [ -n "$table" ]; then ip -4 rule del pref 9010 from "$CIDR" lookup "$table" 2>/dev/null || true; fi
        # Leave the shared forwarding switch to Android; another service may
        # have enabled tethering since Docker started. No Android chain is flushed.
        ;;
    *) echo 'Usage: network.sh {up|down}' >&2; exit 2;;
esac
