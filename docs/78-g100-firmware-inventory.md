# moto g100（XT2533-4）Android 16 镜像来源盘点

记录日期：2026-09-27。本文只针对 USB 序列号 `ZY32M9MRVP` 的 `portov_cn`；原项目开发机 `XT2537-4 / mumba_cn` 是另一台设备。所有实机操作均为读取和一次 fastboot 往返；没有刷写、解锁或改动分区。

## 实机事实

| 项目 | 实机读取结果 |
| --- | --- |
| 型号/代号 | `XT2533-4` / `portov_cn` / `portov` |
| 系统 | Android 16，`W1VT36H.1-51-8`，SDK 36，2026-04-01 安全补丁 |
| fingerprint | `motorola/portov_cn/portov:16/W1VT36H.1-51-8/e9ec8-e96731:user/release-keys` |
| boot/vendor 基线 | Android 15 `VVT35HV-W1-51-ST27.7`，与 Android 16 系统组件共存 |
| SoC/GPU/RAM | QTI `SM7435`，平台 `parrot`，Adreno 710，`MemTotal: 11727552 kB` |
| 内核 | `6.6.87-android15-8-g86c6642d582e-ab14676406-4k` |
| 启动与安全 | 槽 `a`，bootloader unlocked，verified boot `orange`，SELinux Enforcing |
| 存储 | 动态分区 `super`；物理分区有 `boot_a/b`、`init_boot_a/b`、`vendor_boot_a/b`、`dtbo_a/b`、`vbmeta_a/b` 等 |

读取方式：`adb -s ZY32M9MRVP shell getprop`、`uname`、`/proc/meminfo`、`/sys/class/kgsl/kgsl-3d0/gpu_model` 和 `/dev/block/by-name`。另一台 G100 S 的 SoC 是 SM6435，见 [设备记录](01-device.md)。不能跨机复用 boot、vendor_boot、dtbo、GPT 或射频固件。

## 现有固件与提取能力

起初本机只有 `~/Downloads/XT2533-4_PORTOV_RETCN_15_V2VT35.34-33-25_subsidy-DEFAULT_regulatory-DEFAULT_CFC.xml.zip`。包内 `.info.txt` 与 `flashfile.xml` 确认它是 Android 15 `V2VT35.34-33-25`、`portov_cn`、2025-11-16 构建。它比实机当前 Android 16 系统和 Android 15 `VVT35HV-W1-51-ST27.7` boot/vendor 基线都旧，不能充当当前版本镜像或恢复包。

普通 ADB shell 为 UID 2000，没有 `su`。对 `init_boot_a` 和 `super` 各读取 4096 字节均返回 `Permission denied`，因此不能用 `adb exec-out dd` 导出原始分区。进入 bootloader 后，`getvar product` 为 `portov`、`current-slot` 为 `a`、`partition-size:init_boot_a` 为 8 MiB，但 `getvar max-fetch-size` 返回 `not found`，该 bootloader 不提供标准 fastboot fetch 回传能力。随后已用 `fastboot reboot` 正常返回 Android 并由 ADB 确认在线。

## 已核验的可复用路线

1. **同型号同渠道同版本官方全量包，首选。** Motorola [Software Fix/RSA 文档](https://help.motorola.com/hc/apps/service/rsa/58/en-us/CGT1908243440.html)说明可先下载匹配设备的完整固件，再决定是否救援；救援操作会清除用户数据。联想社区[2026-07-09 讨论](https://club.lenovo.com.cn/thread-9565753-1-1.html)称 G100 `W1VT36H.1-51-8` 当天进入 RSA。`lolinet` [2025 portov_retcn 目录](https://mirrors.lolinet.com/firmware/lenomola/2025/portov_retcn/official/RETCN/)目前仅列出旧 Android 15 包；[2026 目录](https://mirrors.lolinet.com/firmware/lenomola/2026/)未列出 `portov_retcn`。这是本轮检索结果，不代表其他来源不存在。用户随后将完整包放到 Home，已由包内信息核对；来源渠道尚未单独证明为 RSA。
2. **现有设备直接读取。** AOSP [fastbootd 文档](https://source.android.com/docs/core/architecture/bootloader/fastbootd)描述 `fetch vendor_boot`，但实际 bootloader 缺少 `max-fetch-size`；当前无法用标准 fastboot 读取全部分区。无 root 的 ADB 也不能读取块设备。获得与本机构建匹配的 root 或可信恢复环境后，才可按活动槽读取并逐块校验。不能用旧 Android 15 init_boot 去为当前机器制作 Magisk 镜像；[Magisk 官方安装说明](https://topjohnwu.github.io/Magisk/install.html)要求使用该设备自身的对应镜像。
3. **Linux 上查询 RSA。** [JoshRob297/moto-firmware-downloader](https://github.com/JoshRob297/moto-firmware-downloader) 1.2.4，固定源码 `d6305e1`（2026-09-13），MIT，副本在 `.work/research/g100/moto-firmware-downloader`；源码使用 `https://lsa.lenovo.com/Interface`、账号 OAuth 和 IMEI 查询，需要用户登录，尚未运行账号查询。该忽略目录中的本地副本仅将凭据状态文件位置改为可配置，以保证令牌留在 `.work`。[enigma550/LenovoMotoFirmwareDownloader](https://github.com/enigma550/LenovoMotoFirmwareDownloader) 固定源码 `061a16c`（2026-05-03），GPL-3.0，同为跨平台候选，依赖更重；本轮只检查了 API 实现，没有据 README 宣称可用。

本机已从 [Node.js 官方发布包](https://nodejs.org/dist/v24.21.0/)校验并解出 Node.js 24.21.0 到 `.work/tools`，准备了 `.work/research/g100/login-rsa.sh`。用户可在本机终端运行该脚本完成网页 OAuth；令牌保存在 `.work/research/g100/private/mfd-state.json`（权限 0600），无需把令牌发到聊天。该候选工具的 6 个本地 token 解析测试已通过；RSA 账号与固件查询仍未验证。

## 成品边界与验收

目标应先确定为**同版本原始分区镜像集**，包括活动槽的 boot/init_boot/vendor_boot/dtbo/recovery/pvmfw/vbmeta/vbmeta_system、`super` 中的逻辑分区及其元数据，以及与当前构建匹配的 bootloader/无线电文件。逐文件保存 SHA-256、字节长度、来源、活动槽和 build fingerprint；用 `avbtool`/`lpdump`/`lpunpack` 等工具离线检查结构和 AVB 关系，并与官方包文件交叉比较。`userdata`、`modemst`、`persist` 等含私有数据或设备校准的分区应另行决定备份范围，不放进通用刷机包。

## 新包与已生成镜像（2026-09-27）

用户提供 `~/PORTOV_CN_W1VT36H.1_51_8_subsidy_DEFAULT_regulatory_DEFAULT_CFC.xml.zip`。包内 `.info.txt`、`flashfile.xml` 与实机的型号、代号、`W1VT36H.1-51-8`、完整 fingerprint、bootloader 版本均一致；`signing-info.txt` 的产品为 `portov`、CID 为 11、HAB security version 为 8。`vbmeta.img` 的 `BUILD_ID`、`HAB_META=portov_11`、系统/boot/vendor 指纹也与实机对应。**这些是匹配证据，不是实机回读比较**。

`tools/prepare_g100_stock.py` 在 `.work/g100/stock-W1VT36H.1-51-8/` 生成并保存：包内 54 个原文件、逐文件大小/MD5/SHA-256 的 `manifest.json`，以及通过 AOSP `simg2img` 合并 32 个 Motorola 稀疏分块的 `super.raw.img`。全部文件的 ZIP CRC 和刷机 XML MD5 已通过；原包 SHA-256 为 `9704e1a6d3b312a162caeb293229acd7cf2a9eb83e75bae928f19e8c4946f975`。合并后的 `super.raw.img` 为 18,924,699,648 字节，SHA-256 为 `3c7922e6a500e46dabd968f39ad43d1b5fc116d9604fa1594b004c927e14a6c2`。每个稀疏分块头中的逻辑大小都是**整个 super 的大小**，不能相加；第一次检查误按相加而失败，已修正并对已提取文件重新读取校验。原始记录为 `.work/g100/prepare.log`、`prepare-resume.log`。

使用 [unix3dgforce/lpunpack](https://github.com/unix3dgforce/lpunpack) 固定源码 `c59b8f3`（2025-03-02，LGPL-3.0，本机副本在 `.work/research/g100/lpunpack`）从 raw super 提取活动槽 `product_a`、`system_a`、`system_ext_a`、`system_dlkm_a`、`vendor_a`、`vendor_dlkm_a` 到 `logical/`。该工具的 JSON 信息输出存在大小错列问题，因此不用其大小表做验收；实际提取文件均由 `file` 识别为 EROFS，并由 `tools/verify_g100_stock.py` 使用 AOSP `avbtool verify_image --follow_chain_partitions` 验证两个 vbmeta 签名、六个逻辑分区的 SHA-256 hashtree 和六个物理镜像的 SHA-256 hash。验证结果与逻辑镜像 SHA-256 留在 `verification.json`、`avb-verification.log`。AOSP 工具来自本机 `android-kernel/prebuilts/kernel-build-tools/linux-x86/bin`，`simg2img` 和 `avbtool` 对应 AOSP Apache-2.0 实现；本轮未改动这两个工具。

至此已完成**主机侧同版本原厂镜像集**，没有制作任何定制镜像，也没有刷写或实机启动验收。`flashfile.xml` 会擦除 userdata/metadata 等分区；即使使用 `servicefile.xml`，也不能把文件存在或 AVB 通过当作整机刷机验收。后续定制前仍需确定修改目标，核对当前内核、Android 宿主、SELinux 与原 G100 S 方案的差异。`userdata`、`modemst`、`persist` 等设备私有分区未包含在通用镜像集内。
