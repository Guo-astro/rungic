# 系统服务页与可选 SSH 登录

**2026-09-29 用户要求更新：SSH 要自动开启，不能依据下文历史默认值擅自关闭。G100 已恢复 ssh.socket 开机启用和监听；本轮部署及纠正见 [G100 更新记录](research/g100-system-update-20260929.md)，局域网连通性见 [SSH 网络记录](research/g100-ssh-connectivity-20260929.md)。下文保留原设计与验收历史。**

2026-09-28。用户要求：列出容器里被屏蔽（mask）的服务，提供图形界面浏览和重新打开；SSH 做成可以开启的服务，密码和密钥都能登录。

## 出发点（已在 ZY32MVJS25 上核对）

- 容器是 `lxc.net.0.type = none`（`plasma/plasma.config`），与 Android 共用网络命名空间。容器服务监听在手机自己的地址上（当时 `wlan0 192.168.5.60/24`），没有独立的局域网 IP。当前 GKI 的配置是 `CONFIG_MACVLAN`、`CONFIG_IPVLAN` 未启用。
- `rungic-plasma-config` 以包内文件的形式装了 31 个 mask（`plasma/config/systemd-masks.txt`，25 个系统单元、6 个用户单元），其中包括 `ssh.service`、`ssh.socket`。另有 7 个 Ubuntu 自带的 mask，都在 `/usr/lib/systemd/system`（x11-common、sudo、hwclock、cryptdisks 等旧式启动脚本的占位）。
- `openssh-server 1:10.2p1-2ubuntu3.6` 来自 Ubuntu 基础镜像，已经安装。`ssh.socket` 在 `sockets.target.wants` 里是启用状态，只是被 mask 挡住；`/etc/ssh` 下没有主机密钥（镜像里本来就不带）。基础镜像的 `/etc/ssh/sshd_config.d/60-cloudimg-settings.conf` 设了 `PasswordAuthentication no`。
- `sshd-keygen.service` 带 `ConditionFirstBoot=yes`，只在第一次开机时生成密钥，所以之后再开 SSH 也不会生成。
- 容器里没有 `pkexec`。但在会话中由用户 systemd 启动的进程（设置应用就是这样启动的）调用受 polkit 保护的 systemd 方法时，polkit-kde 的密码框能正常弹出（实测 `Manager.Reload`，取消后无改动）。polkit 回落到用户的显示会话 `c5`（Active=yes）。

## 设计

**一份清单，默认值只落地一次。** `plasma/services/policy.json` 安装为 `/usr/share/rungic/service-policy.json`。它把单元按功能分组，每组记录默认状态（`masked`/`disabled`）、原因、依据（recorded 表示有文档记录，inferred 表示推测、未实测，unknown 表示原因未记录）和风险（remote、android、unknown、none）。`rungic-plasma-config` 的 postinst 对每个单元只应用一次默认值，并记到 `/var/lib/rungic/service-defaults`。已经记录过的单元不再处理，所以用户在设置里的改动能在升级后保留。原先包自带的 mask 会在升级时被 dpkg 删除，随后由 postinst 重新创建为本地状态（第一次运行即完成迁移）。`deb-systemd-helper disable ssh.socket` 会记下停用状态，所以 openssh-server 自己升级时也不会重新启用它。

**权限走 KAuth。** 设置页（KCM `kcm_rungic_services`，位于“系统管理”分类）用 C++ 和 QML 编写。改动通过 KAuth 辅助程序 `rungic-services-helper` 完成，polkit 动作是 `com.rungic.services.set` 和 `com.rungic.services.unmask`（`auth_admin`，会话内保持授权）。每次改动只弹一次密码框。直接调用 systemd 的 D-Bus 接口则要分别授权 manage-unit-files、reload 和 manage-units，而且没有接口能改全局用户单元（`/etc/systemd/user`）。辅助程序只处理清单中的单元名，或 `/etc/systemd` 里实际存在的 mask，不执行调用方传来的其他单元名。

参考过的现成方案：
- SystemdGenie：KDE，Qt Widgets 桌面界面。Ubuntu resolute 没有这个包。
- Cockpit 360：resolute 仓库里有。它是网页界面，要多跑一个服务；它不知道每个 mask 的原因，也不能对 NetworkManager 这类会断网的服务单独提示。

两者都没有采用。这个页面的价值在于说明每个 mask 的原因和风险，而这部分只能来自我们自己的清单。

**SSH。**
- `ssh.socket`/`ssh.service` 从 mask 改为默认停用。
- `/etc/ssh/sshd_config.d/10-rungic.conf` 设置 `PasswordAuthentication yes` 和 `PubkeyAuthentication yes`。sshd 以第一次读到的值为准，这个文件排在 `60-cloudimg` 前面；root 仍是 Ubuntu 默认的 prohibit-password。
- `sshd-keygen.service.d/rungic.conf` 清除 `ConditionFirstBoot`，改为缺少密钥时生成，所以每台手机都有自己的主机密钥。
- 设置页的开关在开启时确认一次，然后执行 `enable --now ssh.socket`，并显示连接命令和 ED25519 主机密钥指纹；关闭时执行 `disable --now` 两个单元。

**界面行为。**
- 默认屏蔽的服务：开关打开只是解除屏蔽（unmask），已启用的服务会在下次开机或被调用时运行；关闭则重新屏蔽并立即停止（`mask --now`）。
- 风险为 remote/android/unknown 的组，打开前先确认一次。
- 不在清单里的 `/etc` mask 列在“其他”，可以逐个解除。
- Ubuntu 自带的 `/usr/lib` mask 只显示，不能更改。

**完整性检查。** `rungic-integrity` 不再把清单中默认 mask 的链接算作“无主 mask”漂移；用户改过的单元以 `service` 行列出，仅供参考，不算漂移。

## 能力边界与未验证项

- 清单里标为 inferred 的原因是推测，没有逐个在手机上打开验证后果（例如 chrony 改时间、networkd 改路由）。powerdevil 和 ksmserver 的屏蔽原因没有记录。
- 打开 NetworkManager、wpa_supplicant、networkd 这类服务，可能抢走 Android 的网卡，连带断开无线调试。界面会先警告，但不会阻止。
- 本篇只处理 ZY32MVJS25 的容器；G100 用的是同一套 rootfs 和包，但没有在 G100 上验证。
- 独立局域网 IP 不在本次范围内。可行方向（在 wlan0 上加第二个地址，或在 GKI 中开启 IPVLAN）见本次对话结论，尚未研究实施。

## 实机验收（ZY32MVJS25，2026-09-28）

发布 20260928.3（`rungic-plasma-config 0.306+b1`、`rungic-plasma-services 0.306`）以 `--snapshot never` 部署。部署前的 rootfs 仍保留 20260928.2 的快照，没有改动它。部署结果 ok，完整性 clean，smoke 验收通过。

- **迁移**：`/var/lib/rungic/service-defaults` 记录 31 个单元；重新创建的 mask 有 29 个（31 减去 ssh 的两个），dpkg 不再拥有这些 mask；`ssh.socket`/`ssh.service` 为 disabled，`sockets.target.wants` 里不再有 ssh。
- **页面**：`plasma-settings -m kcm_rungic_services` 正常显示各分组、原因、风险和单元名。
  - 点开关后先弹确认框，确认后弹出 KAuth/polkit 密码框（动作说明为 “Turn on or off a service the Rungic container keeps off by default”）。
  - 在确认框取消，开关回到关闭，系统状态不变。
  - 在密码框取消，同样不改动系统。
- **SSH（以 root 执行辅助程序同样的命令 `systemctl enable --now ssh.socket`）**：
  - sshd-keygen 生成了 RSA/ECDSA/ED25519 三组主机密钥，22 端口在 IPv4 和 IPv6 上监听；`sshd -T` 为 passwordauthentication yes、pubkeyauthentication yes、permitrootlogin prohibit-password。
  - 从 K8 经 VPN 地址 10.77.0.16 连接，服务器提供 `publickey,password` 两种方式，ssh-keyscan 的指纹与页面显示一致。
  - 用临时密钥实际登录成功（uid 1000）；测试后删除了密钥和原本不存在的 `~/.ssh`。
  - 页面随后显示“运行中”，以及 wlan0、tun0 和 Docker 网桥三个地址的连接命令和 ED25519 指纹。
  - 测试结束后 `disable --now` 恢复为默认关闭。
- **解除屏蔽**：`unmask`/`mask --now` 在 tpm-udev 组上往返一次；`rungic-integrity` 在改动期间把它们列为 `service ... (changed in Settings)`，不计为漂移。
- **实测修正**：
  - 确认框原本放在滚动页面内，会居中到整个长页面之外，改为放在窗口 overlay 上。
  - 开关点按后绑定断开，取消后仍显示为开，改为每次点按后重新绑定到真实状态。
  - 处理函数改用 `onClicked`，因为无障碍的 Toggle 动作不发 `toggled`。实测无障碍 Press 仍只翻转 FormSwitchDelegate 的外观、不触发处理函数（疑为其内部开关单独响应），自动化测试需用 `ui_tap`。

未验证：
- 输入真实账户密码后，KAuth 辅助程序完整执行的一次（需要用户的密码）。2026-09-28 以 Docker 开关验证（85 篇）：发现密码输入晚于 25 秒会被报成失败（KAuth 默认 D-Bus 超时），已将动作超时改为 10 分钟后通过；SSH 开关走同一路径，未单独复测。
- 用账户密码的 SSH 登录（服务器已声明支持 password）。
- 从 wlan0 所在局域网的另一台设备连接。
