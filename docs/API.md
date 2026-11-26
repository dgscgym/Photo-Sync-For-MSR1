# API v1 · 0.12.0

默认地址 `http://127.0.0.1:8080`。正式模式所有媒体接口要求客户端 / 管理端的独立会话。原生应用使用与网页相同的 HTTP API，不绕过账户权限。

## 认证

- GET `/api/v1/auth/status?audience=client`：authenticated、setup_complete、username、mfa_enabled。仅免登录原型返回 `demo:true`。
- POST `/api/v1/auth/login`：`{username,password,audience:"client"}`，返回 MFA ticket；首次绑定还返回 secret、otpauth_uri、qr_svg。
- POST `/api/v1/auth/mfa/verify`：`{ticket,code,audience:"client"}`。成功返回客户端 `Set-Cookie: photosync_client_session=...` 和首次恢复码。
- POST `/api/v1/auth/logout`：`{audience:"client"}`，撤销当前客户端会话。

客户端每次向媒体 / 上传接口请求增加 `?app=client` 并携带客户端 Cookie。Cookie 不放 URL；不得将管理端 Cookie 当作客户端 Cookie。当前会话 12 小时过期；返回 401 后重新完成登录，不自动降低认证强度。

## 媒体与上传

- GET `/api/v1/client/status`：当前用户的媒体集合、版本、客户端统计。服务端 `/api/v1/status` 仅管理端可访问。
- GET `/api/v1/photos/{sha256}?app=client`：原片，支持 Range/HEAD，SHA256 无权限时返回 404。
- GET `/api/v1/thumbnails/{sha256}?app=client`：最长边 512 的 JPEG 缩略图，不修改原片；不支持的编码 / 超像素限制返回 415。
- GET `/api/v1/media-details/{sha256}?app=client`：格式、大小、分辨率、相机参数、可用性及逻辑存储位置。客户端不披露服务器绝对路径。
- POST/GET `/api/v1/previews/{sha256}?app=client`：生成 / 获取 FFmpeg 兼容预览。
- POST `/api/v1/live-pairs?app=client`：`{photo,video}`，两个资源都需属于当前用户可访问范围。

分片接口见 [MEDIA.md](MEDIA.md)：先 POST `/api/v1/uploads?app=client` 创建 `{name,size}`，GET 查询偏移，PATCH 二进制（`Upload-Offset` 头），POST `/complete` 校验；最大 10 GiB，每片最大 8 MiB，安卓使用 4 MiB。会话按用户隔离，SHA256 由完成阶段流式计算。重复完成幂等，精确去重后原片只保存一次。

旧 POST `/api/v1/photos` 保持 50 MiB 兼容，安卓和网页均使用分片接口。日志和 SnapRAID 状态属于管理端 API。完整账户权限见 [ACCOUNTS-MFA.md](ACCOUNTS-MFA.md)。
