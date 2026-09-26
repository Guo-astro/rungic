# 上游组件改为补丁队列：迁移方案与KWin试点

2026-09-26。用户要求按行业最佳实践管理我们对上游组件的修改，不受现有“直接Vendor”约定限制，并先写方案、用KWin试点。本文是方案；试点结果写在文末。调研报告：`.work/research/patch-queue/tooling-report.md`（在`ubuntu:26.04`容器中实测git-buildpackage 0.9.42、autopkgtest 5.55、lintian 2.129、git-ubuntu 1.1，并克隆Kubuntu、Debian Qt/KDE、KDE neon的kwin打包仓库核对）。

## 为什么改

现状：`vendor/`保存15个上游组件的完整源码（789 MB，其中Mesa 414 MB、FFmpeg 112 MB），我们的修改直接写在源码里。问题：

- 看不出“我们改了什么”：修改和上游代码混在同一棵树，只能靠提交历史拼凑；一个提交常含几项功能（例如KWin的`e07d7448`含投屏光标、宿主文本输入、原始宿主输出）。
- 升级上游没有机械流程：新版本要重新导入，再手工重放修改。
- 修改与测试没有对应关系：升级后不知道哪些功能要测；vendor修改目前没有任何自动测试（Ubuntu对kwin、kscreen、plasma-mobile等都以`BUILD_TESTING=OFF`构建，也没有`debian/tests`）。

## 业界做法

| 领域 | 做法 |
|---|---|
| Debian/Ubuntu及衍生版 | 仓库只放`debian/`；上游以原始tarball固定；修改是`debian/patches`中的DEP-3补丁；编辑时由`gbp pq`把补丁展开为提交。Kubuntu（`~kubuntu-packagers/kubuntu-packaging/+git/kwin`）、Debian Qt/KDE团队（`salsa…/qt-kde-team/kde/kwin`）、KDE neon（`invent.kde.org/neon/kde/kwin`）都如此。 |
| Yocto/OpenEmbedded | 配方固定`SRC_URI`与校验和；每个补丁必须带`Upstream-Status`（Pending、Submitted、Backport、Denied、Inactive-Upstream、Inappropriate＋原因）。 |
| postmarketOS、Alpine | 一个仓库放全部配方，源码按版本与sha512下载；补丁为`git format-patch`序列；上游优先。 |
| Android、ChromeOS | 用manifest管理完整fork，每个提交按`UPSTREAM:`/`BACKPORT:`/`CHROMIUM:`分类；适用于大量深度修改的项目。 |

我们是Ubuntu衍生发行版加少量非Debian上游，最接近前两行：**上游只固定不入库、修改为带元数据的补丁队列、仓库只放配方与补丁、测试分层**。

## 目录与文件

```
packages/<源码包名>/
  recipe.json          上游固定信息（见下）
  debian/              完整打包目录：Ubuntu原有内容 + 我们的补丁、changelog、测试
    patches/series     Ubuntu原有补丁在前，我们的补丁在后
    patches/rungic/    我们的补丁（每条一项功能）
    tests/control      autopkgtest
```

- **Ubuntu包**（kwin、kscreen、plasma-mobile、plasma-settings、plasma-keyboard、xdg-desktop-portal-kde、plasma-camera、libcamera、qtmultimedia、wl-clipboard）：`recipe.json`记录源码包名与版本、`.dsc`/orig/`debian.tar` 的sha256、git-ubuntu的`import/`标签、snapshot.ubuntu.com时间点。取源码优先用`apt-get source --snapshot`（archive签名链覆盖到Sources哈希），退回`pull-lp-source`＋sha256核对（它只用Debian密钥环验签，Ubuntu上传者只给警告）。
- **非Debian上游**（Mesa分支、FFmpeg、Snapshot、typesafe-computer-use、arc-cua、LiteRT）：`recipe.json`记录git地址与提交或tarball与sha256；补丁为`git format-patch`序列，元数据同下；打包目录同样放`debian/`（我们本来就产出deb）。
- **我们自己的代码**（桥接服务、APK、语音Agent、诊断工具等）不是上游修改，仍是普通源码，补单元测试。
- **跨包共享的代码**（`android-display-client.h`被KWin与KScreen共用，目前靠符号链接；`androidgraphicsbuffer.h`、`codec-client`、`gpu-allocator-client`）改为从我们的源码构建一个`-dev`包，使用它的上游补丁只写`Build-Depends`与`#include`。补丁无法表达符号链接，同一代码也不应在多个补丁中各有一份。
- 源码缓存放`.work/sources/`，按sha256校验后使用。

## 补丁规范

每条补丁一项功能，`git format-patch`格式（DEP-3明确接受），头部字段：

| 字段 | 含义 |
|---|---|
| `Subject`/`Description` | 做什么、为什么（DEP-3必填） |
| `Author` | 作者（有它可省`Origin`） |
| `Origin` | `vendor`、`upstream, commit:<id>`、`backport, <url>` |
| `Forwarded` | 上游MR/问题链接；`not-needed`须说明原因；`no`表示尚未提交 |
| `Applied-Upstream` | 上游已合入的版本或提交，下次升级时删除该补丁 |
| `Last-Update` | YYYY-MM-DD |
| `X-Rungic-Status` | 取Yocto的取值：`Pending`、`Submitted [链接]`、`Backport [版本]`、`Inappropriate [原因，例如Android宿主专用]` |
| `X-Rungic-Tests` | 覆盖它的测试ID（见测试分层），没有时写`none`并说明，作为待补清单 |
| `X-Rungic-Docs` | 设计与实测文档，例如`docs/58` |

`gbp pq`的`Gbp-Pq: Topic rungic`使补丁导出到`debian/patches/rungic/`。lintian 2.129对`X-`字段不报错；检查脚本要求每条补丁都有上述字段。

## 工具与工作流

新增`tools/pq.py`（替代`tools/stage_vendor.py`与`tools/vendor_debian.py`的相应部分）：

| 命令 | 作用 |
|---|---|
| `fetch PKG` | 按`recipe.json`下载并校验上游到`.work/sources/` |
| `prepare PKG [--version V]` | 在`.work/pq/PKG`建git树：上游源码一个提交、叠加`packages/PKG/debian`一个提交，再`gbp pq import`，每条补丁一个提交 |
| `export PKG` | `gbp pq export`，把`debian/patches`与`series`写回`packages/PKG/debian` |
| `rebase PKG --to V` | 在新上游版本上重放补丁队列，列出冲突补丁 |
| `lint [PKG]` | DEP-3与`X-Rungic-*`字段、`series`一致性、lintian |
| `verify PKG` | 按配方从零准备源码树，与参考树比较（迁移期与`vendor/`比较） |
| `tests PKG` | 列出补丁与测试的对应矩阵；升级时列出冲突或被改写的补丁所需的测试 |

构建：`tools/build_on_device.py`改为把配方与缓存的源码推到手机，`dpkg-source -x`后`dpkg-buildpackage`（`3.0 (quilt)`在解包时应用补丁）；保留现有的完整构建与增量构建两种方式。

**编辑一个上游组件**：`pq.py prepare kwin` → 在`.work/pq/kwin`像普通代码一样修改并提交（新功能一个新提交，修正某功能就修改对应提交） → `pq.py export kwin` → `pq.py lint` → 构建、测试、提交`packages/kwin`。

**升级上游**：`pq.py rebase kwin --to 4:6.6.7-0ubuntu1` → 解决冲突（每个冲突对应一条补丁及其功能） → 删除`Applied-Upstream`的补丁 → `pq.py tests kwin --changed`列出必须运行的测试 → 构建、分层测试、发布验收。

## 测试分层

| 层 | 内容 | 何时运行 |
|---|---|---|
| L0 补丁检查 | 字段、series、lintian；`pq.py verify` | 每次提交 |
| L1 构建时测试 | 上游自带的相关测试（KWin：`xdgshellwindow`、`idle_inhibition`、`inputmethod`、`test_virtualkeyboard_dbus`、`screencasting`、`test_ftrace`等集成测试），加我们为补丁写的新测试（能提交上游的写成上游风格，随补丁一起提交） | 单独的测试构建（`BUILD_TESTING=ON`），补丁改动或升级时 |
| L2 autopkgtest | `debian/tests`：在装好包的系统中检查我们的功能（D-Bus接口、环境变量开关、服务行为）；经`autopkgtest-virt-null`或`virt-ssh`在手机容器中运行，GUI类标`needs-root`、`allow-stderr`、`skippable` | 每次发布候选 |
| L3 系统验收 | 现有`tools/rungic_acceptance.py`场景（相当于openQA层），每个场景标明覆盖的补丁；补上缺失场景（投屏、按住Home唤起语音助手、空闲抑制、配色联动等） | 每次部署（冒烟）与发布候选（完整） |

每条补丁的`X-Rungic-Tests`至少指向一层；指不到的列为待补项。

## KWin试点

| 步骤 | 内容 | 通过标准 |
|---|---|---|
| 1 配方 | `packages/kwin/recipe.json`固定`4:6.6.6-0ubuntu0.1`（`.dsc` sha256 `4fda1d85…`、orig `76314bb5…`、`debian.tar` `f8e51bab…`、git-ubuntu `import/4%6.6.6-0ubuntu0.1`） | `fetch`校验通过 |
| 2 补丁队列 | 按历史重建：`d1301f2e`中的5个历史补丁（android、idle、screencast、screencast-shm、display-settings，已实测能在基线上干净应用）加其后9个提交，`e07d7448`拆为3条；共享头文件改由`-dev`包提供；每条写全字段 | `verify`：准备出的树与现有`vendor/kwin`除`.pc`与符号链接外逐字节一致 |
| 3 工具 | `tools/pq.py`及其单元测试 | 单元测试通过；`prepare`→`export`往返不改变补丁内容 |
| 4 构建与部署 | 从配方在手机上构建，与现有`+moto19`的包比较文件列表；发布并完整验收 | 完整验收15项通过 |
| 5 测试 | 测试构建运行L1所列上游测试；为“最小尺寸大于最大尺寸”补丁写上游风格的集成测试（同时准备提交上游）；建立`debian/tests`与矩阵 | 测试结果记录；矩阵覆盖全部补丁，缺口列出 |
| 6 模拟升级 | 把队列rebase到较新的KWin（Plasma 6.6后续版本或KDE neon已有的6.7.5）并构建，不部署 | 记录每条补丁的状态（干净、冲突、已被上游合入）与耗时 |
| 7 收尾 | 删除`vendor/kwin`，`vendor/manifest.json`与文档同步；AGENTS.md中Vendor约定的修改由用户确认 | 构建与发布只用`packages/kwin` |

## 全面迁移

试点通过后依次迁移：kscreen（与KWin共享头文件）、plasma-mobile（修改最多，约1300行）、plasma-settings、plasma-keyboard、xdg-desktop-portal-kde、wl-clipboard、plasma-camera、libcamera、qtmultimedia，然后是非Debian上游（Mesa、FFmpeg、Snapshot、typesafe-computer-use、arc-cua、LiteRT）。全部完成后`vendor/`删除，仓库中的上游源码只剩补丁。

与Rungic改名（docs/70）的关系：改名的B阶段暂停，等补丁队列迁移完成后再做，这样vendor中的改名只需修改相应补丁，也能用新的测试层验证。

## 风险与待定

- 迁移期`vendor/`与`packages/`并存，构建工具同时支持两种来源，直到对应组件迁完。
- `gbp pq export`首次会把Ubuntu原有补丁改写为`From/Date/Subject`格式（调研实测），接受这次一次性改动，或只导出`rungic/`主题下的补丁。
- 主机没有arm64的binfmt（qemu-user-static未安装），L1/L2目前只能在手机上运行；如需在主机上跑arm64容器，另行安装。
- KWin的`BUILD_TESTING=ON`构建会明显变长，测试构建与发布构建分开。

## 试点进度

（进行中）
