#!/bin/sh
# Build/install inside the matching Ubuntu ARM64 Plasma container.
# Requires ECM, Qt6 declarative development files and KF6 CoreAddons,
# I18n/Notifications development files, Python GI/GStreamer/GTK4/libadwaita,
# GStreamer PulseAudio/PipeWire/libav plugins and the shared moto codec plugin.
set -eu
source_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
cmake -S "$source_dir" -B "$source_dir/build" -DCMAKE_BUILD_TYPE=Release
cmake --build "$source_dir/build" -j2
plugin=/usr/lib/aarch64-linux-gnu/qt6/qml/org/kde/plasma/quicksetting/record/librecordplugin.so
view=/usr/share/plasma/quicksettings/org.kde.plasma.quicksetting.record/contents/ui/main.qml
for target in "$plugin" "$view"; do
    if [ ! -f "$target.distrib" ]; then
        dpkg-divert --local --add --rename --divert "$target.distrib" "$target"
    fi
done
install -m644 "$source_dir/build/bin/org/kde/plasma/quicksetting/record/librecordplugin.so" "$plugin"
install -m644 "$source_dir/main.qml" "$view"
install -m755 "$source_dir/recorder.py" /usr/local/bin/moto-screen-recorder
install -m755 "$source_dir/settings.py" /usr/local/bin/moto-recording-settings
echo 'Installed. Reload plasmashell after any active recording has finished.'
