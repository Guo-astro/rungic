#!/bin/sh
# Build and install the voice assistant inside the Plasma container (docs/59).
# Needs Qt6 (base, declarative, quickcontrols2) development files and CMake;
# Codex is installed separately under /usr/local/lib/codex (see docs/59).
set -eu
src=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
cmake -S "$src/app" -B "$src/app/build" -DCMAKE_BUILD_TYPE=Release -DCMAKE_INSTALL_PREFIX=/usr/local
cmake --build "$src/app/build" -j4
cmake --install "$src/app/build"
install -m755 "$src/moto_voice_agent.py" /usr/local/bin/moto-voice-agent
install -Dm644 "$src/call_proxy.py" /usr/local/lib/moto-voice-agent/call_proxy.py
install -d /usr/local/share/moto-voice-agent/prompts /usr/local/share/moto-voice-agent/skills/moto-phone-desktop
install -m644 "$src"/prompts/*.md /usr/local/share/moto-voice-agent/prompts/
install -m644 "$src/skills/moto-phone-desktop/SKILL.md" /usr/local/share/moto-voice-agent/skills/moto-phone-desktop/
install -m644 "$src/moto-voice-agent.service" /usr/lib/systemd/user/moto-voice-agent.service
install -m644 "$src/dev.moto.VoiceAgent.service" /usr/share/dbus-1/services/dev.moto.VoiceAgent.service
install -m644 "$src/dev.moto.VoiceAssistant.desktop" /usr/local/share/applications/dev.moto.VoiceAssistant.desktop
# Per user: the Codex skill (skills are read from ~/.codex/skills).
user_home=$(getent passwd 1000 | cut -d: -f6)
install -d -o 1000 -g 1000 "$user_home/.codex/skills"
ln -sfn /usr/local/share/moto-voice-agent/skills/moto-phone-desktop "$user_home/.codex/skills/moto-phone-desktop"
echo "Installed. Restart the service: systemctl --user restart moto-voice-agent"
