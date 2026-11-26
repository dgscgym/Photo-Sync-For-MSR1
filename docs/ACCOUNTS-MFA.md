# 0.10.0 · 账户、2FA 与客户端同步原型

## 首次使用 / 从旧版升级

1. 服务端创建初始管理账户，使用 Google Authenticator 或兼容的 TOTP 验证器扫描本地生成的二维码，输入验证码完成绑定。
2. 保存只显示一次的十个恢复码。恢复码配合密码可作为备用因素，每个只能使用一次。
3. 管理员完成初始化后，在“用户信息 → 设置 → 用户与权限”创建客户端用户，决定是否允许其登录服务端。
4. 初始管理账户仅登录服务端，不能直接用作客户端账户。新建客户端用户首次登录时必须自己绑定 2FA。
5. 获准服务端权限的客户端用户，也必须在服务端入口重新完成密码与 2FA 登录。

旧管理账户的用户名与密码哈希保留；旧的无 2FA 会话不再有效，升级后须重新登录并绑定验证器。不自动建立客户端用户，不重置原片或已登记目录。

## 认证与会话

- 两侧登录均为“密码 → 短期验证挑战 → 2FA”，密码通过不会得到可访问媒体的会话。
- TOTP 为 SHA1 / 六位 / 30 秒，兼容 Google Authenticator；允许相邻一个时间步的时钟误差，拒绝重复使用已消费的验证码。
- MFA 挑战五分钟过期，最多五次尝试，成功后立即消费。失败计数按来源 IP + 用户名持久化并串行保护，五次失败锁定五分钟；密码通过不提前清除 MFA 失败计数。
- 管理端和客户端使用不同 Cookie 名称和 audience，服务端管理 API 不接受客户端会话。
- 每个会话最长十二小时；退出只撤销对应入口会话。账户禁用、服务端权限变更会撤销该用户全部会话。
- TOTP 密钥用 Fernet 加密，密钥保存在权限 0600 的 data/auth.key。必须连同数据库备份它；已有绑定但密钥丢失时拒绝启动，不静默生成新密钥。
- 恢复码只存 SHA256，不将验证码、密码、TOTP 密钥、二维码或认证请求正文写进日志。
- 本版选择 TOTP 路线，没有实现邮箱发送验证码。

## 设备认证（客户端）

完整密码 + TOTP / 恢复码登录后五分钟内，可登记本机 WebAuthn 平台认证器。浏览器/系统可能使用指纹、面容或设备 PIN，服务端不能保证每次都只使用生物识别；服务端只保存凭证公钥和计数，不保存生物信息。

客户端登录仍需密码；登记的设备可在七天内替代验证码。服务端校验签名、challenge、RP ID、origin、用户验证标记和计数。到期必须重新输入 TOTP / 恢复码，不能凭设备签名续期；设备会话到期时间也不越过该确认期限。服务端登录不接受这一替代方式。

远程部署需要 HTTPS、--secure-cookies 和明确的 --webauthn-origin，例如 https://photos.example.com。本机 127.0.0.1 / localhost 根据监听地址自动设置信任 origin，不信任请求的 Host 头来改变校验目标。切换域名或端口会影响已登记凭证。

已用生成的真实 EC 签名和 WebAuthn 数据格式验证协议路径；尚未在真实 Touch ID / Face ID / 安卓设备上验收。多设备撤销、密码重置与管理员辅助重绑仍待完善。

## 权限与媒体隔离

- 管理员可创建用户、授予/撤销服务端权限和停用账户；不能通过普通用户接口创建或升级初始管理员。
- 客户端不能访问媒体目录、SnapRAID、管理日志或用户管理 API。
- 客户端媒体列表、原图、视频 Range、预览、Live Photo 配对、上传会话和上传日志均按所属用户检查。
- 相同 SHA256 的原片仍可跨用户共享底层存储，只有实际完成上传的用户才新增访问关联；知道摘要或上传会话 ID 不等于获得访问权限。
- 服务端管理员可查看全库媒体。已有外部目录索引归入服务端管理范围，没有自动分享给新建客户端用户；相册共享/授权界面后续补充。

## 客户端同步策略原型

客户端设置仅有本机相册同步与认证，不包含服务端路径、SnapRAID 或云备份配置。

- 支持手动同步。具备 File System Access API 的浏览器可保存用户授权的目录句柄，并在页面开启、权限有效时定时/联网触发同步。
- 缺少目录句柄能力的浏览器回退到文件夹选择，刷新后需重新选择。不能保证关闭页面后继续执行。
- 自动条件包含联网、可确认的 Wi-Fi 类型、指定 SSID。指定 SSID 只保存策略原型，不在浏览器中假装检测；留给后续 Android / iOS / 鸿蒙客户端。
- 自动扫描使用相对路径、文件大小、修改时间作为未变化缓存。服务端最终入库仍全文件计算 SHA256。可手动勾选重新校验全部文件，避免相同元数据下内容变化未被发现。
- 当前只保存一个目录句柄，可递归包含多个子相册；文件夹自动扫描不自动推断 Live Photo 配对。

## 新入口与 API

- 管理台概览：媒体数量、占用、云备份和 SnapRAID 状态；进入照片库隐藏统计卡片。
- 客户端照片页无服务端统计卡片。
- 运行日志从两侧用户菜单进入 /admin/logs、/client/logs，客户端只能看自己的上传日志。
- POST /api/v1/auth/login：username、password、audience=admin|client，返回 MFA 挑战。
- POST /api/v1/auth/mfa/verify：ticket、code；成功后才设置相应会话。
- GET/POST /api/v1/admin/users：用户及服务端权限管理。
- WebAuthn 接口：/api/v1/auth/passkey/register/options、register/verify、login。

## 依赖与数据

从此版本起使用项目虚拟环境，安装 requirements.txt（引用锁定的 requirements.lock），不再是纯标准库服务。

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m server.app --port 8080 --data data
.venv/bin/python -B -m unittest discover -s tests -v
```

schema 6 增加用户、MFA 挑战、独立会话、恢复码、公钥、媒体访问关联及上传/日志用户归属。升级前自动备份旧 schema，原片不移动。若回滚必须同时核对数据库版本；不能启动旧版绕开强制 2FA。

这是可联调的原型，不包含站外验证码投递、真实原生后台服务、完整多用户相册共享或生产安全审计。MS-R1 / PVE 实机、真实设备认证与浏览器视觉仍需验收。

参考：[RFC 6238](https://www.rfc-editor.org/rfc/rfc6238)、[py_webauthn](https://github.com/duo-labs/py_webauthn)、[浏览器网络信息 API](https://developer.mozilla.org/en-US/docs/Web/API/NetworkInformation)、[目录句柄 API](https://developer.mozilla.org/en-US/docs/Web/API/FileSystemDirectoryHandle)。
