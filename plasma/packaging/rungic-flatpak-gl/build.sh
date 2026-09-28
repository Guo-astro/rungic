# This project's Mesa (packages/mesa: KGSL for Freedreno, Zink and Turnip) as the Flatpak GL
# extension org.freedesktop.Platform.GL.rungic of the Freedesktop 25.08 runtimes (docs/49): the
# runtime's own GL.default has no KGSL driver and left Flatpak apps on llvmpipe. Runs in the
# Freedesktop SDK's container image ("image" in package.json): the extension must link against
# the runtime's libraries, not Ubuntu's. Same options as the system Mesa (plasma/mesa-meson-options)
# plus softpipe, the fallback of an app that is not given /dev/kgsl-3d0.
BRANCH=25.08
PREFIX=/usr/lib/aarch64-linux-gnu/GL/rungic
EXT=/var/lib/flatpak/extension/org.freedesktop.Platform.GL.rungic/aarch64/$BRANCH
BUILD=$DESTDIR/../flatpak-gl-build
# Mesa's build scripts need PyYAML, which the SDK does not have.
python3 -c 'import yaml' 2>/dev/null || python3 -m pip install -q --target "$BUILD-py" pyyaml
export PYTHONPATH=$BUILD-py
rm -rf "$BUILD"
# shellcheck disable=SC2046
meson setup "$BUILD" "$SRC/upstream/mesa" --prefix="$PREFIX" --libdir=lib \
  $(grep -v -e '^--prefix' -e '^--libdir' -e '^-Dgallium-drivers=' "$SRC/plasma/mesa-meson-options") \
  -Dgallium-drivers=freedreno,zink,softpipe
ninja -C "$BUILD" -j"${JOBS:-4}"
DESTDIR=$BUILD/root ninja -C "$BUILD" install
# The extension's directory is what Flatpak mounts at $PREFIX; the runtime merges the vendor
# files of glvnd/egl_vendor.d and vulkan/icd.d from there (its metadata, merge-dirs).
root=$DESTDIR$EXT
mkdir -p "$(dirname "$root")"
mv "$BUILD/root$PREFIX" "$root"
mkdir -p "$root/glvnd/egl_vendor.d" "$root/vulkan/icd.d"
sed "s#\"libEGL_mesa.so.0\"#\"$PREFIX/lib/libEGL_mesa.so.0\"#" "$root/share/glvnd/egl_vendor.d/50_mesa.json" \
  > "$root/glvnd/egl_vendor.d/10_rungic.json"
sed "s#\"library_path\": \"[^\"]*libvulkan_freedreno.so\"#\"library_path\": \"$PREFIX/lib/libvulkan_freedreno.so\"#" \
  "$root/share/vulkan/icd.d/freedreno_icd.aarch64.json" > "$root/vulkan/icd.d/rungic_freedreno_icd.aarch64.json"
rm -rf "$root/include" "$root/lib/pkgconfig" "$root/share/glvnd" "$root/share/vulkan" "$BUILD"
