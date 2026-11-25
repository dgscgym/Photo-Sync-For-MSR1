# 0.2.0 大视频与 Live Photo

## 大文件

新客户端统一使用持久化分片会话。单文件最大 **10 GiB（10,737,418,240 字节）**，每片最大 8 MiB。服务端落盘，完成时重新流式计算完整 SHA256 并去重；没有把 10 GiB 文件整体放入内存。

浏览器记录会话 ID；断网或刷新后重新选择同一个未修改文件可续传。浏览器不会在刷新后自动获得磁盘文件权限。请勿修改正在续传的文件。完成时全文件哈希可能耗时，需等待结果；网络失败可以重试完成请求。

- POST `/api/v1/uploads`：JSON `{name,size}`，返回 id / offset / chunk_size。
- GET `/api/v1/uploads/{id}`：查询落盘偏移。
- PATCH 同一路径：原始分片，`Upload-Offset` 必须与服务端一致，冲突返回 409。
- POST `/api/v1/uploads/{id}/complete`：完整校验、入库；重试返回相同结果。
- DELETE `/api/v1/uploads/{id}`：清理会话和未完成文件，不删除已入库原片。

旧 POST `/api/v1/photos` 保留 50 MiB 兼容限制；网页已不使用旧接口。未完成会话尚无自动过期清理；可通过 DELETE 主动释放空间。当前是单进程原型，分片写入与完成过程串行保护，不适用于多实例部署。

## 预览

原片和预览均支持 HTTP Range / 206 / 416 及 HEAD，便于视频拖动定位。浏览器原生支持的编码优先直接播放。MP4/MOV 为容器，不能仅凭扩展名承诺所有浏览器均可播放其视频编码。

点击“生成兼容预览”时，可选的 FFmpeg 后台单任务队列生成 H.264/AAC MP4（最长边限制在 1280×720 范围内），不修改原片。尚未生成时返回 queued / processing；失败明确返回 failed；未安装时返回 unavailable。重启后可重新请求未完成任务，已完成副本可复用。预览占额外空间，当前无自动清理策略；长视频转码上限为 6 小时，速度需实机验证。

HEIC/HEIF 原片可保存；浏览器不支持时可尝试生成 JPEG 预览，但依赖 FFmpeg 对具体输入的解码支持，不承诺所有 HEIC、HDR 或手机厂商格式均可转换。GIF 和动态 WebP 通过浏览器原图播放。

## Live Photo

支持上传独立的静态图（JPEG/HEIC 等）与 MOV/MP4，并显式关联成 Live Photo。客户端会对**同次选择且文件主名相同的唯一照片与视频候选**请求用户确认；不把文件名匹配当作 Apple 内容标识验证。

POST `/api/v1/live-pairs`，JSON `{photo:照片SHA256,video:视频SHA256}`。两个文件分别去重并保留原始内容，配对记录持久化。照片卡片显示 LIVE，预览时播放配对视频。已配对到其他视频时返回 409，避免误覆盖。

当前不解析 Apple asset identifier；非同名资源可通过 API 显式关联。iOS 网页选择器可能只提供静态图，需要导出未修改原片与配对视频再一同上传。Android 单文件 Motion Photo / 小米实况格式、原生 iOS 相册导入以及跨格式导出均未实现。

## MS-R1 部署与验证

Debian 提供 ARM64 FFmpeg 软件包，但这不证明某台 MS-R1 的 VPU 驱动或硬件编码已可用。

```bash
sudo apt update
sudo apt install ffmpeg
python3 tools/check_media.py
```

检查脚本输出目标机器架构、FFmpeg 版本、可列出的硬件 API，并实际执行一次 **CPU libx264 编码和解码**。硬件 API 出现在列表里不代表设备可用。请在最终 PVE 客体或推理服务运行环境中执行，而非只在宿主机执行。

本版转码使用软件 libx264、单队列及两线程，不依赖此芯 NPU、CUDA 或 VPU。大视频软件转码可能较慢；适合上传后后台准备预览，未承诺实时转码。此芯 VPU 的驱动、设备权限和 FFmpeg 后端需要另做实机验证，成功前不自动启用。NPU 的人脸推理与 VPU 视频编解码是不同能力。

本地开发机已验证真实短视频转码、51 MiB 分片上传，以及稀疏 10 GiB 文件末尾 Range 读取；**未进行真实 10 GiB 全量上传，也未在 MS-R1 / ARM64 实机运行**。上线前还需用真实演唱会视频验证断网续传、耗时、磁盘余量、浏览器播放及 HEIC Live Photo。

参考：[Debian ARM64 FFmpeg](https://packages.debian.org/en/bookworm/arm64/ffmpeg)、[Apple Live Photo 资源说明](https://developer.apple.com/documentation/avfoundation/capturing-and-saving-live-photos)、[HTTP Range](https://developer.mozilla.org/en-US/docs/Web/HTTP/Guides/Range_requests)。
