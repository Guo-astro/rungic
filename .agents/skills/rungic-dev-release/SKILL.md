---
name: rungic-dev-release
description: 本项目改动上机的两条路径：本地开发覆盖（tools/rungic_dev.py，工作区构建，装在已安装发布之上，可见可撤销）与正式发布（提交 → rungic_package 构建 → rungic_release 元包 → 部署、验收、快照）。用于“改完装到手机看看”“部署到手机”“出一个正式发布”“回到发布版本”，以及设计系统/界面改动的实机核对（状态总览截图）。
---

# Rungic 开发覆盖与正式发布

用户于 2026-09-30 要求区分这两条流程。方法和实测结果见 [docs/97](../../../docs/97-local-development-deploy.md)，发布机制见 [docs/61](../../../docs/61-delivery-diagnostics-plan.md)，最近一次发布的经验见 [docs/96](../../../docs/96-desktop-recovery-after-apk-restart.md)。先读 `AGENTS.md`。

## 选哪条

| 情况 | 路径 |
|---|---|
| 试一下改动、给用户看效果、调试 | **开发覆盖**：`rungic_dev.py deploy`，不需要提交 |
| 用户说“提交 / 出发布 / 正式部署” | **正式发布**：提交、构建、部署 |
| 撤销试验 | `rungic_dev.py reset [包]` |

- 不要用 `dpkg -i` 装包，也不要直接替换容器里的文件。那样 apt 和 Discover 会想把包换回发布版本，完整性检查也会报漂移（docs/61）。
- G100 S（ZY32MVJS25）是用户的日常机。装开发覆盖可以，但必须经工具，保证状态里看得见、能撤销。
- 开发覆盖只管容器里的 deb。APK、`rungic-plasma` 控制器和发布清单里的 `android` 文件还没有覆盖机制，要单独安装，并在 docs 中记录。

## 每次开始前

1. **核对本机**（AGENTS.md「网络」）：`hostnamectl`、`uname -m`、`ip route`，以及系统代理。
2. **核对构建机**：在 Mac mini 上执行 `hostname; uname -m; route -n get default; scutil --proxy`，并确认容器 `rungic-build` 在运行。设备包默认在这里构建。
   - 不要用 `--host phone`：它会把 Qt、CMake 等构建依赖装进日常机，重任务还会引发低内存查杀。
3. **核对手机**：`adb devices -l`，按序列号确认是哪台手机。adb server 是共用的，不能 `kill-server`；也不要断开 Wi-Fi。
4. **看手机现状**：`python3 tools/rungic_dev.py status`，看基线发布和已有覆盖；`python3 tools/rungic_release.py status`，看 rootfs 快照状态。

## 开发覆盖

```sh
python3 tools/rungic_dev.py deploy <包>...      # 后台运行，不要套短超时
python3 tools/rungic_dev.py status
python3 tools/rungic_dev.py reset [<包>...]
```

- **包名**：取 `packaging/<名>/package.json` 里 `paths` 覆盖到改动文件的那些包。`tools/rungic_package.py list` 里显示 stale 或 uncommitted 的就是它们。
- **上游组件**：改了 `packages/<名>` 的补丁队列（例如 `plasma-mobile`），直接 `deploy <组件名>`。它经 `build_on_device.py` 在 Mac mini 上构建，第一次是全量构建，可能要几十分钟；只覆盖发布里登记的那几个二进制包。`reset <组件名>` 一次撤销全部（docs/97）。
- **版本号**：`<该包在发布里的版本>+dev<UTC 时间>.<短 sha>[.dirty]`。再次部署时，之前的覆盖保留，基线不变。
- **部署后逐项核对**：
  - 记录里 `[verify] apt=ok`，也就是每个覆盖都满足 Installed 等于 Candidate；
  - 可选：在容器里跑 `apt list --upgradable` 和 `apt-get -s dist-upgrade`，确认不涉及任何 rungic 包；
  - 完整性检查：`release.dev` 列出了覆盖；如果 `summary.state` 是 drift，逐项看是不是部署前就有的；
  - 记录在 `.work/dev-deploy/<时间>-deploy/`。
- **会重启什么**：按 `release/packages.json` 的 `user_restart`、`service_restart`、`session_restart` 重启。比如 `rungic-design` 会重启 plasmashell 和语音浮层。提前告诉用户。
- **rootfs 快照**：开发覆盖不做快照；上一次发布的快照没 commit 也不影响开发部署。但之后执行 `rollback --snapshot` 会连覆盖一起丢掉。

## 正式发布

1. **提交到 main**：按逻辑分组提交，提交信息末尾带 attribution。`rungic_package.py` 和 `rungic_release.py build` 都要求干净的提交。
2. **构建包**：`python3 tools/rungic_package.py list` 找出 stale 的包，再 `build <包>... --host macmini`。版本是 `0.<提交数>`。
3. **生成元包**：`python3 tools/rungic_release.py build --note "…"`，得到 `YYYYMMDD.N`。它会查询手机上 coupled 包的版本，开发覆盖不影响这一步。
4. **处理快照**：上一次部署留下的快照还在时，部署会中止。要问用户：commit 上一版（接受它）再部署，还是用 `--snapshot never` 部署。不要替用户决定。
5. **部署**：`python3 tools/rungic_release.py deploy <版本>`。
   - 要在后台运行，不要加客户端超时：经 Wi-Fi 会超过 10 分钟，2026-09-30 的一次部署就是被 590 秒超时杀掉的（docs/96）。
   - 顺序是：快照 → 安装 → 写 pin → 清掉开发覆盖（记录里的 `dev-overlay` 步骤）→ Android 侧文件 → 重启 → 完整性检查 → 冒烟验收。
   - 验收失败会自动回滚到快照。
6. **部署后**：看记录 `.work/deploy/<时间>-<版本>/deploy.json` 的 `result`，以及 `rungic_dev.py status`：覆盖应当为空，基线就是新发布。新快照要等用户接受后，再执行 `rungic_release.py commit`。
7. **写进 docs**：在对应篇目里写版本、提交、包数、各步结果和验收边界。研究结论、离线校验和实机结果要分开标注。

## 界面和设计系统改动的核对

- **本机离线**：`python3 tools/design_gallery.py local <目录> [--section A,B] [--rev <提交>]`。
  - 用 PySide6 渲染 `desktop/design/qml` 的状态总览（需要先执行 `sh tools/dev-setup.sh`）。
  - `--rev` 渲染某个提交的版本，用来做改动前后对照。
- **手机**：`python3 tools/design_gallery.py phone <目录>`。以桌面用户身份、用 offscreen 平台运行已安装的 `rungic-design-gallery`，不在用户屏幕上开窗口；每节每种主题各一张，另拼一张 `sheet.png`。
- **已知限制**：software 后端不画 `MultiEffect`，所以 Thumbnail 和 LivePicture 的示例图是空的。这不是回退；这类控件要在真实会话里另行确认。
- 截图和记录放 `.work/verify/<日期>-<主题>/`。

## 改这些工具时

- 离线测试不能碰手机。`tools/conftest.py` 会拦住 `rungic_device._run`，测试一旦走到 adb 就直接失败。
- 部署流程里新加的设备操作，要走调用方模块自己的 `run`，比如 `rungic_release.run`，或者把 runner 作为参数传进去。这样测试里的替身才能拦住它。2026-09-30 曾有一个测试因此删掉了真手机上的开发覆盖（docs/97）。

## 汇报

- 说明走的是哪条路径、覆盖或发布的版本、重启了什么；
- apt 和完整性检查的结果，其中已有的漂移单独列出；
- 截图的位置，以及哪些没有验证到。
