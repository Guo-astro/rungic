# Plasma Mobile 应用商店

2026-09-23，Ubuntu26.04ARM64。

## 选择

使用现成[Discover](https://apps.kde.org/discover/)6.6.6 + PackageKit1.3.4的APT后端，与系统Qt/KDE、Mesa KGSL及媒体桥共享依赖。已安装`plasma-discover`、`apt-config-icons-hidpi`，APT下载完整AppStream/DEP11与图标元数据，实际Discover能显示应用介绍、版本及安装按钮。

比较[Plasma Mobile官方推荐应用](https://plasma-mobile.org/apps/)和本机ARM64仓库：所列应用去重后12个均有包。Flatpak不是本轮默认来源，因为其独立图形运行时还需按[GL扩展机制](https://docs.flatpak.org/en/latest/extension.html)接入本机KGSL驱动，不能假定现有系统Mesa桥自动适用于所有沙箱运行时。没有因此断言Flatpak无法支持。

## 应用清单

| 应用 | Ubuntu包 | 当前安装版本 |
|---|---|---|
| Angelfish | angelfish | 25.12.3-0ubuntu1 |
| Arianna | arianna | 25.12.3-0ubuntu1 |
| Journald Browser | kjournaldbrowser | 25.12.3-0ubuntu1 |
| KleverNotes | klevernotes | 1.2.5-1build2 |
| Kontrast | kontrast | 25.12.3-0ubuntu1 |
| Marble Maps | marble-maps | 4:25.12.3-0ubuntu1 |
| Marknote | marknote | 1.4.1-1 |
| Plasma Camera | plasma-camera | 2.1.1-2build1 |
| 计算器 | kalk | 25.12.3-0ubuntu1 |
| 录音机 / Recorder（同一个App） | krecorder | 25.12.3-0ubuntu1 |
| 时钟 | kclock | 25.12.3-0ubuntu2 |
| 天气 | kweather | 25.12.3-0ubuntu1 |

12个应用已经通过Discover相同的PackageKit后端批量安装；日志`.work/refs/plasma-store-20260923/packagekit-apps-install.log`，调用身份是已获授权的安装管理员，不能冒充用户已完成Discover界面的密码验证。Kalk正确AppStream地址为`appstream://org.kde.kalk`，加`.desktop`会匹配失败。

## 授权与代理

本次临时试过只允许签名仓库事务的免密码polkit规则；用户随后明确要求真实用户名密码，已从设备移除该规则，并删除本地待部署源文件。首次账户设置见44篇；今后沿用Ubuntu的sudo组管理员与polkit密码验证。

**Discover反复要求输入密码（2026-09-24修复）**：

- **原因**：会话由`moto-plasma-session.service`经PAM创建时没有seat，logind把它视为非本地会话。从plasmashell启动的程序（Discover等）在`user@1000.service`下，polkit按用户的显示会话判断，该会话同样不是本地会话，于是对它们一律采用polkit的“any”默认值`auth_admin`：每一步都要密码，且不保留授权。
- **Flatpak的放大效应**：一个Flatpak应用会拆成应用本体、运行时、GL、编解码与语言扩展等多个ref分别部署，每个ref都要一次授权，于是安装VSCode这类应用要输入多次密码。修复前`pkcheck --process <plasmashell>`对Flatpak与PackageKit安装均返回`auth_admin`。
- **修复**：服务加`Environment=XDG_SEAT=seat0`（systemd把服务环境传入PAM，pam_systemd据此把会话挂到seat0；容器内seat0无VT，无需vtnr），会话成为`seat0`上的本地活动会话。
- **修复后发行版默认策略生效**（未新增任何规则）：
  - Flatpak安装/卸载：`yes`。依据`/usr/share/polkit-1/rules.d/org.freedesktop.Flatpak.rules`，sudo组用户在本地活动会话中免密码。
  - PackageKit（apt）安装：`auth_admin_keep`，输入一次后同一进程约5分钟内不再询问。
  - apt卸载：上游默认`auth_admin`，每次都要密码。

**Flatpak在LXC中的沙箱（2026-09-24修复）**：在Discover中安装VSCode（`com.visualstudio.code`，extra-data类型）时，所有运行时都已下载，部署应用本体这一步失败，flatpak随后回滚删除了刚装的运行时。根因是两处容器限制，与bubblewrap 0.11.1、flatpak 1.16.6源码核对如下：

1. **`bwrap: cannot open /proc/sys/user/max_user_namespaces: Read-only file system`**
   - flatpak给每个新沙箱加`--unshare-user --disable-userns`，用来禁止沙箱内再建用户命名空间（防逃逸），不应去掉。
   - bwrap实现时在自己的子用户命名空间里，经原`/proc`写该sysctl。这个值按用户命名空间独立，只影响沙箱本身。
   - LXC的`proc:mixed`把`/proc/sys`挂为只读，所以写入失败。
2. **`bwrap: Can't mount proc on /newroot/proc: Operation not permitted`**
   - 沙箱新建PID命名空间时要挂新proc。内核只在该挂载命名空间里已有“完全可见”的proc时才允许。
   - LXC在`/proc`上叠加了`/proc/sys`、`sysrq-trigger`、`boot_id`等遮盖挂载，使`/proc`不完全可见。
   - 不带新PID命名空间的bwrap可以运行，带了就失败。

**修复**：在容器init（`plasma/init`）中处理，其余部分不变：

- 只把`/proc/sys/user`重新挂为可写，`/proc/sys`其余部分保持只读。
- 在仅root可进入的`/run/moto-proc`再挂一个未遮盖的proc，满足内核的可见性检查。
- 失败时只记日志，不阻止容器启动。

**实测**（容器重启后）：

- 沙箱内写全局sysctl被拒（Permission denied），嵌套`unshare -U`被禁止。
- VSCode完整安装，`flatpak run`可进入沙箱，图形窗口正常出现。

**剩余**：flatpak以root执行的安装后触发器（桌面文件关联、图标缓存、MIME数据库）使用`--unshare-net`，root在新网络命名空间中配置回环需要`net_admin`，而容器按设计去掉了该能力（保护Android网络），因此这些缓存更新会报`loopback: Failed RTM_NEWADDR`。应用本身以普通用户身份在用户命名空间中运行，不受影响；应用照常出现在菜单中。

用户指定代理仍为`http://192.168.5.45:6152`，APT全局代理有效。PackageKit1.3.4的命令行是`pkgcli`；带http_proxy的CLI会尝试按logind会话设置代理，在LXC attach上下文返回“failed to get the session”，所以批量CLI去掉其代理环境，由APT已配置的代理负责下载。桌面/浏览器的代理环境不删除。

定制Mesa7包与KWin5包整体hold，避免通用更新覆盖图形桥。当前PackageKit更新清单未提出替换它们，见`packagekit-updates.json`；不意味着未来所有第三方软件源的依赖求解都已测试。

## 功能边界与待验收

安装成功与硬件功能可用分开：

- Plasma Camera2.1.1是Qt6并直接访问libcamera；已有Camera2→PipeWire桥服务Snapshot/Firefox，不能直接证明Plasma Camera可拍摄。需单独适配libcamera入口。
- KRecorder使用Qt6音频输入，已有PulseAudio麦克风桥是可复用基础，仍需在实际界面完成录制回放。
- Angelfish使用QtWebEngine；普通浏览和浏览器沙箱待实测，不能把Firefox专有FFmpeg硬编解码桥验收直接当它的结果。
- Marble Maps的自动定位仍需Android定位桥；手动地图不依赖该接口。KWeather可先手动选城市。
- KClock的Android息屏定时唤醒尚无AlarmManager桥，不承诺容器被冻结后闹铃仍可靠。
- Journald Browser通过用户加入systemd-journal组读取Linux日志，范围不含Android全部系统日志。

Discover内安装/卸载、当前账户密码认证与这些应用GUI冒烟测试待用户完成首次账户设置后继续；这里只记录已验证的安装与元数据结果。
