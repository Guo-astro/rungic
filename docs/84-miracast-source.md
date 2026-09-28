# 自研Miracast发送端：不依赖厂商投屏组件

> **状态（2026-09-28晚）：暂缓。** 用户澄清可以使用高通WFD组件，只要求连接不经过Moto Ready For；58篇的引擎A在Ready For停用时4/4连接成功（见58篇），因此不再以本篇为主路径。原型代码移至`shared/android/miracast-probe/`（不编入APK），保留已验证的结论供以后需要时继续。

2026-09-28，G100 S（XT2537-4，SM6435，Android 16），接收端TCL 85Q6H。用户明确目标：投屏不再依赖厂商组件——Moto Ready For（`com.motorola.mobiledesktop*`）与高通闭源WFD栈（`wfdservice`、`wifidisplayhalservice`、`wfdconfig.xml`）。本篇是58篇“引擎B”的调研、设计与实施记录；58篇的引擎A（经Android无线显示框架与厂商栈）在引擎B实机验收前保留为回退。

“已核实”指本机实测或读过源码；“推断”未验证；调研源码存于`.work/refs/miracast-20260928/`（不入库）。

## 现状依赖（已核实）

| 层 | 引擎A的作用 | 问题 |
|---|---|---|
| Moto Ready For | `.core`参与P2P发现；Moto框架把连接交给`mobiledesktop`（`hce`服务） | 仅Moto机型；停用后18:44仍连接成功，只多`Failed to connect to hce service`（58篇），是否影响成功率未做完对照 |
| 高通WFD栈 | RTSP、硬件编码、TS/RTP | 闭源、几乎无日志；平台共用的`wfdconfig.xml`曾超出SM6435编码器（58篇） |
| AOSP `WifiDisplayController` | 扫描、连接、创建WIFI显示 | 连接走厂商`ExtendedRemoteDisplay` |

## 调研结论

| 来源 | 版本/状态 | 许可证 | 用法 |
|---|---|---|---|
| AOSP `frameworks/av/media/libstagefright/wifi-display` | 最后存在于`android-8.1.0_r81`，9.0起删除；约8.5k行C++，已读源码 | Apache-2.0 | 协议主参考：`WifiDisplaySource`（M1–M16状态机）、`TSPacketizer`（PAT/PMT/PCR/PES、AVC与LPCM描述符）、`RTPSender`、`VideoFormats`（CEA/VESA/HH表与`wfd_video_formats`）；依赖ALooper/ABuffer，不能直接编译，按逻辑移植 |
| GNOME Network Displays | 0.99.0（2026-01），2026-09仍有提交，已读`src/wfd/*` | GPL-3.0+ | 只参考接收端兼容经验，不复制代码 |
| Intel WDS（libwds） | 2022归档 | LGPL-2.1 | 解析器与状态参考 |
| MiracleCast | 维护中，主线仅接收端；源端为未合并PR #172 | LGPL-2.1/GPL-2 | 不用 |
| AirPlay发送端DoubleTake | Go，LGPL-3.0，含逆向FairPlay | — | 未测乐播接收端、有法律风险，不作主路径 |
| DLNA | 电视有`MediaRenderer` | — | 拉流延迟数秒，不适合桌面 |

本轮未找到维护中的开源Android源端应用（只能记为本轮未找到）。

### 协议要点（取自AOSP 8.1与GND源码，WFA规范原文未读）

- 源端监听TCP 7236（端口在WFD IE中），接收端来连；源端先发M1 `OPTIONS * Require: org.wfa.wfd1.0`，回应M2，M3 `GET_PARAMETER`查询`wfd_video_formats`/`wfd_audio_codecs`/`wfd_client_rtp_ports`/`wfd_content_protection`，M4 `SET_PARAMETER`下发选定格式、`wfd_presentation_URL`与回显的RTP端口，M5 `wfd_trigger_method: SETUP`，接收端M6 SETUP、M7 PLAY；M16保活为带Session的空`GET_PARAMETER`，每25秒一次；M13 `wfd_idr_request`时立即出IDR（`PARAMETER_KEY_REQUEST_SYNC_FRAME`）。
- 强制能力：CEA 640×480p60 CBP；LPCM 48kHz 16bit双声道。R2接收端接受R1源端，首版只做R1+H.264。
- TS：PMT 0x100、PCR 0x1000、视频0x1011（stream_type 0x1b），LPCM音频0x1100（stream_type 0x83，stream_id 0xBD）；PCR/PAT/PMT至少每100ms；每个IDR前补SPS/PPS。RTP：PT 33、90kHz、每包≤7个TS包（UDP载荷≤1472字节）。
- 兼容（GND/AOSP记录）：session-id≤15字符；源端请求带`;timeout=`会让部分接收端出错；缺保活会在20–40秒断开；RTCP端口为0或同RTP时用RTP+1；忽略接收端native分辨率；TCP连上后约500ms再发M1。

### Android P2P接口（已读packages/modules/Wifi main并实机核对）

- `wifi_display_on=1`时AOSP `WifiDisplayController`已下发源端WFD IE。实测：root `app_process`以`ActivityThread.systemMain()`的系统Context（包`android`、uid 0）初始化`WifiP2pManager`，`requestDeviceInfo`显示`WFD enabled: true`、DeviceInfo 16（源端+会话可用）、端口7236、吞吐50。
- `setWfdInfo`自API 34公开、需`CONFIGURE_WIFI_DISPLAY`（uid 0/1000通过）；WFD信息是全局状态。
- `isChannelConstrainedDiscoverySupported()`本机为true；`discoverPeersOnSocialChannels`/`discoverPeersOnSpecificFrequency`（API 33）可用。
- `WifiDisplayController`仅在其自身扫描或有`mDesiredDevice`时干扰（后者会`disconnect()`拆组），引擎B运行时不调用它。

## 电视何时可被发现（已核实）

- 屏保期间电视停止P2P监听（58篇）。
- 更关键：19:00–19:05连续查找（27次重启查找，每次重启会重新上报已知设备）中，电视只在用户退出屏保后的19:02:45–19:03:07回应，之后两分钟画面仍在等待界面也不再回应。推断TCL接收端只在等待界面出现后的短时间内监听（与“断开后十几秒内总能重连”一致）。监听信道6（2437MHz）。
- 手机侧：连着5GHz家庭Wi-Fi时，框架查找每10秒重启并从全频段开始，高通驱动的P2P扫描多为约1.8秒的全频段扫描，落在2437的探测很少；对发送端的要求是在电视监听窗口内用定向/社交信道快扫尽快发现并立即连接。
- 19:13在2437定向查找与社交信道查找各20秒均未收到任何P2P设备，当时电视状态未确认。

## 设计

原则：Linux拥有桌面与交互；Android只提供P2P、硬件编码和显示合成这些公开能力。

```
KWin输出CAST-1 ─(宿主已有零拷贝Presenter)─▶ PlasmaCastDesktop窗口(SurfaceView)
      放在 DisplayManager.createVirtualDisplay(PRESENTATION, 目标=MediaCodec输入Surface) 上
        SurfaceFlinger合成 ─▶ c2.qti.avc.encoder(H.264, 按MediaCodecList能力) ─▶ TS ─▶ RTP/UDP ─▶ 电视
容器声音 ─▶ “电视”PulseAudio输出 ─▶ LPCM ─────────────────────────────────────┘
P2P：WifiP2pManager（定向快扫+立即connect；手机优先做组主、与家庭Wi-Fi同信道）
控制：RTSP源端（M1–M16），rungic-cast接口与快捷开关不变
```

- 复用：`CastDesktop`接管任意非默认演示类显示，因此私有虚拟显示可直接承载现有桌面、触控板与Docked模式；无需改KWin与宿主Rust。
- 新写：P2P控制、RTSP源端、TS/RTP封装（按AOSP移植为Java）、编码器配置、音频输出。

## 实施顺序

1. **协议原型（root `app_process`，独立于APK）**：P2P发现与连接、RTSP源端、MediaCodec输入Surface绘制测试图（`lockHardwareCanvas`）、TS/RTP、静音LPCM；在TCL上出画面，记录协商参数、M13/M16行为与45秒掉线是否复现。
2. **接入APK**：虚拟显示+`CastDesktop`，真实桌面；声音经PulseAudio“电视”输出；rungic-cast/快捷开关/语音入口改用引擎B，引擎A保留为回退。
3. **收尾**：自动重连、组主与信道选择、整包组件、多台接收端兼容性验证；验收后决定是否移除引擎A及`wfdconfig.xml`挂载。

## 原型实测（2026-09-28，root `app_process`，`shared/android/miracast-probe`）

- 已跑通：`WifiP2pManager`在2437MHz定向查找约3秒发现电视、约4秒建组（电视为组主）；电视连入7236，M1–M7全部成功并发来PLAY；每25秒M16保活正常；硬件编码1920×1080p30 CHP Level 4，60秒与约20秒两次推流无掉线；`p2p0`抓包确认RTP经`local_network`表走P2P网卡；录下的TS经ffprobe识别正确，解码画面正确。
- 电视协商结果：`wfd_video_formats: 38 00 03 1f 000194a0 …`（CEA只有720p/1080p的30/25/24帧，无1080p60；profile CBP+CHP，最高4.2），`wfd_audio_codecs: AAC 00000001 00`（不支持LPCM），`wfd_content_protection: none`。
- 未解决：电视一直停在等待画面，没有显示视频。最可疑的是M4未下发音频（原型只做了LPCM，电视只支持AAC），电视播放器可能在等音频；其次是与厂商栈在M4参数、TS细节上的差异。下一步应抓引擎A会话的RTSP与RTP做逐项对比，并实现AAC。
- `app_process`中画文字会因未加载系统字体触发hwui断言（`gDefaultTypeface`），测试图改用矩形数码管。

## 实机验收

- 在Ready For与高通WFD服务均未参与的情况下（停用`mobiledesktop*`，日志中无`wfdservice`会话）完成：发现→连接→桌面上电视→触控板操作→声音→断开→重连。
- 分别记录：协商结果、编码参数、端到端延迟、稳定时长（至少10分钟，覆盖45秒点）、功耗温度。
