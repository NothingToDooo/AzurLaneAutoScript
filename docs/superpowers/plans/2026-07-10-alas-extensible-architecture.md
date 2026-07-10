# ALAS 可扩展架构实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在不重写现有游戏状态机的前提下，把持续变化的国区游戏内容从稳定运行内核中收口出来，并显式化设备 serial、任务目录、内容目录和回放验证边界。

**Architecture:** 保持单进程模块化单体和现有 `Device`、任务类、战役类外部接口。通过兼容适配器渐进引入 `ContentCatalog`、`StageSpec`、`TaskDefinition`、配置快照及设备组合对象；历史关卡继续可运行，新内容优先走新边界。

**Tech Stack:** Python 3.14.6、uv、Ruff、ty、pytest、Windows、MuMu。

## Global Constraints

- 当前个人版只支持 Windows + MuMu + 国区 + WebUI。
- 设备栈始终是 MuMu + nemu_ipc 截图 + minitouch 控制；ADB 是连接、shell、包名、forward、minitouch 等必要底座。
- Python 命令统一使用 `uv run`，不用裸 `python`。
- 不添加 `from __future__ import annotations`。
- 触碰到的注释和 docstring 尽量使用中文。
- 不建设多平台、多服务器、动态安装插件、微服务或通用 FSM 框架。
- 现有 imperative screenshot loop、Combat 三阶段、Fleet.goto、CampaignBase.run 和科研状态机不做整体重写。
- 新行为必须先看到对应测试按预期失败，再写实现。
- 每个任务独立验证、独立审查、小步提交；提交信息使用英文 tag + 中文说明。

---

### Task 1: 原子 serial 重绑定

**Files:**
- Modify: `module/device/connection_attr.py`
- Modify: `module/device/mumu_discovery.py`
- Modify only if required by lifecycle ownership: `module/device/connection.py`
- Test: `tests/test_connection_attr_serial.py`
- Test: `tests/test_device_detect_device.py`

**Interfaces:**
- Produces: `ConnectionAttr.bind_serial(serial: str, *, persist: bool = False) -> bool`
- Guarantees: serial 不变时无副作用；serial 改变时先释放旧 serial 资源，再失效所有 serial 派生缓存，最后发布新 serial；运行时端口漂移不写回用户配置。
- Invalidates at minimum: `port`、`is_mumu12_family`、`is_mumu_family`、`adb`、`emulator_instance`、MuMu getprop/version cache、minitouch forward/client/stream/builder；已创建 nemu_ipc 时安全释放。

- [ ] **Step 1: 写会失败的缓存失效测试**

```python
def test_bind_serial_invalidates_runtime_state_without_persisting_config():
    connection = make_connection("127.0.0.1:16384")
    prime_serial_bound_state(connection)

    changed = connection.bind_serial("127.0.0.1:16385")

    assert changed is True
    assert connection.serial == "127.0.0.1:16385"
    assert connection.config.Emulator_Serial == "127.0.0.1:16384"
    assert_serial_bound_state_released(connection)
```

- [ ] **Step 2: 运行定向测试并确认因缺少 `bind_serial` 或旧缓存仍存在而失败**

Run: `uv run pytest tests/test_connection_attr_serial.py tests/test_device_detect_device.py -q`

- [ ] **Step 3: 实现最小重绑定边界并让 MuMu 端口漂移只调用这一入口**

- [ ] **Step 4: 补 serial 不变、持久修正、重复释放和旧 minitouch 初始化线程场景**

- [ ] **Step 5: 运行设备连接相关测试、Ruff、ty 和差异检查**

Run: `uv run pytest tests/test_connection_attr_serial.py tests/test_device_detect_device.py tests/test_device_minitouch_retry.py tests/test_device_nemu_ipc_retry.py tests/test_platform_base_find_emulator_instance.py -q`

- [ ] **Step 6: 提交**

Commit: `fix: 收拢设备serial重绑定状态`

---

### Task 2: 内容与回放契约基础

**Files:**
- Create: `module/content/__init__.py`
- Create: `module/content/errors.py`
- Create: `module/content/models.py`
- Create: `module/content/validation.py`
- Create: `module/replay/__init__.py`
- Create: `module/replay/trace.py`
- Create: `module/replay/device.py`
- Test: `tests/test_content_models.py`
- Test: `tests/test_replay_device.py`

**Interfaces:**
- Produces: frozen/slotted `ContentId`、`EventPack`、`StageRef`、`StageSpec`、`AssetRef`、`ValidationIssue`。
- Produces: `ReplayFrame(image_path: Path, expected_actions: tuple[RecordedAction, ...])` 与只实现截图、点击、滑动所需窄接口的 `ReplayDevice`。
- Boundary: 回放只记录语义动作和帧，不导入 WebUI，不启动 ADB、nemu_ipc 或 minitouch。

- [ ] **Step 1: 写模型边界和非法输入测试**

```python
def test_stage_ref_rejects_empty_pack_or_stage():
    with pytest.raises(ValueError):
        StageRef(pack_id="", stage_id="t1")
```

- [ ] **Step 2: 写 ReplayDevice 帧耗尽、动作顺序和错误动作测试并确认失败**

Run: `uv run pytest tests/test_content_models.py tests/test_replay_device.py -q`

- [ ] **Step 3: 实现最小不可变模型、JSON trace 读写和 ReplayDevice**

- [ ] **Step 4: 使用临时目录与合成 1280×720 图片验证 trace 往返，不提交游戏截图**

- [ ] **Step 5: 运行定向检查并提交**

Commit: `feat: 建立内容与截图回放契约`

---

### Task 3: ContentCatalog 与历史关卡适配器

**Files:**
- Create: `module/content/catalog.py`
- Create: `module/content/legacy_stage.py`
- Modify: `module/campaign/run.py`
- Test: `tests/test_content_catalog.py`
- Test: `tests/test_legacy_stage_adapter.py`
- Modify: `tests/test_campaign_run_flow.py`

**Interfaces:**
- Produces: `ContentCatalog.get_pack(pack_id: str) -> EventPack`、`resolve_stage(StageRef) -> StageSpec`。
- Produces: `LegacyStageModuleAdapter.load(StageRef) -> LoadedStage`，其中 `LoadedStage` 暴露 `config_class`、`campaign_class` 和 `map`。
- Campaign compatibility: `CampaignRun.load_campaign()` 经 catalog/adapter 装载，但当前 `campaign.<folder>.<stage>` 模块的 Config 合并和 Campaign 构造语义不变。

- [ ] **Step 1: 写 catalog 重复 ID、未知 pack/stage 和 legacy module 装载测试**

- [ ] **Step 2: 确认测试因 catalog/adapter 不存在而失败**

Run: `uv run pytest tests/test_content_catalog.py tests/test_legacy_stage_adapter.py -q`

- [ ] **Step 3: 实现确定性显式注册表与 legacy adapter**

- [ ] **Step 4: 将 CampaignRun 装载入口切到 adapter，并锁定 ModuleNotFoundError 的现有中文诊断信息**

- [ ] **Step 5: 全量扫描现有 stage 模块的静态导出契约；不实例化设备、不运行关卡**

- [ ] **Step 6: 运行 campaign 定向测试并提交**

Commit: `refactor: 为历史关卡建立内容目录边界`

---

### Task 4: 活动清单与日期策略收口

**Files:**
- Create: `content/events/*.yaml`
- Create: `module/content/manifest.py`
- Create: `module/content/campaign_policy.py`
- Modify: `module/campaign/run.py`
- Modify: `module/config/config_updater.py`
- Modify: `campaign/Readme.md`
- Test: `tests/test_content_manifest.py`
- Modify: `tests/test_campaign_stage_name.py`
- Modify: `tests/test_config_generator_insert_event.py`

**Interfaces:**
- Produces: `load_event_manifests(path: Path) -> tuple[EventPack, ...]`，严格拒绝重复 ID、非法日期、未知 UI profile、悬空 stage/asset 引用。
- Produces: catalog 驱动的 stage alias、章节集合和运行覆盖策略。
- Generator boundary: 活动 manifest 是机器真相；`campaign/Readme.md`、活动选项和 i18n 是生成结果。
- Core invariant: `module/campaign/run.py` 不再包含 `event_YYYYMMDD_cn` 或 `war_archives_YYYYMMDD_cn` 字面量。

- [ ] **Step 1: 写 manifest schema、README 等价输出和现有 alias/policy 参数化测试**

- [ ] **Step 2: 确认测试因 manifest loader 不存在或 dated 分支仍在核心而失败**

- [ ] **Step 3: 从当前 README 和核心纯映射机械生成首版 manifest，逐项审查后提交源文件**

- [ ] **Step 4: 让 ConfigGenerator 从 catalog 生成活动选项和 README**

- [ ] **Step 5: 将 CampaignRun 纯 alias/override 日期分支迁到 pack policy；特殊有状态行为暂留 pack-local Python hook**

- [ ] **Step 6: 加守卫测试禁止稳定核心重新出现 dated event ID**

- [ ] **Step 7: 运行配置生成与战役测试并提交**

Commit: `refactor: 收拢国区活动内容清单`

---

### Task 5: 原生 StageSpec 与有限 BattlePolicy

**Files:**
- Create: `module/content/stage_loader.py`
- Create: `module/content/battle_policy.py`
- Create: `content/events/event_20260625_cn/stages/*.yaml`
- Modify: `dev_tools/map_extractor.py`
- Modify: `module/campaign/run.py`
- Test: `tests/test_stage_spec_loader.py`
- Test: `tests/test_battle_policy.py`
- Test: `tests/test_map_extractor_stage_spec.py`

**Interfaces:**
- Produces: 原生 StageSpec loader，可构造与历史 `CampaignMap`/Config 等价的 LoadedStage。
- Produces: 有限命名策略 `siren_then_filtered_enemy`、`filtered_enemy_then_default`、`fleet_boss`；策略只组合现有 Campaign 行为，不解释任意表达式。
- Escape hatch: manifest 可引用 pack-local `strategy` 导入路径；未知策略在加载时失败。
- Generator: 新活动默认输出 map/spawn/camera/config 数据文件与独立策略引用，不覆盖手写策略文件。

- [ ] **Step 1: 为 20260625 T/HT/SP 选择代表关卡写旧模块与 StageSpec 等价测试**

- [ ] **Step 2: 写三种命名 BattlePolicy 的调用顺序和短路测试并确认失败**

- [ ] **Step 3: 实现 loader 与有限策略，不增加通用 DSL**

- [ ] **Step 4: 修改 map_extractor 输出新格式并加 golden test**

- [ ] **Step 5: 迁移 20260625 内容；旧 Python 模块保留薄兼容导出，运行调用方不变**

- [ ] **Step 6: 运行战役、提取器和全量内容契约并提交**

Commit: `feat: 让新活动使用StageSpec内容格式`

---

### Task 6: TaskCatalog 单一任务目录

**Files:**
- Modify: `module/task_registry.py`
- Modify: `module/config/argument/task.yaml`
- Modify: `module/config/config.py`
- Modify: `module/webui/process_manager.py`
- Modify: `module/config/config_updater.py`
- Test: `tests/test_task_registry.py`
- Modify: `tests/test_webui_process_manager.py`
- Create: `tests/test_task_catalog_config.py`

**Interfaces:**
- Renames/evolves: `TaskSpec` → `TaskDefinition`，保留 `execute(runner)`。
- Adds: `config_scopes: tuple[str, ...]`、`priority: int | None`、`launch_mode: Literal["scheduled", "direct", "both"]`。
- Produces: `TASK_CATALOG` 为任务 identity/executor/launch metadata 的唯一真相。
- Config schema remains: `argument.yaml` 定义字段；task groups 必须引用 catalog 中存在的 command。
- WebUI direct tools derive from `launch_mode`，不保留第二份 allowlist。

- [ ] **Step 1: 写 catalog、task.yaml、配置绑定和 WebUI direct 列表一致性测试**

- [ ] **Step 2: 确认测试在当前多份真相下失败**

- [ ] **Step 3: 演进 TaskSpec 并兼容 `get_task_spec()`**

- [ ] **Step 4: 让配置作用域和 WebUI direct 能力读取 catalog**

- [ ] **Step 5: 运行全部任务 registry/config/WebUI 测试并提交**

Commit: `refactor: 统一任务目录与启动能力`

---

### Task 7: 配置解析与调度状态分界

**Files:**
- Create: `module/config/resolved.py`
- Create: `module/config/schedule.py`
- Modify: `module/config/config.py`
- Modify: `alas.py`
- Test: `tests/test_config_resolver.py`
- Test: `tests/test_schedule_planner.py`
- Modify: `tests/test_config_bind.py`
- Modify: `tests/test_alas_scheduler_wait.py`

**Interfaces:**
- Produces: immutable `ResolvedTaskConfig`，记录绑定链和解析后的字段快照，同时提供旧式属性读取适配。
- Produces: pure `SchedulePlanner.select(entries, *, now, priority) -> ScheduleDecision`。
- Storage boundary: AzurLaneConfig 暂时继续持久化 JSON；纯选择算法不写文件、不调用设备。
- Runtime boundary: scheduler 选择与等待行为保持，任务类仍可接收兼容 config facade。

- [ ] **Step 1: 写配置层优先级、不可变快照与 fake-clock 调度测试**

- [ ] **Step 2: 确认测试因 resolver/planner 不存在而失败**

- [ ] **Step 3: 提取纯解析器和调度选择，不迁移任务内部配置访问**

- [ ] **Step 4: 让 AzurLaneConfig/alas.py 委托新对象，锁定现有行为**

- [ ] **Step 5: 运行调度、配置、任务运行测试并提交**

Commit: `refactor: 分离任务配置解析与调度选择`

---

### Task 8: Device 门面后的显式组合

**Files:**
- Create: `module/device/runtime.py`
- Create: `module/device/services.py`
- Modify: `module/device/device.py`
- Modify: `module/device/connection.py`
- Modify: `module/device/platform/platform_base.py`
- Modify: `module/device/app_control.py`
- Modify: `module/device/method/minitouch.py`
- Modify: `module/device/method/nemu_ipc.py`
- Test: `tests/test_device_runtime.py`
- Test: `tests/test_device_imports.py`
- Modify: existing device tests as required

**Interfaces:**
- Keeps: 上层仍只持有 `Device`，现有 `screenshot/click/swipe/app_start/app_stop/adb_shell` API 不变。
- Produces concrete composition: `DeviceRuntime(adb_session, mumu_runtime, capture, controller, app_controller)`。
- Ownership: 一个 AdbSession；MumuRuntime 解析实例；NemuIpcCapture 只截图；MinitouchController 只控制；AppController 只管理包进程。
- No registries: 不引入截图后端、控制后端、平台或服务器插件注册表。

- [ ] **Step 1: 写真实 Device MRO characterization、构造顺序、资源释放和 façade 委托测试**

- [ ] **Step 2: 确认新组合接口测试失败，旧行为 characterization 通过**

- [ ] **Step 3: 先组合 AppController，再组合 minitouch，再组合 nemu_ipc；每步保留委托兼容**

- [ ] **Step 4: 移除不再需要的 Connection 菱形继承边，但不重写业务任务**

- [ ] **Step 5: 验证 MuMu + nemu_ipc 截图 + minitouch 控制和 ADB 底座职责**

- [ ] **Step 6: 运行全部设备测试并提交**

Commit: `refactor: 在Device门面后组合设备服务`

---

### Task 9: 删除全局 Config.when 魔法并完成总验证

**Files:**
- Modify: `module/campaign/campaign_base.py`
- Modify: `module/shop/base.py`
- Modify: `module/base/decorator.py`
- Test: `tests/test_campaign_battle_policy_dispatch.py`
- Test: `tests/test_shop_base_items.py`
- Modify: relevant tests

**Interfaces:**
- Removes: 全局按函数名索引、依赖导入顺序的 `Config.func_list` 分派。
- Replaces with: CampaignBase 中显式 policy 选择；国区商店中显式固定策略。
- Invariant: 不增加通用策略注册器或字符串反射。

- [ ] **Step 1: 写当前三种 battle_function 配置组合和商店网格行为测试**

- [ ] **Step 2: 确认 characterization 测试通过；写全局同名碰撞测试并确认暴露现有问题**

- [ ] **Step 3: 改成显式分派，删除 Config.when 及其 F811/noqa**

- [ ] **Step 4: 运行所有定向测试**

- [ ] **Step 5: 运行完整门禁**

Run:

```powershell
uv sync --check
uv run ruff check . --no-cache
uv run ruff format --check .
uv run ty check
uv run pytest
git diff --check
```

- [ ] **Step 6: 独立审查整个提交范围，修复全部 Critical/Important 问题并复验**

- [ ] **Step 7: 提交**

Commit: `refactor: 删除全局配置分派魔法`

---

## Completion Criteria

- MuMu 动态端口漂移不会残留旧 adb、模拟器实例或 minitouch 资源。
- `module/campaign/run.py` 不含具体活动日期字面量。
- 活动机器清单来自 ContentCatalog，README/WebUI 选项为生成结果。
- 所有历史关卡可通过 LegacyStageModuleAdapter 加载；新活动可使用 StageSpec。
- 常见战斗顺序用有限 BattlePolicy，复杂机制保留 pack-local Python hook。
- TaskCatalog 统一执行入口、配置作用域和 WebUI 启动能力。
- 调度选择可用 fake clock 纯测试，任务配置可形成不可变解析快照。
- Device 外部 API 不变，内部设备服务有明确所有权。
- `Config.when` 删除。
- 内容、任务、设备、回放契约和全量验证全部通过，工作区干净，独立审查无未解决 Critical/Important 问题。
