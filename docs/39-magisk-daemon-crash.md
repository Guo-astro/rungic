# Magisk 31.0 守护进程退出调查

2026-09-23。初次调查按用户要求保持现场，没有重启手机、恢复守护进程或改写授权数据库。随后用户明确要求“重启一下”，已执行重启并恢复root；恢复检查见文末。

结论：**高度确定是此次排查授权时执行的只读 `PRAGMA table_info(policies)`，触发 Magisk 31.0 的 SQL NULL 到字符串转换缺陷。** 该命令由本次助手执行。源代码中缺陷明确存在，隔离复现成功，现场连接中断与该命令吻合；尚未取得 magiskd 本身的完整崩溃栈，因此不把隔离复现冒充实机守护进程栈。

## 现场与时间线

1. 新 Plasma APK 安装成功后，`magisk --sqlite "SELECT uid,policy FROM policies"` 成功，返回已有三项授权。此查询没有 NULL。
2. 新 `plasma` 容器以 `/bin/sleep infinity` 启动，`lxc-attach` 读取初始 forky rootfs 的 os-release 成功。尚未安装 Plasma/KWin，未更换 Android 内核。
3. 随后执行 `magisk --sqlite "PRAGMA table_info(policies)"`，调用端出现 `failed to fill whole buffer`，退出255。logcat保存了 **12:14:37.645，PID6498，Magisk，failed to fill whole buffer**。
4. 之后 `su` 连接失败，报 `Cannot connect to daemon: Connection refused`，并以 SIGTRAP 退出。进程表无 magiskd，仍有原 Phosh、原 Alpine 和新 Plasma 的 LXC 主进程。
5. crash buffer 中保留下来的大量回溯是后续 `su` 客户端，包含音频watchdog及APK调用；不能用这些栈证明 magiskd 的故障指令地址。

实机 `/product/bin/magisk -c` 显示 `31.0:MAGISK:R (31000)`，Build ID `387db137e8f31b78d2d3e30803691c4555cc6da3`。读取出的二进制SHA256与本地原v3固件预置副本完全一致：`44eece7e1faefe3156c289c74b9f747e0d5b029aed84cbeb85be0139fb03d813`。没有证据表明此次换了Magisk二进制。

## 源码中的故障链

固定Magisk版本 `v31.0`，提交 `96221b69fae9910b1c0c75c2f92a4ebb2c2dc698`：

- [`sqlite.cpp`](https://github.com/topjohnwu/Magisk/blob/v31.0/native/src/core/sqlite.cpp)创建的policies表没有给各列指定DEFAULT，`PRAGMA table_info(policies)`的`dflt_value`因此为SQL NULL。
- [`db.rs`](https://github.com/topjohnwu/Magisk/blob/v31.0/native/src/core/db.rs)中的`MagiskD::db_exec_for_cli`在守护进程内遍历每列，调用`values.get_text`拼接输出。
- [`lib.rs`](https://github.com/topjohnwu/Magisk/blob/v31.0/native/src/core/lib.rs)把Rust的`get_text`映射到C++的`get_str`。
- [`sqlite.hpp`](https://github.com/topjohnwu/Magisk/blob/v31.0/native/src/core/include/sqlite.hpp)的`get_str`直接将`get_text(index)`返回的`const char*`转成`rust::Str`；没有NULL保护。
- [SQLite官方接口约定](https://www.sqlite.org/c3ref/column_blob.html)说明NULL值的`sqlite3_column_text`返回空指针。
- v31.0固定CXX子模块为 `topjohnwu/cxx@b09b91554b392523f633b9e3cbe0b43273528c71`，版本1.0.189。其[`Str::Str(const char*)`](https://github.com/topjohnwu/cxx/blob/b09b91554b392523f633b9e3cbe0b43273528c71/src/cxx.cc)先断言非空，再调用`strlen`。在禁用断言的构建中会访问空指针；启用断言时也不能接受此输入。

这能解释为什么一个正常的只读SQL查询会终止整个root服务，而不是返回查询错误。查询没有修改policies，但执行查询的程序自身存在缺陷。调查阶段没有root访问，尚不能检查数据库整体完整性；后续重启恢复后已对本地副本完成只读检查，结果见文末。

## 隔离复现

材料在[.work/refs/magisk-daemon-crash-20260923](../.work/refs/magisk-daemon-crash-20260923/README.md)。使用电脑上的内存SQLite、上游相同建表语句、原版`sqlite.hpp`及固定CXX实现，完全不连接手机Magisk：

| 条件 | 结果 |
|---|---|
| 原始PRAGMA查询＋无NULL保护的转换 | 在第一行`dflt_value=<NULL>`后SIGSEGV，返回-11 |
| `SELECT name FROM pragma_table_info('policies')` | 五个列名全部完成，返回0 |
| 同一PRAGMA，但将NULL转换为空字符串后再构造 | 五行全部完成，返回0 |

复现程序是局部故障链验证，未编译整个Magisk。为免引入完整Rust运行时，测试仅对非空ASCII构造提供成功回调，不消费生成的Rust对象；NULL崩溃发生在这个回调之前的未修改CXX构造函数中。原始程序、保护逻辑、编译参数与输出全部留存，不能将该测试称为完整Magisk二进制验收。

## 处置与恢复方向

已经将查询约束写入AGENTS.md：此版本不向实机Magisk查询可能含NULL的列，优先从固定版本源码读取结构；必要查询只选非空列或显式COALESCE。仓库当前启动/管理脚本检索未找到自动执行该PRAGMA的路径，触发发生于此次手工排查。

本轮抓取的上游master `sqlite.hpp/sqlite.cpp`对应实现仍与v31.0相同；这不是对全部新版本安全性的结论，也没有据此替换设备Magisk。长期修复应在数据库结果到Rust字符串的边界处理NULL并测试相关调用者；本次未部署核心补丁。

恢复需要可用的既有root执行通道启动正确tmpfs中的Magisk daemon，或者通过系统重启恢复开机启动。普通ADB shell不能自行取得已经失效的root。初次调查按用户“先研究”的要求没有执行重启；后续收到明确重启指令才执行。

Phosh容器文件和配置没有被本次Plasma部署修改，但管理调用依赖Magisk，音频watchdog也会反复失败，因此调查阶段不能声称现有桌面的所有功能仍正常。应先恢复root管理，再确认Phosh音频、Docker和新容器状态，最后继续Plasma稳定版部署。

## 用户授权重启后的恢复检查

同日收到“重启一下”后，通过ADB重启手机，`sys.boot_completed=1`；`su -c id`重新返回UID0、`u:r:magisk:s0`，magiskd主进程PID1386。Android全局SELinux仍为Enforcing，Docker沿用此前单独宽松域。

- 只读复制 `/data/adb/magisk.db` 到电脑，现场未见其WAL/journal文件；用电脑SQLite以只读方式执行 `PRAGMA integrity_check` 返回 `ok`。授权UID为2000、10348、10351、10352，policy均为2。没有向运行中的Magisk提交故障PRAGMA，也没有手工改写授权。
- 重启后读取的 `/cache/magisk.log.bak` 同样保留12:14:37.645、PID6498的 `failed to fill whole buffer`，但仍没有原守护进程完整栈。
- Docker自动恢复，`moto-nginx`为healthy；原Alpine LXC手动恢复为RUNNING。新Plasma仍是未完成的引导环境，保持停止。
- 初次打开Phosh时手机处于Android锁屏，外层Surface未就绪。确认锁屏 `secure=false` 后用系统 `wm dismiss-keyguard` 关闭该非安全锁屏，再打开原APK。

另发现独立的重启兼容性问题：GPU `/dev/kgsl-3d0` 的major:minor由原先478:0变成477:0，旧LXC配置仍允许478:0，因此Phoc打开真实节点返回EPERM。设备路径、权限及SELinux标签正常，音频后端可用。

按[LXC设备规则文档](https://linuxcontainers.org/lxc/manpages/man5/lxc.container.conf.5.html)及[`lxc-start -s`接口](https://linuxcontainers.org/lxc/manpages/man1/lxc-start.1.html)，并核对设备已安装工具的帮助输出后，修改外层 `phosh/moto-phosh`：启动前用stat读取KGSL与system DMA heap的当前major/minor，分别以rw和r加入精确规则；配置模板移除这两个写死的编号，保留默认拒绝其他设备。未修改Phosh rootfs中的软件或GPU库，未修改SELinux。原控制脚本、配置及失败日志已在调查材料中备份。

重新完整启动Phosh容器后，控制器返回 `Linux desktop ready (native Wayland)`，Phosh/Phoc进程及会话环境文件均就绪。普通Linux用户执行GPU探针显示 `GL_RENDERER: FD710`、OpenGL ES3.2，硬件绘制读回和GBM DMA-BUF导出均PASS；探针仍输出两条既有Mesa设备信息查询警告，但不影响本次结果。Android音频sink可枚举，空闲为SUSPENDED，此次未做实际听音/麦克风复测。最终root有效、Docker容器healthy、Android全局Enforcing。

本次已验证在重启后产生的新设备号上重新启动与GPU绘制；未为此再次整机重启，也未将运行时修复更新到Fastboot整包。新Plasma引导配置仍待继续部署时同步处理，不能将其视为已可用的第二套桌面。

这次重启恢复服务，没有替换Magisk核心；其NULL转换缺陷仍通过避免有风险的实机查询来规避。
