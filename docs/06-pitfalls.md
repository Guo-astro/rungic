# 踩坑清单

按伤害排序。以后这台机再刷，先扫一遍。

## 1. 用 GSI 的 vbmeta 覆盖原厂 vbmeta

**症状：** `no valid operating system could be found`，槽位却仍是 bootable。

**原因：** Moto bootloader 要 OEM 签名的 vbmeta；`--disable-verity` 只改 flags，救不了错误的 key。

**处理：** 刷回 lolinet 抽出的 `stock/vbmeta.img` + `vbmeta_system.img`，带 disable 标志。

## 2. 把 DSU 的 8GiB 当成整机容量

**症状：** 设置里约 16GB。

**原因：** `KEY_USERDATA_SIZE` 默认 8GiB。原厂 userdata 还在。

**处理：** 要完整空间就永久刷 + wipe。不要在 DSU 里纠结扩容。

## 3. `fastboot fetch` 不存在

bootloader 和 fastbootd 都没有 `max-fetch-size`。不要写 “进 fastboot 把分区 dump 出来” 的脚本当唯一备份手段。没有 root 时备份 vbmeta/init_boot 只能靠官方包。

## 4. `fastboot -w` 在 fastbootd 不 format

userdata 类型被报成 `raw`：

```
Erase successful, but not automatically formatting.
File system type raw not supported.
wipe task partition not found: cache
```

本机首启会自己建文件系统。若卡 logo，再 `fastboot format:f2fs userdata`。没有 `cache` 分区是正常的。

## 5. 原 `system_a` 只有 1.1G

不删 `product_a`（7.1G）就刷 1.8G GSI 会失败。`product` 是 MYUI 应用和 overlay，GSI 不依赖它。`system_ext` 不要删。

## 6. raw ext4 的 “Invalid sparse file format”

不是镜像坏了。fastboot 会当 sparse 传，七片都 OKAY 就可以。

## 7. aria2 / 代理

- 直连 dl.google.com 极慢，开 IPv6 更慢 → `--disable-ipv6` + `http://127.0.0.1:8080`
- 这版静态 aria2 拒绝 `socks5://` 的 `--all-proxy`
- `--lowest-speed-limit` 会误杀慢速连接
- 自制 16 线程 Range 下载，中途改线程数会把已下分片作废

## 8. `_b` 槽当备份

`system_b` ≈ 190MB Virtual A/B 残片，`slot-successful:_b: no`。切 B 不会回到 MYUI。救砖 = 官方包或至少手里的 `stock/*.img`。

## 9. 自定义 recovery

没装 TWRP。这代 Virtual A/B + fastbootd，烂 recovery 比没 recovery 更危险。解锁后 fastbootd 足够删逻辑分区、刷 system。

## 10. Magisk 打错分区 / 打错版本

- 打 `boot` 没用，打 `init_boot`
- Android 17 用 Magisk 31.0，不要停在 30.7
- 刚开机 `su` 失败先等 `boot-complete`，再查 `/debug_ramdisk/su`
- 补丁失败就刷回 `dumps/stock/init_boot.img`，不必整包救

## 11. DSU sticky

`gsi_tool enable` 之后每次开机进 GSI。永久刷之前最好 `gsi_tool disable`。本次是靠 wipe userdata 把 DSU 镜像一起清掉的。

## 12. USB 调试授权会丢

进 DSU、wipe、换系统后都会再出 unauthorized。AOSP gadget 是 `22b8:2e81`，bootloader 是 `22b8:2e80`。线没插时 `lsusb` 完全没有摩托罗拉设备，别误判成驱动坏了。

## 13. 不要动的分区（再列一次）

`boot`、`vendor_boot`、`vendor`、`vendor_dlkm`、`system_dlkm`、`abl`、`xbl*`、`dtbo`、`modem`、`bluetooth`、`dsp`。GSI + Magisk 只需要：

- `system_a`（GSI）
- `vbmeta_a` / `vbmeta_system_a`（原厂 + disable）
- `init_boot_a`（Magisk）
- wipe `userdata` + `metadata`（只要完整空间时）
