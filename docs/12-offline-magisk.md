# 原厂精简包 v2：已弃用的系统应用方案

**已弃用：用户反馈 Magisk 不支持作为系统应用。即使更新到 /data/app，也可能仍有 UPDATED_SYSTEM_APP 标记。修正为 v3 的普通应用首启安装，禁止发布本 v2 包。**

日期：2026-09-22。设备 XT2537-4 / mumba_cn / ZY32MVJS25，原厂 Android 16 W1WAA36.48-23-10。

## 用户要求与修正

只给 init_boot 打 Magisk 补丁，清数据首启后会出现 stub 管理器，需要下载完整 App；即使手动安装完整 App，运行文件缺失时仍提示修复环境。这不符合进入系统即可使用的要求。

v2 增加三部分：

1. product/app/Magisk/Magisk.apk 内置未修改的官方完整 Magisk 31.0；对应 ARM64 原生工具放入 app/Magisk/lib/arm64。
2. product/etc/magisk-prebuilt 保存同一 APK 的运行文件。init_boot 的 overlay.d 自定义 post-fs-data 动作在 Magisk 自身动作之前执行，只有运行文件缺失时才初始化 /data/adb/magisk。
3. sys.boot_completed 时，另一个 overlay.d 动作在 Magisk 自身 boot-complete 回调之前，从 product 本地 APK 自动安装管理器更新。官方 v31 的 find_apk_path 仅搜索 /data/app，因此仅把 APK 放进系统分区还不够。已有用户安装版本时跳过，以保留后续升级。

不修改官方 APK、不跳过签名校验、不默认向第三方应用授予 root。保持加密参数与 SELinux Enforcing。

## 构建与检查

目录：~/moto-clean-W1WAA36/offline-v2/。

- product 基于已验证删除 15 个第三方预装的 v1 镜像，所有原有 4,667 个 inode 保持原 uid/gid/mode/时间、符号链接和 SELinux 标签。
- 新增 31 个 inode，最终 4,698 项；4,257 个普通文件经重新解包和 SHA-256 比较一致。
- product raw 5,048,365,056 字节，补齐原有 7,613,104,128 字节分区大小后转 sparse。
- init_boot 基于实机修补的原厂镜像；overlay.d 添加两个 shell 脚本。重新解包确认 CPIO Magisk 标志、脚本原文、PREINITDEVICE=sde9 及原始 SHA-1。
- 首次原型在刷写过程中停止，补齐本地库及管理器自动安装逻辑后，完整重刷最终 product；最终交付以 images.json 和 flash-final.log 为准。

| 镜像 | SHA-256 |
|---|---|
| product.img | 406fd59c4273ecd0b0ac290b37aaf8d1f6d1e76c92f82a3c176c53a72a99d80d |
| init_boot.img | 4a2491a64bed2771e0e77d6605c7e68fb1e18ef3092b47641fb414696b1e2589 |

源码/脚本：tools/build_offline_magisk.py、verify_offline_product.py、moto-magisk-bootstrap.rc、moto-magisk-bootstrap.sh（2026-09-27 Rungic改名C阶段后为`tools/rungic-magisk-bootstrap.*`，日志`/data/adb/rungic-magisk-bootstrap.log`；下次构建并刷入ROM后生效，上表哈希对应当前刷入的moto名版本）、moto-magisk-manager.sh、install_offline_v2.py。

## 实机验证方法

17:57 已写入最终 product 和 init_boot，未清用户数据。随后 USB 长时间显示 authorizing，重连并重启电脑 adb server 后显示 offline；18:04 仍未恢复，手机当前屏幕未知。**尚未验证 Android 首启或离线 Magisk，release.partial.zip 不应视为已验证交付。** 已请用户确认手机画面及 USB 调试授权。

本次备份并移走旧运行文件，卸载此前通过 adb 安装的完整 App，开启飞行模式。保留其他用户数据和 Magisk 授权数据库，刷入 v2，以验证缺少管理器/运行环境时能离线自动恢复；不再次清空整机数据。

这模拟本任务涉及的 Magisk 首启缺失状态，不等同于再次执行全机恢复出厂。

## 安装范围

v2 ZIP 是匹配原厂底包的更新包，包含 product、init_boot 及两个原厂派生 vbmeta。默认安装不清用户数据，明确指定 --factory-reset 才清空。已经复制进 /data 的旧预装需要卸载或清数据才会消失。

只适用于上述底包、已解锁、槽 a。v1 自制 super 被 Motorola bootloader 拒绝，v2 必须走 fastbootd 写 product。原始官方 ROM ZIP 保持不变。

## 官方依据

- [Magisk overlay.d 开发说明](https://topjohnwu.github.io/Magisk/guides.html#root-directory-overlay-system)
- [v31 rootdir.cpp：自定义 rc 插入顺序](https://github.com/topjohnwu/Magisk/blob/v31.0/native/src/init/rootdir.cpp)
- [v31 bootstages.rs：运行文件初始化](https://github.com/topjohnwu/Magisk/blob/v31.0/native/src/core/bootstages.rs)
- [v31 package.rs：管理器路径与签名检查](https://github.com/topjohnwu/Magisk/blob/v31.0/native/src/core/package.rs)
- [v31 MagiskInstaller.kt：nativeLibraryDir 工具提取](https://github.com/topjohnwu/Magisk/blob/v31.0/app/core/src/main/java/com/topjohnwu/magisk/core/tasks/MagiskInstaller.kt)
