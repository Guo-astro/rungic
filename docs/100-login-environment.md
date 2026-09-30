# 桌面会话的登录环境：~/.local/bin 与 ~/.profile（2026-10-01）

- **现象**：用户在手机终端里运行 Codex 这类安装脚本，装完后当前终端找不到新命令；在用户用过的其他 Linux 系统上，同样的操作“自动生效”。
- **用户的要求**：查清原因并修复。

标注：“实测”指在 G100 S 上查看过；其余为分析和设计。

## 原因

- **没有哪个 shell 会自动重新加载环境**：安装脚本往 `~/.bashrc` 末尾追加 `export PATH="$HOME/.local/bin:$PATH"`（实测：手机上是第 120 行，2026-09-30 22:39 写入），并提示在当前终端执行 `export`。
- **在别的系统上“自动生效”**，是因为 PATH 里本来就有 `~/.local/bin`：安装脚本刚把程序放进去，下一条命令就能找到。bash 只缓存找到过的命令，所以不需要重新加载。
- **我们的会话 PATH 里没有 `~/.local/bin`**（实测）：
  - plasmashell 和 systemd 用户管理器的 PATH 都是 `/etc/environment` 的值：`/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:/usr/games:/usr/local/games:/snap/bin`；
  - `~/.profile` 是 Ubuntu 默认的，里面有“目录存在就加 `~/.local/bin`”这一段，但从来没被执行过。
- **根源在会话的启动方式**：
  - 普通的 Ubuntu 桌面由 SDDM 或 GDM 登录，它们通过用户的登录 shell 启动会话，会读 `/etc/profile` 和 `~/.profile`，整个桌面都继承这个 PATH；
  - 我们的桌面由 systemd 单元 `rungic-plasma-session` 启动，`desktop/session` 只加载了 `/etc/profile.d/proxy.sh`；
  - 终端里的 bash 是非登录的交互式 shell，只读 `~/.bashrc`，安装脚本加的那一行只对之后新开的终端生效。
- **另外一个差别**：Ubuntu 的 `~/.profile` 只在 `~/.local/bin` 已经存在时才加它，目录是登录后才建的，就要重新登录；Fedora 的 `~/.bashrc` 则无条件加上。systemd 的 file-hierarchy(7) 把 `~/.local/bin` 定为用户程序的位置。

## 修复

改在共享层：会话启动时补上显示管理器会做的那一步，不给 Codex 单独打补丁。

- **`desktop/login-environment.py`**，安装为 `/usr/libexec/rungic-login-environment`：
  - 在子进程里分别执行 `sh -c '. /etc/profile'` 和用户的登录 shell（`$SHELL -l`，与 SDDM 的 wayland-session 做法一致），取出导出的环境；
  - 带 10 秒超时，出错时丢弃结果，所以 profile 出错或卡住都不会影响会话启动；
  - **PATH**：用登录 shell 的结果，并按 Ubuntu 的顺序保证 `~/.local/bin`、`~/bin` 在最前面，目录还不存在也放进去；
  - **用户自己的导出**：登录 shell 的结果里，比 `/etc/profile` 多出来的变量。会话自己决定的变量（Wayland、GPU、代理、输入法、XDG 目录等，见 `PROTECTED`）不会被覆盖；
  - **`/etc/profile.d` 里 PATH 以外的设置不导入**：`maliit-framework.sh` 会把所有 Qt 和 GTK 程序的输入法切到 Maliit；`flatpak.sh` 会改 `XDG_DATA_DIRS`；
  - 输出 `export` 行，最后一行是 `RUNGIC_LOGIN_VARS`，列出导出了哪些变量。
- **`desktop/session`**：
  - 加载代理和 GPU 设置之后，`eval` 上面的输出；
  - PATH 写进 `rungic-session.env`，供 `rungic-plasma-user-exec` 使用；
  - PATH 和 `RUNGIC_LOGIN_VARS` 列出的变量导入 systemd 用户管理器，这样 systemd 启动的单元和程序也用同一个 PATH。
- **实测预览**（部署前在手机上以桌面用户身份运行）：只导出了 PATH，即 `~/.local/bin:~/bin:` 加上原来的系统路径；用户的 `~/.profile` 没有别的导出。
- **没有改的**：安装脚本写进 `~/.bashrc` 的那一行保持原样，它只会让 PATH 里出现重复的一项，不影响使用。

## 离线核对

`tools/ci/test_login_environment.py` 覆盖了这些情况：
- 目录还不存在时，`~/.local/bin`、`~/bin` 也在 PATH 最前面，并且顺序与 Ubuntu 一致；
- `~/.profile` 里的 PATH 和用户导出会被带上，受保护的变量不会；
- bash 作为登录 shell 时会读 `~/.profile`；
- profile 出错或卡住时，只剩 PATH，会话不受影响；
- 输出能在会话 shell 里被正确 eval；
- 会话脚本和打包确实用上了这个小程序。

## 实机（G100 S，2026-10-01）

- **部署**：用开发覆盖装上 `rungic-plasma-session 0.510+dev20260930t154603…`（docs/97），基线是发布 20260930.10。apt 核对通过，会话重启完成（Plasma Mobile ready，native Wayland）。
- **会话**：KWin、plasmashell、rungic-voice-agent 都是 active。
- **PATH**：plasmashell、systemd 用户管理器、`rungic-session.env` 三处都是 `~/.local/bin:~/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:/usr/games:/usr/local/games:/snap/bin`。
- **模拟终端**：用 plasmashell 的 PATH 开交互式 bash，启动之后才往 `~/.local/bin` 放一个新程序，同一个 shell 的下一条命令就运行成功了；`command -v codex` 找到 `~/.local/bin/codex`。测试用的程序已删除。
- **冒烟验收** 9/9 通过：会话、单元、新崩溃、显示几何、文字输入、摄像头、休眠抑制、播放、录音（`.work/acceptance/unreleased/20261001-005040/`）。
- **还没验证的**：在屏幕上的终端里亲手运行一次安装脚本；修复前就开着的终端要重开一次。
