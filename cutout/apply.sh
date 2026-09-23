#!/system/bin/sh
# Register and enable the mumba punch-hole fabricated overlays.
# Must run as root after overlay manager is up.

XML="${1:-/data/adb/modules/mumba-cutout/overlay.xml}"

cmd overlay fabricate --target android --name MumbaCutout --file "$XML" || exit 1

# TYPE_INT_BOOLEAN = 0x12, true = 0xffffffff
cmd overlay fabricate --target android --name MumbaCutoutFill \
  android:bool/config_fillMainBuiltInDisplayCutout 0x12 0xffffffff || exit 1

# TYPE_DIMENSION = 0x05, 80px = (80 << 8) | UNIT_PX = 0x5000
cmd overlay fabricate --target android --name MumbaStatusBar \
  android:dimen/status_bar_height_portrait 0x05 0x5000 || exit 1

cmd overlay enable com.android.shell:MumbaCutout
cmd overlay enable com.android.shell:MumbaCutoutFill
cmd overlay enable com.android.shell:MumbaStatusBar
