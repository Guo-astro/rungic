#!/bin/sh
# Install inside the Plasma container as root. Requires python3 (3.14, for
# compression.zstd) and gdb. See docs/55-agent-native-debugging.md.
set -eu
src=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
install -Dm644 "$src/60-moto-core.conf" /etc/systemd/system.conf.d/60-moto-core.conf
install -Dm644 "$src/60-moto-core.conf" /etc/systemd/user.conf.d/60-moto-core.conf
install -Dm644 "$src/moto-coredump.tmpfiles" /etc/tmpfiles.d/moto-coredump.conf
install -Dm644 "$src/moto-coredump.path" /etc/systemd/system/moto-coredump.path
install -Dm644 "$src/moto-coredump.service" /etc/systemd/system/moto-coredump.service
install -Dm755 "$src/moto-coredump-collect" /usr/local/libexec/moto-coredump-collect
install -Dm755 "$src/moto-crash-symbols" /usr/local/bin/moto-crash-symbols
install -Dm644 "$src/../config/etc/apt/moto-ddebs.sources" /etc/apt/moto-ddebs.sources
# systemd-coredump (for coredumpctl) must never set Android's global core_pattern.
ln -sfn /dev/null /etc/sysctl.d/50-coredump.conf
install -Dm755 "$src/moto-a11y" /usr/local/bin/moto-a11y
install -Dm755 "$src/moto-fs-audit" /usr/local/bin/moto-fs-audit
install -Dm755 "$src/moto-integrity" /usr/local/bin/moto-integrity
install -Dm644 "$src/moto-local-config.json" /usr/share/moto/local-config.json
install -Dm644 "$src/moto-plasma-session.service" /etc/systemd/system/moto-plasma-session.service
install -Dm644 "$src/sys-kernel-tracing.conf" /etc/systemd/system/sys-kernel-tracing.mount.d/60-moto.conf
systemd-tmpfiles --create /etc/tmpfiles.d/moto-coredump.conf
# Managers read DefaultLimitCORE only at (re)exec; running services keep their limits.
systemctl daemon-reexec
runuser -u "$(getent passwd 1000 | cut -d: -f1)" -- env XDG_RUNTIME_DIR=/run/user/1000 systemctl --user daemon-reexec || true
systemctl enable --now moto-coredump.path
systemctl start sys-kernel-tracing.mount
echo 'Installed. Restart the desktop session to apply the core limit and journal output to it.'
