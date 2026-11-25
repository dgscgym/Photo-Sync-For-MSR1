# 版本管理

采用 SemVer：`MAJOR.MINOR.PATCH`。0.x 为原型期，接口可能调整，但必须记录不兼容变化。

- `main`：已经验证的版本；每次开发使用独立的 `feature/*` 或 `fix/*` 分支。
- 开发提交使用 `feat:`、`fix:`、`docs:`、`test:` 等前缀。
- 合并前运行集成测试并检查差异；发布时更新 VERSION、CHANGELOG 和部署说明。
- 版本标签采用 `v0.1.0` 形式，发布后不移动标签。
- API 路径包含版本，例如 `/api/v1`；数据库用 schema_version 记录版本。
- 数据库结构后续变更必须有迁移与备份说明，不得依靠删除用户数据库升级。
- key/、数据目录、令牌、照片、运行环境配置不得进入 Git。
- 回退代码前核对数据格式兼容性；Git 回退不等于用户数据回退。

当前数据库 schema 5；0.2.0 自动创建会话及 Live 配对表，保留 schema 1 的原片和元数据。升级前应备份 data/，旧版本降级不支持新媒体能力。0.4.0 增加来源、位置与初始化设置，升级前自动备份元数据（见 INITIALIZATION.md）。0.3.0 增加日志与监控状态表（见 LOGGING.md）。v0.5.0 已加入单管理员登录，远端备份尚未实现，只用于本机评审。

CI 模板位于 `docs/ci-workflow.example.yml`；令牌具备 workflow 权限后可移至 `.github/workflows/test.yml` 启用。目前只验证了本机 Python 3.9，不能将模板矩阵视为已经通过。
