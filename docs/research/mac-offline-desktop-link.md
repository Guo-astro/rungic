# MacBook 无外部网络直连手机桌面：opendrop-rs 评估

2026-09-29，源码与接口调研，随后完成G100无线能力只读实机检查及在用驱动二进制核对；未部署、未做手机/MacBook互通实测。用户澄清：重点是不依赖路由器和互联网的直连；Mac App 查看手机上的桌面模式。

**本轮实机结论：G100现有无线驱动声明monitor，但monitor网络设备没有发送回调，原版filin所需的原始帧发送通路不具备，不能直接使用内置网卡完成AWDL双向直连。** 证据与具体固件边界见文末。此结果不代表所有高通手机或修改后的驱动/固件都不可能实现。

## 结论

`opendrop-rs` 中的 **filin/AWDL 层与需求相关**：它把 Apple 无线点对点链路暴露为 IPv6 网络接口，理论上可以在其上运行自定义桌面串流，不必使用 AirDrop 文件传输。不能因 AirDrop 本身只传文件，就否定 AWDL 对本题的价值。但仓库不是可直接安装到当前手机的远程桌面方案；最大的未决条件是 Android 厂商无线驱动/固件是否支持所需的原始帧收发与时序。

若只要求无路由器、无互联网，优先验证 **Android LocalOnlyHotspot → Mac 普通 Wi-Fi 加入 → 本地桌面串流**。若进一步要求“不切换 Wi-Fi、不加入热点，打开 App 就自动发现直连”，则单独评估 filin；不能把热点方案当作已经满足后一种交互。

## 来源、版本与许可

本次执行端现场核验为 mibook/x86_64，Wi-Fi 地址 192.168.5.62，默认路由 192.168.5.1。GNOME代理模式 none，但 KDE `kioslaverc` 指定 HTTP/HTTPS 192.168.5.45:6152；已测试连通，源码获取使用该代理。环境配置文件另有旧代理地址，未将其当作当前有效配置。源码/网页快照位于 `.work/research/mac-desktop-20260929/`。

| 来源 | 本轮读取版本 | 许可/用途 |
|---|---|---|
| [opendrop-rs](https://github.com/ayourtch-llm/opendrop-rs) | `dccc798e244363eb92d35e3c52e9a913188dda91`，提交日期2026-06-28 | Cargo声明GPL-3.0-only；读取filin底层及luftlift收发实现 |
| [Apple Network includePeerToPeer](https://developer.apple.com/documentation/network/nwparameters/includepeertopeer)、[Apple DTS解释](https://developer.apple.com/forums/thread/751839) | 在线文档2026-09-29读取；API含macOS 10.14+ | 仅接口研究，不复制实现 |
| [Android LocalOnlyHotspot](https://developer.android.com/develop/connectivity/wifi/localonlyhotspot) | 页面更新2026-09-16，API26+ | 官方接口研究；明确创建的网络没有互联网 |
| [Apple Wi-Fi Aware](https://developer.apple.com/documentation/wifiaware)、[Mac支持说明](https://developer.apple.com/forums/thread/827887) | 文档及2026-05 Apple DTS答复 | 当前不能据Mac Catalyst可导入框架推断Mac无线硬件/API可用 |
| [KRDP](https://github.com/KDE/krdp) | `f1e9d7cb5ea94ee8bf7e935201623147349e2182`，master声明6.8.80 | 核心源码LGPL-2.1-only OR LGPL-3.0-only OR LicenseRef-KDE-Accepted-LGPL；不是当前手机6.6.5的保证 |
| [Sunshine](https://github.com/LizardByte/Sunshine) | `f309ef6577c48dd0a0c20883127e66d180248769`；latest release另为v2026.914.233613 | GPL-3.0；读取KWin/PipeWire采集与编码器选择 |
| [Moonlight Qt](https://github.com/moonlight-stream/moonlight-qt) | latest release v6.1.0 | GPL-3.0；macOS接收端候选，未构建 |
| [gst-plugins-rs WebRTC](https://github.com/GStreamer/gst-plugins-rs/tree/ba57447c8696c07b0aacd9944430cc8d4bb8e9e4/net/webrtc) | 查询main为`ba57447c8696c07b0aacd9944430cc8d4bb8e9e4`，读取同轮main的Cargo/README/webrtcsink实现 | 插件MPL-2.0；共享串流组件候选，尚未固定部署版本 |

## AWDL具体能做什么、卡在哪里

- `filin-rs/src/lib.rs`实际使用Linux `AF_PACKET`、radiotap、nl80211、`/dev/net/tun`及`IFF_TAP`，创建awdl0、收发原始802.11帧、做选主/同步/信道调度。不是在普通UDP上模拟AWDL，也不是只编译ARM64即可用。
- Mac端自定义App可以通过Network.framework的`includePeerToPeer`加入系统点对点接口的发现/连接流程；Apple把AWDL视作实现细节。与filin的自定义服务发现、IPv6 scope、实际路由及持续连接仍须验证。Mac端不应照搬filin的Linux网卡实现。
- `luftlift`实现`/Discover`、`/Ask`、`/Upload`和归档传输；自定义Host App无需复用这一层。README中的AirDrop BLE唤醒缺口，不等于运行自定义Mac App时一定有同样限制，也不等于自定义发现已经验证。
- 上游主要声明Apple→Linux文件接收实测；硬件例子是外接Atheros carl9170。Realtek rtw88即使报告monitor能力也可能不能注入数据帧。上游还记载单无线电大传输停滞、原始注入缺少MAC重传等限制；不能将文件传输成功外推为稳定低延迟桌面串流。
- 本项目Wi-Fi由Android管理，LXC共享宿主网络。root权限不能凭空补出固件不支持的monitor/injection/TSFT；直接切wlan0模式可能干扰Android Wi-Fi及现有Miracast。后续G100检查确认monitor存在但标准发送回调缺失；G100S/X70未在本轮核验，不能跨机型推定。

## 无网连接方式比较

| 方式 | 无路由器/无互联网 | 与MacBook互通及成本 |
|---|---|---|
| Android本地专用热点 | 满足；不需要移动数据 | Mac以普通Wi-Fi终端加入；最适合先做基线。热点生命周期、频段、凭据交付、系统防火墙与Mac加入流程需实测 |
| filin AWDL | 协议上满足 | 有潜力实现类似AirDrop的邻近直连；手机驱动/固件适配和持续吞吐是主要风险，保留为研究路线 |
| Android Wi-Fi Direct | 满足 | 不应假定Mac存在与Android WifiP2pManager对等的公开接口；让Mac以普通STA加入手机P2P组是另一路径，仍涉及加入SSID，未验证 |
| Wi-Fi Aware/NAN | 协议上满足 | Apple当前官方支持设备表列iPhone/iPad；DTS明确Mac当前不支持。不能作为MacBook的已可用方案 |
| USB | 满足 | 备选有线链路。ADB转发适合研发但需调试授权；产品化USB网络需核验手机的NCM/ECM gadget和Mac驱动，不假定Android默认USB共享兼容Mac |

热点方案中的发现、配对、信令必须在两端本地完成；若使用WebRTC，直连网段可用host ICE候选，不能把公网信令/STUN/TURN设为必需条件。是否需要手动加入SSID、是否保留Mac已有Wi-Fi连接，是产品取舍，未获用户进一步约束。

## 与现有桌面的复用关系

目标链路：KWin手机输出或既有CAST-n第二输出 → PipeWire → 共享H.264硬编 → 本地连接 → Mac App。输入扩展可复用RemoteDesktop portal/EIS等桌面接口。先验证单屏查看，再增加键鼠与音频；不为Mac另建一套Android硬件访问通路。

已有证据见[65篇](../65-agent-screen.md)、[48篇](../48-plasma-media-pipelines.md)、[74篇](74-vaapi-feasibility.md)。48篇后续修复记录表明原生尺寸录屏有吞吐限制，不能沿用早期“配置60fps”作为持续60fps保证。第二输出现有无人观看降速策略也要把远程观看纳入，避免收起浮窗后串流只有5fps；应以消费者状态管理，不能让Mac与浮窗相互覆盖watched标记。

串流实现初步比较：

- **GStreamer/WebRTC**：最贴近已有`rungich264enc`；上游webrtcsink支持H.264输入，但内置编码器码率控制有按名称适配的逻辑，未识别本项目插件。当前插件关键帧请求已映射MediaCodec，bitrate属性仅READY可改；动态拥塞反馈需在共享编解码接口补齐，不能宣称现成全兼容。
- **KRDP**：现有源码通过KPipeWire编码、提供portal/EIS及KWin采集；不会直接调用GStreamer硬编插件。可作为标准远程桌面基线，Mac客户端兼容与手机编码性能待验。
- **Sunshine/Moonlight**：已有KWin直采、PipeWire和Mac客户端；Sunshine编码器表没有rungic桥，不能把其VAAPI/Vulkan路径等同本机KGSL/MediaCodec可用。还需核验输入后端。改造成本需与GStreamer复用路线比较。

以上为选型研究，不表示已完成Mac桌面互通。Wi-Fi连接方案与视频协议独立，不因选WebRTC/RDP就要求外部网络。

## 下一步实机验收边界

1. 固定目标手机型号/固件及Mac型号/macOS；现场核对连接归属、无线能力、Android权限及LXC网络，不套用历史设备状态。
2. 本地热点基线：关闭蜂窝数据、断开外部AP，在没有公网服务条件下验证发现、授权、双向socket、吞吐/时延/丢包和重连，再传实际桌面；不是只看Wi-Fi关联成功。
3. 若要求AWDL：先只读核对nl80211能力、驱动/固件、monitor与普通联网并发；有依据后再隔离测试原始帧注入、TSFT同步及Mac自定义服务。不能在当前工作的wlan0上直接运行filin自动配置。
4. 桌面测试从1080p30目标开始，测端到端延迟、文字清晰度、持续温升/功耗、后台/熄屏、丢包恢复和停止后的资源释放；这些都是待验目标，不是性能承诺。回归手机主屏、现有投屏及网络恢复。

## G100只读实机检查与发送路径核对

用户随后授权检验。执行主机重新核验为mibook/x86_64，代理仍为KDE配置192.168.5.45:6152。`adb devices -l`与5038分别枚举：USB G100在**5038 / ZY32M9MRVP**；另有无线G100S，未操作后者。每条设备命令显式指定端口与序列号，root多命令通过stdin交给`su -c sh`。

### 设备和运行环境

- XT2533-4 / portov，固件`motorola/portov_cn/portov:16/W1VT36H.1-51-8/e9ec8-e96731:user/release-keys`，槽位`_a`。
- 内核`6.6.87-android15-8-g86c6642d582e-ab14676406-4k`，aarch64，SELinux Enforcing。Android普通代理设置为null；容器profile指定192.168.5.45:6152。本轮设备侧不下载文件。
- 在用无线模块`qca_cld3_adrastea`；`ethtool -i wlan0`报告平台驱动icnss2。phy0属于`22800000.qcom,icnss`，不据模块代号推断精确芯片型号。`con_mode=0`。
- `/dev/net/tun`存在；Android声明wifi/direct但未声明wifi.aware。后者不用于推断AWDL能力。

### 内核能力查询

Android与容器没有iw。使用容器已有Python，经NETLINK_GENERIC只发送`CTRL_CMD_GETFAMILY`及`NL80211_CMD_GET_WIPHY`：一次按wlan0的ifindex查询（与filin `supported_iftypes()`相同），一次带`SPLIT_WIPHY_DUMP`做完整分片查询。两种结果一致；没有发送SET/NEW/DEL，没有切换模式或创建网卡。

- supported iftypes：`managed(2), AP(3), monitor(6), P2P-client(8), P2P-GO(9)`。
- software iftypes：未返回。
- monitor只出现在独立的并发组合（最多2个monitor）；没有monitor+managed、monitor+AP或monitor+P2P组合。因此不能承诺监听与现有普通联网/投屏共存。
- **原版filin的`--check`只检查monitor声明，因此按相同判据会通过；这不能验收注入。** 本轮未编译或运行filin，以相同内核查询核对其判据。

### 当前二进制给出的阻碍

只读取回`/vendor/lib/modules/qca_cld3_adrastea.ko`：

- SHA256：`fb06e48bb5ffafbcf87bba6b61feca72f6d8fca38134371d6b35d917604e8730`。
- ELF Build ID：`38ec36bef0eeaaf8b11cdb8200e93abee743c720`；与`/sys/module/qca_cld3_adrastea/notes/.note.gnu.build-id`读到的**已加载模块**完全一致。
- 反汇编`hdd_set_station_ops`：调用`cds_get_conparam`，与4（global monitor）比较；普通模式选择`.rodata+0x6098`，monitor选择`.rodata+0x6738`作为netdev_ops。
- 普通表`+0x20`位置（`.rodata+0x60b8`）有指向`hdd_hard_start_xmit`的ABS64重定位；monitor表对应`.rodata+0x6758`为全零，且**没有重定位**。monitor表仅见stop/uninit/get_stats相关引用。这证明标准monitor设备的`ndo_start_xmit`缺失，而非只因符号搜索没有找到函数。
- filin依赖AF_PACKET向monitor设备发送radiotap/802.11动作帧和数据帧；没有上述TX路径，不能通过这个现成接口完成AWDL选主/同步与双向数据通信。简单放行能力检查或增加用户态权限不能解决。

公开源码旁证：[Motorola qcacld-3.0，提交dff1deca7b2a6c6b25359a209c1f68d5f3f96f2d，wlan_hdd_main.c](https://github.com/MotorolaMobilityLLC/vendor-qcom-opensource-wlan-qcacld-3.0/blob/dff1deca7b2a6c6b25359a209c1f68d5f3f96f2d/core/hdd/src/wlan_hdd_main.c#L6116)。分支`android-16-release-w1vt36h.22-20`，**不是本机W1VT36H.1-51-8精确源版本**，仅用于解释结构；文件采用ISC许可文本。其monitor ops也未注册ndo_start_xmit，注释明确不发送。最终判断由本机二进制支持，不依赖把邻近固件源码当成一致版本。

同类研究[kimocoder/qualcomm_android_monitor_mode](https://github.com/kimocoder/qualcomm_android_monitor_mode)区分监听与注入，提及其他旧机型的注入研究；不能将其监听开启命令或QCACLD-2案例直接套到本机QCACLD-3。

### 结果、保留状态及后续取舍

这是**能力查询实测＋静态发送路径核对**，不是AWDL收发实测。未切换con_mode、未断开Wi-Fi、未注入无线帧、未更换内核/模块、未修改SELinux。结束时con_mode仍为0，wlan0仍UP/LOWER_UP，p2p0保持DOWN。

不继续在当前网卡盲目切monitor做发送测试：现有证据已定位标准TX入口缺失，切换只会中断现有联网，无法弥补该缺口。TSFT字段实际质量、信道切换时延、AWDL发现和Mac串流均未验收。

若坚持AWDL，需要单独研究厂商驱动/固件的原始TX路径和可维护的注入实现，或采用有已验证注入能力的外接无线网卡；不能把工作量称为“编译filin即可”。对“不依赖外部网络”的产品目标，本地专用热点仍是优先验证路线，但本轮没有启动热点或完成Mac互通。

全部原始证据在`.work/research/mac-desktop-20260929/g100-probe/`：`identity.txt`、`driver-paths.txt`、`container.txt`、`nl80211_probe.py`、`nl80211.json`（含原始netlink报文）、`wireless-state.txt`、`qca_cld3_adrastea.ko`、`loaded-build-id.bin`、`station-ops-disassembly.txt`、`ops-evidence.json`、`ops-relocations.txt`、`after-state.txt`及固定提交源码。二进制和日志不加入源码目录。
