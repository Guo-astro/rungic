# 永久刷入 Android 17 GSI

DSU 证明能开机之后，才动 `super`。目标：GSI 作为 slot a 的 `system`，`/data` 用完整 userdata。

## 正确步骤（救砖后的版本）

在 **fastbootd**（用户空间 fastboot）里改逻辑分区；vbmeta 在 **bootloader** 或 fastbootd 都能刷，但镜像必须是原厂的。

```bash
# 1. 进 fastbootd
adb reboot bootloader          # 或从 DSU/系统
fastboot reboot fastboot       # userspace，is-userspace: yes

# 2. 关掉 AVB（必须用原厂 vbmeta，禁止用 GSI 那张 4KB）
fastboot --disable-verity --disable-verification \
  flash vbmeta ~/a17-gsi/dumps/stock/vbmeta.img
fastboot --disable-verity --disable-verification \
  flash vbmeta_system ~/a17-gsi/dumps/stock/vbmeta_system.img

# 3. 给 system 腾地方（原 system_a 只有 1.1G，GSI 1.8G）
fastboot delete-logical-partition product_a
fastboot delete-logical-partition product_b
fastboot delete-logical-partition product_a-cow   # 有就删，没有会 OKAY/报错可忽略
fastboot delete-logical-partition product_b-cow

# 4. 扩 system 再刷
fastboot resize-logical-partition system_a 3221225472   # 3GiB
fastboot flash system_a ~/a17-gsi/system.img
# 刷写时会再 resize，并出现 Invalid sparse file format，属正常

# 5. 清空 userdata（否则仍可能挂到旧 MYUI/DSU 数据）
fastboot -w
# 这台机 fastbootd 把 userdata 类型报成 raw，-w 只会 erase 不会 format。
# 第一次开机 init 会自己格式化。若卡在 logo，再进 fastbootd：
#   fastboot format:f2fs userdata
#   fastboot erase metadata

# 6. 开机
fastboot --set-active=a
fastboot reboot
```

**不要刷：** `vendor`、`vendor_dlkm`、`boot`、`vendor_boot`、`init_boot`（root 另说）、`abl`、`xbl`、`dtbo`、`modem`。

**保留：** `system_ext_a`。DSU 时期带着摩托罗拉 `system_ext` 就能开机；缺的是空间，不是 system_ext。

刷完 `lpdump` 里不再有 `product_a`。`system_a` 可能裂成两段 extent（原位置 + 原 product 腾出来的空间），这是 lp 的正常现象。

## 实际操作时间线（2026-09-17）

1. 设备还在 DSU Android 17。bootloader **不支持** `fastboot fetch`（`max-fetch-size: not found`）。fastbootd 同样不支持。
2. 进 fastbootd，误用 **GSI zip 里的 4KB vbmeta** 加 disable 标志刷进 `vbmeta_a` / `vbmeta_system_a`。
3. 删除 `product_*`，`system_a` 扩到 `0xC0000000`（3GiB），`system.img` 七片刷入全部 OKAY。
4. `fastboot -w`：userdata / metadata erase 成功，但 `File system type raw not supported`，没有 format。
5. 重启 → bootloader 英文红字：**`no valid operating system could be found`**。
6. 从 lolinet 官方包抽出原厂 `vbmeta.img`（8KB）和 `vbmeta_system.img`（4KB），用同样的 disable 标志刷回。
7. 约 80 秒后 adb 回来：`aosp_arm64` / Android 17，`/data` **222G**。erase 后的 userdata 被首启格式化了，这一步反而不是砖因。

日志原文：`~/moto/.work/refs/permanent-flash.log`。

## 砖因：GSI vbmeta ≠ 摩托罗拉 vbmeta

现象：开机循环，bootloader 菜单上写 no valid operating system。槽位仍是：

- `slot-unbootable:_a: no`
- `slot-successful:_a: yes`
- `slot-retry-count:_a: 6`

所以不是 A/B 把槽打成 unbootable，是 **AVB 在加载任何 Android 之前就把镜像拒了**。

原因：

- 摩托罗拉 `vbmeta` 带 OEM 签名和 chained 描述符（boot / vendor / dtbo / init_boot …）。
- 官方 GSI 的 `vbmeta.img` 只有 4KB，算法是 Google 的 AVB key（本包 `algorithm_type=2`，flags 默认 0）。
- `fastboot --disable-verity --disable-verification flash vbmeta …` 只改 **这张镜像内部的 flags**。如果整张 blob 不是 OEM 签的，解锁后的 Moto bootloader **仍然可能直接判定没有合法 OS**。
- disable 标志只有写在 **原厂 vbmeta** 里才被承认。

错误示范（已经踩过）：

```bash
# 不要再这么干
fastboot --disable-verity --disable-verification \
  flash vbmeta ~/a17-gsi/dumps/vbmeta.img          # GSI 4KB
```

正确：

```bash
fastboot --disable-verity --disable-verification \
  flash vbmeta ~/a17-gsi/dumps/stock/vbmeta.img    # 原厂 8KB
fastboot --disable-verity --disable-verification \
  flash vbmeta_system ~/a17-gsi/dumps/stock/vbmeta_system.img
```

现场 `fastboot getvar verity-state` 在救砖后是 `disabled (0)`。

自制 `vbmeta-flags3.img`（把 GSI vbmeta 的 flags 改成 3）**没有**用来救机，也不该用。必须 OEM 签名那张。

## 进不了系统时怎么进 bootloader

那块 “no valid operating system” 屏幕本身就是 bootloader。

- USB 插上后应枚举 `22b8:2e80 Motorola PCS Fastboot mumba S`
- 音量键切 START / RESTART BOOTLOADER / RECOVERY / POWER OFF
- 线没插时电脑 `lsusb` 是空的，不像 adb 掉线那么含糊

## 空间账

`mot_dp_group_a` 上限 14558429184 字节。删掉 7.09G 的 `product_a` 之后，把 `system_a` 扩到 3GiB 完全放得下；即使扩到 ~12G 也还在组限额内。GSI 实际只需要 ~1.8G。

`fastboot flash system_a` 会按镜像再 resize 一次，最终 `/` 约 1.7G（`df` 1.6G 已用 / 48M 可用）。这不影响 `/data`。
