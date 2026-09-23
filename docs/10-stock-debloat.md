# 原厂固件精简版：W1WAA36.48-23-10

2026-09-22 离线制作。固件目录：`~/moto-clean-W1WAA36/package/`。

**后续实机发现：v1 的 `super.img` 被 Motorola bootloader 以不支持的格式拒绝。安装改走匹配原厂底包上的 fastbootd + `product_a` 路径，见 [实机安装记录](11-stock-install.md)。以下为离线构建记录，不能作为直接运行 v1 XML 的依据。**

基于国行 XT2537-4 / mumba_cn / RETCN Android 16 原厂包，删除明确列出的第三方预装应用。原始 ZIP 和 `~/moto-stock-W1WAA36/` 保留原样。

## 删除清单

以下 15 个应用的整个 `/product/preinstall/<目录>` 已从重建镜像中移除，包括 APK 和该目录内的库文件：

| 应用 | APK manifest 中的包名 |
|---|---|
| 高德地图 | `com.autonavi.minimap` |
| 百度 | `com.baidu.searchbox` |
| 星小辰 | `com.teleagi.xxc` |
| 抖音 | `com.ss.android.ugc.aweme` |
| 番茄小说 | `com.dragon.read` |
| 爱奇艺 | `com.qiyi.video` |
| 快手 | `com.smile.gifmaker` |
| 美图秀秀 | `com.mt.mtxx.mtxx` |
| 网易云音乐 | `com.netease.cloudmusic` |
| 今日头条 | `com.ss.android.article.news` |
| QQ 音乐 | `com.tencent.qqmusic` |
| 小红书 | `com.xingin.xhs` |
| 微博 | `com.sina.weibo` |
| 优酷 | `com.youku.phone` |
| 哔哩哔哩 | `tv.danmaku.bili` |

同时删除两个专用预装配置：

- `/product/etc/packagemanager/preinstall-CT_XCC.xml`
- `/product/etc/preinstall/lenovo_aweme_183_pre_install.config`

应用目录内共移除 3,193,334,693 字节的普通文件（约 2.97 GiB）；这不是 userdata 增加量。完整路径与体积见包内 `removed-apps.json`。

## 本轮保留的功能

默认按“删除第三方推广应用，保留系统功能”实施。搜狗输入法、最美天气及百度网络定位服务保留，避免未确认替代方案时影响中文输入、天气和定位；WebView、Google 服务、支付/通信组件也保留。

摩托罗拉/联想的相册、相机、电话、短信、录音、闹钟、桌面、钱包、杜比、应用商店、游戏模式、联想社区、想帮帮等在本轮保留。没有按包名中包含 `google`、`baidu`、`lenovo` 等字符串批量删除。

保留的应用商店/初始化向导可能提供联网推荐或再次下载应用；本轮未修改这些应用的行为，也未实测联网首启。用户后来自行安装的相同应用不会被此镜像主动卸载。

## 重建与验证

1. 原厂 49 个刷写输入文件的 MD5 全部与原厂 `flashfile.xml` 一致。
2. 合并 34 个 sparse super 分片，读取并验证 LP 元数据的 header/table SHA-256，再提取 product、system、system_ext、vendor 进行应用盘点。
3. 用 `fsck.erofs` 解出完整 product，逐 APK 读取二进制 manifest 核对删除包名。
4. 从原始 EROFS inode 提取 uid/gid、mode、mtime、符号链接和所有 xattr。该分区所有 4,739 个条目的 xattr 都仅有 `security.selinux`，重建时逐项恢复。
5. 用 Android erofs-utils 1.7.1 重建。保留的 4,667 个文件系统条目元数据匹配；其中 4,231 个普通文件逐个比较 SHA-256，内容全部一致。
6. 新旧 EROFS 均为 4 KiB block，compat `0x7`、incompat `0x1`。新 product 镜像为 5,031,768,064 字节。
7. 合回原有 super 中的 `product_a` extent，保持 LP 布局及其他分区内容；旧 product extent 剩余部分在工作镜像中置零。
8. 生成 Android sparse `super.img`，将 `flashfile.xml` / `servicefile.xml` 的 34 条 super 刷写步骤合成一条，并更新镜像 MD5。最终校验结果见包内 `package-verification.json`。

product 镜像 SHA-256：

```text
8d6ef42c1ba9a04cf9d029e1a28b48781b87d70a1298aed240de54a79913ada9
```

没有缩小 LP 分区或扩大 userdata。移除的是镜像中的预装文件，空出的 product 空间不会自动加给用户存储。

## AVB、root 与实机状态

修改 product 后，其原厂 AVB hashtree 不再匹配。新包的 `vbmeta.img`、`vbmeta_system.img` 来自本机型原厂文件，仅将 offset 120 的 flags 从 0 改成 3；没有替换 OEM key 或使用 GSI 空 vbmeta。这属于修改验证策略，不代表新镜像取得了官方签名，必须保持 bootloader 解锁，不能给这个包重新上锁。

包内 `init_boot.img` **仍是原厂镜像**，同时附带已有的官方 `Magisk-v31.0.apk`。本轮完成的是精简部分；Magisk 需要连接目标手机后按 [root 核验文档](09-stock-magisk.md) 在该手机上修补，再作为后续步骤刷入。附带 APK 不等于已经取得 root。

本轮未连接手机、未刷写、未清除设备数据，尚未验证启动、电话/相机、联网首启或 Magisk。`flashfile.xml` 沿用原厂的清数据流程，包含擦除 `userdata`、`metadata` 等操作；`servicefile.xml` 沿用原厂不擦这两个分区的流程，但不代表本修改包已验证保数据兼容性。实际刷写前应结合当前版本和槽位确定步骤。以后原厂 OTA 也可能恢复被删应用或覆盖 root，本包未验证原厂增量 OTA。

## 文件位置

- 精简固件目录：`~/moto-clean-W1WAA36/package/`
- ZIP：`~/moto-clean-W1WAA36/mumba_cn-W1WAA36.48-23-10-clean-v1.zip`，同目录附 `.zip.sha256`。
- 完整清单：`package/removed-apps.json`
- product 文件/元数据验证：`package/product-verification.json`
- super/刷写清单验证：`package/package-verification.json`
- 全包文件哈希：`package/SHA256SUMS`
- 精简 product 镜像、原始 inode 清单、218 个 product APK 的包名清单及日志：`~/moto-clean-W1WAA36/work/`。验证后清理本轮生成的大型临时 raw 镜像和解压目录，原厂包不受影响。
- 构建与验证工具：本目录 `tools/` 中的 `erofs_inventory.py`、`apk_manifest_info.py`、`build_clean_product.py`、`verify_clean_product.py`、`assemble_clean_rom.py`、`verify_clean_rom.py`。

参考：[AOSP EROFS 文档](https://source.android.com/docs/core/architecture/kernel/erofs)、[Magisk 官方安装说明](https://topjohnwu.github.io/Magisk/install.html)。
