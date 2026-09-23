# Magisk 离线首启 v3：普通应用安装

2026-09-22，XT2537-4 / mumba_cn / ZY32MVJS25，原厂 W1WAA36.48-23-10，槽 a、已解锁。

## 修正 v2 的问题

用户明确指出 Magisk 不支持作为系统应用。v2 在 product/app/Magisk 放置 APK 的方案错误；把它再安装到 /data/app 也可能保留 UPDATED_SYSTEM_APP 标记，不能解决系统应用身份问题。v2 不作为最终交付。

v3 中 product/app 和 product/priv-app 均无 Magisk。完整官方 APK 仅保存在 /product/etc/magisk/Magisk.apk，系统包扫描器不会将它注册为系统应用。

## 首启路径

Magisk 的自定义 overlay.d rc 会在自身 post-fs-data 动作前执行。此处先把临时 stub.apk 替换为指向上述完整 APK 的符号链接，然后按缺失状态准备 /data/adb/magisk。

官方 v31 的 preserve_stub_apk 会打开 APK、保留文件描述符并验证签名；它随后删除临时符号链接。boot-complete 阶段，如果管理器不存在，官方 install_stub/install_apk 流程从已保留的文件描述符安装 APK。这里提供的是完整原始 APK，因而安装的是普通完整应用，无需联网下载。

完整 APK 和原 stub 的签名证书 SHA-256 相同：b4cb83b4dad99f997dbe872f013aa16c14eec41d167021f371f7e1330f273ee6。两者版本注释均为 versionCode=31000。未修改 APK 或签名校验代码。

取消 v2 在 init 的 sys.boot_completed 动作中直接调用 pm 的脚本。管理器安装时序由 Magisk 自己处理。

## 镜像与验证

工作目录：~/moto-clean-W1WAA36/offline-v3/。

product 继续保留 15 个预装删除结果；所有既有文件、权限、所有者、时间戳、符号链接和 SELinux 标签与已验证精简镜像一致。

init_boot SHA-256：6ed2ac5572c3f3c82c298dada2bb3c3af33210375a392ee49ed332aacf7f7943。

实机检查必须同时满足：

- 无网络条件下获得完整 App，APK 内容与本地官方文件相同。
- pm list packages -3 包含 com.topjohnwu.magisk；-s 不包含；dumpsys 中无 UPDATED_SYSTEM_APP。
- Magisk 官方 env_check 返回 0，无下载完整 App、修复环境或系统应用不支持提示。
- 授权后 uid=0、Magisk 31.0、SELinux Enforcing。
- 15 个指定预装未安装，本次更新保留用户数据。

## 实机结果

设备：XT2537-4 / mumba_cn / ZY32MVJS25，原厂 Android 16 W1WAA36.48-23-10，槽 a，bootloader 已解锁。

18:29 完成 product_a、init_boot_a 和两个原厂派生 vbmeta 的刷入，未清空用户数据。

### 离线首启验证

测试前确认 /data/app 中没有 Magisk，备份并移走旧 /data/adb/magisk，保留其他用户数据和授权数据库。飞行模式开启，Wi-Fi 关闭。

启动后，完整管理器自动从固件安装到 /data/app，SHA-256 与未修改的官方 Magisk 31.0 APK 相同：2c8a488b9a5293e578e95ae4f07e3c57aba4feec4a52ca4dd852a2692d6dd4e8。

- 普通应用查询包含 com.topjohnwu.magisk；系统应用查询为空，没有 UPDATED_SYSTEM_APP 标记。
- App 主页与 Magisk 核心均显示 31.0 (31000)，无需下载完整 App 或修复环境，也没有系统应用不支持提示。
- 官方 env_check 返回 0；su 返回 uid=0；SELinux Enforcing。
- 15 个指定第三方预装包均不存在；/data 为 222G；原用户数据标记仍保留。
- init_boot_a 实机 SHA-256 与包内镜像一致。

测试模拟缺少管理器与运行文件的首启状态；本次未再次执行整机恢复出厂。

### 正常重启验证

随后再次重启。Magisk 安装路径、firstInstallTime 和 lastUpdateTime 均未变化，仍为 2026-09-22 18:30:07；运行环境初始化记录时间未变化。确认正常开机不重复安装，也不重复初始化运行文件。

只有没有有效管理器时，Magisk 自身流程才自动安装固件中的完整 APK。运行环境完整时初始化脚本直接退出。

root、普通应用标记和 SELinux 状态在第二次启动后仍正常。测试用飞行模式已恢复关闭。

### 离线镜像验证

4,250 个文件重新解包后 SHA-256 一致，4,689 项 inode 元数据一致。product 的 app/priv-app 中没有 Magisk。init_boot 中的脚本已重新解包逐字校验，官方完整 APK 与 stub 的签名证书及版本注释一致。


官方依据：[package.rs](https://github.com/topjohnwu/Magisk/blob/v31.0/native/src/core/package.rs) 的 preserve_stub_apk/install_stub 与 [rootdir.cpp](https://github.com/topjohnwu/Magisk/blob/v31.0/native/src/init/rootdir.cpp) 的自定义 rc 插入顺序。
