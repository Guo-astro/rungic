# Mesa 的底座：lfdevs 分支，还是上游加我们自己的补丁（调研，2026-09-30）

状态：调研，**尚未实施**。标注：“源码”指在代码或 git 历史里核对过；“文字”指只见于 PR、MR 或 README 的说法；“推断”是未验证的判断。调研工作目录：`.work` 之外的临时目录（partial clone、diffstat、分组 diff），可以随时重做。

## 现状

- 系统 Mesa 从 Phosh 时期起就是社区分支 [lfdevs/mesa-for-android-container](https://github.com/lfdevs/mesa-for-android-container)，固定在 `98f3d622`（docs/40）。
- 这个提交是“把上游 `4c1c22e9` 合进 dev/adreno-main”，所以分支相对上游的全部改动就是 `git diff 4c1c22e9 98f3d622`：37 个文件，+2446/−255（源码）。
- 我们在上面还有 4 个补丁（`packages/mesa/debian/patches/rungic/`）。其中 3 个修的都是分支自己引入的问题（docs/49、research/93）。

## 分支改了什么，我们用不用得上（源码）

| 组 | 内容 | 行数 | 我们的环境 |
|---|---|---|---|
| G1 | freedreno gallium 的 KGSL 后端 `src/freedreno/drm/kgsl/*`，外加设备探测、复位状态 | +917/−22 | **要用**：整个 GL 驱动就是它。它来自上游已关闭的 !21570，分支另加了 dma_heap 分配。固定版本里有一个提交前释放 submit 的错误，分支后来用 `91f7e8c6f` 修了 |
| G2 | KGSL dma-buf 规则：只用 LINEAR；导出时把非共享资源影子复制 | +94 | **要用，但写法有问题**：导入的缓冲再导出会变成另一块（research/93 的黑窗） |
| G3 | EGL/GBM 选 KGSL 设备（`Options.Kgsl`、platform_drm、Wayland 回退、surfaceless） | +91/−23 | **要用**：KWin、plasmashell、Qt/GTK、Firefox 都靠它 |
| G4 | `x11_dri3_open` 自己打开 KGSL | +5 | 用不上：我们的 Xwayland 在 DRI3Open 时已经给出 KGSL fd |
| G5 | Termux 专用：LINEAR 改写成 1274、去掉 xshmfence 和 damage、EGL 默认 zink、`dri3_x11_connect` 失败也返回成功 | +74/−98 | **有害或用不上**：Flatpak 崩溃（docs/49）和 1274 问题（research/93）都出在这里 |
| G6 | zink 调整 | +34/−3 | 用不上（docs/90 不用 zink） |
| G7 | Turnip：ION 回退、去掉 `KHR_display` 检查、`tu_wsi` 的 KGSL 呈现检查 | +113/−48 | 部分要用：`KHR_display` 放宽、X11 Vulkan 的呈现检查（推断） |
| G8 | 设备表（FD710 等） | +111/−1 | 上游已有，由上游替代 |
| G9 | llvmpipe SVE 检测 | +40 | 不编译（`-Dllvm=disabled`） |
| G10 | CI | +967/−60 | 用不上 |

真正用得上的只有 G1–G3 和 G7 的一小部分，约 1000 行。

## 上游 main 现在有什么（`190d227a`，2026-09-29，源码）

- Turnip 支持 KGSL，包括 dma-buf 导入和导出。导出的内存从 `/dev/dma_heap/system` 分配（`tu_knl_kgsl.cc`）。
- **freedreno gallium 不支持 KGSL**。`meson.options` 写明 “the freedreno gallium driver doesn't support KGSL. On those systems, zink with Turnip should be used instead.”，`src/freedreno/drm/` 下也没有 `kgsl/`。
- 加载器认得 `kgsl` 这个名字，但 EGL/GBM 仍要求 `drmGetDevice2` 成功，所以 KGSL fd 在 EGL 和 GBM 里用不了。Wayland 没有设备信息时也没有回退。
- FD710 已由 !44466 加入（2026-09-23），参数与分支不同：

  | | num_ccu | highest_bank_bit | 寄存器魔数 |
  |---|---|---|---|
  | 上游 | 1 | 15 | FD710 专用 |
  | 分支 | 3 | 16 | 抄自 A730 |

  `num_ccu` 会影响 GMEM 缓存布局，换底座后要在本机核对。
- 相关 MR：
  - !14928 Turnip KGSL 外部内存，已合并；
  - !21570 gallium KGSL 后端，已关闭；
  - !40302 zink 不依赖 libdrm，已合并；
  - !43136 Turnip KGSL fd 泄漏，已合并；
  - !39751 Turnip KGSL timeline 同步，草稿。

## 其他来源（源码）

没有比 lfdevs 分支更接近上游、同时提供 glibc 下 freedreno GL 的来源：
- Termux：只有 Turnip 和 zink，补丁多为 Bionic 专用；
- xMeM：2024 年后停止更新；
- anland：已并入 lfdevs 分支；
- Droidspaces：直接用 lfdevs 的构建；
- Debian：freedreno 只支持 msm。

## 建议（待用户决定）

以上游 main `190d227a` 为底座，26.3 分支出来后改跟稳定分支，自带 4 个补丁，约 1000 行，大部分是新文件：
1. freedreno KGSL 后端：移植 !21570 和分支的 dma_heap 分配，带上 `91f7e8c6f` 修复和两个小错误修复，去掉用不上的 `control_fd`/`FD_FORCE_KGSL`。约 830 行。
2. KGSL dma-buf 规则，**重写**：已有 dma-buf 的缓冲导出时直接复制 fd，只对 KGSL 原生缓冲做影子复制；保留 gralloc UBWC 导入。现有的 `kgsl-import-is-shared` 和 `kgsl-dmabuf-import-ubwc` 并入这里。约 80–100 行。
3. EGL/GBM 选 KGSL 设备，Wayland 回退只在 `Kgsl` 选项打开时生效。约 80 行。
4. Turnip：`KHR_display` 放宽和 `tu_wsi` 的 KGSL 呈现检查。约 15 行。

补丁的去留：
- 现有的 `egl-x11-dri3-fallback-software` 和 `x11-kgsl-needs-dri3` 不再需要：上游的 `dri3_x11_connect` 失败时正常返回失败，`x11_dri3_open` 也先检查 DRI3。
- Xwayland 补丁里的 1274 映射在同一组提交里去掉。

风险：
- 上游 main 变化快：底座之后已有 2096 个提交，其中 236 个涉及 freedreno、ir3 或 Turnip。
- 上游 CI 只在 msm 上测 a618、a660、a702、a750，没有 KGSL，也没有 a7xx gen1。
- FD710 的新参数需要在本机验证；G100 同为 Adreno 710（docs/78）。

实机验收：
1. GBM 探针，以及“导入后导出 inode 不变”；
2. KWin：UBWC 导入，按 docs/56、docs/57 的指标测帧间隔；
3. plasmashell、Qt/GTK、Firefox（WebGL、视频）；
4. Blender：Vulkan 视口，并复查 docs/90 的 GL 显示错误；
5. Xwayland：glamor、DRI3、glmark2、改变窗口大小、30 分钟运行；
6. 没有 DRI3 的 X 服务器，以及拿不到设备的 Flatpak，都应退到 softpipe；
7. Flatpak GL 扩展；
8. docs/56 的 Turnip WSI 闪烁，确认不比现在更差；
9. 长时间运行时 dma-buf fd 和内存有没有增长。

附带更正：docs/57 说 gallium 在 CPU 分块拷贝时使用写死的 `highest_bank_bit=16`。实际上 `src/gallium/drivers/freedreno` 里没有任何地方读取 `highest_bank_bit`（源码）。
