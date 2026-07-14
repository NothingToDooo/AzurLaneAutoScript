# ALAS 目标架构

本文定义本仓库重构完成时必须成立的边界。它不是旧实现说明，也不承诺旧类、旧配置 schema 或旧扩展点兼容。

## 设计目标

- 保留游戏仍存在的全部玩法；已经从游戏删除的 SOS 不属于迁移范围。
- 游戏更新时，优先新增内容定义、识别 profile 或窄领域策略，而不是继续扩大公共基类。
- 一次设备会话只有一个写入者；调度任务、辅助会话和直接命令不能并发操作同一模拟器。
- 游戏操作循环保持同步、单线程。并发只存在于进程监督、事件订阅等外围，不进入点击决策链。
- 任何正常结束、等待、重试、阻塞、取消和故障都有显式结果，不再以异常或配置文件副作用表达正常控制流。

## 依赖方向

```text
WebUI / Supervisor
        ↓ IPC
InstanceAgent
        ↓
application ─────→ state
     ↓                ↑
domain use cases ─────┘
     ↓
interaction ports
     ↓
MuMu12 / Replay adapters

content definitions ─→ typed catalogs ─→ domain policies
client UI profiles ──────────────→ recognizers / action drivers
```

约束：

- `application` 只认识任务身份、运行模式、取消/抢占、结果和效果。
- task catalog 只保存身份和启动元数据；implementation resolver 从同一个不可变 snapshot 一次产出
  `TaskResolution(task, metadata)`，不能让任务设置与 run revision 分两次读取。
- 领域模块不直接改 scheduler、全局配置或 WebUI 状态。
- `interaction` 的原始截图无业务副作用；全局弹窗处理发生在显式 `poll(scope)` 层。
- `state` 保存事实和原子事务，不决定业务策略。
- adapter 可以依赖端口和第三方库；端口不能反向依赖 adapter。

## 三种运行语义

- `SCHEDULED_JOB`：有限、可重调度的任务，包括 Campaign、设施、商店和大世界 farming。
- `ASSIST_SESSION`：与玩家操作共存、只能显式取消的 daemon。
- `DIRECT_COMMAND`：用户主动执行的一次性工具。

允许从 WebUI 的哪个入口启动是另一条轴，由 `LaunchSurface` 表达，不能用它推导运行生命周期。

## 任务结果和效果

任务统一返回 `TaskResult(outcome, effects)`。

终态闭合为：

- `Succeeded`
- `Deferred`
- `Retryable`
- `Blocked`
- `Cancelled`
- `Faulted`

跨任务或调度副作用闭合为：

- `RescheduleSelf`
- `RescheduleTask`，只调整既有目标任务的 due time 并保持 enabled 状态
- `WakeTask`，并显式选择尊重禁用或强制启用
- `DisableTask`
- `RequestAppRestart`

用户立即停止由 `AbortToken` 表达；调度器请求在安全点切换由 `PreemptionRequest` 表达。两者不能合并。

## 状态事实

每个实例使用一个 SQLite/WAL 数据库，并分离：

- `settings`：带 revision 的用户意图快照
- `configuration_source`：编译后配置摘要及其实际发布到的 settings revision
- `schedule`：enabled、due time、priority
- `task_state`：领域 checkpoint
- `runs`：运行身份、版本信息和终态
- `run_events`：有序运行事实
- `outbox`：与 run 终态同事务提交的外发事件

一次 run 的终态、调度变化、领域事件和 outbox 必须原子提交。游戏点击无法回滚，因此不可逆动作采用：

```text
observe → record intent → issue action → observe confirmation → checkpoint
```

实例启动时只在编译摘要变化后以 CAS 原子替换 `settings + schedule + configuration_source`；摘要未变化时，
必须保留运行中已经推进的 due time，禁止用磁盘 JSON 的旧 `NextRun` 覆盖 SQLite 事实。

每次 run 必须记录 settings revision、content revision 和 client UI revision，保证故障与 Replay 可以还原当时环境。

`RescheduleTask` 与 `WakeTask` 不能混用：前者用于 OpSi 等批量延后但不改变用户启用意图的场景，后者表示真正唤醒任务。

## 设备交互

`Frame` 拥有只读像素、单调递增 id、monotonic 时间和带时区 wall time。业务代码不得依赖可被下一次截图覆盖的 `device.image`。

动作是闭合类型：`Click`、`LongPress`、`Swipe`。每个动作保存语义目标、最终坐标和产生决策的 frame id。Live MuMu12 与 Replay 实现同一组端口：

- `FrameSource`
- `ActionSink`
- `AppLifecycle`
- `Clock`

## 领域边界

共享 runtime 契约不意味着共享业务状态机。稳定领域至少包括：

- Grid Campaign
- 非网格 Encounter
- Exercise
- Operation Siren World
- Commission / Research / Tactical 等独立设施
- Market 与 DockCapacityRecovery
- 复合日常 use case
- 活动专用不可变 client profile 与窄策略

Raid、Coalition 只与 Campaign 共享战斗能力，不共享地图 session；Operation Siren 是持久世界，不是大号 Campaign。

## 活动内容与客户端 profile

活动不再由日期分支、动态资源名或 Campaign 子类表达。`EventPack.activity` 是严格的
`EventStoryDefinition | RaidDefinition | CoalitionDefinition | None`；`ActivityCatalog` 从与
`ContentCatalog` 相同的不可变 manifest snapshot 一次建立，并只对外暴露带 `ContentId` 的
`EventStoryActivity`、`RaidActivity`、`CoalitionActivity` 与不可变 activity 序列。

所有权分配如下：

| 层 | 拥有的事实 | 不应拥有 |
| --- | --- | --- |
| manifest definition | EventStory 是否可用；Raid 的 modes、daily modes、ticket modes；Coalition 的 stage、battle count、fleet rule | 模板、ROI、OCR 参数、日期特判 |
| immutable client profile | 页面、入口、结束检查点、识别参数与封闭的导航/OCR/弹窗策略 | 可玩 mode、战斗次数、调度和任意回调 |
| domain/workflow | 构造已验证 plan/session，执行有界安全单元，返回 typed result/report | scheduler 写入、跨任务唤醒或禁用 |
| application/coordinator | 把 report 转换为 `TaskResult` 与调度 effect | 客户端识别和点击细节 |

client profile 必须是 `frozen` 值对象，策略必须是闭合枚举或窄类型。EventStory 只组合 landing page、
special-entry probe 和 popup handler；Raid 只组合 landing/navigation、每 mode 入口与次数识别；
Coalition 只组合 mode driver、entry strategy、PT OCR、oil 读取位置与 stage assets。新活动优先只新增
manifest 并绑定已有 profile；客户端布局真正出现新切面时，才增加一个 profile 或一个窄策略，
不能以活动日期继续扩大公共 runner。

War Archives 不是 Activity runner，但遵守相同的内容/客户端分层：每个 archive manifest 在 pack 层声明
semantic `war_archives.profile`，不可变 client registry 只负责把该语义 profile 绑定到入口模板。profile 随
`StageSpec → CampaignStageDefinition` 投影到运行时；导航不得再用 `Campaign_Event`、日期 ID 或全局字典查资产。
manifest 引用集合与 client registry 必须 exact closure，unknown 与 unused profile 都在启动期失败。

production bootstrap 必须遵守以下顺序：

```text
load manifests
  → ContentCatalog
  → validate every War Archives/client-profile binding
  → ActivityCatalog + validate every activity/client-profile binding
  → compile and validate every Campaign runtime profile/executor contract
  → build campaign session source
  → construct Device
  → build workflows
```

profile 校验遍历 `ActivityCatalog.activities`，不只校验当前选中的活动。未知 profile、Raid content/client mode
不一致、daily/ticket mode 缺少次数识别、Coalition content/client stage 不一致，都必须在
`Device` 构造和任何 I/O 之前失败。单次命令中的原始 content/mode/stage/fleet 值在 factory 边界转为
typed options，Raid plan 与 Coalition client session 在 `_device_for` 激活设备前再验证选择约束。

Raid、Coalition 与 Maritime Escort 的原子执行分别返回 `RaidExecutionResult`、`CoalitionExecutionResult`
和 `MaritimeEscortExecutionResult`；活动
workflow 统一向上返回 `ActivityReport`、`EncounterReport` 或 `AssistSessionReport`。正常停止、资源不足、
次数耗尽、活动不可用和恢复等待都是 typed fact；activity domain/adapter 不调用 scheduler 变更 API，
只有 application/coordinator 能把这些事实解释为调度 effect。

## Campaign 内容与策略

关卡编译为不可变 `CampaignStageDefinition`，静态地图定义、运行状态、观测证据和推断知识分别保存。

```text
Frame
  → MapObservation
  → Reconciler
  → CampaignSnapshot
  → StagePolicy
  → typed Intent
  → IntentExecutor
  → DomainEvent
  → Reducer
```

Campaign 的调度边界是一个已确认的 battle 安全单元，而不是整个地图循环。`CampaignProgress` 同时保存
`StageRef`、run variant、完整 `CampaignSessionState`、累计地图完成数以及 settings/content revision；
`pending` action 只能存在于进程内的 decide/execute/reduce 期间，run 边界必须为空。继续执行或安全点抢占时，
checkpoint 与立即重调度原子提交；真正终止时删除 checkpoint。Stage、variant 或 revision 已变化的 checkpoint
先删除并立即重调度，不允许带入新的 workflow。

`LiveCampaignWorkflow` 已把一次真实执行固定为 `observe → decide → issue_and_confirm → reduce`，并通过
`CampaignBattlefieldObserver`、`CampaignBattleIntentDriver` 两个窄端口连接客户端。现有 Campaign Map adapter
只执行原子 typed intent，以 `battle_count` 恰好增加一次作为成功证据；Boss 路障与 Boss 本体分别结算，禁止调用
会在内部清路障、猜刷新点或连续执行的 compound `clear_boss/brute_clear_boss`。动作确认后即使收到迟到取消，也必须
先完成 reduce 并提交 pending-free checkpoint。

每个 manifest stage 都严格加载 schema v4 YAML，并一次编译为不可变 `CampaignStageDefinition`。它组合而不继承以下正交内容：

1. `MapDefinition` / `RunVariant`：普通、周回的地图和刷新事实。
2. `StageRules` / `StageMechanicRules`：导航、观测、移动敌人、墙、迷宫、要塞等规则。
3. `StagePolicy`：普通 battle 的闭合目标选择策略。
4. `BattleProgram`：少数复合 battle 的有界 typed action 程序。
5. `BossApproachPlan`：只在 generic Boss 分支生效的候选格排序与进场动作。
6. `CampaignRuntimeProfile`：识别、导航、活动 UI、地图机制和 engine extension 的显式实现绑定与 tuning。

`BattleProgram` 不是任意脚本语言：没有循环、动态 import、字符串方法调用或隐式异常分支，只允许闭合 statement/condition/action
代数。每个 program 必须声明 `NORMAL`、`CLEAR_ALL`、`POOR_MAP_DATA` 中的激活模式；未覆盖的模式回到同一套 generic
mode policy。需要复用 generic 行为时只能通过 typed `DelegateBattle` 委托。地图内一次性事实使用 `ProgramMarker` 持久化，
不能继续增加以具体关卡命名的 boolean flag。

`Mumu12CampaignRuntimeProvider` 是地图 runtime 的 composition boundary：从 stage definition、attempt settings 和 runtime profile
创建一个 runtime，并由 activation、guard、observer、program executor 共用。`LiveCampaignWorkflow` 在唯一报告出口调用 lifecycle：
`IN_PROGRESS/PROGRAM_CONTINUE + ACTIVE` 保留同一 runtime 供下一 turn 恢复；地图完成、停止、阻塞、失败、取消或异常则以明确
outcome 释放。Hard mode 通过不可变 attempt overlay 组合，不修改基础 definition，也不另走 legacy Campaign class。

普通和周回地图在加载时编译成完整 `RunVariant`，运行中不修改同一份静态地图。关卡拥有自己的 policy、mechanics 和
program；复用发生在闭合类型与组合子层，而不是把单关行为拆到全局匿名引用表。只有真正跨关卡、依赖客户端实现且无法数据化的
能力，才能进入带稳定 id、显式 executor kind 和 options 的窄 runtime registry。不得用动态 stage import、`battle_N` 反射、
legacy Stage fallback、通用 uppercase config bag 或伪造 outcome 绕过边界。

runtime 契约由 production bootstrap 调用的纯 validator 负责，`dev_tools/campaign_runtime_profile_validator.py`
只是同一 validator 的命令行门面。它只读取当前 manifest、runtime profile registry 和 production executor registry，
在 `Device` 构造前校验每个 stage 引用已声明且有使用者的 profile、
每个声明的 extension 都有 profile 引用且不存在未知或未使用 extension，以及每个 executor kind/options
与已注册 production descriptor 闭合；
旧 Campaign Python 源码存在时直接失败。它不从历史 coverage 生成 runtime profile，也不依赖固定 profile/extension 数量。

一次性 migration inventory、固定数量账本和 legacy source parser 已在迁移验收后删除，避免未来新增关卡时维护
第二份历史事实。manifest + 当前严格、自包含的 YAML 与 runtime profile registry 共同构成唯一内容源；
动态闭包验证只检查当前 stage/profile/extension/executor 关系，不锁死数量。SOS 已从游戏删除，因此不进入内容包或兼容层。

## 游戏更新的两个版本轴

- `ContentRevision`：地图、spawn、敌人、奖励和活动规则。
- `ClientUiRevision`：页面结构、ROI、模板、OCR 和导航。

运行时只支持一个当前内部 schema 和一个当前客户端 UI revision。历史玩法先迁移到当前 schema，再保留为 content pack、窄策略和 Replay；不保留多版本 runtime 解析分支。

## 完成标准

- catalog 中全部当前命令都通过 coordinator 和 state transaction 运行。
- 每个仍存在的玩法均有明确 domain、definition/profile/policy，并有语义模拟或 Replay 验收。
- 所有 native content 在启动前严格编译；未知字段、引用、mechanic 或 UI revision 立即失败。
- `ActivityCatalog` 中全部 activity 的 manifest/profile 关系在 `Device` 构造前通过；单次选择在设备 I/O 前编译为 typed plan/session。
- 全部 War Archives profile 与 Campaign runtime executor/options 契约在 `Device` 构造前 exact closure。
- activity domain 的正常终止只通过 typed result/report 上报，不存在 scheduler 写入或日期特判。
- manual stop 在下一次 I/O 前停止产生新输入；preemption 只在领域安全点生效。
- WebUI 不直接写运行中状态，不创建第二个进程争抢同一设备。
- 设备独占必须是跨进程 OS lease；仅有进程内 mutex 不满足要求，进程崩溃后 lease 必须自动释放。
- 截图层不点击、不处理委托、不修改调度。
- 删除 `TaskEnd`、`task_delay/task_call/task_stop` 业务控制流、`battle_N` 反射、动态 `Campaign` 类型、legacy stage fallback 和通用 uppercase config bag。
- 全量 pytest、Ruff、ty、内容编译、语义模拟与 Replay 套件通过。
