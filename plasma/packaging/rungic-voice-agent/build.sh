# rungic-voice-agent
V=$SRC/plasma/voice-agent
cmake -S "$V/app" -B "$V/app/build" -DCMAKE_BUILD_TYPE=RelWithDebInfo -DCMAKE_INSTALL_PREFIX=/usr -DCMAKE_CXX_FLAGS=-g1
cmake --build "$V/app/build" -j"${JOBS:-4}"
DESTDIR="$DESTDIR" cmake --install "$V/app/build"
install -Dm755 "$V/rungic_voice_agent.py" "$DESTDIR/usr/bin/rungic-voice-agent"
install -Dm644 "$V/call_proxy.py" "$DESTDIR/usr/lib/rungic-voice-agent/call_proxy.py"
for f in "$V"/prompts/*.md; do install -Dm644 "$f" "$DESTDIR/usr/share/rungic-voice-agent/prompts/$(basename "$f")"; done
for f in "$V"/skills/rungic-phone-desktop/*.md; do
    install -Dm644 "$f" "$DESTDIR/usr/share/rungic-voice-agent/skills/rungic-phone-desktop/$(basename "$f")"
done
install -Dm644 "$V/rungic-voice-agent.service" "$DESTDIR/usr/lib/systemd/user/rungic-voice-agent.service"
install -Dm644 "$V/rungic-voice-overlay.service" "$DESTDIR/usr/lib/systemd/user/rungic-voice-overlay.service"
install -Dm644 "$V/com.rungic.VoiceAgent.service" "$DESTDIR/usr/share/dbus-1/services/com.rungic.VoiceAgent.service"
install -Dm644 "$V/com.rungic.VoiceAssistant.service" "$DESTDIR/usr/share/dbus-1/services/com.rungic.VoiceAssistant.service"
install -Dm644 "$V/com.rungic.VoiceAssistant.desktop" "$DESTDIR/usr/share/applications/com.rungic.VoiceAssistant.desktop"
install -Dm644 "$V/kconf_update/rungic-voice-agent.upd" "$DESTDIR/usr/share/kconf_update/rungic-voice-agent.upd"
install -Dm755 "$V/kconf_update/rungic-codex-setup.sh" "$DESTDIR/usr/share/kconf_update/rungic-codex-setup.sh"
