#!/system/bin/sh
# Shared by firstboot and the development deployer; preserves receiver/lease state.
set -eu
DEST=/data/adb/rungic-wfd
SERVICES=/data/adb/service.d
healthy() {
    [ -f "$DEST/SHA256SUMS" ] || return 1
    (cd "$DEST" && sha256sum -c SHA256SUMS >/dev/null 2>&1) || return 1
    for script in rungic-cast-watch.sh rungic-wfd-sepolicy.sh; do
        cmp -s "$DEST/service.d/$script" "$SERVICES/$script" || return 1
    done
    [ -x "$DEST/rungic-cast" ] && [ -x "$SERVICES/rungic-cast-watch.sh" ]
}
if [ "${1:-}" = --check ]; then healthy; exit; fi
SOURCE=$1
(cd "$SOURCE" && sha256sum -c SHA256SUMS >/dev/null) || exit 1
for file in rungic-cast rungic-cast.jar adapters.json install.sh service.d/rungic-cast-watch.sh service.d/rungic-wfd-sepolicy.sh; do
    [ -s "$SOURCE/$file" ] || exit 1
done
if cmp -s "$SOURCE/SHA256SUMS" "$DEST/SHA256SUMS" && healthy; then
    echo 'casting already healthy'
    exit 0
fi
mkdir -p "$DEST" "$DEST/service.d" "$SERVICES"
# Each file is replaced atomically; publishing the manifest last makes interrupted
# updates unhealthy and repairable. Mutable session/receiver data is never copied.
while read -r digest relative; do
    case "$relative" in
        rungic-cast|rungic-cast.jar|rungic-cast-watch|adapters.json|wfd.sepolicy.rule|install.sh|service.d/rungic-cast-watch.sh|service.d/rungic-wfd-sepolicy.sh) ;;
        *) echo "unexpected cast payload: $relative" >&2; exit 1 ;;
    esac
    cp -p "$SOURCE/$relative" "$DEST/$relative.new"
    mv "$DEST/$relative.new" "$DEST/$relative"
done < "$SOURCE/SHA256SUMS"
restorecon -RF "$DEST" >/dev/null 2>&1 || true
for script in rungic-cast-watch.sh rungic-wfd-sepolicy.sh; do
    cp -p "$DEST/service.d/$script" "$SERVICES/$script.new"
    chcon u:object_r:adb_data_file:s0 "$SERVICES/$script.new"
    mv "$SERVICES/$script.new" "$SERVICES/$script"
done
cp "$SOURCE/SHA256SUMS" "$DEST/SHA256SUMS.new"
mv "$DEST/SHA256SUMS.new" "$DEST/SHA256SUMS"
healthy
echo 'casting installed'
