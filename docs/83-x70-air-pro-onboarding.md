# X70 Air Pro / vantage 首轮接入

日期：2026-09-28。用户要求为当前 USB 连接的 X70 Air Pro 刷入 Rungic。使用项目三段式 skill，先核对 75/77/79/80 和最新首启协议 82 篇。下述离线结果不能替代自编内核启动与完整清数据安装。

## 实机与原厂恢复基线

运行目录 `.work/ci/runs/vantage-20260928-onboarding/`，ADB 5037，目标 `ZY22MHZKFT`。另有 Wi-Fi G100 S 在线，所有命令必须绑定目标；本轮不操作它。

| 项目 | 2026-09-28 实测 |
| --- | --- |
| 型号/产品 | Motorola XT2603-1，`vantage` / `vantage_cn` |
| 固件 | `W2WV36.55-75-15`，Android 16 / API 36 |
| 指纹 | `motorola/vantage_cn/vantage:16/W2WV36.55-75-15/0a2efa-422586:user/release-keys` |
| SoC / GPU | SM8845 / canoe，KGSL sysfs 报 Adreno829 |
| 内核 | `6.12.38-android16-5-g7aecc84c5b34-ab14496924-4k` |
| 槽位與锁定 | `_a`，flash.locked=0、unlocked、orange；SELinux Enforcing |
| 容量/电量 | /data 可用约 425 GiB；电量 100%；主机初始约 234 GiB 可用 |
| boot 布局 | boot header v4、无 ramdisk；init_boot header v4、只有 ramdisk |

原厂 ZIP 位于 Home 的 `XT2603-1_VANTAGE_RETCN_16_W2WV36.55-75-15_subsidy-DEFAULT_regulatory-DEFAULT_CFC.xml.zip`。文件名之外，已逐项核对包内 info、flash/service XML 和实机指纹。原始下载渠道尚未单独证明。

全部 62 个 ZIP 成员通过长度、CRC、XML MD5 核验；41 个 super 分片重组完成，原包及每个产物记录 SHA-256。原厂 AVB 的两个 vbmeta 签名、6 个物理镜像和7个逻辑镜像验证通过。精确摘要见 spec 与运行目录 `stock/{manifest,verification}.json`；AVB 公钥 SHA-1 为 `27bcbab040b154eecdce885d6c0e6283cee9c227`。该值只证明内部链一致，不单独证明下载渠道。

新设备有独立 `odm_a`，不能沿用 G100 的六逻辑分区假设。原厂 info 文本写有 `AB Update Enabled: False`，但设备槽位和实际 liblp 明确存在 a/b 分区；以运行状态与真实布局为准，不据此字符串判定非 A/B。

恢复材料已离线验证。具体 bootloader/fastbootd 路径尚需实机识别；此时没有执行任何分区写入、擦除或切槽。不得直接运行旧 G100 包。

## 上游、许可证与选型

- ACK 精确提交 [`7aecc84c5b34a3f9659e24d74a8080e1dc19b6fd`](https://android.googlesource.com/kernel/common/+/7aecc84c5b34a3f9659e24d74a8080e1dc19b6fd)，对应 `android16-6.12-2025-08_r16`；Git tree `310bd3cca9341a49f573c3195ae21e95215cf28a`。许可证 GPL-2.0-only 及逐文件 SPDX。新增 `packages/gki-android16-6.12/recipe.json`，通过 pq 固定来源与补丁，源码只在 `.work`。
- 原厂 Image 的配置和 version string 确认 Clang r536225 / 19.0.1（Android 14043575）、Rust 1.82.0（linux-12909517）、BUILD_NUMBER=14496924、4 KiB、KMI generation 5、无 LTO。Kleaf manifest 基线 `35c7b6da4128d4d49b42db9bfa03c9177c847e9d`，工具链已下载，Clang 与原厂版本吻合；实际同步的 30 个仓库提交保存在 `gki/checkout-revisions.json`，固定子集 manifest 随仓库保存于 `kernel/targets/gki/android16-6.12-manifest.xml`，不把分支名当作完整构建锁。
- 原厂未开启 SYSVIPC、POSIX_MQUEUE、PID_NS、USER_NS、DEVTMPFS。复用最小 LXC 配置和 task_struct KABI 预留槽方法，按新源码移植；6.12 改用 gendwarfksyms，必须重新比较 CRC，不能继承 G100 的零差异结论。
- 新内核启用 `CONFIG_EXTENDED_MODVERSIONS`。已检查同提交的 `kernel/module/version.c`、`scripts/mod/modpost.c`：u32 CRC 数组与 NUL 分隔符号名配对，内核优先采用 extended 格式；C 字符串还有末尾隐式 NUL。更新公共 `tools/ci/module_abi.py`，保留 6.6 格式，拒绝缺段、错配和重复符号。单元测试覆盖长 Rust 名、尾终止符、优先级和损坏输入；加入 vendor_boot 后，本机 722 个模块、40,330 个引用已成功解析，**这不是候选 CRC 已通过**。
- 原厂 Image 唯一 X.509 模块信任锚长 1357 字节，SHA-256 `f7c4d29a15e94c4ecfb1e3fbde0b4b794cfcdea580854dead28b03aaa00851ac`。候选仍需验证证书区域与运行信任链。
- Mesa 现有固定来源 [`lfdevs/mesa-for-android-container` 98f3d622](https://github.com/lfdevs/mesa-for-android-container/tree/98f3d6229d61452cef80f8563af7c56ae599dc14)，MIT 等（见 recipe / docs/license.rst）。源码 `src/freedreno/common/freedreno_devices.py` 已有 Adreno 829 KGSL `chip_id=0x44030a20`，优先复用当前 Mesa/KWin 公共后端。尚未在本机运行 GPU/桌面，条目存在不等于实机通过。
- Motorola readme 仓库本轮树查询未找到 W2WV 条目；只记录检索范围，不宣称厂商没有公开源码。已找到 AOSP 精确 GKI 基线；OEM 模块保留原厂输入，单独审计其 ABI 和签名。

## 公共工具改动与剩余门槛

`prepare_g100_stock.py` 增加显式、独立审核的 `--identity`（型号、device、完整 fingerprint、info 文件和 super 分片数），继续保留 G100 默认身份拒错；不依据待验 ZIP 自动放宽匹配。`verify_g100_stock.py` 增加精确 fingerprint 和逻辑分区列表，要求 AVB 实际验证集合完全一致。运行时身份 JSON 放在 `.work`，最终锁定字段进入设备 spec。

当前 spec 是接入候选：15 个预装应用已逐项审核包名与 X70 APK 哈希，8 个渠道文件纳入排除；AI 依赖尚未审核，因此没有复制旧机型的禁用列表。刷写计划尚未验证、内核尚未启动、rootfs 未针对这台手机验收，不能授予发行状态。当前源码 APK 为 2.9 / versionCode 57、账户协议为 2；必须与更新 rootfs 共同交付，不能直接复用 G100 `.5` 的旧协议包冒充最新版。

先完成 CI1 工具链/ABI/候选 boot，核验模式及恢复路径后进行授权的实机测试；CI2 核验新版账户包和 Adreno 829 后端；CI3 纳入 odm 与真实容量，再完成包本身的清数据首启 → loading → 账户 → Plasma。验收范围优先首启与桌面，不扩大相机等测试。

## 网络实测

GNOME proxy=none、环境无 proxy 变量，但上级 AGENTS 要求 SwiftWire；1080 SOCKS 与 8080 CONNECT 均 20 秒超时。用户随后明确要求测试直连，AOSP 源码请求约 1.1 / 1.8 秒返回 HTTP 200，后续改用直连。大源码 `+archive` 请求返回 503，GitHub镜像该提交返回404；转用 AOSP 浅层 Git fetch，精确提交及 tree 校验成功。不能把归档端点失败写成整个网络不通。

## 离线构建与 USB 阻塞（本轮进行中）

- 原厂 product 去除精确列表后重建为 10,471,612,416 字节；4,635 个保留条目的 mode、UID/GID、mtime、SELinux/xattr、文件长度与符号链接已逐项比较，记录在 `product-clean/metadata-verification.json`。最终载荷仍须核验不超过 13,194,330,112 字节逻辑分区。
- 当前源码 `363777649152d4d379febb75c3cb31753492febf`，本次设备/工具修改另存 diff。重新编译 ARM64 native core 与 APK 2.9，APK SHA-256 `5bdf413629f03502fb53c0ab46e6c41b93bc5e8e91adfa826eb6391a1f97a321`。未进行本机应用启动验收。
- Mac mini 先读取系统代理，再原生构建缺少的当前项目包。release `20260928.2` 锁定 63 项；rootfs 使用相应精确包和 27 个 Ubuntu 依赖快照。安装前先模拟，安装后 dpkg audit、项目 venv pip check 和账户协议 2 检查通过。
- 16 GiB rootfs 原始 SHA-256 `e1a8ecfb0563ecba25686de1611b4be4f0774ab81be769474c2d722b988a1b28`；gzip `64468bfa907cc2cddd8b41ff41ae276d770dcc24983a038244b80736970c6cf8`，文件系统检查通过。1479 个包的清单 SHA-256 `ead716ef4a69a96c213dc80d488adb82495f1f1858fbdf7f25c54c89b574ee9c`。这是离线候选，尚无 X70 桌面实机结果。
- 宿主种子基于现有 ARM64 Alpine LXC 6.0.4 runtime 加当前宿主桥及同一 release 仓库，SHA-256 `3581b6666f7513b1cd777e7941486589508378d0f0724920d9efcfa867701d27`。复用的 Termux APK/prefix 与稀疏写入器逐项和已归档报告比对，见 `reused-arm64-inputs.json`；不复用旧手机内核。
- Magisk 31.0 官方 APK 已作为普通应用安装。使用当前手机运行 magiskboot 修补本机原厂 init_boot，保留 verity / forceencrypt，探测到 `PREINITDEVICE=sde13`；简单补丁 SHA-256 `34bea306b6992f2b8faef266c1316d936caafd65e6ebd9e1943c67015d673635`。离线注入安全阶段引导后的候选 SHA-256 `d7633b57a69ce609422d0d417f6bab4f7376ffe36af74c4bb3ee3c6aaebf2ba2`。两者都尚未刷入，不代表 root 可用。
- 11:52:38 执行指定目标的 `adb reboot bootloader` 后，主机只记录 USB disconnect，此后没有重新枚举 Motorola；第一次只读 `fastboot getvar product` 等待 90 秒超时。未发现 USB -71；此时从未执行 flash、erase 或切槽。停止设备写入，保留 `bootloader-transition.json` 与 `usb-after-bootloader.txt`，已请用户确认屏幕并重插 USB；独立的离线构建继续。
- 内核配置生成成功；相对原厂新增 SYSVIPC/POSIX_MQUEUE、IPC/PID/USER namespaces、DEVTMPFS 及相应依赖。另有 fast 构建配置的 FRAME_WARN 2048→0（编译警告门槛），完整差异保存在 `gki/config-diff.json`。完整内核和模块 ABI 检查仍在进行。

公共工具的 10 个针对性测试通过（分别直接运行 `tools/ci/test_module_abi.py` 和 `tools/test_prepare_stock.py`）。Bazel dist 目标额外依赖尚未同步的 kselftest libcap-ng，改为构建实际需要的 `//common:kernel_aarch64`；没有以禁用源码检查绕过内核错误。

### 6.12 编译与 ABI 对照定位

首次容器配置编译在 modpost 阶段报告 Rust Binder 的 `init_ipc_ns` 未导出；补齐后又报告 `put_ipc_ns`。已核对同提交的 `drivers/android/binder/rust_binderfs.c` 与 `ipc/` 源码，并复用 [Alice Ryhl 2026-02-05 上游补丁](https://lists.openwall.net/linux-kernel/2026/02/05/686) 的两个导出（GPL-2.0-or-later 文件）；通过独立 `kernel/targets/gki/android16-lxc-symbols` 加入允许列表。没有关闭 KMI strict 检查。此时 v3 完成编译，但 18,587 个引用发生 CRC 差异，故禁止刷入。

同一固定源/工具链恢复原厂配置构建对照，722 个模块的 40,330 个引用中：36,262 个 GKI 可比较引用完全一致，CRC 差异为 0；4,068 个引用不由 GKI 导出，不能归入“已比较通过”。配置仅剩 FRAME_WARN 编译警告门槛差异。对照证据为 `gki/module-abi-stock-control.json`。

进一步核对 `scripts/gendwarfksyms/dwarf.c` 的 `check_struct_member_kabi_status`：替换 union 中只使用第一个 `__kabi_reserved` 成员。两个预留槽一并替换虽保持物理大小，却会让第二个槽从 CRC 类型描述中消失。隔离 C/header 复现与 `--dump-dies` 保存于 `gki/kabi-two-slots.*`。修订 task_struct 补丁：slot 6 按官方单槽 KABI 宏使用；slot 7/8 保持原始独立 u64 声明，以有类型的 helper 访问连续存储，并静态检查大小、对齐和偏移相邻。原厂对照 task_struct 大小 5184，slot 6/7/8 偏移 3464/3472/3480，thread 偏移 3488。修订版待重新比较 CRC；不以物理大小相同代替 ABI 验收。

v4 的 C ABI 修订后差异降为 22 个引用，全部来自原厂 `system_dlkm/rust_binder.ko`；另有该模块的 3 个旧导出未提供。不能把这写成所有模块通过。对照生成绑定发现，启用 SYSVIPC 后 task_struct 的匿名 union 改变了 Rust 类型名称，两个原先为空的 SysV 类型新增 Default impl，进而改变后续 rb_node/rb_root impl 的符号消歧编号；USER_NS 又让 `rust_helper_from_kuid` 从条件编译中消失。

最终候选源码继续收敛：三段 task 预留存储都保留原始字段声明，用静态断言保护的 helper 访问；对不被 Rust 使用的两个 SysV 类型采用 bindgen 官方 `--no-default` 参数；UID helper 始终保留，实际调用具有 namespace 语义的 `from_kuid`。没有改写模块 CRC、Rust 导出名称或跳过内核校验。重新生成的 task_struct Rust 声明与对照完全相同，1077 个 Default impl 的顺序也完全一致；最终 CRC 仍需以完整链接结果为准。

原厂对照中不由 GKI 提供的 4068 个引用对应 1546 个独立名称，均能在保留的 OEM 模块导出中找到，见 `gki/oem-export-name-check.json`。这只核对名称提供者，不替代跨模块 CRC、签名或实机载入检查。


### 最终 CI1 离线候选（v7）

v7 完整链接和 Kleaf KMI strict 检查通过。`module-abi-final.json` 覆盖 722 个原厂模块、40,330 个引用：36,262 个 GKI CRC 匹配，0 差异，4,068 个非 GKI 引用，与原厂配置对照范围完全相同、没有新增缺失。报告记录 Module.symvers 和逐模块 SHA-256。v7 的 pahole task_struct 输出与原厂配置对照逐字相同；从最终 Image 回读的配置也与构建配置逐字相同。

stamp 构建使用实际 30 个项目的固定 manifest，避免未同步的测试/引导工程让 repo manifest -r 失败而退化成未知版本。Kleaf 使用其原生 `--repo_manifest=<source>:<manifest.xml>` 参数；三段补丁逐文件与实际构建源码核对一致。构建参数为 `BUILD_NUMBER=14496924 tools/bazel build --repo_manifest=... --config=fast --config=stamp --lto=none --defconfig_fragment=//rungic:lxc_defconfig --user_kmi_symbol_lists=//rungic:android16-lxc-symbols //common:kernel_aarch64`。`rungic/` 的两份输入来自 `kernel/targets/gki/`，BUILD.bazel 将其 exports_files。

最终 release string 为 `6.12.38-android16-5-g7aecc84c5b34-dirty-ab14496924-4k`；dirty 对应已归档补丁，不伪装原厂二进制。全部 722 个模块同时带 legacy/extended 版本段，该固定源码的 same_magic 在有 legacy CRC 段时按既有规则忽略 release 字符串部分，仍检查其余 vermagic 和符号 CRC；未修改此检查。

恢复原厂信任锚时只改动证书区域 1096 字节，区域外不变；最终 Image SHA-256 `42c1479afde9d63e576963dc28df5e1ea58768e4177af262925c04167a7e7f45`。用固定 AOSP mkbootimg 生成 header v4，无 ramdisk；回读确认除 kernel_size 外原厂头部全部一致、payload 与 Image 相同。候选 boot 为 40,161,280 字节，小于原厂 96 MiB，SHA-256 `5799040aa8447bf258dc912df9ebdc919630cf428d29b6b8f6e9d6b4ccb677cc`。报告 `gki/{boot-report,trust-report}.json` 将 boot、实际 Image、编译 Image 和符号表关联。

**以上仍是离线验证。设备没有重新枚举，因此尚未临时启动/刷入、尚未验证模块实际载入、Android/SELinux/LXC 或清数据首启。**


## v7 实机启动与 root（保留已有数据）

12:32 重新枚举后，精确目标的 bootloader 确认为 vantage / XT2603-1、slot a、电压 4445 mV、`securestate=flashing_unlocked:SDP`。该机 fastboot 分段版本值比 Android property 少末尾 `fa`，为 `MBM-3.0-vantage_cn-cc61af6b1f1e-260507-W2WV36V.55-75-ST2.5-0a2e`。这两个实际差异进入独立 fastboot adapter；不放宽旧 G100 的一字符规则或只匹配 unlocked 子串。新增 adapter 绑定 spec SHA 和实际固件映射，并须通过模式探针才可组成发行包。

`fastboot -s ZY22MHZKFT boot boot-candidate.img` 发送及启动成功，10.431 秒返回。Android boot_completed=1，运行 v7 内核，508 个模块、Adreno829、SurfaceFlinger/音频服务存在，SELinux Enforcing。之后 ADB reboot bootloader 再次只断开 USB，30 秒只读 getvar 超时，尚未写入；用户明确重新插拔后恢复。该主机/线缆的 Android→bootloader 过渡两次需要重插，不能标为全自动稳定。

重新核对型号、完整分段版本、解锁状态、slot、电压和分区尺寸后，只写 `boot_a` 与简单 Magisk `init_boot_a`，未修改 vbmeta、product，未清数据。两次写入均返回 OKAY。Android 正常启动；按 Magisk 普通应用提示修复环境并自动重启，在超级用户页启用 Shell 后 `su -c id` 返回 uid 0。没有执行 Magisk SQL 查询。

`device/kernel-root-probe.log`：内核和 Magisk 31.0 正确，SELinux Enforcing；BusyBox 合并创建 mount/PID/IPC/network/UTS/user namespaces 成功；rust_binder 在 /sys/module 中，508 模块载入。boot_a 前 40,161,280 字节回读 SHA 与候选相同；init_boot_a 整分区 SHA 仍为简单 Magisk 候选。此时 LXC/Plasma 及完整清数据首启尚待验收。

product 候选已完成：12,466,253,824 字节，小于 13,194,330,112 字节逻辑容量，SHA-256 `73f5d36973090e2b368429ecd3e6ebdc302b2b7f66d488953b0ac7761916e2a0`。fsck.erofs、全部 4682 个条目的路径和元数据检查通过，APK JNI 已按只读预装方式展开。仍未写入手机。

## 12:50 当前停点

ADB reboot fastboot 后约 42 秒自动进入 fastbootd（USB 2.0），is-userspace=yes、product=vantage、slot=a、unlocked=yes，七个逻辑分区尺寸逐项匹配原厂 verification，单次下载上限为 0x10000000。随后 `fastboot reboot bootloader` 返回 OKAY，但 USB 未重新枚举，30 秒只读 getvar 超时；已请求用户再次插拔，12:50 仍未见设备。本次停点没有正在执行的写入，没有清数据。

`W2WV36.55-75-15-fastboot.json` 的 `mode_probe_verified` 仍为 false。还需重新识别 bootloader，实测 `oem fb_mode_clear` 与 bootloader→fastbootd 路径后才允许封装整包；不能将 ADB→fastbootd 的成功当作整个刷写器切换链已通过。公共安装器支持该独立 adapter 的精确固件/解锁状态映射；默认 G100 校验维持原限制。6 项安装器测试（含错误固件/spec、锁定状态、未验证模式和不支持槽位的拒绝）通过，另有 10 项 stock/module 工具测试通过。

续作入口：运行目录的 `status.json`、`gki/device-report.json`、`assemble-release.py`；组包前重新运行 `snapshot-source.py`。当前仓库未提交的源码、spec、补丁和文档另存 `source-snapshot.json` 与 `source.patch`，组包工具将相关来源文件和差异纳入最终 manifest 哈希。整包、LXC/Plasma 及清数据首启均未标记通过。

## 12:59 模式探针完成

用户重插后重新确认精确 bootloader 身份、解锁状态和槽 a。`oem fb_mode_clear` 成功；bootloader→fastbootd 命令在 51.364 秒返回，is-userspace=yes、product=vantage、slot=a、unlocked=yes。该方向能够自动切换，之前 Android/fastbootd→bootloader 仍有需要物理重插的已知现象；adapter 记录此限制，不称为全自动 USB 验收。证据 `device/bootloader-to-fastbootd.json`。至此模式探针允许组包，尚未完整刷写或清数据。

## 完整候选包开始刷写

`release/vantage-20260928.1` 组装完成，manifest SHA-256 `d75f07389f10b5bedb96afde948834adffebbcaced0783b8c1b0f0ec53a576dc`；94 个文件离线校验通过。包括 41 个原厂 super 分片、最终 product、v7 boot、安全阶段 init_boot、设备 adapter、源码快照/补丁、包锁及 CI1/模式证据。manifest 显式记录候选 kernel release（含 dirty），避免验收工具错误地要求 stock release；boot 分区回读仍独立核验精确哈希。

返回 bootloader 再次由用户重插后恢复连接。13:01 开始包自身 `flash.sh --yes-wipe`；型号/固件/解锁/电压核验通过，辅助分区写入成功，约 50 秒自动进入 fastbootd。当前进行系统分片传输，不能将启动刷写等同于全部完成。实际完成/清数据/首启结果后续追加，实时证据 `full-flash.log`。

## 13:17 USB 超时停点（系统分区已完成，尚未清数据）

41 个原厂 super 分片全部发送/写入 OKAY，7 个逻辑分区容量重新核对完全吻合。product 的 47 个发送段全部写入成功，总计 275.912 秒，product_a 容量仍为 0x312718000。随后返回 bootloader 命令成功，USB 再次未枚举；请求用户重插后，`getvar is-userspace` 等待 180 秒超时，完整刷写进程以 1 退出。没有执行本轮最终 boot/init_boot，也没有 erase userdata/metadata 或启动 Android。不得把该状态写为整包通过。

已写入的是辅助分区、原厂系统及最终 product；boot/init_boot 仍为早先 v7 与简单 Magisk 探针。恢复后先重新核验设备身份/版本/解锁/槽位和发行包摘要，从阶段 7 接着刷最终 boot/init_boot，再执行授权的阶段 8 清数据与启动；无需重复大分区传输。保留原始 `full-flash.log` 和包内 `flash.log`，续写另留日志。当前没有进行中的设备写入。

## 14:56 用户重插后：执行环境权限阻塞

用户回复“好了”，但新回合从全访问切为 workspace-write 受限环境，`/dev/bus/usb` 不存在、libusb 初始化失败；ADB 5037 listener 被 `Operation not permitted` 拒绝，NSpid/Seccomp 显示隔离进程。此时 fastboot 空列表不能用于断定手机仍未重连。没有执行任何设备写入，也不尝试绕过沙箱。

本次运行目录新增 `resume-final-stage.py`：默认仅离线校验；固定原 manifest 和原始中断日志 SHA，复用包内已验证刷写器，续作仅包含 boot/init_boot、userdata/metadata 清除及 reboot。执行参数 `--execute` 下仍先重新核验型号、完整固件、解锁、槽位、电压及启动分区容量；独立日志与单次写入标记防止误重复。未执行实机续刷，待恢复能访问宿主 USB 的执行环境。

## 恢复 USB 权限后完成清数据刷入

执行环境恢复 full access 后 fastboot 重新识别 ZY22MHZKFT。续刷脚本重新核验原 manifest/中断日志及全部载荷、设备精确身份/固件/解锁/槽 a/电压/boot 和 init_boot 容量后，写入最终 v7 boot 与安全阶段 init_boot，均 OKAY；erase userdata、erase metadata、清除 fb_mode 及 reboot 均 OKAY。续刷进程退出 0。完整路径从此前 41 个系统分片与最终 product 接续完成，未重复大分区刷写。证据 `resume-final-stage.log`、`device/final-stage-started.json` 及对应独立日志。

此时阶段为 flashed；清数据首启、自动离线部署、账户配置和 Plasma 尚需验收。不能把刷写命令完成等同于桌面通过。

## 清数据首启与 kevinzhow 账户冲突

用户已完成 Android 引导并进入 Rungic 账户页，但用户名 kevinzhow 显示不可用。重新开启 USB 调试后，5037 只列 Wi-Fi G100 S，5038 接管 USB X70；后续设备命令固定 `-P 5038 -s ZY22MHZKFT`。Android boot_completed=1、v7 内核、SELinux Enforcing。Magisk 普通应用无修复提示，Shell 授权单独在超级用户页启用，仅用于诊断。

实际自动部署日志：15:07:47 开始 release vantage-20260928.1，16 GiB 稀疏写入完成，15:08:49 标记 seed complete；完成标记与 release 一致。这证明离线部署完成，不证明账户/桌面或整包无需人工修复。

账户 UI 对“用户名已被使用”和“主目录已存在”都显示“这个用户名无法使用”。源码规则允许 kevinzhow；实际发现构建残留 `/home/kevinzhow/moto/.work/cache/python/`，共 337 个 `.pyc`，并不存在 kevinzhow 用户。最终 rootfs 和 host seed 都包含该目录，后者复制整个 home 到 Android state/home，实机 /home 正是此 f2fs 绑定目录。该现象不是用户命名错误，也不能要求换用户名规避。

原因：tools/work-env.sh 的 PYTHONPYCACHEPREFIX 为宿主绝对路径；arm64_chroot.py 原先复制全部环境，导致 chroot 内 Python 以相同绝对路径生成缓存。Python 官方[环境变量说明](https://docs.python.org/3/using/cmdline.html#envvar-PYTHONPYCACHEPREFIX)与当前源码吻合。复用标准 Python 环境隔离，无需改写账户检查：arm64_chroot 清除继承的 PYTHON*；两个镜像构建器在输入及暂存树检查 home，仅允许实际模板账户和指向该账户的 linux 兼容链接，拒绝其他条目。六项针对性测试通过；当前受影响 root-tree 被新检查准确拒绝。

实机修复先核对未配置账户、UID1000 仍为 rungic、无 kevinzhow 用户，并逐文件 SHA 比对这 337 个文件与交付镜像中的缓存。原拟 rename 因 /home(f2fs)/var/cache(ext4) 跨文件系统报 EXDEV，未改动原目录；随后先复制到 `/var/cache/rungic-build-residue/vantage-20260928.1-kevinzhow`，复核全部摘要一致后移除原缓存目录。未删除用户数据或放宽账户冲突保护。证据 `device/account-cache-reference.json`、`device/account-cache-repair.log`，脚本 `repair-account-cache.py`。账户页重新打开，待用户用原用户名完成配置。

**vantage-20260928.1 需要此人工修复，不能标记 clean-install bundle-validated。** 源码防回归已修复，重建 rootfs/host seed/product/发行包及其全新安装验收仍须单列；当前实机优先继续账户与桌面验证。


## 账户完成、标准目录及显示重构

缓存残留移除后，用户以 `kevinzhow` 完成账户配置，实际进入 Plasma，浏览器可打开。照片应用随后报告 Pictures 不存在，定位为首装 home 只含模板，未统一准备 XDG 用户目录；并非照片应用私有路径问题。

新增共享 `plasma/user-dirs`，在真实 Android Shared 挂载就绪后建立媒体目录及 home 相对链接，保留已有文件/目录，不覆盖用户数据；本地 Documents/Desktop 与其余 XDG 标准目录统一登记。会话启动先调用该助手；root 控制器 `account-prepare` 也先检查挂载并调用，准备成功才允许表单。实机安装会话 0.306 后 Koko 实际打开空 Pictures，Qt/GLib 目录查询一致；之后显示重构升级到 0.314 仍包含该助手。四项目录语义测试通过。

首装构建防护进一步检查：仅允许一个 UID1000 模板账户，root/template 密码必须锁定，没有账户完成标记及所列常见凭据路径；machine-id 在最终树清空。十一项 chroot 环境/home/账户隔离测试通过。检查范围是列出的契约，不称为整棵系统的全面秘密扫描。已有设备不是模板，不从当前 home 反向生成镜像。

用户另授权显示大小重构，最终实机 release `20260928.6`，KWin rungic7、KScreen rungic4、会话 0.314、配置 0.308。公共策略、GUI 确认/恢复、模式补偿、第二输出、Qt/GTK 和保持用户偏好的证据见 [85 篇](85-phone-display-size-policy.md)。当前设备已恢复原来的 300% 和自动刷新率，没有因新默认 350% 改写用户偏好。

`.2` 修订整包使用 v3 暂存重新生成 rootfs、host seed 与 product，吸收缓存污染、标准目录、账户准备门槛和显示策略。旧 v2 仅含缓存修复且不是最终包；其可重建大文件已按 run-id 清理，保留报告/日志。新包离线校验和清数据实机验收继续分别记录，不重刷当前已配置账户。


## 修订整包 `.2` 已完成离线校验

最终目录 `.work/ci/runs/vantage-20260928-onboarding/release/vantage-20260928.2/`，79 项 manifest 文件校验通过。源码提交 `64976128623f8b1f83eba4c1c9cc02c70ff9b093`，组包时工作区 clean；APT release 为 `20260928.6`。manifest SHA-256 `90af9a73cf354e8d6bedcbd009d39d7a36c15a49f19ad482ebfda2fb6dbd53b9`。

- rootfs 原始 SHA-256 `fc66e9b71f33f2b99059ba253bcbd840cfa82e2f1a002f279933783c8b0ea8e1`；1479 个安装包，文件系统检查 0，fresh-account/home 两项检查通过。
- product 为 12,460,376,064 字节，小于 13,194,330,112 字节逻辑容量；SHA-256 `fc84d4771d2ab94cc67b71204159542cf6007fae4aaedbfa9d6bd457cffced1c`。4682 条路径及元数据验证通过，保留只读 APK 的 ARM64 JNI 库。
- 包内 `VALIDATION.md`、`offline-verification.json` 和 `reports/display-runtime-acceptance.json` 明确区分离线校验和已配置账户实测。该新包没有再次清数据刷入，`clean_install_accepted=false`；旧 `.1` 的人工修复结果不转记为新包首装通过。
- 归档完成后删除本 run 的 v3 product/rootfs/host 展开暂存，保留正式包、恢复输入、原始/压缩 rootfs、精确仓库快照及证据；共享增量构建目录和固定源码依赖保留供后续维护。当前设备保持已配置账户、scale=3、自动刷新率，无障碍调试已关闭。


## Android density 修订整包 `.3` 已完成离线校验

目录 `.work/ci/runs/vantage-20260928-density/release/vantage-20260928.3/`。使用 APK 2.10、APT release 20260928.7，首次显示默认由 Android density 与 360 逻辑宽度保护计算；已有选择及渲染模式补偿保持。当前账户实测范围与刷新状态边界见 [85 篇](85-phone-display-size-policy.md)。

- 组包源码 `7744314c7a6afecb4af9a29beb467463a1d74a29`，工作区 clean；manifest `df42f11ada903c86bfcc8d4198411c894feff8c0751a2667fe339982da84f39b`，84 项文件与设备 spec 离线校验通过。
- rootfs SHA-256 `fc528853fd9c56dd400ee34f2df3c658b4fb8e6be9f92fc3f7ee793ff7f03c0c`；1479 个安装包，文件系统检查 0，fresh-account/home 契约通过；rootfs 和 host 模板均没有已有 kwinoutputconfig.json。
- product 12,460,355,584 字节，低于分区容量；SHA-256 `dd4e8e25cd7a6e4ec9ed76a10a6dad7d3c51e21f9123231e9b757d09a4966266`。4682 条路径/元数据通过；两份 APK 与实机安装文件一致，三份只读 ARM64 JNI 库逐一核对哈希。
- 包内 `VALIDATION.md`、`offline-verification.json` 和 `reports/density-runtime-acceptance.json` 明确记录 `clean_install_accepted=false`。仅已有账户升级及显示测试，未再次刷写或清数据；旧版本的首装经历不转记为本包验收。
- 已删除本轮 product/rootfs/host 展开暂存，保留正式包、镜像/种子、精确仓库、源码/实机证据及恢复输入。另在核对原 SHA 后删除旧 run 可由 41 个原厂分片重建的 `stock/super.raw.img`，记录在旧 run `super-raw-cleanup.json`；原厂分片及旧正式包保留。空间始终高于 60 GiB 预留线，清理后约 66 GiB 可用。


## 通用经验、spec 档案与旧 product 清理

本轮通用方法已纳入三段式 skill 的 `references/kernel-compatibility.md`、`build-isolation.md` 及既有新机型/首启/工具指南。机型知识入口为 [W2WV spec 配套档案](../profiles/devices/motorola/vantage_cn/W2WV36.55-75-15-knowledge.md)，同目录另保存提取器实际使用的 stock identity；原执行 spec 和 fastboot adapter 未改字节，既有包的 SHA 绑定保持。

按用户要求删除旧 product 构建：G100 assembled-v3 至 v8、X70 product-assembled/v1 至 v3、G100 原始 product/root 和 X70 product-stock，共 11 个目录；当前 clean 基线、最新 product、全部发行包和恢复输入保留。删除前核对 8 条发行包 product 引用的 SHA，删除后核对保留文件 inode/长度不变。旧报告/seed/元数据归档到 `.work/audits/product-cleanup-20260928/build-metadata/`；Termux APK/prefix/稀疏写入器先提升到 `.work/deps/product-seed-20260928/` 并更新本地 X70 组装脚本，不再依赖旧 G100 展开树。

文件系统实际可用量由 70,679,048,192 增至 95,583,150,080 字节，释放 24,904,101,888 字节（约 23.2 GiB），清理后约 89.0 GiB 可用。Btrfs 共享及正式包硬链接保留导致实际收益小于目录 du 合计，不将旧目录总大小称为释放量。清理 JSON/原脚本快照在上述 audit 目录；未删除 rootfs、内核或其他项目缓存。
