# 开发 APK 签名

用户于2026-09-23明确要求将开发用签名密钥同步到私有仓库。

- 文件：`launcher-signing.p12`，PKCS#12格式。
- Alias：`launcher`；开发口令沿用构建脚本中的`android`。
- 这是已用于本项目APK的原有签名身份，从`.work/secrets/`移入，内容未改变。
- `plasma/build-apk.sh`默认读取本目录；构建产物继续写入`.work/`。

只跟踪此开发密钥；其他密钥和本地材料继续按项目忽略规则处理。
