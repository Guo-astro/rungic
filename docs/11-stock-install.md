# 原厂精简系统与 Magisk 实机安装记录

设备：XT2537-4 / mumba_cn，序列号 ZY32MVJS25。日期：2026-09-22。

用户在已告知整包恢复会清数据后明确授权刷入。安装开始前实机为原厂 Android 16 `W1WAA36.48-23-10`，bootloader 已解锁，当前槽为 a，电量 80%。机型、底包、内核与精简包匹配。

## 镜像与安装路径

全部安装日志、补丁和校验结果保存在：

```text
~/moto-clean-W1WAA36/device-install-20260922/
```

- 在这台手机当前原厂 Android 16 环境，用本地官方 Magisk 31.0 APK 中的工具重新修补原厂 `init_boot.img`。
- 参数：`KEEPVERITY=true`、`KEEPFORCEENCRYPT=true`、`PATCHVBMETAFLAG=false`；检测到 `PREINITDEVICE=sde9`。
- 修补结果在目标手机重新解包，Magisk CPIO 标记为 1；备份配置中的原始镜像 SHA-1 与本包原厂镜像一致。
- 补丁镜像 SHA-256：`0039243a97e249dc82531e8c1254aa5e7b40d3acb837402dcaae80bfc9afd258`。

## 实机发现的限制

**v1 ZIP 中重新封装的 `super.img` 不能直接通过这台 Motorola 的 bootloader fastboot 刷写。** 实际在首个 sparse 分片的预刷校验阶段收到：

```text
Unsupported super image format, rejecting...
Preflash validation failed
```

这是离线内容校验无法替代的 bootloader 格式兼容性检查。该失败发生在清数据和 Magisk 刷入之前；不应再照 v1 的 XML 在 bootloader 中直接刷这个 `super.img`。

改用匹配原厂底包上的 fastbootd 路径，只更新 `product_a`，保留其原有 7,613,104,128 字节大小。使用已逐文件验证的 `product-clean.img`，尾部补零到原分区大小，再转成 sparse 文件 `product-clean-fastboot.img`。

Motorola 的 `oem fb_mode_set` 会设置 UTAG 快速启动标志。进入 fastbootd 前必须清除本次设置的标志：

```bash
fastboot -s ZY32MVJS25 oem fb_mode_clear
fastboot -s ZY32MVJS25 reboot fastboot
```

清除前 `reason` 报 `UTAG bootmode configured as fastboot`，进入 fastbootd 失败；清除后这次转换耗时约 62 秒，最终 `is-userspace: yes`、`unlocked: yes`。不能仅因转换时短暂 USB 消失就认定故障。

本次安装步骤：

1. bootloader 中写原厂派生、flags=3 的 `vbmeta_a` / `vbmeta_system_a`。
2. fastbootd 中写 `product-clean-fastboot.img` 到 `product_a`，确认分区大小不变。
3. 回 bootloader，写本次手机上修补的 `init_boot_a`。
4. 所有镜像写入成功后擦除 `userdata` / `metadata`，清除 fb_mode 标志并启动。

未重刷分区表、bootloader 或基带。此路径要求已运行匹配底包，不能用于直接把任意 GSI/其他版本变成原厂系统。

## 验证状态

17:30 已完成写入：fastbootd 的 product 19/19 分片均成功，分区大小保持不变；随后 `init_boot_a`、`userdata` / `metadata` 擦除和重启命令全部成功。见 `flash-complete.json` 和 `flash-fastbootd.log`。

首次开机与 USB 调试重新授权已完成。实机指纹为匹配的原厂 Android 16，SELinux Enforcing，15 个第三方预装目录均不存在。手动安装完整 Magisk APK 并修复环境后，已验证 uid=0 和 Magisk 31.0。

用户进一步要求首启无需下载完整 App 或手动修复环境，因此制作 v2 离线首启包，见 [12-offline-magisk.md](12-offline-magisk.md)。本节的手动安装路径不满足最终交付要求，应以 v2 实机验证为准。

参考：[AOSP fastbootd 文档](https://source.android.com/docs/core/architecture/bootloader/fastbootd)。
