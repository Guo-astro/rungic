#!/bin/sh
# Team run at a glance: units, statuses, the logs' last lines, memory.
R=$HOME/Projects/flappy-team-run; P=$HOME/Projects/flappy-team
echo "== $(date +%H:%M:%S) units: $(for r in godot art audio; do printf '%s=%s ' $r $(systemctl --user is-active team-$r.service); done)"
for r in godot art audio; do printf '%-6s %s\n' "$r" "$(head -1 $P/.team/$r.md 2>/dev/null || echo '(no status yet)')"; done
for r in godot art audio; do echo "-- $r log:"; grep -v '^\s*$' $R/$r.log 2>/dev/null | tail -4 | cut -c1-200; done
echo "-- memory: $(free -m | awk 'NR==2{print "used "$3" avail "$7" MiB"}'); memcg $(($(cat /dev/memcg/rungic-plasma/memory.usage_in_bytes 2>/dev/null || echo 0)/1048576)) MiB"
ps -eo rss=,comm= | sort -rn | awk '$2 ~ /godot|krita|ardour|codex|kwin_wayland|plasmashell|python3/ {printf "%s:%dM ", $2, $1/1024}' | cut -c1-400; echo
ls $P/art/export $P/audio/export $P/game 2>/dev/null | tr '\n' ' '; echo
