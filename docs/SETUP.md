# 独立初始化与登录

0.7.0 起，日常 SnapRAID 调整使用 `/admin/settings/snapraid`，不进入本初始化流程。前端代码位于 `server/admin/web/`；客户端入口为 `/client`。

0.6.0 已将主要 SnapRAID 初始化入口改为图形化磁盘与模式选择，见 [SNAPRAID-DISKS.md](SNAPRAID-DISKS.md)。下文已有配置接入描述保留为高级兼容路线。

## 首次使用顺序

1. `/setup/welcome`：创建唯一管理员（用户名与至少 12 字符密码），获得仅用于继续设置的会话。
2. `/setup/library`：多个目录每行一个，最多 200 个一批，可分多批添加。每个目录递归扫描，后端校验整个批次，任一无效则整批回滚。
3. `/setup/snapraid`：接入现有 SnapRAID 配置、登记全部数据/校验盘路径和身份、设置检查周期；也可明确选择暂不启用。
4. `/setup/review`：确认目录列表和 SnapRAID 配置状态。未接入或未明确跳过 SnapRAID，不能在新流程中完成初始化。
5. 完成设置后，全部引导期间的会话失效，跳到 `/login`。登录成功才能进入照片页面。

这是独立 URL 的全屏引导，无应用侧边栏。主应用只保留日常“目录管理”和多盘保护页的“配置 SnapRAID”链接，不把首次初始化当作普通导航选项。

## 多目录

媒体目录与根授权均支持多个。使用多个 --library-base 可授权不同磁盘；在引导或目录管理文本框里每行填写一个容器内绝对路径。

相同/重叠目录不重复登记（例如已有父目录，就不必再加其子目录）。不同目录里内容相同的文件可有多个位置，相册仍按 SHA256 去重。路径重绑针对一个来源，不使用批量重绑。

## SnapRAID 初始化的实际范围

当前是**接入现有配置与检查计划**，不是自动建立新阵列。不会格式化磁盘、写盘身份标记、生成 parity/content 数据或自动执行首次 sync。

```bash
python3 -m server.app \
  --data /var/lib/photosync \
  --library-base /media/photos1 \
  --library-base /media/photos2 \
  --storage-base /media/parity \
  --snapraid-config-base /etc/snapraid
```

接入页填写 `/etc/snapraid/snapraid.conf`，以及全部数据盘/校验盘目录与预先存在的 `.photosync-volume-id` 文本值。配置文件必须位于 --snapraid-config-base 范围，磁盘必须在 --storage-base 或 --library-base 范围。GUI 不能指定可执行文件。

保存监控配置到持久化 data/snapraid-monitor.json，重启自动加载并继续检查；若指定 --snapraid-monitor-config，则启动参数优先，GUI 显示受服务器管理并禁止覆盖。保存成功不代表阵列健康或数据已有校验保护，需查看实际检查结果。新阵列规划与首次 sync 向导仍待实现，页面有明确提示。

## 登录与保护边界

- 服务端保护照片、原图、视频 Range、上传、日志、目录与监控接口；不是仅隐藏网页按钮。
- 密码以随机盐 + PBKDF2-HMAC-SHA256（600000 次）保存，不保存明文密码。
- 会话为随机令牌，数据库只保存令牌哈希；Cookie 为 HttpOnly、SameSite=Strict，12 小时过期。退出登录立即撤销当前会话。
- 同一来源 IP 连续 5 次失败后暂停登录 5 分钟。反向代理部署需另行规划真实客户端 IP 与限流，当前未信任 X-Forwarded-For。
- HTTPS 反向代理部署时使用 --secure-cookies；应用本身不提供 TLS，默认回环地址适合本机测试。
- 账户创建前应限制网络访问，避免其他人抢先创建管理员。无默认用户名密码。
- 旧版没有账户的数据升级后保留原片与配置，首次访问要求创建管理员并重新确认设置，无需搬动文件。
- 当前仅单管理员；多用户、密码重置、MFA 与远程生产安全验收尚未实现。不要删除数据库作为密码恢复方式。

数据库 schema 5 新增账户、会话与登录失败计数表；保留原有元数据，升级前自动备份旧 schema。

## API

- GET /api/v1/auth/status；POST /api/v1/auth/bootstrap、login、logout。
- GET /api/v1/setup；POST /api/v1/setup/snapraid、finish。
- POST /api/v1/library/sources/batch：`{sources:[{path,name?},...]}`。
- 旧 /api/v1/library/finish 返回 410，统一使用独立设置完成接口。

单元与 HTTP 集成测试覆盖初始化各独立页面、批量回滚、SnapRAID 路径授权与配置持久化、登录限流、会话撤销和未登录接口拒绝。浏览器视觉及 MS-R1 / PVE 实机验证尚未完成。
