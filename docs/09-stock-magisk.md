# 原厂 MYUI + Magisk 可行性核验

核验日期：2026-09-22。结论：现有国行原厂 ROM 具备通过修补 `init_boot` 安装 Magisk 的条件；结合这台设备此前的 GSI root 记录，可行性高。本次没有连接到手机，没有进行修补、刷写或原厂系统上的启动验证。

## 固件与镜像证据

- 完整包：`~/XT2537-4_MUMBA_RETCN_16_W1WAA36.48-23-10_subsidy-DEFAULT_regulatory-DEFAULT_CFC.xml.zip`
- 已解压：`~/moto-stock-W1WAA36/`
- 包内 `.info.txt`：XT2537-4 / mumba_cn / Android 16 / `W1WAA36.48-23-10`。
- 原厂 fingerprint：`motorola/mumba_cn/mumba:16/W1WAA36.48-23-10/1c41a-29619:user/release-keys`。

| 镜像 | 本次实际解析结果 | 用途 |
|---|---|---|
| `init_boot.img` | 8,388,608 字节，header v4，kernel 0，ramdisk 2,455,313 字节，LZ4 legacy | Magisk 修补目标 |
| `boot.img` | 100,663,296 字节，header v4，kernel 36,456,960 字节，ramdisk 0 | 原厂内核 |
| `vbmeta.img` | 8,192 字节，AVB flags=0 | 原厂 AVB 元数据 |
| `vbmeta_system.img` | 4,096 字节，AVB flags=0 | 原厂系统 AVB 元数据 |

`boot`、`init_boot`、`vendor_boot`、`vbmeta`、`vbmeta_system` 的 MD5 均与包内 `flashfile.xml` 一致。另从完整 ZIP 读取 `init_boot.img`，确认与已解压文件逐字节一致；本次未校验整个 ZIP 的全部条目。

原厂 `init_boot.img` SHA-256：

```text
83ed46fdf155749ced60510a329663262095d2f60b23379a6100cbe55bb27789
```

它与 `~/a17-gsi/dumps/stock/init_boot.img` 完全一致。此前 [Magisk 记录](05-magisk-root.md) 记载使用这一原始镜像，在同一台手机的 GSI 环境下成功取得 Magisk 31.0 root。这支持镜像和硬件层面的可行性，但不能替代原厂 MYUI 上的实测。

## 手机状态的证据边界

历史 fastboot 日志记录 `securestate: flashing_unlocked` / `unlocked: yes`，当时当前槽为 a。

本次 `adb devices -l` 与 `fastboot devices` 均为空，所以当前系统版本、槽位、解锁状态和 root 状态未知。不能把 9 月 17 日的 README 状态当作今天的实机状态。

连接手机后先读取：

```bash
adb shell getprop ro.product.model
adb shell getprop ro.build.fingerprint
adb shell getprop ro.boot.flash.locked
adb shell getprop ro.boot.verifiedbootstate
adb shell getprop ro.boot.slot_suffix
```

这些是检查命令。如果指纹显示已升级到别的原厂版本，应重新取得对应版本的 `init_boot.img`；不能只凭型号一致使用旧镜像。

## 原厂系统上的推荐路径

1. 确认手机已解锁且当前固件与镜像匹配。
2. 在这台手机上安装官方 Magisk，用“选择并修补一个文件”修补 `~/moto-stock-W1WAA36/init_boot.img`。
3. 将新生成的补丁镜像拉回电脑，核对输出和当前槽位，再在 bootloader fastboot 中刷入该槽位的 `init_boot`。
4. 启动 MYUI，按 Magisk 应用提示完成环境设置，再用 `su -c id` 验证。

官方安装文档明确要求解锁，并在存在 `init_boot.img` 时使用它。修补应在目标手机上完成，不能因为拥有 APK 或旧补丁就认为原厂系统已经 root。

现有 `~/a17-gsi/dumps/magisk_patched_init_boot.img` 的 SHA-256 仍与历史记录一致：

```text
dc096154409aa9f011df3a800cfde67cf9690456dcab7752d4803ef368fe5b06
```

旧补丁是在 GSI 下以 `KEEPVERITY=false` 生成，当时还改过原厂 vbmeta 的验证标志。此次原厂 MYUI 方案应从干净镜像重新修补，让 Magisk 按当前设备环境处理，不能照搬旧 GSI 的全部步骤。原厂 `vbmeta` 先保留；是否需要额外调整 AVB，应根据实际启动结果判断。官方将禁用验证列为可选操作，并提示可能清数据。

若只改了 `init_boot` 后无法启动，在仍能进入 fastboot、且底包版本未改变的前提下，可向同一槽位刷回本包原厂 `init_boot.img`。

## 是否需要清数据

- 手机已运行匹配版本 MYUI 且已解锁：单独修补和刷入 `init_boot` 通常不需要清数据，流程中不应包含 `-w` 或 erase userdata。
- 手机仍是 GSI：恢复完整 MYUI 是另一项操作。现有 `~/moto-stock-W1WAA36/flash-official.sh` 明确会擦除 `userdata` 和 `metadata`，还会写入 bootloader、分区表、基带及完整 super。它不是只安装 Magisk 的脚本。
- 不应把历史 b 槽当作可直接切换的完整原厂备份，见 [恢复原厂笔记](07-restore-stock.md)。

## Magisk 版本与官方依据

截至本次查询，GitHub Latest 指向 v30.7，其说明包含 Android 16 QPR2 支持；v31.0 标记为预发布，增加 Android 17 支持。本地已有 v31.0 APK，其 SHA-256 与历史记录一致。原厂 Android 16 不需要仅因旧 GSI 使用 Android 17 而强制选择预发布版本。

- [Magisk 官方安装说明](https://topjohnwu.github.io/Magisk/install.html)
- [Magisk v30.7 发布说明](https://github.com/topjohnwu/Magisk/releases/tag/v30.7)
- [Magisk v31.0 发布说明](https://github.com/topjohnwu/Magisk/releases/tag/v31.0)
