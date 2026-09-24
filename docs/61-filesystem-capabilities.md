# 文件系统与容器能力审计

应用把数据放在哪个目录，就依赖那个目录所在挂载支持的文件操作。挂载缺一项能力，所有在那里用到这项能力的应用都会出问题。所以问题出在挂载时，要在挂载这一层修，不逐个修应用。本篇记录各挂载实际支持哪些操作，以及检查工具和处理原则。

## 起因：微信反复提示“数据库损坏”（2026-09-25）

- **现象**：微信4.1登录后提示数据库损坏并自动修复；清空数据重新登录后依旧，每次启动都卡很久，然后再修复一次，无限循环。微信的提示建议检查目录权限。
- **原因**：
  - 微信把账号数据库放在`$XDG_DOCUMENTS_DIR/xwechat_files`。`~/Documents`是指向`~/Shared/Documents`的链接，也就是Android共享存储。
  - `~/Shared`是bindfs挂载（`plasma/shared-storage`），原先带`--direct-io`。FUSE对direct-io打开的文件拒绝可写的共享内存映射（`mmap MAP_SHARED`返回`ENODEV`）。
  - SQLite的WAL模式需要这样映射`-shm`文件，于是每次访问数据库都返回`disk I/O error`。微信的数据库全部是WAL模式（`*.db-wal`、`*.db-shm`）。
  - 权限不是原因：这个挂载确实改不了权限位（一律0666），但不影响SQLite。
- **修复**：去掉`--direct-io`。
  - 这样读写走内核页缓存。FUSE在每次重新打开文件时丢弃旧缓存，挂载本身又有`attr_timeout=0`，所以Android一侧的修改在Linux下次打开时可见。
  - 只有一种情况理论上可能读到旧数据：Linux应用一直开着某个文件，同时Android一侧在改它。
  - 原先为什么加`--direct-io`，仓库里没有记录。
- **验收**：
  - 在临时挂载点上先测，只去掉该选项、其他参数相同：共享映射和SQLite WAL（第二个连接读出、完整性检查）都通过。
  - 正式重新挂载后，`moto-fs-audit ~/Documents`已无必需项失败。
  - 微信保留原有数据重新打开：修复一次后，用户确认“完全没问题了”。

## 挂载链路

```
~/Desktop ~/Documents ~/Downloads ~/Music ~/Pictures ~/Videos ~/Templates ~/Public（链接）
  → ~/Shared  fuse.bindfs（映射为uid 1000、权限一律a+rwX、忽略chmod/chown、无xattr、noexec）
  → /mnt/android-shared  Android MediaProvider FUSE（/dev/fuse，/storage/emulated/0/Plasma，noexec）
  → 手机存储
家目录、~/.cache、~/.local/share、/var/tmp → 容器根目录 f2fs（本地）
/tmp、/dev/shm、/run/user/1000 → tmpfs
/run/user/1000/doc → xdg-document-portal（fuse.portal，Flatpak应用经它访问文件）
```

## 检查工具：`moto-fs-audit`

`plasma/diagnostics/moto-fs-audit`由`plasma/diagnostics/install.sh`安装到`/usr/local/bin`，以桌面用户身份运行。

- 默认检查：家目录、`~/.cache`、`~/.local/share`、各XDG用户目录、`/tmp`、`/var/tmp`、`/dev/shm`、`$XDG_RUNTIME_DIR`。也可以指定目录。
- 检查内容：在每个目录的临时子目录里实际执行24项操作，每项都注明会影响哪类应用。
- 选项：`--env`同时报告容器的各项限制；`--json`输出机器可读结果。
- 必需项失败时退出码为1。必需项包括：共享映射、SQLite WAL和回滚日志、fcntl锁和flock、原子替换、inotify。

**新增或修改挂载，或某个应用只在某个目录出问题时，先跑它。**

## 实测结果（2026-09-25，内核6.6.87-android15）

| 位置 | 文件系统 | 不支持的操作 |
|---|---|---|
| 家目录、`~/.cache`、`~/.local/share`、`/var/tmp` | f2fs | 无（24/24） |
| `/tmp`、`/dev/shm`、`/run/user/1000` | tmpfs | `user.*` xattr |
| 8个XDG用户目录（`~/Shared`） | bindfs → Android FUSE | 修复前还有共享映射和SQLite WAL（已修复），其余见下表 |

共享存储上仍不支持的操作：

| 操作 | 结果 | 所在层 | 受影响的应用 |
|---|---|---|---|
| 符号链接、硬链接 | `ENOSYS` | Android FUSE | git仓库、npm/pip目录树、Wine前缀、Electron/Chromium的SingletonLock、解压带链接的归档 |
| 区分大小写 | 大小写不同的两个名字指向同一个文件 | Android存储（casefold） | 源码仓库、Linux软件包内容 |
| 执行 | `EACCES`（noexec） | 两层都是noexec；bindfs还忽略chmod，无法加执行位 | 下载到这里的AppImage、安装脚本、游戏启动器 |
| chmod | 一律0666 | bindfs（`--perms`、`--chmod-ignore`） | ssh/gpg密钥（要求0600）、校验自身文件权限的应用 |
| xattr | `EOPNOTSUPP` | bindfs（`--xattr-none`），Android FUSE本身也不支持 | 下载来源标记、KDE文件标签 |
| Unix套接字、FIFO | `EACCES` | Android FUSE（不支持mknod） | Chromium/Electron单实例套接字、语言服务器 |
| `O_TMPFILE`、`RENAME_EXCHANGE` | 不支持 | FUSE | systemd工具、部分GLib安全保存（会退回普通方式） |

容器环境（`--env`）：

| 项目 | 值 | 说明 |
|---|---|---|
| 用户命名空间、`unshare`、bwrap、memfd | 正常 | Chromium/Electron沙箱和Flatpak可用 |
| `nofile` | 软1024/硬32768 | 硬上限低于Ubuntu桌面常见的524288。Wine esync和大型Electron应用可能不够 |
| `vm.max_map_count` | 65530 | Android内核全局值。Proton/Wine游戏、JVM大应用常要求1048576 |
| inotify | watches 52628，instances 128 | 大型IDE或同步客户端监视大目录时可能不够。属Android内核全局设置 |
| `/dev/shm`、`/tmp` | 约3.6 GiB可用 | 够用 |

## 处理原则

1. **应用的私有数据、数据库、源码仓库、可执行程序放在本地（家目录、`~/.local/share`、`~/Applications`等）**。Android共享存储只用于和Android交换的文件：下载、图片、视频、音乐。
2. **共享存储上能在挂载层补上的能力就补**（本次的共享映射）。补不上的，是Android FUSE本身的限制，应在文档和应用放置策略里说明，不要逐个修应用。
3. **新增挂载先跑`moto-fs-audit`**，结果记入本篇。

## 待决定

- **`~/Documents`、`~/Desktop`、`~/Templates`、`~/Public`是否改到本地**：
  - 改到本地后，“文档”在Android上就看不到了；好处是Linux应用放在这里的数据库、仓库和脚本都能正常工作。
  - 下载、图片、视频、音乐仍放在共享存储，用于和Android交换文件。
- **下载的AppImage无法直接运行**：需要应用或用户把它放到本地目录，或者去掉两层noexec并允许执行位（Android FUSE存不下执行位）。
- **`nofile`硬上限、`vm.max_map_count`、inotify上限**：是否在Android一侧调高。其中`vm.max_map_count`和inotify是内核全局设置，会影响Android。
