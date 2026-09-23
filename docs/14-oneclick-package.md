# v3 一键完整重装包（差分封装）

用户选择的用途：以后从 Fastboot 完整重装，接受清空用户数据。目标为本次已实机验证的原厂 Android 16 `W1WAA36.48-23-10`，移除 15 个第三方预装，完整 Magisk 31.0 离线安装为普通应用。

## 文件与入口

- 正式压缩包：`/home/kevinzhow/moto-clean-W1WAA36/mumba_cn-W1WAA36.48-23-10-clean-magisk-v3-oneclick-compact-linux-x86_64.zip`
- 同目录同名 `.zip.sha256` 为外部 SHA-256 校验文件。
- 构建结果与校验记录：`/home/kevinzhow/moto-clean-W1WAA36/oneclick-v3-delta-release.json`。
- 解包目录：`mumba_cn-clean-magisk-v3-compact/`。
- 组装目录：`/home/kevinzhow/moto-clean-W1WAA36/oneclick-v3-delta/`。
- 脚本源码：[tools/oneclick_flash.py](../tools/oneclick_flash.py)，测试：[tools/test_oneclick_flash.py](../tools/test_oneclick_flash.py)。
- 差分生成：[tools/build_product_delta.py](../tools/build_product_delta.py)，还原：[tools/product_delta.py](../tools/product_delta.py)，还原测试：[tools/test_product_delta.py](../tools/test_product_delta.py)。

正式包于 2026-09-22 19:14（UTC+8）生成，9,779,944,338 字节（约 **9.78 GB**），比上一版减少 4,475,185,509 字节（约 31.4%）。包含 62 个文件。ZIP SHA-256：

```text
7cca0040b0c31a618aaaf7624a0aac2996cb1576bc6f08d881b51f2fe7cef59d
```

Linux x86_64，需 Python 3.8+。包内已有 adb/fastboot 37.0.1，无需下载镜像、工具或 Magisk。除 ZIP 本身外，建议预留至少 20 GB 供解压和还原镜像使用。

在解压目录运行：

```bash
bash 一键完整重装-会清数据.sh
```

手机可直接进入 bootloader Fastboot；也可从已授权 USB 调试的 Android 开始。脚本先在电脑上校验源文件并还原精简镜像；还原结果必须与已实机验证镜像的 SHA-256 相同。随后检查机型、解锁状态、bootloader 和电量，输入 `WIPE` 才开始写分区。所有刷写成功后才清除 userdata 和 metadata，随后重启。

另附保留数据更新入口（仅限当前槽 a、已启动的同版本原厂系统），以及不连接设备的 `仅校验安装包.sh`。工具始终对选中的序列号操作；连接多台设备时要求明确选择。日志写入包目录下 `logs/`。

只执行电脑上的还原与校验：`bash flash.sh --prepare-only`，不会连接设备。

## 为什么体积更小

旧版同时带了完整原厂 super 和压缩后约 4.49 GB 的精简 product，因此达到 14.26 GB。新版保留原厂分片，仅额外保存 15,386,168 字节（约 15.4 MB）的差分内容和还原索引，仍是自包含完整重装包。

差分从原厂分片复制完全相同的数据块，补入新增数据，得到字节完全相同的 Android sparse product 文件。还原仅依赖 Python 标准库，不需要安装第三方差分工具。输出约 5.05 GB，SHA-256 固定为：

```text
b5d417cb6cb30ff362e2f49b3a8923d410b96764da3428938977900899f24885
```

还原先写临时文件，完整摘要通过后才转为可刷写镜像；已有缓存每次使用前也会重新校验。空间不足、源文件损坏或差分错误时不会进入设备操作。

## 恢复范围

仅支持 XT2537-4 / mumba_cn，已解锁，且 bootloader 必须为：

```text
MBM-3.0-mumba_cn-134d447f1e26-260413-WWAA36V.48-23-ST12.4-1c41a
```

完整重装切换到槽 a，写入原厂 boot、init_boot、vendor_boot、dtbo、recovery、pvmfw 和 34 个原厂 super 分片，再经 fastbootd 写入 v3 精简 product，最后写入 v3 Magisk init_boot。两个 vbmeta 使用已验证的原厂派生镜像。

保留已匹配的 GPT、bootloader、基带和校准分区，因此支持该底层版本上的 GSI、修改后的系统或无法启动的 Android 恢复，不承担底层固件损坏救援或跨版本降级。

## 验证范围

- 原厂镜像沿用逐文件匹配原厂 XML 的 MD5 的版本，50 个镜像、差分和工具文件的 SHA-256 校验通过。
- 镜像沿用 v3 实机验证版本：断网首启自动安装完整普通应用、root 正常、SELinux Enforcing、15 个预装已删除；再次重启未重复安装。详见 [13-offline-magisk-user-app.md](13-offline-magisk-user-app.md)。
- 16 项测试通过，覆盖 34 个原厂分片顺序、完整/保留数据模式、机型和解锁状态检查、版本不符拒绝、校验失败与刷写失败停止、清数据顺序，以及差分损坏、越界、空间不足、缓存复用和还原失败禁止设备连接。
- 差分已实际还原，并独立重新读取输出文件核对 SHA-256，结果与实机验证版本相同。
- 最终 ZIP 的 62 个条目已全部解压，CRC 和 SHA-256 全部通过；随后仅使用解包目录运行 `--prepare-only` 完整还原镜像，再次独立读取还原文件计算 SHA-256，与实机验证版本一致。结果记录于 `oneclick-v3-delta-release.json`。
- 封包过程中没有再次刷写或清空当前手机；完整清数据流程本次仅做模拟测试，没有重新执行整机恢复出厂。

包内也包含使用说明、文件校验清单、实机验证记录、脚本测试记录和原厂刷机 XML 参考。
