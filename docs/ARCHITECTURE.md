# 浏览器客户端与服务端管理台

0.10.0 已拆分账户与 audience 会话，并强制 2FA。客户端设置只保留本机同步和设备认证；运行日志入口位于用户菜单。当前行为见 [ACCOUNTS-MFA.md](ACCOUNTS-MFA.md)。

## 入口与代码归属

| 入口 | 职责 | 代码 |
| --- | --- | --- |
| /client | 选择照片/视频、分片上传、进度与重试、浏览和预览 | client/ |
| /client/login | 浏览器客户端登录 | 服务端统一鉴权，登录后返回客户端 |
| /admin | 服务概览、照片/视频浏览、媒体目录、备份、SnapRAID 状态和日志 | server/admin/web/ |
| /admin/settings/snapraid | 单独修改 SnapRAID 配置，无初始化步骤条或完成初始化操作 | server/admin/web/snapraid.* |
| /setup/* | 仅首次使用的独立引导 | server/admin/web/setup.* |
| /login | 管理台登录，登录后返回 /admin | server/admin/web/login.* |

/ 默认转到服务端管理台。首页告警和管理页的 SnapRAID 配置链接均指向 /admin/settings/snapraid，不再复用首次引导页面。

浏览器客户端不包含磁盘、目录配置或 SnapRAID 表单，也不查询管理日志；GET /api/v1/client/status 只返回媒体列表、统计和版本。存储、扫描、归档、鉴权和数据库仍由服务端提供，客户端不直接读服务器磁盘。

## SnapRAID 日常设置

- GET /api/v1/snapraid/settings：只返回 SnapRAID 配置相关状态，不返回完整初始化/媒体目录状态。
- GET /api/v1/snapraid/settings/disks：获取可选磁盘。
- POST /api/v1/snapraid/settings：预览与保存独立设置。
- 未同步方案可调整模式、磁盘与后续检查周期；更新需携带当前 plan_revision，防止旧页面覆盖新设置。
- 保存前重新枚举磁盘并验证旧磁盘仍可用、设备身份未变化、配置文件未被外部修改。已出现校验/Content 文件的磁盘不按未同步新方案处理。
- 只修改 SnapRAID 方案与配置，不修改 setup_complete、用户账户、会话或媒体来源。
- 已接入并运行中的阵列仍只读，本版不提供磁盘迁移、首次 sync 或未经验证的自动重建。

## 当前部署边界

本轮拆分的是前端职责、代码目录与 HTTP 入口；管理台和客户端均可浏览媒体。原型仍只运行一个 8080 API 服务，同时提供两套静态前端，避免额外起服务。尚未提供独立镜像、跨源部署或独立客户端构建发布流程。

当前仍使用单管理员账户和共用会话，不是面向不同权限用户的 RBAC 实现。登录会话有效时可切换客户端与管理台；退出会撤销当前会话。后续多用户/普通客户端账户需要独立权限设计，不能把 URL 分离视为权限隔离。

兼容保留旧的静态资源地址和首次引导路径；原片、数据目录、已登记来源与登录账户不迁移、不重置。当前 schema 仍为 5。
