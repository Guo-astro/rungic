# 回到官方 MYUI

本机 **没有** 完整 `super` 备份。回官方只能刷 RETCN 包。`_b` 槽不是 MYUI。

## 对应固件

刷 GSI 前跑的就是这一包，lolinet 上有：

```
XT2537-4_MUMBA_RETCN_16_W1WAA36.48-23-10_subsidy-DEFAULT_regulatory-DEFAULT_CFC.xml.zip
https://mirrors.lolinet.com/firmware/lenomola/2026/mumba_retcn/official/RETCN/
```

同目录还有旧一点的 `W1WAA36.48-23-2`。不要混刷国际版 `mumba/official/`（非 `_retcn`）。

也可用联想/摩托罗拉 Rescue and Smart Assistant（Software Fix）。Linux 下 RSA 不方便，lolinet + fastboot 脚本更实际。

包很大（约 9.8GB）。zip 可断点、可 Range。抽单文件用 `~/moto/tools/remote_zip_extract.py`。

## 已经在手里的原厂镜像

`~/a17-gsi/dumps/stock/`：

- `boot.img`
- `init_boot.img`（没打 Magisk 的）
- `vbmeta.img`
- `vbmeta_system.img`

这些 **不够** 单独恢复 MYUI（没有 `super` / `system` / `product` / `vendor`）。它们够：

- 去掉 Magisk：`fastboot flash init_boot init_boot.img`
- 修好 AVB：`fastboot --disable-verity --disable-verification flash vbmeta vbmeta.img`  
  回官方时通常应刷 **不带** disable 标志的原厂 vbmeta，让 Rescue/官方脚本自己处理。

## 回官方时注意

1. 用包里的 `flashfile.xml` / 官方脚本，不要只刷 `system`。
2. 现已删除 `product_a/b`。官方脚本会重建逻辑分区；若中途失败，先 `fastboot reboot fastboot` 再跑一遍。
3. 回官方等于再 wipe 一次用户数据。
4. bootloader 保持解锁即可刷入；想重新上锁另说，未验证。
5. 基带/bootloader 版本已是 `WWAA36V.48-23-ST12.4`，与 `W1WAA36.48-23-10` 匹配。不要随便降级 abl/xbl。

## 只撤 GSI、暂不重装 MYUI

没有完整 super 备份就做不到 “一键回 MYUI 且保留当时数据”——数据在永久刷时已经 wipe 了。现在盘上是干净 AOSP `/data`。
