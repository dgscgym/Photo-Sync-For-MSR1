# API v1 · 原型

默认地址 `http://127.0.0.1:8080`，单用户，无身份认证。

## GET /api/v1/status

返回 version、stats（photos/bytes/duplicates）、photos、最近 30 条 events 及 capabilities。
尚未实现的能力返回明确状态，不报告成功。

## POST /api/v1/photos

请求体为单个文件的原始二进制；需 Content-Length，文件上限 50 MiB。
`X-Filename` 为 encodeURIComponent 编码的原始文件名。
服务端流式计算 SHA256，文件名不会用于生成磁盘路径。

- 201：新增成功，`{"sha256":"…","duplicate":false}`。
- 200：文件已经存在，`duplicate:true`。
- 400：请求长度错误或上传不完整。
- 403：浏览器跨站上传被拒绝。
- 413：空文件或超过限制。
- 415：文件签名不属于 JPEG/PNG/GIF/WebP。
- 500：存储失败。

当前仅检查文件签名，不提供完整解码验证、缩略图或恶意图片检测。
照片原片只保存一份；重复事件仍记录，以便审查上传结果。

## GET /api/v1/photos/{sha256}

按 SHA256 返回原始文件；不存在或无效的摘要返回 404。

## 原型边界

旧单请求上传接口保持兼容；新分片、配对与预览 API 见 [MEDIA.md](MEDIA.md)。

未实现：账号、目录扫描、EXIF 时间线、缩略图、人脸推理、加密归档、115 同步、删除和多进程部署。
Live Photo 支持显式双资源配对，暂不解析手机厂商单文件实况格式。

当前浏览器与服务端分别位于 client/ 和 server/，默认同源部署，不是原生手机客户端。
