# Plasma容器内的rootless Docker：试验记录与打包方案

2026-09-28，G100 S（XT2537-4）上的Plasma LXC容器（Ubuntu 26.04），内核即整包所用GKI配置（19篇末节）。目的：用Ubuntu软件包在Linux侧提供Docker，取代19篇Android侧的独立Alpine运行时（约340MB，未进整包）。“已核实”为本机实测。

## 结论

- 容器内**rootful Docker不可用**：Plasma容器与Android共用网络命名空间，并去掉了`net_admin`/`net_raw`（`plasma/plasma.config`）。容器即使`--network none`也要在自己的netns里把`lo`拉起、写网络sysctl，host网络在沙箱初始化时同样被拒（`failed to create default sandbox`、`error during container init: operation not permitted`）。
- **rootless Docker可用**：进程在自建的user namespace中拥有完整能力（仅限其中），能在自己的netns里拉起`lo`、建bridge与veth；overlayfs在userns中于ext4上读写正常。不必把`net_admin`还给整个容器，也不碰Android网络。
- 实测（Docker 29.1.3、containerd 2.2.2、Compose 2.40.3、rootlesskit 2.0.2、slirp4netns 1.3.3，均为Ubuntu包）：`hello-world`；镜像已有目录写入；bridge网络出网；`-p 18080:80`在容器内与Android的`127.0.0.1:18080`均可访问；Compose自定义网络内按服务名互访（内置DNS 127.0.0.11）——全部通过。
- **不支持单容器资源限制**：Android把memory/cpu/cpuset/blkio放在cgroup v1，cgroup v2没有控制器，Docker的`--memory`等不生效（`No memory limit support`）。Docker整体仍受Plasma容器的内存上限约束。19篇的Android侧Docker同样受此布局限制（推断）。

## 需要的环境条件（试验中逐一核实）

| 条件 | 原因 | 试验中的做法 | 打包时的做法 |
|---|---|---|---|
| `/dev/net/tun` | slirp4netns/pasta的用户态网络需要TUN；容器设备白名单没有`c 10:200` | `lxc-cgroup -n plasma devices.allow "c 10:200 rwm"`，容器内`mknod /dev/net/tun c 10 200` | `plasma.config`加`devices.allow`与绑定Android的`/dev/tun`。在Android网络中建TUN接口仍需`net_admin`，容器做不到，只能用于自建netns |
| 完整可见的proc/sysfs | Plasma容器是`proc:mixed sys:ro`，嵌套命名空间挂新proc需要一个未被覆盖的实例（LXC nesting的做法） | 容器root挂`/dev/.lxc/proc`、`/dev/.lxc/sys` | `plasma.config`的`lxc.mount.entry`（同LXC `nesting.conf`）。这两个路径上的proc/sys可写，是嵌套的代价，普通程序不写这里 |
| 可写的`/proc/sys/net`（仅rootless Docker自己） | Docker要在容器netns里写`disable_ipv6`等；容器的`/proc/sys`只读 | 只在rootlesskit子进程的mount namespace里`mount --bind /dev/.lxc/proc/sys/net /proc/sys/net` | 服务启动后自动执行 |
| iptables（legacy） | 内核无nftables；Ubuntu默认`iptables-nft` | `update-alternatives`切到`iptables-legacy` | 包的postinst |
| `"iptables": false`＋自加MASQUERADE | 内核缺`xt_addrtype`，Docker的NAT跳转规则失败（19篇同） | 在rootless netns内`iptables -t nat -A POSTROUTING -s 172.16.0.0/12 ! -o docker0 -j MASQUERADE`（`XTABLES_LOCKFILE`指向`$XDG_RUNTIME_DIR`） | 服务启动后自动执行；端口发布走`docker-proxy`，内置DNS仍可用 |
| slirp4netns＋builtin端口驱动 | pasta在rootlesskit中为实验性，且只能配implicit端口驱动；implicit下端口不可达 | `DOCKERD_ROOTLESS_ROOTLESSKIT_NET=slirp4netns`、`…PORT_DRIVER=builtin` | user unit的drop-in |
| 数据目录在ext4 | `/home`是Android的f2fs（`/data`），overlayfs不接受 | `data-root=/var/lib/rungic-docker/<用户>` | 同左，由root预建并归该用户 |
| subuid/subgid | rootless需要从属UID/GID段 | `usermod --add-subuids 165536-231071 …` | 账户创建（`plasma/account`）时分配 |
| 不用`--pidns` | rootlesskit加`--pidns`后，runc用`busctl --user status`判定rootless失败，转去系统systemd被拒 | 不加 | 不加 |
| user unit | `dockerd-rootless-setuptool.sh`把内置的`ip_tables`误判为缺失，其`--skip-iptables`又会给dockerd加`--iptables=false`以外的限制 | 按官方模板手写`~/.config/systemd/user/docker.service` | 包内提供user unit（systemd `--user`） |

其余：安装`docker.io`会启用rootful的`docker.service`/`containerd.service`，在本容器中不可用，已`systemctl disable`。

## 安全边界的一次误判（已更正）

曾把可写的`/proc/sys/net`直接绑定到容器的`/proc/sys/net`，并以为容器root缺`net_admin`就不能写Android的网络参数。实测可以写：内核对uid 0放行网络sysctl的写入。若保留，容器内systemd启动时会把Ubuntu的默认网络参数（`rp_filter`、`ping_group_range`等）写进Android。测试写入的`net.ipv4.conf.lo.forwarding=1`与原值相同（Android的`ip_forward`与各接口forwarding均为1），没有造成改变；随即撤销该绑定，改为只在rootless Docker的mount namespace内绑定，并实测：容器内`/proc/sys`恢复只读；rootless一侧进程写Android的网络参数被拒（`Permission denied`）。

## 打包与部署（2026-09-28，release 20260928.5，提交`edd3f055`）

- **`rungic-docker`**（`plasma/docker`，host构建，已进release的project清单）：依赖`docker.io docker-compose-v2 rootlesskit slirp4netns uidmap iptables util-linux procps`。
  - 用户单元`/usr/lib/systemd/user/docker.service`：slirp4netns＋builtin端口驱动；数据目录`/var/lib/rungic-docker/%U`（按UID，账户改名不丢数据）；`ExecStartPre`检查目录归属。
  - `DOCKERD=/usr/libexec/rungic-docker/dockerd-child`：在RootlessKit子命名空间里只给自己绑定可写的`/proc/sys/net`（来源`/dev/.lxc/proc`），打开转发，给经`tap0`出去的流量加MASQUERADE，读取`/etc/profile.d/proxy.sh`的代理，再以`--iptables=false --ip6tables=false --data-root`启动dockerd。
  - 系统服务`rungic-docker-prepare.service`（开机）：建`/dev/net/tun`（0666），为UID 1000–59999的登录账户补从属UID/GID段（从现有最大段之后分配），建数据目录。
  - postinst切换`iptables`/`ip6tables`到legacy；`environment.d`与`profile.d`设置`DOCKER_HOST`。
- **`plasma.config`**：`devices.allow c 10:200`；`lxc.mount.entry`挂`/dev/.lxc/proc`、`/dev/.lxc/sys`（同LXC `nesting.conf`）。随release的Android侧文件部署，deploy检测到后重启容器；整包的宿主种子取同一文件。
- **设置→服务**（`policy.json`）：新增“Docker（rootless）”（用户单元，默认关闭，风险remote）与“Docker 系统服务（rootful）”（`docker.service`、`docker.socket`、`containerd.service`，默认屏蔽并说明原因）。KCM此前对用户单元只做`daemon-reload`，现在开关可选组时对其用户单元执行`systemctl --user --no-block start/stop`，当场生效。
- **账户设置**：`usermod --login`不会迁移`/etc/subuid`、`/etc/subgid`中按登录名记录的段（实测；G100 S上遗留的`linux:100000:65536`即初始账户`linux`改名后的残留）。`plasma/account/setup.py`改名成功后迁移这两项（新名已有段则不动）；新增两项单元测试，现有测试改用临时文件。

部署：`rungic_release.py deploy 20260928.5 --snapshot never --acceptance none`（按记忆不用快照回滚），更换5个包并重启容器。

实机验收（G100 S，经与服务页相同的后端操作开启：`systemctl --global enable docker.service`、用户`daemon-reload`、`--no-block start`）：
- 系统侧：`/dev/net/tun`、`/dev/.lxc/{proc,sys}`、`rungic-docker-prepare`运行、从属ID段、`/var/lib/rungic-docker/1000`、iptables legacy、三个rootful单元为`/dev/null`。
- Docker：`rootless`＋`seccomp`＋`cgroupns`，overlayfs；`hello-world`、镜像已有目录写入、bridge出网、`-p 18080:80`（容器内与Android均可访问）、Compose服务名互访——通过。用户systemd与plasmashell环境中有`DOCKER_HOST`。
- 安全边界：桌面`/proc/sys`仍只读、写入被拒；rootless的mount namespace内`/proc/sys/net`可写，但其进程写Android网络参数被拒；Android的`lo.forwarding`保持1。
- `rungic-integrity`：清理试验遗留的rootful配置（`/etc/docker/daemon.json`、`/etc/containerd/config.toml`、两个代理drop-in，均不属任何包）后为`clean`。
- 设置→服务界面实测（设置应用须由用户systemd启动，与桌面启动方式一致；从调试入口直接启动时polkit找不到会话，不弹密码框）：
  - 发现KAuth的D-Bus调用使用默认25秒超时，而polkit密码框就在这次调用中等待：输入晚于25秒时页面报`could not contact the helper … reply timeout expired`，但辅助程序随后照常改了单元状态；页面因此不执行用户单元的启停与`daemon-reload`，出现“已关闭但仍在运行”、页面显示与实际不符。此问题也影响SSH开关（83篇未验证项）。修复：`Action::setTimeout`设为10分钟（提交`7ff996ca`，`rungic-plasma-services` 0.340）。
  - 修复后：开启——先弹确认（策略中的警告），确认后弹密码框，37秒后输入，全局启用、用户服务当场启动，页面“运行中”无报错；关闭——会话内免再次输入密码，全局停用、用户服务当场停止，页面“已关闭”。
  - 0.340仅以`dpkg -i`单独装到G100 S验证：合并远端后的release还需要另一台机器构建的KWin（`rungic8`）、kscreen（`rungic5`）等包，本机池中没有，未构建新release；在此之前`rungic-integrity`会报该包与release 20260928.5不一致。
- 未做：整包清数据刷入验收；G100 S上19篇的Android侧Docker尚未迁出停用。

试验留下的手工状态（用户级unit与`daemon.json`、按名字的数据目录、rootful配置）已在部署前后清理；从属ID段沿用试验时为`kevinzhow`分配的`165536`段。
