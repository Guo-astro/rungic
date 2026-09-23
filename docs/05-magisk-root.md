# Magisk root（init_boot）

这台是 GKI 设备：**打 `init_boot`，不要打 `boot`。** 官方 user GSI 没有 PHH `su`。

## 版本

用 **Magisk v31.0**（pre-release，但 changelog 写明 Zygisk 支持 Android 17 / API 37）。GitHub “Latest” 当时还停在 v30.7，那版只声明到 Android 16 QPR2。

- APK：`~/a17-gsi/magisk/Magisk-v31.0.apk`
- SHA-256：`2c8a488b9a5293e578e95ae4f07e3c57aba4feec4a52ca4dd852a2692d6dd4e8`
- 安装后 `versionName=31.0`，`versionCode=31000`，`targetSdk=37`

## 原厂 init_boot 从哪来

设备 **不能** `fastboot fetch`。未 root 时也不能 `dd` `/dev/block/by-name/init_boot_a`。

从 lolinet 官方包抽，版本必须对应当时底包：

```
XT2537-4_MUMBA_RETCN_16_W1WAA36.48-23-10_subsidy-DEFAULT_regulatory-DEFAULT_CFC.xml.zip
https://mirrors.lolinet.com/firmware/lenomola/2026/mumba_retcn/official/RETCN/
```

约 9.8GB，但 zip 里是独立 img，不是单一 payload.bin。用 HTTP Range 只拉需要的文件：

```bash
python3 ~/moto/tools/remote_zip_extract.py \
  --url 'https://mirrors.lolinet.com/firmware/lenomola/2026/mumba_retcn/official/RETCN/XT2537-4_MUMBA_RETCN_16_W1WAA36.48-23-10_subsidy-DEFAULT_regulatory-DEFAULT_CFC.xml.zip' \
  --out ~/a17-gsi/dumps/stock \
  vbmeta.img vbmeta_system.img init_boot.img boot.img
```

抽出的原厂文件：

| 文件 | 大小 | SHA-256 |
|---|---|---|
| `init_boot.img` | 8388608 | `83ed46fdf155749ced60510a329663262095d2f60b23379a6100cbe55bb27789` |
| `boot.img` | 100663296 | （备份，未刷） |
| `vbmeta.img` | 8192 | AVB0，OEM |
| `vbmeta_system.img` | 4096 | AVB0，OEM |

`init_boot` 头：HEADER_VER 4，KERNEL_SZ 0，RAMDISK lz4_legacy，PAGESIZE 4096。符合 “只 ramdisk、kernel 在 boot” 的 GKI 布局。

国行走 `mumba_retcn`，不是 `mumba/` 下面的国际版。

## 在手机上修补（不需要先有 root）

Magisk 的 `boot_patch.sh` 可以在未 root 的 AOSP 里跑。GSI 已经能开机后：

```bash
WORKDIR=~/a17-gsi/magisk/patch
mkdir -p "$WORKDIR" && cd "$WORKDIR"
unzip -o ~/a17-gsi/magisk/Magisk-v31.0.apk \
  assets/boot_patch.sh assets/util_functions.sh assets/stub.apk \
  'lib/arm64-v8a/*'
cp assets/boot_patch.sh assets/util_functions.sh assets/stub.apk .
cp lib/arm64-v8a/libmagiskboot.so magiskboot
cp lib/arm64-v8a/libmagiskinit.so magiskinit
cp lib/arm64-v8a/libmagisk.so magisk
cp lib/arm64-v8a/libinit-ld.so init-ld
chmod 755 magiskboot magiskinit magisk init-ld boot_patch.sh

adb install -r ~/a17-gsi/magisk/Magisk-v31.0.apk
adb push "$WORKDIR" /data/local/tmp/magiskpatch
adb push ~/a17-gsi/dumps/stock/init_boot.img /data/local/tmp/init_boot.img

adb shell 'cd /data/local/tmp/magiskpatch && \
  KEEPVERITY=false KEEPFORCEENCRYPT=true PATCHVBMETAFLAG=false \
  sh ./boot_patch.sh /data/local/tmp/init_boot.img'

adb pull /data/local/tmp/magiskpatch/new-boot.img \
  ~/a17-gsi/dumps/magisk_patched_init_boot.img
```

当时脚本输出要点：

- Stock boot image detected
- Pre-init storage partition: **sde9**
- KEEPVERITY=false KEEPFORCEENCRYPT=true
- 打好的镜像仍是 8.0M Android bootimg

`PATCHVBMETAFLAG=false`：vbmeta 已经在 fastboot 侧关过 verity，不要让 Magisk 再改 vbmeta。

## 刷入

在 **bootloader**（不是必须 fastbootd）刷物理分区：

```bash
adb reboot bootloader
fastboot flash init_boot ~/a17-gsi/dumps/magisk_patched_init_boot.img
# 当前槽是 a 时等价于 init_boot_a
fastboot reboot
```

**不要** `-w`。Magisk 不需要再清数据。

补丁镜像 SHA-256：`dc096154409aa9f011df3a800cfde67cf9690456dcab7752d4803ef368fe5b06`

若 Magisk 导致无法开机，刷回原厂即可：

```bash
fastboot flash init_boot ~/a17-gsi/dumps/stock/init_boot.img
```

## 验证

开机后等十几秒（Magisk 要等到 `boot-complete`）：

```
I Magisk: ** boot-complete triggered
I Magisk: * Found preinit dir: /metadata/watchdog/magisk
```

```bash
adb shell su -c 'id; magisk -v'
# uid=0(root) ... context=u:r:magisk:s0
# 31.0:MAGISK:R
```

二进制在 `/debug_ramdisk/magisk`，`su -> ./magisk`。PATH 里 `/system_ext/bin` 比 `/system/bin` 靠前，本机 Magisk 也挂到了 `/system_ext/bin/su`。刚开机那几十秒 `adb shell su` 可能失败，属于还没 post-fs-data 完，不是没 root。

SELinux 仍是 Enforcing。`magisk --path` → `/debug_ramdisk`。

桌面 Magisk 应用已安装。若弹出 Additional Setup，在应用里做完再重启一次。

## 不要用的替代方案

| 方案 | 原因 |
|---|---|
| 打 `boot.img` | GKI 的 ramdisk 不在 boot 里，打了也没 su |
| KernelSU 通用 GKI boot | 必须精确匹配 `6.6.87-android15` 4K；错版本会丢厂商模块 |
| PHH su | 这是官方 AOSP GSI，没有 |
| 自制空 vbmeta 当 root | 与 root 无关，而且会再次触发 “no valid OS” |
