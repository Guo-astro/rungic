# Ubuntu 26.04 ships KPipeWire 6.6.4 with Plasma 6.6.5 and relaxes the upstream
# equal-version requirement by packaging patch. This shim does the same for
# local builds of vendored Plasma trees (tools/build_on_device.py targets mode):
#   --cmake-arg=-DKPipeWire_DIR=/root/rungic-build/cmake-shims/KPipeWire
include(/usr/lib/aarch64-linux-gnu/cmake/KPipeWire/KPipeWireConfig.cmake)
