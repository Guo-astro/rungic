# 内核配置增量与 ABI 对照

适用：新 ACK 代际、启用 LXC/namespace 配置、OEM 模块 CRC 或 Rust 符号异常。方法来自 [X70 接入记录](../../../../docs/83-x70-air-pro-onboarding.md)，具体提交、预留槽、工具链和验收计数只适用于该固件，不作为其他内核的默认值。

## 先建立能复现原厂的对照

- 锁定 ACK commit/tree、实际同步的每个工具仓库、Clang/Rust、BUILD_NUMBER、页大小、LTO 与配置。分支名或只固定 common commit 不足以复现 Kleaf 构建。
- 使用同一工具链先构建原厂配置对照，再引入最小功能增量。若对照 CRC 已不一致，先定位来源/配置/工具问题；不要靠更改模块 CRC、导出名称、vermagic 或关闭 KMI strict 使结果“通过”。
- 稀疏 checkout 的版本 stamp 应使用实际仓库的固定 manifest 和 Kleaf 支持的参数，不能因缺少无关仓库而接受 unknown 版本。补丁源码与构建树逐文件核对，最终 Image 回读配置、boot 回读 payload/头部。

## C 布局相同仍可能改变 ABI

gendwarfksyms 使用类型描述计算 CRC。把两个 KABI 预留槽放进同一个替换 union，即便 sizeof 和偏移不变，也可能丢失第二个槽的类型描述。先用小 C/header 复现、DWARF dump、pahole 和原厂对照定位，再决定采用该版本支持的单槽宏或保留原声明的有类型 helper；后者必须验证大小、对齐和槽位相邻。不要把 X70 的槽号或 task_struct 偏移硬编码进其他目标。

## Rust Binder 与 extended modversions

- 对照固定版本的 `kernel/module/version.c` 和 modpost。extended CRC 数组与 NUL 分隔名称必须正确配对，兼顾尾部终止符；不能截断长 Rust 符号或在 extended 存在时只验 legacy 表。
- namespace/SYSVIPC 开关可能同时改变 C 导出、bindgen 匿名类型名称、生成 Default impl 的顺序及 Rust 符号消歧编号。C ABI 修复后剩少量 Rust 差异时，比较生成绑定和 impl 顺序，而非仅比较源文件文字或结构大小。
- 需要补导出时先核对同提交实现与上游修复，保留命名空间语义，纳入独立 KMI 允许列表。bindgen 参数调整只针对有证据的类型，不全局屏蔽生成代码。X70 的具体补丁由 `packages/gki-android16-6.12/` 管理。

## 报告范围与启动验证

分别记录模块总数、引用总数、GKI 可比较匹配/差异、非 GKI 引用。其他 OEM 模块存在同名导出只证明名称提供者，不能称为跨模块 CRC 或签名验证。证书恢复报告绑定实际 Image，说明修改区域与区域外不变；不能伪装成原厂未修改内核。

离线 ABI、模块信任和 boot 封装通过后，再使用该设备已验证的启动路径。运行中确认候选版本、模块实际载入、Android/SELinux、namespace 等必需能力并回读启动镜像；这仍不等于 LXC/桌面及整包清数据首装通过。
