Docker 与手机文件管理器共享文件

此目录在文件管理器中显示为“内部存储/Docker”。
Docker 中可使用 /sdcard/Docker 或 /storage/emulated/0/Docker。

shared/：容器和文件管理器可以直接读写的普通文件。
exports/：从普通 Docker 卷导出的备份或文件。
compose-example.yaml：同时展示普通卷、目录挂载、共享目录命名卷的示例。

在 Termux 中启动示例：
docker compose -f /sdcard/Docker/compose-example.yaml up -d
浏览器访问 http://手机IP:18089/
修改 shared/web-example/index.html 后刷新浏览器即可看到变化。
停止示例：
docker compose -f /sdcard/Docker/compose-example.yaml down

共享目录支持普通文件、目录、读写、重命名，但不保留完整 Linux 权限和符号链接。
数据库、node_modules 等依赖 Linux 文件特性的内容，请使用普通 Docker 卷。
普通卷默认保存在 Docker 私有 ext4 中，不会自动显示在本目录。
共享目录不是自动文件同步：容器与文件管理器访问同一份文件，删除同样会生效。

详细本地文档：电脑 /home/kevinzhow/moto/20-docker-storage.md
