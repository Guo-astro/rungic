# rungic-codex: the official release, checked against the pinned SHA256 (downloaded once into .work).
meta=$SRC/agent/codex/codex.json
version=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["version"])' "$meta")
url=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["url"])' "$meta")
sum=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["sha256"])' "$meta")
cache=$SRC/.work/cache/downloads
mkdir -p "$cache"
archive=$cache/codex-$version-$(basename "$url")
[ -s "$archive" ] || curl -fsSL --retry 3 -o "$archive.part" "$url" && { [ ! -f "$archive.part" ] || mv "$archive.part" "$archive"; }
echo "$sum  $archive" | sha256sum -c --quiet
lib=$DESTDIR/usr/lib/codex/$version
mkdir -p "$lib"
tar -xzf "$archive" -C "$lib" --no-same-owner
ln -s "$version" "$DESTDIR/usr/lib/codex/current"
install -Dm755 "$SRC/agent/codex/codex-wrapper" "$DESTDIR/usr/bin/codex"
