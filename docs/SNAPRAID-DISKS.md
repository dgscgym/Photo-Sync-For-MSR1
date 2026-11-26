# 0.6.0 · 图形化磁盘与保护模式

参考 OMV 的 Data / Parity / Content 角色设计，将首次配置的主要入口改为“选择磁盘 → 选择模式 → 检查方案 → 确认保存”。用户无需填写 snapraid.conf。

## 模式和磁盘

- 单校验：1 块独立校验盘。
- 双校验：2 块独立校验盘。
- 三校验：3 块独立校验盘。
- 数据盘与校验盘互斥；可为所选磁盘勾选 Content 元数据副本，至少为校验级别 + 1 份，分布在独立物理磁盘。
- 校验容量不小于最大数据盘，并检查剩余空间能否满足当前已用数据的保守估算；这不是实际 sync 后的容量保证。
- 本版不提供 RAID0/RAID1 选项，SnapRAID 校验不是实时镜像或条带；4–6 级校验、Split Parity 与 mergerfs 后续单独评估。

## 真实磁盘发现

Linux 中读取 /proc/self/mountinfo，结合 stat、容量和 /sys/dev/block 识别挂载与物理失效域。只显示 --storage-base 或 --library-base 授权范围中的挂载磁盘，不把普通文件夹或根文件系统当作独立盘。

同一物理盘的不同分区 / 绑定目录不能用作多块独立盘。只读、已发现既有 SnapRAID 文件、无法确认物理盘身份的设备不可选择；多设备卷也不按独立单盘处理。

PVE / LXC 内必须提供正确挂载与只读设备识别信息。无法识别时说明原因并阻止保存，而非虚构可用磁盘。Mac 开发预览没有 Linux 磁盘枚举，显示无可选磁盘，不代表 MS-R1 没有磁盘。

```bash
python3 -m server.app --storage-base /media --library-base /media/photos
```

## 保存结果与边界

- POST /api/v1/setup/snapraid，JSON `{mode,disks:[{id,role,content}],preview:true}` 检查方案；确认时改为 `confirmed:true`。
- 服务端每次重新枚举并校验，不信任浏览器提供的路径、容量或物理盘信息。
- 生成 data/snapraid/snapraid.conf，方案保存在数据库 app_settings；不修改实际数据盘 / 校验盘文件。
- 当前只建立 **planned** 状态，全局提示“未首次同步、未建立校验保护”。不会自动执行 sync / scrub / fix，不会格式化、清空磁盘或创建盘身份标记。
- 已保存方案和由启动参数管理的阵列不能直接覆盖；后续增加迁移与受控变更流程。
- 先前已有配置的 API / 启动参数接入保留兼容，但不再作为普通用户的初始化表单。
- 检查周期随方案保留，真正启用自动检查需后续的阵列首次同步与托管生命周期集成；本版不将“保存方案”显示成“阵列运行正常”。

已测试单/双/三校验生成、Content 副本数量、容量不足、同物理盘拒绝、方案预览不落盘与禁止覆盖。真实 MS-R1 / PVE 磁盘识别、首次同步及浏览器视觉仍待验收。

参考：[OMV SnapRAID 插件](https://wiki.omv-extras.org/doku.php?id=omv7:omv7_plugins:snapraid)、[OMV 配置生成模板](https://github.com/OpenMediaVault-Plugin-Developers/openmediavault-snapraid/blob/master/srv/salt/omv/deploy/snapraid/files/etc-snapraid_conf.j2)、[SnapRAID 官方手册](https://www.snapraid.it/manual)。
