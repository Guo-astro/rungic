# 补丁与自有源码的关系

上游源码统一由`packages/<名称>/recipe.json`固定来源、版本、校验值与许可证，本地修改在`debian/patches/rungic/`，顺序由`debian/patches/series`声明。用`tools/pq.py prepare/export`维护补丁，实际源码只在`.work/`展开。2026-09-30已补齐Android宿主、Smithay/Winit及Firefox移动配置，原`vendor/`和直接维护的两棵源码树已删除。见[71篇](../docs/71-upstream-patch-queue.md)、[73篇](../docs/73-reduce-upstream-changes.md#remaining-source-trees-migrated-2026-09-30)。

`android/`、`agent/`、`desktop/`、`system/`与`shared/`中的自有应用、桥接和共享模块直接维护；上游组件使用它们时由recipe的`overlay`加入生成树，不在多个补丁中复制。宿主自有Rust模块在`android/host/`，上游宿主修改在`packages/android-host/`。

`desktop/patches/qt-video-duration.patch`仍是未验收实验，没有进入`packages/qt6-multimedia`的补丁队列。其他历史适配补丁若仍由导入记录引用，只作为历史证据，不是当前构建入口；不要把旧补丁手动叠加到已准备好的源码树。
