# 命令速查

## 状态

```bash
adb devices -l
adb shell getprop ro.build.id
adb shell getprop ro.build.version.release
adb shell getprop ro.boot.slot_suffix
adb shell getprop ro.boot.dynamic_system
adb shell df -h /data /system
adb shell su -c 'id; magisk -v; getenforce'
adb shell su -c lpdump
```

## 进 bootloader / fastbootd

```bash
adb reboot bootloader          # 0x22b8:2e80
fastboot devices
fastboot getvar is-userspace   # no = bootloader
fastboot reboot fastboot       # yes = fastbootd，才能改逻辑分区
```

音量减 + 电源也能进 bootloader。

## 再刷 GSI（已有镜像时）

```bash
STOCK=~/a17-gsi/dumps/stock
GSI=~/a17-gsi/system.img

fastboot reboot fastboot
fastboot --disable-verity --disable-verification flash vbmeta "$STOCK/vbmeta.img"
fastboot --disable-verity --disable-verification flash vbmeta_system "$STOCK/vbmeta_system.img"
fastboot delete-logical-partition product_a || true
fastboot delete-logical-partition product_b || true
fastboot resize-logical-partition system_a 3221225472
fastboot flash system_a "$GSI"
fastboot -w
fastboot --set-active=a
fastboot reboot
```

## Magisk

```bash
# 刷补丁
fastboot flash init_boot ~/a17-gsi/dumps/magisk_patched_init_boot.img

# 撤补丁
fastboot flash init_boot ~/a17-gsi/dumps/stock/init_boot.img
```

## 从官方大包抽文件

```bash
python3 ~/moto/tools/remote_zip_extract.py \
  --url 'https://mirrors.lolinet.com/firmware/lenomola/2026/mumba_retcn/official/RETCN/XT2537-4_MUMBA_RETCN_16_W1WAA36.48-23-10_subsidy-DEFAULT_regulatory-DEFAULT_CFC.xml.zip' \
  --out /tmp/mumba-stock \
  vbmeta.img vbmeta_system.img init_boot.img boot.img
```

lolinet 支持 `Accept-Ranges: bytes`，不必走代理。`dl.google.com` 才需要 `http://127.0.0.1:8080`。

## 下载官方 GSI

```bash
aria2c -c -x 8 -s 8 --file-allocation=none --disable-ipv6 \
  --all-proxy=http://127.0.0.1:8080 \
  -d ~/a17-gsi -o aosp_arm64-gsi.zip \
  'https://dl.google.com/developers/android/cinnamonbun/images/gsi/aosp_arm64-exp-CP2A.260605.012-15430684-8e545e1e.zip'
sha256sum ~/a17-gsi/aosp_arm64-gsi.zip
# 8e545e1e1e977c3b43b4e54a3af463f3e7d1c3177b120e772138334e15f48f75
```

## DSU（仅试验，不给满存储）

```bash
gzip -c ~/a17-gsi/system.img > ~/a17-gsi/system.img.gz
adb push ~/a17-gsi/system.img.gz /sdcard/Download/system.img.gz
adb shell gsi_tool status
adb shell gsi_tool disable     # 下次开机回 super 里的系统
```

## 救 “no valid operating system”

确认 USB 是 fastboot：

```bash
fastboot --disable-verity --disable-verification \
  flash vbmeta ~/a17-gsi/dumps/stock/vbmeta.img
fastboot --disable-verity --disable-verification \
  flash vbmeta_system ~/a17-gsi/dumps/stock/vbmeta_system.img
fastboot --set-active=a
fastboot reboot
```
