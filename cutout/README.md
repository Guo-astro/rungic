# 挖孔 / safe area 修复

刷 GSI 时删了 `product`，摩托罗拉原来的 display cutout overlay 没了。系统把挖孔当成不存在，只按圆角半径 **59px** 给状态栏和底部 insets，时钟/图标会顶到摄像头上，应用的 WindowInsets 也不对。

## 已做的修复

Magisk 模块 `mumba-cutout` 往 `/product/overlay/MumbaCutout/` 挂了一张 **静态 RRO**：

- 居中圆形挖孔：半径 32px，圆心距顶 **52px**（相对初版下移 10px）
- 上报 bounding rect 约 `Rect(500, 0 - 580, 84)`
- 状态栏高度 84px
- `config_fillMainBuiltInDisplayCutout=true`（挖孔周围软件补黑，防锯齿）

重启后 dumpsys 确认：

```
mDisplayCutout=DisplayCutout{insets=Rect(0, 80 - 0, 0)
  boundingRect top=Rect(500, 0 - 580, 80)
  cutoutSpec={M -32,42 a 32,32 0 1 0 64,0 a 32,32 0 1 0 -64,0 Z}}
statusBars frame=[0,0][1080,80]
```

底部仍是 **59px**（屏幕圆角，手势导航）。这和挖孔无关；MYUI 若底部更宽，再另加 `navigation_bar_height`。

## 模块位置

- 源码：`~/moto/cutout/config.xml`、`AndroidManifest.xml`
- APK：`~/moto/cutout/MumbaCutoutOverlay.apk`
- Magisk：`~/a17-gsi/magisk/mumba-cutout/` → 设备 `/data/adb/modules/mumba-cutout`

路径坐标系：原点在屏幕 **顶边中点**，不要加 `@left`。

## 挖孔偏了怎么改

改 `config.xml` 里的 path / 80px，然后重新 aapt2 打包、放进模块、`magisk --install-module`、重启。

| 想改的 | 动哪里 |
|---|---|
| 圆太大/太小 | `a 32,32` 和 `64`（= 2r） |
| 上下位置 | 圆心 y：现在 `42`（顶到圆心） |
| 状态栏高度 | `status_bar_height_portrait`，建议 ≥ 圆心 y + 半径 |
| 不要软件涂黑 | `config_fillMainBuiltInDisplayCutout` → false |

不要用 `cmd overlay fabricate`：system_server 一重启就丢，而且读不了 `/data/local/tmp` 的 xml。
