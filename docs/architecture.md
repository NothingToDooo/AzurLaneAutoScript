# ALAS 个人版架构

本文只描述当前实现。这个分支面向一台 Windows 电脑、一个 MuMu 12 模拟器和国服客户端，不保留多实例、多设备、多平台或旧配置兼容路径。

## 目标与边界

- 保留游戏仍存在的全部玩法；已经从游戏删除的 SOS 不保留。
- 同一时刻只有一个执行者操作模拟器，截图、识别、点击和状态提交均为同步串行流程。
- WebUI 是日常入口；CLI 保留，用于直接运行、复现和调试。
- 游戏更新优先修改内容定义或窄领域适配，不扩展通用框架。
- 正常结束、等待、重试、阻塞、取消和故障都返回显式结果。
- 只维护当前 schema。配置或内容不符合当前契约时立即报错，不做静默迁移。

## 运行路径

```text
WebUI ──→ singleton ProcessManager ──→ child process ─┐
                                                     ├─→ run_default_command
CLI ─────────────────────────────────────────────────┘
                                                           │
                                                           ├─ load config/alas.json
                                                           ├─ compile settings + parsed driver document + SMTP
                                                           ├─ load manifests and validate profiles
                                                           ├─ create one in-process config owner
                                                           ├─ build one MuMu Device and 57 task factories
                                                           └─ RuntimeRunner
                                                                  │
                                                                  ├─ scheduler loop: command = alas
                                                                  └─ one task: explicit CLI/WebUI command
                                                                         │
                                                                         └─ RunCoordinator
                                                                                │
                                                                                ├─ TaskResult
                                                                                └─ ConfigStateRepository
                                                                                       └─ atomic write alas.json
```

WebUI 使用子进程是为了能够可靠停止游戏任务并持续显示日志，不代表允许多个模拟器执行者。`ProcessManager` 是进程内 singleton；保存或导入配置前先停止唯一子进程。CLI 直接调用同一个 production composition root，不维护第二套运行逻辑。

## 唯一配置与状态

唯一事实源是 `config/alas.json`。首次运行时，如果该文件不存在，就从 `config/template.json` 复制一次；之后只读取和写入 `alas.json`。

同一个文件保存三类事实：

- 模拟器、ADB 路径、用户配置和任务开关；
- `Scheduler.Enable`、`Scheduler.NextRun` 等调度状态；
- `Storage.Storage` 中的领域 checkpoint。

子进程启动时只读取一次文件，并由同一次编译得到 typed settings 和 legacy driver 需要的 parsed document。`ConfigStateRepository` 随后成为该子进程内唯一的文档 owner，同时持有 raw 与 parsed 快照：scheduler、checkpoint 和 legacy `AzurLaneConfig` 都经它读取或提交，不在调度循环中反复读盘，也不会由两个 writer 用 stale snapshot 相互覆盖。每次修改先完整编译候选，再一次原子写入，写失败时内存快照和磁盘都保持原状。

typed settings 在子进程启动时固定；WebUI 修改配置会先离线校验候选，再停止唯一子进程并写入，下一次启动使用新 revision。个人版没有 SQLite、WAL、CAS、lease、outbox、配置发布器或热重载协议，也不支持运行中从外部编辑文件。

任务内部学习或推进的字段仍通过同一个 owner 提交，并在下一次 legacy config bind 时读取最新值，不能再投影回 frozen policy。需要影响当前进程调度的变化必须作为 workflow report 的显式事实返回；例如装备码连续导出保留最新表，指挥喵训练自动关闭后立即停止周期检查。

配置 JSON 拒绝重复字段、非有限数字、未知或缺失字段、隐式字符串数值转换和无效 MuMu/截图参数。编译结果的 payload 对调用方只返回独立快照，摘要不会因外部 mutation 失真。

本地 `Scheduler.NextRun` 按 `Asia/Shanghai` 解释，运行时统一转换为带时区的 UTC 时间。checkpoint 保存 schema version、JSON payload 和 UTC 更新时间。任务只能修改自己的 checkpoint namespace。

## 任务与结果

`TASK_CATALOG` 是 57 个命令的唯一目录。每个任务只声明：

- command；
- config scopes；
- scheduler priority；
- `ExecutionMode`。

运行模式只有：

- `SCHEDULED_JOB`：由 `alas` 调度循环选择的有限任务；
- `ASSIST_SESSION`：需要用户明确停止的辅助会话；
- `DIRECT_COMMAND`：一次性工具。

任务统一返回 `TaskResult`。outcome 包括 `Succeeded`、`Deferred`、`Retryable`、`Blocked`、`Cancelled` 和 `Faulted`；调度 effect 包括重新调度、唤醒、禁用任务和请求重启；checkpoint 通过独立 state effect 写入。`RunCoordinator` 负责闭合一次执行，业务任务不直接操作 WebUI 或运行进程。

checkpoint 只记录 `settings_revision` 和 `content_revision`。配置或内容发生变化时，依赖旧 revision 的 Campaign、活动或大世界进度会失效并按当前事实重新开始；没有无人使用的 client UI revision 轴。

## 玩法与内容

玩法实现按真实业务边界拆分，包括 Campaign、非网格遭遇、演习、大世界、设施、商店、复合日常和活动。共享的是小型 typed contract，不共享大而全的任务基类。

活动和关卡的机器事实位于：

- `content/events/*.yaml`：活动包、关卡索引、别名、进度和活动定义；
- `content/events/stages/*.yaml`：完整关卡定义；
- `content/campaign-runtime-profiles.json`：客户端行为和 runtime implementation 组合；
- `module/content`：严格解析、catalog、policy 和不可变 definition；
- `module/adapters`：MuMu 12 客户端实现与少量无法数据化的窄策略。

production 启动时读取全部 manifest，并在创建 `Device` 前验证活动、作战档案和 runtime profile 引用闭合。关卡 definition 与 session 按第一次实际访问惰性编译并在当前进程缓存，避免每次启动预编译全部 1203 个关卡。

WebUI 保存和导入也会走同一内容目录及 57 个真实 settings decoder/factory 做离线校验。校验使用明确的只读 config 和无连接 Device seam，不创建 ADB client、不启动模拟器、不执行 workflow，也不写文件。自动保存遇到 pack/stage 等跨字段中间态时保留 pending changes，后续字段补齐后再形成一个原子候选。

开发阶段可以显式验证全部内容：

```powershell
uv run python -m dev_tools.campaign_runtime_profile_validator
```

该命令编译所有关卡并校验 production runtime contract；它不启动模拟器。

## 游戏更新的扩展顺序

新增或更新活动时，按下面的最短路径处理：

1. 修改对应 manifest 和 stage YAML。
2. 优先复用现有 activity/client/runtime profile。
3. 只有出现新的页面结构、识别方式或地图机制时，才新增一个不可变 profile 或窄 implementation。
4. manifest 改变任务选项后，运行配置生成器。
5. 运行全部内容验证和测试。

```powershell
uv run python -m module.config.config_updater
uv run python -m dev_tools.campaign_runtime_profile_validator
uv run pytest
```

禁止通过日期分支、动态 import、`battle_N` 反射、任意脚本 DSL 或旧 schema fallback 添加玩法。未知字段、未知引用、未使用 profile 和未注册 implementation 都应在验证阶段失败。

配置生成器把 manifest 中的当前 event、raid、coalition 和 war archive 投影为默认值与选项；缺少当前包、默认关卡或活动定义时立即失败。生成器不会保留手写日期补丁，`CoalitionSp` 等内容相关选项也由所选 manifest 的真实能力收窄。

## 故障诊断

设备始终保留一个有界的最近截图队列。任务或 composition 发生异常时，在 `log/error/` 写入一个独立目录：

- `error.json`：命令、任务、异常类型、消息和完整 traceback；
- `log.txt`：当前日志最后 2000 行；
- `screenshots/`：异常前最近的游戏截图。

CLI 返回稳定退出码并打印 error bundle 路径；WebUI 通过结构化 `CommandOutcome` 区分完成、停止、重启请求、故障和强制终止，不解析日志文字猜结果。

OCR 识别失败另外按 profile 保存最新 raw、processed 和 metadata 样本。该存储是有界覆盖，不维护指标数据库、去重索引或后台清理进程。

## 通知

通知只保留显式 SMTP 字段。发送发生在任务结果边界，每个收件人只尝试一次；失败写日志，但不改变已经确定的任务结果。没有 OnePush YAML、spool、outbox、pump 或后台重试服务。

## 完成约束

- 57 个任务全部有 factory，当前所有玩法测试通过。
- 调度器和直接命令共用同一个 runner、coordinator、repository 和错误处理边界。
- WebUI 不允许第二个游戏进程，也不在运行中改配置。
- production 只有 MuMu 12、`nemu_ipc` 截图和 `minitouch` 控制路径。
- 当前内容可全量编译，所有 profile/implementation 引用闭合。
- 全量 pytest、Ruff、ty、内容 validator 和 CLI smoke test 通过。
