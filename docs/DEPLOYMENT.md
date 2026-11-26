# 服务端容器部署与安卓联调

## 启动

在已经完成 PVE 客体系统安装的 Linux VM / LXC 内运行 Docker：

```bash
git clone https://github.com/dgscgym/Photo-Sync-For-MSR1.git
cd Photo-Sync-For-MSR1
git checkout v0.12.0
docker compose up -d --build
```

`compose.yaml` 仅发布一个 8080 服务，数据使用 `photosync-data` 命名卷。新增照片盘时，把宿主已有目录以只读方式映射到 `/media/名称`，例如 compose 中的注释示例；网页设置中登记容器内路径。不要求重新复制照片，也不要在升级时删除数据卷。

服务端 `/admin` 初始化管理账户和验证器、媒体目录、SnapRAID 接入或跳过，然后创建客户端账户。安卓填同一个服务的根地址。默认没有创建账号、口令或假磁盘。

远程使用需在前面配置 HTTPS 反向代理，并在服务启动参数增加 `--secure-cookies`。代理需透传 Range、PATCH、Upload-Offset、足够的请求超时；每片 4 MiB，但最终 10 GiB 校验可能耗时。不要开启把整个分片上传路径缓存在内存的代理配置。

## ARM64 / MS-R1 / PVE

Dockerfile 基于 Debian Bookworm 的 Python 3.12 多架构镜像，安装 Debian FFmpeg 和 SnapRAID，不嵌入 x86 二进制；**本次未在 MS-R1/PVE/ARM64 实机运行**。需要在目标 Linux 容器中实测构建和权限。Docker 在 LXC 中的 nesting / cgroup 需求由 PVE 部署策略决定；VM 内 Docker 也是可选路径，本仓库不自动修改 PVE 配置。

默认不直通 NPU/VPU、不启用硬件编码、不使用 privileged。CPU FFmpeg 功能不需要 GPU/NPU 设备。硬件加速需先在客体验证此芯驱动、设备节点、ARM64 runtime 和 FFmpeg 后端，再最小化授权映射设备。模型转换及人脸嵌入的 NPU 路径仍属待研究项目。

SnapRAID 当前仅规划磁盘、保存配置和只读状态检查，不执行 sync/scrub/fix。需要在目标环境检查容器内挂载和实际物理盘身份对应，不可将容器目录当成独立物理盘。无需为本版授予整机块设备写权限。

## 升级与恢复

先停止服务，完整备份 `/data` 卷（SQLite、`auth.key`、上传分片、原片、来源索引及设置），原地引用的媒体盘另外备份。更换镜像后挂回同一数据卷和同一媒体目录；改变路径使用来源重新绑定。`auth.key` 不可只备份数据库后丢弃；恢复旧版本应恢复对应数据备份，不能假设任意版本可降级数据库。

安卓通过版本号和固定签名升级，应用私有队列和 URI 授权原地保留。卸载应用会丢失本机队列和授权，服务端已入库原片不受影响。新增跨 schema 变更必须提供迁移；本版安卓初始 SQLite schema 为 1。

## 开发联调

已有 8080 原型可继续用 USB `adb reverse tcp:8080 tcp:8080`；不必再运行一个服务。正式服务测试使用独立数据目录，避免把无认证原型数据目录直接切换成正式部署。见 [Android 文档](ANDROID.md)。
