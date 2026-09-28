# 新机型与新固件接入

适用：未验证机型、同机型固件变化、内核/分区/root 提供者变更。以新基线重新核对；销售名称相同不等于相同设备。

## 1. 建立事实清单

先读项目 [兼容契约](../../../../docs/75-image-build-separation.md)，再对照 [G100 实施复盘](../../../../docs/80-g100-image-installation-retrospective.md)。后者仅证明特定设备组合；前者部分接口仍是设计。

| 类别 | 接入时需要的事实 |
| --- | --- |
| 身份 | 厂商、代号、SKU/渠道、完整 fingerprint、bootloader、Android/API、CPU 架构 |
| 原厂输入 | 来源、固件版本、原包及各分区摘要、恢复方法、AVB 链与回退版本限制 |
| 启动/分区 | A/B 或非 A/B、boot/init_boot/vendor_boot/recovery 实际布局、header/DTB、动态分区几何与文件系统、刷写模式 |
| 内核 | ACK/Kleaf 固定版本、构建编号/工具链、页大小、KMI、OEM 模块版本符号/签名、最小功能增量 |
| 宿主与后端 | root 提供者、SELinux、容器/存储机制、APK/桥协议、显示/GPU/触摸及所选共享后端 |
| 容量 | 只读种子空间、展开 rootfs 和 /data 余量、本机/远端构建峰值及保留量 |
| 纯净化 | 包名、路径、哈希、依赖/角色、移除/排除安装/保留决定、恢复来源 |
| 验收 | 启动必需项、用户要求项、可选能力；每项的观测方法、预期与证据路径 |

原机缺少将由本包安装的 Magisk/LXC，不等于目标方案不兼容。反过来，原机已有这些组件也不能替代清数据后部署验证。

## 2. 形成 spec 与运行实例

跟踪路径：`profiles/devices/<vendor>/<codename>/<firmware>.json`。现有 schema v1 示例是 `profiles/devices/motorola/portov_cn/W1VT36H.1-51-8.json`，根字段如下：

- `schema_version`、`id`：配置版本和唯一设备/固件标识。
- `identity`：`product/device/sku/fingerprint/bootloader`。
- `stock`：OEM archive、boot/init_boot/vbmeta/vbmeta_system/super/product 摘要，product 容量与 AVB 公钥摘要。
- `kernel`：manifest/common 仓库与提交、stock_release、page_size、module_trust_certificate_sha256。
- `release_requirements`：架构、API、电量和空间门槛。
- `deployment`：当前实现中的手机代理配置。
- `purity`：`remove_preinstall/remove_files/disable_packages`。

这不是覆盖所有手机的完整 schema。当前 v1 未完整表达 flash plan、非 init_boot root 入口、后端变体等。遇到新需求，扩展数据契约及读写工具并维护已支持设备回归；不要添加无人读取的字段后宣称已适配，也不要填虚假分区/哈希来通过旧工具。

运行实例另记序列号、ADB 端口、当前槽位、runner/代理、run-id、产物路径和本次授权范围。已有 v1 将代理放在 `deployment`；新设备核实实际环境，不复制旧私网地址。活动槽和具体连接不作为型号能力。

已交付 spec 的 SHA 被 fastboot adapter 和发行包绑定。新增知识优先放同目录 `<firmware>-knowledge.md`，注明适用固件、spec SHA、证据与验收边界，不为补充笔记改写已绑定 spec。真正的执行参数变更则同步更新消费者、adapter 绑定及新包，旧包保持可审计。

原厂提取身份可存成 `<firmware>-stock-identity.json`，供 `prepare_g100_stock.py --identity` 实际消费；必须来自独立核对的实机/固件身份，不能从待验 ZIP 自举信任。X70 已保存此输入。`verify_g100_stock.py --logical-partitions` 的列表须覆盖实际 liblp/AVB 集合；info 文本的 A/B 字样不能推翻真实分区表。名称中含 G100 的工具已有部分显式参数化，使用前查当前 CLI，既不能照抄默认值，也不必重写整套工具。

## 3. 适配工具，避免复制整套流水线

读 [工具地图](tool-map.md)，列出当前实现与目标的差异。选择成本最低的正确复用边界：

- 输入格式相同、仅数值不同：放进 spec 并验证取值与实际设备一致。
- OEM 容器、分区/刷写协议、root 引导或图形接口不同：增加范围明确的适配器，复用哈希、报告、生命周期及首启契约。
- 非 GKI 设备、无法获得匹配基线、未能满足硬要求：如实记录不适用或阻塞原因；不得以同 SoC 镜像替代。完成可独立推进的研究和用户空间工作。

适配器更改要有目标场景的离线计划/失败检查，并回归既有设备计划；静态检查未通过前不发送写入命令。跨组件协议更改同步到宿主、rootfs、首启和验收入口。

Android property 与 fastboot 的 bootloader 字符串可能不同；记录两端精确值和 spec SHA 绑定的 adapter，不用模糊匹配解锁状态或放宽所有机型规则。模式探针分别验证两个方向；一次 ADB→fastbootd 成功不证明 bootloader→fastbootd 或反向 USB 枚举可靠。失联时还须区分主机 USB/沙箱权限与设备状态。

中断续刷不是无条件重跑：先保留已完成阶段的返回值、原包 manifest 和日志摘要，再核验当前身份/槽位/模式，才制定只覆盖剩余阶段的方案。X70 有经专用脚本核验的阶段 7/8 续刷记录；通用安装器没有因此自动获得任意断点恢复能力。

## 4. 能力与结果记录

每项结论至少带：spec/release、实际产物摘要、原机还是候选、方法/版本、预期值、观测值、结果（通过/失败/未知/跳过）、时间及证据路径。跳过附原因；未知硬要求不能提升为通过。

只保存已有工具真实输出，不虚构一个已存在的统一 `capability-report.json` 生成器。需要统一格式时，先定义并实现生产者/消费者，再以现有报告合成；ABI 可比较范围必须保留。

## 5. 从候选到发行

先离线核验，再执行授权的候选启动与完整包清数据安装。最终验收绑定相同 release，记录首次 loading、账户配置与实际桌面。新 GPU 后端须验证 KWin 桌面，单独渲染探针不够；共享能力按任务范围验收。

root 修补产物应注明设备范围；G100 当前包绑定测试序列号。没有跨机证据，不能去掉绑定后直接宣称同型号通用。发行包支持的主机操作系统/架构也需要单独验证。
