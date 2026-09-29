# G100 局域网 SSH 连通性（2026-09-29）

当前开发主机实测为 **mibook / Xiaomi Book Pro 14**，不是旧记录中的 K8。下列地址为本次实测，不能作为固定机型参数。

| 节点 | 地址 | 结果 |
| --- | --- | --- |
| mibook | 192.168.5.62 | 起初到手机 ping 全丢、TCP 返回 No route to host，邻居表 FAILED |
| Mac mini | 192.168.5.45 | 到手机 ping 3/3 成功、22 端口收到 OpenSSH banner |
| USB G100 / ZY32M9MRVP | 192.168.5.69 | 反向 ping mibook 2/2 成功；随后 mibook 学到手机 MAC，ping 与 SSH 恢复 |

## 已确认

- G100 与 Linux 共用网络命名空间，ssh.socket enabled / active，IPv4/IPv6 所有地址监听 22；Mac mini 的连接触发 ssh.service 成功启动。
- Android INPUT 为 ACCEPT，检查的输入链没有针对 wlan0 的 ICMP/TCP 丢弃规则。icmp_echo_ignore_all=0；all/wlan0 的 arp_ignore、arp_filter 及 wlan0 rp_filter 均为 0。
- 手机反向通信后，mibook 邻居表从 FAILED 变为手机实际 MAC，随后两轮 ping 为 3/3、2/2 成功。mibook 的 SSH 握手完成，ED25519 主机密钥与 USB 读取的手机公钥匹配，服务端提供 publickey/password；本轮没有使用用户密码或临时加登录密钥。
- 独立广播 ARP 探针最初为 4 次请求 / 0 回复，稍后为 3 / 1；对 Mac mini 的对照为 3 / 2。手机 wlan0 抓包能看到 mibook 的正常 ICMP 请求/回复与手机主动发出的 ARP，但本次抓包没有看到 mibook 的广播 ARP 请求。Wi-Fi 固件可能代处理 ARP，因此不能由内核抓不到包断言空口没有收到。
- 两端均连接 902-5G；手机 RSSI -38 dBm、11ac / 5240 MHz，Android mMulticastDisabled=0。没有修改路由、ARP 参数、无线省电、路由器配置或关闭防火墙。

## 结论与边界

已观察到的直接故障点在局域网邻居解析，早于 SSH 握手；不是 Linux SSH 没有监听。反向通信后连接已恢复，但广播 ARP 回复不稳定，不能称永久修复。现有证据不能区分 AP 广播转发、无线丢包和手机 Wi-Fi 固件/ARP offload，需进一步受控对照后才能修改对应配置；不按厂商名硬编码或用定时 ping 某个开发机掩盖问题。

证据在 `.work/experiments/g100-ssh-connectivity-20260929/`；`mibook-ssh-handshake.log` 的 Permission denied 是刻意禁用所有客户端认证方式后的预期结束，不是再次网络不通。没有验证用户密码登录。
