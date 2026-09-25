# moto-voice-agent
V=$SRC/plasma/voice-agent
cmake -S "$V/app" -B "$V/app/build" -DCMAKE_BUILD_TYPE=RelWithDebInfo -DCMAKE_INSTALL_PREFIX=/usr -DCMAKE_CXX_FLAGS=-g1
cmake --build "$V/app/build" -j"${JOBS:-4}"
DESTDIR="$DESTDIR" cmake --install "$V/app/build"
install -Dm755 "$V/moto_voice_agent.py" "$DESTDIR/usr/bin/moto-voice-agent"
install -Dm644 "$V/call_proxy.py" "$DESTDIR/usr/lib/moto-voice-agent/call_proxy.py"
for f in "$V"/prompts/*.md; do install -Dm644 "$f" "$DESTDIR/usr/share/moto-voice-agent/prompts/$(basename "$f")"; done
for f in "$V"/skills/moto-phone-desktop/*.md; do
    install -Dm644 "$f" "$DESTDIR/usr/share/moto-voice-agent/skills/moto-phone-desktop/$(basename "$f")"
done
install -Dm644 "$V/moto-voice-agent.service" "$DESTDIR/usr/lib/systemd/user/moto-voice-agent.service"
install -Dm644 "$V/moto-voice-overlay.service" "$DESTDIR/usr/lib/systemd/user/moto-voice-overlay.service"
install -Dm644 "$V/dev.moto.VoiceAgent.service" "$DESTDIR/usr/share/dbus-1/services/dev.moto.VoiceAgent.service"
install -Dm644 "$V/dev.moto.VoiceAssistant.service" "$DESTDIR/usr/share/dbus-1/services/dev.moto.VoiceAssistant.service"
install -Dm644 "$V/dev.moto.VoiceAssistant.desktop" "$DESTDIR/usr/share/applications/dev.moto.VoiceAssistant.desktop"
install -Dm644 "$V/kconf_update/moto-voice-agent.upd" "$DESTDIR/usr/share/kconf_update/moto-voice-agent.upd"
install -Dm755 "$V/kconf_update/moto-codex-setup.sh" "$DESTDIR/usr/share/kconf_update/moto-codex-setup.sh"
