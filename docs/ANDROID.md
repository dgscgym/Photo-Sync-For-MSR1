# Android 0.12.0：第一版真实客户端

这是原生 Android 应用，直接访问服务端 API，不是 WebView。Android 8.0 / API 26 起可安装，编译 / 目标 API 36，Java 17。浏览器客户端和服务端管理台继续保留，安卓端没有管理台跳转或运行日志入口。

## 获取和安装

GitHub 仓库的 `v0.12.0` 预发布附带 `PhotoSync-0.12.0-debug.apk`。这是调试签名版本，可连接局域网 HTTP；release 构建只允许 HTTPS。不要将调试 APK 当作正式商店发布版本。

仓库提供 `docs/workflow-templates/android.yml` 自动构建模板。现有推送凭据没有 GitHub `workflow` 权限，所以未启用 Actions；由有权限的维护者将模板复制到 `.github/workflows/` 并推送后，可在 Actions → Android debug APK 下载构建产物。每次在新 CI 机器生成的默认 debug 证书可能不同，覆盖安装要求签名一致；为保持 CI 升级身份，仓库管理员可配置 `ANDROID_DEBUG_KEYSTORE_BASE64` Secret（debug keystore、alias `androiddebugkey`、密码 `android`）。本次本地构建使用固定的本地 debug keystore，未提交私钥。正式分发应另建并备份正式签名，不应依赖默认 debug 证书。

```bash
adb install -r PhotoSync-0.12.0-debug.apk
```

## 连接服务

1. 正式数据：先在服务端网页初始化管理账户及 TOTP，然后由管理员创建客户端用户。初始管理员不能登录客户端。
2. 安卓填写服务根地址，例如 `https://photos.example.com`；不要填写 `/admin` 或 `/client`。
3. 输入客户端账户和密码，首次登录显示 TOTP 密钥，可复制到验证器或交给本机验证器打开；验证后保存仅显示一次的恢复码。
4. 后续登录仍强制验证码。手机与服务器都需要正确的系统时间。

本机已有免登录原型可以继续用，不必为了查看安卓界面在当前电脑创建真实账户：

```bash
# 保持现有原型仅监听本机，通过 USB 转发；不用再起第二个服务
adb reverse tcp:8080 tcp:8080
# 安卓 debug 应用中填 http://127.0.0.1:8080
```

模拟器填 `http://10.0.2.2:8080`。实体手机经 Wi-Fi 连接时填服务端局域网 IP，并让**正式服务**监听 `0.0.0.0`。免登录原型仍限制回环地址，不允许免认证暴露到局域网。

## 已实现

- 客户端独立账户、密码 + TOTP / 恢复码；服务端授权隔离不因安卓端改变。
- 会话 Cookie 使用 Android Keystore 的 AES-GCM 加密，不保存密码，禁止系统备份应用数据。
- 照片列表及服务端 JPEG 缩略图、原图详情；视频使用系统播放器和 Range 流式播放，不先下载整个视频；可请求 FFmpeg 兼容预览。
- 详情显示存储位置（客户端为逻辑位置）、格式、大小、分辨率、相机参数、SHA256、视频时长。缺失元数据不伪造。
- GIF / 动态 WebP 在 Android 9+ 使用系统动态图片解码；Android 8 显示静态帧。Live Photo 可选择两个已上传的图像 / 视频资源确认配对及播放，不把同名文件直接当作配对证据。
- 多文件上传、多本机相册目录。通过系统文件选择器获得持久只读 URI 授权，不索取所有文件访问权限，不搬动或删除原文件。
- SQLite 上传队列按服务器 + 客户端用户名隔离。4 MiB 流式分片，服务端最大 10 GiB，全文件 SHA256 精确去重；先查询服务端持久偏移，再恢复上传。源文件大小 / 修改时间变化时拒绝沿用旧会话。
- 手动同步前台服务及通知，可暂停；超时 / 断网 / 进程退出后，队列和服务端偏移仍保留。修复网络后点击同步重试。
- 自动扫描每 15 分钟由 JobScheduler 调度、开机恢复调度；应用存活时网络变化也会触发尝试。每次上传分片前检查配置 SSID，无法确认匹配时暂停。
- 生物认证用于返回应用时解锁当前会话。**不冒充服务端第二因素，也不延长会话**：当前服务端会话 12 小时过期，之后必须重新密码 + TOTP。原生 passkey 跨登录替代仍未实现。

## Wi-Fi 自动同步权限

指定 SSID 需要精确定位授权、系统定位开关及 Wi-Fi 状态权限。Android 对后台读取 SSID 还限制后台定位，使用设置中的授权入口或系统“应用权限”选择允许后台定位；不同系统可能只允许在系统设置授予。拒绝权限仍可手动同步。只支持配置一个精确 SSID。

自动任务额外要求“不计费网络”，所以配置为计费的 Wi-Fi 不自动上传。Android 省电、强制停止、重启后首次解锁、厂商后台管理都会影响调度；**不承诺连接 Wi-Fi 当刻立即同步**。手动同步不受 SSID 策略限制，可使用当前网络。

## 大视频和同步边界

- 没有把整个视频放入内存或复制到临时目录。云文档提供方的 URI 可能需要逐段跳读，续传寻址速度依赖提供方。
- 单次后台任务限制约 7 分钟，前台同步约 5 小时；达到系统预算后保存偏移，稍后继续。Android 15+ 数据同步前台服务受系统每日时限限制。
- 本轮最多处理 500 条队列记录；大量图库可重复执行同步 / 等待下一轮。扫描单次最多遍历 100000 个目录。
- 空文件、未知大小和超过 10 GiB 的目录资源跳过；单独选择上传会提示大小错误。当前不提供所有跳过资源的独立报告。
- 源文件应保持不变。修改时间和大小只是变化检查，不是内容签名；请勿在上传期间以相同时间戳覆盖源文件。最终 SHA256 由服务端计算。
- 暂无“删除同步”、系统相册 MediaStore 全库扫描、安卓厂商单文件 Motion Photo 解包、iOS / 鸿蒙客户端。
- 缩略图仅支持服务端 Pillow 能解码的图像；HEIC 不支持时可尝试 FFmpeg。无图像缩略图时文件条目仍可打开，视频直接显示条目。原图本机显示限制 32 MiB，大图可使用兼容预览。
- 安卓端目前不执行 NPU 人脸识别、115 归档或 SnapRAID。它们属于服务端功能；尚未实现的能力不会显示为已成功。

## 从源码构建

Android Studio 打开 `android/`，安装 SDK platform 36 和 Build Tools 36.0.0；JDK 17+。

```bash
cd android
./gradlew :app:assembleDebug :app:assembleDebugAndroidTest :app:lintDebug
# 有真机 / 模拟器时
./gradlew connectedDebugAndroidTest
```

`local.properties`、缓存、数据库和签名文件都不入库。可选 `PHOTOSYNC_DEBUG_KEYSTORE` 环境变量指定固定 debug keystore。Gradle Wrapper 固定 9.1.0，AGP 固定 8.13.1，不依赖电脑上预装 gradle。

## 验证与真机调试清单

本次验证结果见发布说明；没有连接安卓设备时，构建成功不等于通过真机后台同步测试。

- 用服务端创建两个客户端用户，确认不能互相浏览媒体或续传会话。
- 上传相同照片两次，服务端只保存一个 SHA256 原片；重启服务再上传应保持去重。
- 上传视频到中途断网 / 暂停 / 关闭进程，恢复后偏移继续增长；使用真实 10 GiB 演唱会文件验证耗时、播放和磁盘余量。
- 设置两个相册目录，重启应用和手机，确认授权仍有效；撤销目录权限应报错并保留已上传照片。
- 配置 SSID 后，在其他 Wi-Fi / 移动网络 / 拒绝定位时确认自动上传暂停；在指定 Wi-Fi 上等待系统调度。手动同步可单独测试。
- 实测 TOTP 首绑、恢复码、会话过期、指纹取消、视频拖动和 Live 配对。

参考：[Android 文件夹授权](https://developer.android.com/training/data-storage/shared/documents-files)、[JobScheduler 网络限制](https://developer.android.com/reference/android/app/job/JobInfo.Builder)、[Android 前台服务时限](https://developer.android.com/develop/background-work/services/fgs/timeout)。
