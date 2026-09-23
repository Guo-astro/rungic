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
