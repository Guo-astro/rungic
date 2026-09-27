# 工具地图与当前实现边界

2026-09-28 根据仓库源码核对。执行前重读目标工具参数及实现；下表是入口索引，不是所有手机可直接执行的固定命令链。所有路径相对仓库根目录。

## 源码与工具入口

| 阶段 | 当前入口 | 使用边界 |
| --- | --- | --- |
| 原厂提取/验证 | `tools/prepare_g100_stock.py`、`tools/verify_g100_stock.py` | 内含 portov 固件、格式及分片假设；新机型先适配 |
| 设备/输入预检 | `tools/ci/preflight.py` | v1 spec、已核验 OEM manifest/verification；要求已授权 ADB 和匹配的原机状态，不是纯 bootloader 安装前提 |
| 上游配方 | `packages/*/recipe.json`、`tools/pq.py` | prepare/export 补丁队列；遵循当前 CLI |
| GKI 构建依据 | `packages/gki-android15-6.6/recipe.json`、`kernel/targets/gki/lxc_defconfig`、`kernel/README.md` | 固定版本配方与历史记录；尚无覆盖所有机型的一条 GKI 构建命令 |
| ABI | `tools/ci/module_abi.py` | 比较 symvers 与 OEM 模块，保留未覆盖引用的范围 |
| 模块信任 | `tools/ci/restore_module_trust.py` | 核验基线与证书、输出报告；证书恢复方法不对任意 Image 自动成立 |
| ARM64 包 | `tools/build_on_device.py`、`tools/rungic_release.py` | 固定配方构建、collect 和版本化包集合；仓库快照成熟度见 77 篇 |
| ARM64 rootfs 安装环境 | `tools/ci/arm64_chroot.py`、`tools/ci/rootfs.Dockerfile` | QEMU/真 chroot，检查所在 runner 的 namespaces、binfmt 和容量 |
| rootfs 镜像 | `tools/ci/build_rootfs_image.py` | 接收已准备的 root 树和 release，生成 ext4/压缩种子、包锁及报告；自身不是完整包下载器 |
| APK | `plasma/build-apk.sh`、`tools/ci/apk-builder.Dockerfile` | Android 入口构建；保持指定开发签名身份，不混入其他凭据 |
| 宿主种子 | `tools/ci/build_host_seed.py` | 输入 runtime、rootfs-tree、repo 与 lxc/plasma enter 二进制 |
| 纯净 product | `tools/ci/clean_product.py` | EROFS + product/preinstall 的命名、xattr 和 SKU 策略假设 |
| 完整 product | `tools/ci/assemble_product.py` | 加入 APK/JNI、种子、首启及权限；输入必须与 spec/容量匹配 |
| Magisk 引导 | `tools/ci/inject_magisk_seed.py` | 在已正确修补的 init_boot 中注入 bootstrap，不负责通用 root 修补 |
| 整包组合 | `tools/ci/assemble_release.py` | 报告交叉核验、打包安装器/fastboot、生成 manifest；现有布局仍专属于已验证方案 |
| 刷写 | 生成包中的 `flash.sh` / `flash.py` | 源文件 `tools/ci/flash_release.py` 依赖同目录 manifest；不要直接在源码目录执行刷写 |
| 安装检查 | `tools/ci/accept_release.py` | 指定 release/serial/ADB 端口，检查当前实现约定；不替代用户首次配置及实际桌面证据 |

## 必须重新核对的 G100 假设

当前 `assemble_release.py` / `flash_release.py` 仍假定：

- `super.img_sparsechunk.*` 命名与 OEM manifest 结构；固定需要 vendor_boot/dtbo/recovery/pvmfw 等文件。
- 槽 a、`product_a`、`boot_a`、`init_boot_a`、特定 vbmeta 分区；先恢复 super 再写 product。
- Motorola `oem fb_mode_clear` 和 bootloader 版本表示；fastbootd 切换路径及设备返回值。
- 从原厂 vbmeta 派生 flags=3 的具体方案；这不是其他设备默认应采用的 AVB 配置，更不意味着可以重新锁定 bootloader。
- bootloader 电压阈值为代码常量 3700 mV，独立于 preflight 中按 spec 核对的电量百分比。
- Linux x86_64 主机、Python 3、随包 fastboot；Magisk 修补 init_boot 及现有首启机制。

新设备在上述任一项不适用时，先扩展配置/适配器与校验；不能仅修改 JSON 身份后运行旧刷写器。32 个分片是 G100 输入事实；组包器虽动态枚举分片，其他 OEM 提取工具仍可能固定数量。

## 参数化使用示例

以下变量须先绑定到本次核验过的输入，不提供旧设备序列号或固件默认值。先从仓库根目录 `source tools/work-env.sh`，让开发缓存留在 `.work/`。可用各工具 `--help` 查看当前参数。

```bash
python3 tools/ci/preflight.py "$device_spec" "$stock_dir" \
  --serial "$device_serial" --adb-port "$adb_port" --output "$run_dir/preflight.json"

python3 tools/ci/module_abi.py "$kernel_symvers" "$oem_modules" \
  --output "$run_dir/kernel-abi.json"

python3 tools/ci/build_rootfs_image.py --root "$rootfs_tree" \
  --release "$package_release" --output "$rootfs_output" \
  --size-gib "$rootfs_size_gib" --firefox-version "$firefox_version"
```

最终组合器所需路径参数：`--spec`、`--stock`、`--product-image`、`--product-report`、`--boot`、`--init-boot`、`--init-boot-report`、`--rootfs-report`、`--host-report`、`--kernel-abi-report`、`--package-lock`、`--img2simg`、`--fastboot`、`--output`；另需实际 `--serial`、`--fastboot-bootloader-value`、`--release-id`。当前用硬链接收集部分载荷，输入与输出须位于支持该操作的文件系统；跨盘归档后重新核验完整性。

组合器已做多项摘要核对，但 ABI 报告没有自动证明与最终 boot 的全部来源关系。执行者仍需串联内核输出、封装过程、信任报告与最终摘要；不得以组合器退出 0 替代缺失的来源证据。

离线校验只运行生成包：

```bash
bash "$release_dir/flash.sh" --verify-only
```

实际刷写只在已授权且通过目标核验后执行包内入口。`--yes-wipe` 是实际清数据开关，不能用于探测或当成无副作用 dry-run。`--verify-only` 不访问设备，也不证明设备匹配。

刷后诊断入口（需要正常 Android ADB/root，不能成为用户首次安装必须手工完成的步骤）：

```bash
python3 tools/ci/accept_release.py "$release_dir" \
  --serial "$device_serial" --adb-port "$adb_port" \
  --output "$run_dir/install-acceptance.json"
```

## 按修改范围选择检查

- 引导变更：`tools/ci/test_magisk_bootstrap.py`，加对应 shell 语法检查。
- 刷写器变更：`tools/ci/test_flash_progress.py` 的隔离假设备检查；新布局还需自己的计划与失败场景验证。
- APK/首启状态变更：检查 `FirstBootState.java` 与实际共享控制入口，验证缺失/旧 release/失败不放行、ready 后准备账户。
- 镜像产物：对应文件系统校验、包检查、manifest 回读和用户范围内的清数据实机流程。

隔离测试和受控 UI 状态都不能替代整包首启证据。不要为了文档或 skill 变更执行手机测试或重刷。
