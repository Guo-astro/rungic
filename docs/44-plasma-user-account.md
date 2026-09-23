# 首次账户与密码设置

2026-09-23。用户要求在安装/首次启动时由本人设置用户名密码，替代没有可用Linux密码的初始状态。

## 复用调查

- [Plasma Setup 6.6.6](https://github.com/KDE/plasma-setup/tree/v6.6.6)：现成首次启动向导，含账户模块。查实际`src/auth/authhelper.cpp`：标准useradd与通过stdin调用chpasswd；通过sudo/wheel等附加组提供管理身份。其bootutil与display-manager前置启动服务面向整机登录，不能直接接管本机Android嵌套Wayland入口。
- [KDE移动适配进展](https://blogs.kde.org/2026/03/12/making-plasma-setup-more-mobile-friendly-a-sok26-midterm-update/)：已有窄屏适配；仅凭页面可显示不能认为屏幕键盘/启动架构适合本机。
- Ubuntu AccountsService 23.13.9-8ubuntu5.2与现有`kcm_users`用于后续账户管理。Ubuntu默认polkit管理员组是sudo，需要本人的密码。

选用Android首次入口表单与小型root安装助手，后台沿用发行版shadow/PAM账户工具；不安装另一个整机显示管理器。上游源码原样保存在`.work/refs/plasma-account-20260923/upstream/`，含原许可；实现未复制上游C++代码。

## 结构

`AccountSetup.java` → 已获Magisk授权的固定`moto-plasma account-setup`命令 → stdin JSON管道 → LXC root `/usr/local/libexec/moto-plasma-account-setup` → `usermod`/`chpasswd`。

- 用户名32位内、小写字母开头，可包含数字、下划线和短横线；拒绝已有其他UID的账户名。
- 密码由用户在设备上输入两次，至少8字符，最多256 UTF-8字节；不经命令行参数、不记录请求或密码/哈希。Android输入框不保存实例状态或自动填充，表单窗口禁止截屏。
- 保留UID/GID1000和`/home/linux`家目录，实际登录名可以更改；文件所有权、共享目录与原用户配置保留。路径是内部兼容选择，不把显示名冒充登录名。
- 停止会话及用户服务后改名，避免shadow工具拒绝更改正在使用的用户。密码失败时恢复原锁定哈希、附加组与原名；临时状态不标记完成。
- 完成标记`/etc/moto-plasma/account.json`为root所有、0600，只含用户名/UID/版本。已有密码或完成标记的账户不能用首次安装接口重置。
- 服务`User=1000`、user-exec动态查询UID1000的登录名；网络D-Bus授权保留稳定的linux主组。原Phosh策略文件不改。
- 账户加入sudo和systemd-journal，软件管理使用Ubuntu原生polkit密码验证。已移除试验中的PackageKit免密码授权规则；不会设置固定默认密码。
- 手机设备锁定仍由Android管理；设置Linux管理密码不自动重新启用第二层Linux锁屏。
- “用户与密码”桌面入口使用现成`kcmshell6 kcm_users`和AccountsService。

## 验收状态

APK1.5账户页面已部署。输入验证、成功时密码只走stdin、0600完成标记、重复初始化拒绝、失败回滚、已有密码保护共4组自动测试通过，脚本`plasma/account/test_setup.py`。

用户已在设备上完成首次设置并进入桌面。实机确认登录名为`kevinzhow`、UID1000、家目录仍为`/home/linux`，sudo/systemd-journal组有效；会话服务正常。APK1.6更新后再次进入桌面，没有重复要求初始化。密码由用户保管，本地验收材料不包含密码或shadow哈希。Discover内的实际密码认证另行验收，不能用账户创建成功代替。
