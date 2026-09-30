# rungic-codex: /usr/bin/codex only, which runs the user's official standalone Codex behind the
# proxy (docs/99). Codex itself is no longer part of the system: Settings installs and updates it.
install -Dm755 "$SRC/agent/codex/codex-wrapper" "$DESTDIR/usr/bin/codex"
