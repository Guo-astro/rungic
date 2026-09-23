# 设备身份

## 型号

| 项 | 值 |
|---|---|
| 销售名 | Motorola moto g100s |
| SKU | XT2537-4 |
| 内部名 | `mumba` / `mumba_cn` |
| 序列号 | ZY32MVJS25 |
| 市场 | 国行（bootloader `radio: PRC`，固件频道 RETCN） |
| 生产日期（bootloader） | 2026-05-08 |
| 外壳 | PVT |

bootloader `product` 报 `mumba`，原厂 fingerprint 是 `motorola/mumba_cn/mumba`。

## 硬件

| 项 | 值 |
|---|---|
| SoC | Qualcomm SM6435（bootloader 写作 `SM_NETRANILITE`；平台常叫 parrot）Snapdragon 6s Gen 4 |
| GPU | Adreno 710 |
| RAM | 8GB LPDDR4x（SK hynix） |
| UFS | 256GB SK hynix H9QT1G6DN6X132 |
| 屏幕 | 1080×2400，120 / 90 / 60 / 30 Hz，约 390 dpi，圆角 59px |
| USB | Type-C **2.0** + OTG。gadget 在 AOSP 下是 `22b8:2e81`，bootloader 是 `22b8:2e80` |

### USB-C 外接显示器

**不支持。** 这是 USB 2.0 Type-C，没有 DisplayPort Alt Mode。DRM 只看到内置 `DSI-1` 和 `Virtual-1`，没有 DP/HDMI connector。OTG 外接 U 盘 / 键鼠可以，外接显示器不行。

## 原厂软件（刷 GSI 之前）

| 项 | 值 |
|---|---|
| 用户可见系统 | Android 16，MYUI 8 |
| vendor | Android 15 |
| 完整 fingerprint | `motorola/mumba_cn/mumba:15/WWAA36V.48-23-ST12.4/1c41a:user/release-keys` |
| bootloader | `MBM-3.0-mumba_cn-134d447f1e26-260413-WWAA36V.48-23-ST12.4-1c41a` |
| 基带 | `M6435_DE314_05.436.01.110R MUMBA_PVT_PRCDSDS_CUST` |
| kernel | GKI `6.6.87-android15-8-g3f57bfb65ab4-ab14067820-4k`（4K 页） |
| 官方包代号 | `W1WAA36.48-23-10`（与 bootloader 的 `WWAA36V.48-23-ST12.4` 是同一分支） |
| Treble | `ro.treble.enabled=true` |
| board API | 202404 |
| first_api | 36 |
| 解锁 | `securestate: flashing_unlocked`，verifiedboot `orange`，保修标记 `iswarrantyvoid: yes` |

## 分区形态

A/B + Virtual A/B，动态 `super`。

| 分区 | 大约大小 | 备注 |
|---|---|---|
| super | 0x364000000 ≈ 13.56 GiB | 组 `mot_dp_group_a/b` 上限各约 13.56 GiB |
| userdata | 0x3777EFB000 ≈ 222 GiB 可用文件系统 | UFS 256G 扣掉 super 等 |
| init_boot_{a,b} | 8 MiB | **Magisk 打这里**，不是 `boot` |
| boot_{a,b} | 96 MiB | GKI kernel，不要动 |
| vendor_boot_{a,b} | 96 MiB | 不要动 |
| vbmeta_{a,b} | 64 KiB | 必须刷**原厂** vbmeta + disable 标志 |
| vbmeta_system_{a,b} | 64 KiB | 同上 |
| metadata | 64 MiB | wipe 时一起擦 |

刷 GSI **之前** slot a 逻辑分区：

| 逻辑分区 | 大小 |
|---|---|
| product_a | 7.090 GiB（14869344 扇区） |
| system_a | 1.103 GiB（2313640 扇区）—— **装不下 1.8G GSI** |
| system_ext_a | 1.027 GiB |
| vendor_a | 0.950 GiB |
| vendor_dlkm_a | 21 MiB |
| system_dlkm_a | 7 MiB |
| system_b | ~190 MiB VAB 残片 |
| product_b 等 | 0 |

`product_a` 占了 super 里绝大部分空间。不删/缩小 `product`，GSI 刷不进去。

刷完之后 `product_a/b` 已删除，`system_a` 扩到 3 GiB 再被 fastboot 按镜像收缩，GSI 占用约 1.7G 的 `/`。`vendor` / `system_ext` / `*_dlkm` 仍是原厂。

## 物理分区节点（slot a）

```
boot_a          -> /dev/block/sdd22
init_boot_a     -> /dev/block/sdd23
vbmeta_a        -> /dev/block/sdd15
vbmeta_system_a -> /dev/block/sdd16
vendor_boot_a   -> /dev/block/sdd25
super           -> /dev/block/sde33
userdata        -> /dev/block/sde34
```

Magisk 选中的 preinit 设备是 `sde9`（metadata 一侧），日志里是 `/metadata/watchdog/magisk`。
