# 官方 Android 17 GSI 与 DSU 试验

## 选哪张 GSI

用 **Google 官方 AOSP arm64 GSI**（vanilla，无 GMS），不是 PHH / Lineage GSI。

| 项 | 值 |
|---|---|
| 文件 | `aosp_arm64-exp-CP2A.260605.012-15430684-8e545e1e.zip` |
| 版本 | Android 17 / sdk 37 / `CP2A.260605.012` |
| 安全补丁 | 2026-06-05 |
| 官方 URL | https://dl.google.com/developers/android/cinnamonbun/images/gsi/aosp_arm64-exp-CP2A.260605.012-15430684-8e545e1e.zip |
| SHA-256 | `8e545e1e1e977c3b43b4e54a3af463f3e7d1c3177b120e772138334e15f48f75` |
| 包内容 | `system.img`（1904779264 字节 raw ext4）+ 4KB `vbmeta.img` + `build.prop` |
| 本地 | `~/a17-gsi/aosp_arm64-gsi.zip`、`~/a17-gsi/system.img` |

`system.img` 是 **raw ext4**，不是 sparse。`file` 会显示 `Linux rev 1.0 ext2 filesystem`。fastboot 刷它时会报 `Invalid sparse file format at header magic`，然后按 sparse 分片传，**这是正常的**，写入仍然 OKAY。

不要用包里那张 4KB `vbmeta.img` 去覆盖摩托罗拉 `vbmeta`（见 [04-permanent-gsi.md](04-permanent-gsi.md)）。

## 下载经验

`dl.google.com` 直连很慢（约 30–70KB/s），IPv6 尤其差。本机：

- `127.0.0.1:1080` 是 SOCKS5，约 27MB/s
- `127.0.0.1:8080` 是 HTTP 代理，约 10–26MB/s
- 系统没有发行版 aria2，用了静态二进制 `~/.local/bin/aria2c`（1.37.0）
- 这版 aria2 的 `--all-proxy=socks5://…` 会拒；要用 `http://127.0.0.1:8080`
- `--disable-ipv6` 必要
- `--lowest-speed-limit=1K` 曾经把慢连接直接掐死，不要开

成功的下法：

```bash
aria2c -c -x 8 -s 8 --file-allocation=none --disable-ipv6 \
  --all-proxy=http://127.0.0.1:8080 \
  -d ~/a17-gsi -o aosp_arm64-gsi.zip \
  'https://dl.google.com/developers/android/cinnamonbun/images/gsi/aosp_arm64-exp-CP2A.260605.012-15430684-8e545e1e.zip'
```

自己写 16 线程 Range 下载时，**线程数变了（16↔8）会导致分片错位**，文件损坏。要么固定分片方案续传，要么用 aria2 `-c`。

## 为什么先 DSU

当时约定：先 DSU 验证 GSI 能开机，**不刷自定义 recovery**（TWRP 更容易弄坏 fastbootd，而不是当救砖保险）。

DSU 优点：

- 不动 `super` 里的原厂 `system` / `product` / `vendor`
- 失败就禁用 DSU，重启回 MYUI
- 能完整验证显示、adb、开机动画

DSU 缺点：

- userdata 是单独划的一块，**不是** 256G
- 没有 root（官方 user GSI 无 PHH su）
- sticky 开启后每次开机还是进 GSI，直到 `gsi_tool disable` 或 wipe

## DSU 怎么装（已做过，可复现）

需要把 `system.img` gzip 后推进手机（gsid 吃 `.img.gz`）：

```bash
gzip -c ~/a17-gsi/system.img > ~/a17-gsi/system.img.gz
adb push ~/a17-gsi/system.img.gz /sdcard/Download/system.img.gz
adb shell gsi_tool install --gsi-file /sdcard/Download/system.img.gz
# 或用 gsid / DSU 侧载，并设置：
# KEY_USERDATA_SIZE 默认 8GiB
adb shell gsi_tool enable    # sticky
adb reboot
```

成功后：

- `gsi_tool status` → `running` / `installed` / `enabled`
- `ro.product.name=aosp_arm64`，`ro.build.id=CP2A.260605.012`
- 1080×2400 @ 120Hz 正常
- USB 会先变 unauthorized，再枚举成 AOSP gadget `22b8:2e81`，需要再点一次允许调试

## “设置里只有 16GB” 是什么

不是 UFS 坏了，也不是刷错分区。

DSU 的数据盘由 `KEY_USERDATA_SIZE` 控制，这次用的是默认 **8GiB**。`df /data` 看到 `7.9G`，设置里再算上系统大约显示成 16GB 机。

原厂 `userdata` 一直在，大约 222G，只是 DSU 没挂它当 `/data`。

要完整空间：**永久刷 GSI + `fastboot -w`（会清空 MYUI 数据）**。这是用户明确接受过的。
