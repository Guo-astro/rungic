# 为什么不做成 Linux 发行版

最初目标是评估 **postmarketOS**，后来看了几个 “Android 上跑 Linux” 的方案。结论：**这台机短期内不该走主线 Linux 移植**，GSI 才是能用的系统层替换。

## postmarketOS / 主线内核

不可行（至少不是几周能做完的活）。

- pmOS 设备树里没有 `mumba` / XT2537。
- SoC 是 SM6435（parrot / Netrani Lite）。高通新中端的 GPU、显示、调制解调器、相机、充电都还绑在厂商模块上。
- 运行中的 kernel 是 **GKI 6.6.87-android15 4K**。真正驱动硬件的是 `vendor_dlkm` / `system_dlkm` 里的闭源 `.ko`，不是一份能直接 `make defconfig` 的板级树。
- 主线要重新点亮：UFS、面板（1080×2400 120Hz）、触控、Wi-Fi/BT、调制解调器、充电、指纹。每一项都是独立坑。
- 没有现成的下游 CAF/msm-5.15 板级仓库可以 “改 dt 就开机”。

pmOS 两条路都不通：

| 路线 | 问题 |
|---|---|
| 下游（用原厂 kernel 配 pmOS 用户空间） | 需要能编译、能匹配 module ABI 的完整 kernel 源码和 defconfig；摩托罗拉这代基本不给 |
| 主线 | SoC 支持度不够，工作量等于新开一款机 |

## 保留原厂 kernel、只换 Linux 用户空间

理论上就是 “Android kernel + 非 Android userspace”。实际产品形态有这几种，都不等于一台正常 Linux 手机：

| 方案 | 是什么 | 对本机 |
|---|---|---|
| Termux / proot | 应用里的 Linux | 随时能装，不是系统替换 |
| chroot / LXC 在 Android 上 | 完整用户空间，显示仍走 Android | 有 root 之后可以做 |
| Halium / libhybris | 用 Android 的 HAL 跑 Ubuntu Touch 一类 | 需要设备专用 port，mumba 没有 |
| 自己做 ramdisk + systemd 挂上 vendor 模块 | 等于从零做 Halium | 不划算 |

“做一个新镜像，kernel 原厂、系统换成 Linux” **不是刷一张 `system.img` 就完**。Android 的 `system` 假定 zygote、hwbinder、vndbinder；Linux distro 假定 udev、DRM、NetworkManager。中间缺一层 HAL 翻译。GSI 能开机，正是因为它仍然是 Android 用户空间，vendor 接口没断。

## mayukh4/linux-android

仓库本质是 **在 Android/GKI 上跑 Linux userspace 的实验**，不是 pmOS 那种发行版移植，也不是通用 root 方案。

- 仍然依赖能开机的 Android kernel 和厂商模块。
- 显示、输入、射频通常还是半残或走 Android 服务。
- 他写的 “root 方案” 是 Magisk/KernelSU 一类 Android root，不是把设备变成 Linux 后的 sudo。本机最后用的也是这条：GSI + Magisk。

## NativOS（orailnoor/NativOS）

同样是 “Android 底层 + 另一套桌面/用户空间” 的方向，没有 mumba 适配。投入产出比低于直接刷 GSI。

## 实践上采用的路线

```
原厂 boot / init_boot / vendor_boot / vendor / vendor_dlkm
        +
官方 AOSP 17 GSI 替换 system
        +
原厂 vbmeta（关掉 verity）
        +
Magisk 打在 init_boot
```

这是 Treble 设备的正路：kernel 和 HALs 原封不动，只换 framework。DSU 证明 GSI 能点亮 1080×2400@120Hz，然后才永久刷入。
