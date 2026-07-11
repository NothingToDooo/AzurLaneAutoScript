# ALAS 上游选择性移植实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在不恢复上游多平台、多服务器和旧设备依赖的前提下，吸收当前国服运行真正需要的船坞新版布局、科研九期和联合作战状态修复。

**Architecture:** 保持现有个人版边界，按当前 CN-only 配置生成链和已拆分的战斗辅助方法手工移植。每块更新只改变一个业务边界，先写能复现旧行为缺口的测试，再实现最小改动。

**Tech Stack:** Python 3.14.6、uv、Ruff、ty、pytest、Windows、MuMu。

## Global Constraints

- 当前个人版只支持 Windows + MuMu + 国区 + WebUI。
- 设备栈始终是 MuMu + nemu_ipc 截图 + minitouch 控制；ADB 是连接、shell、包名、forward、minitouch 等必要底座。
- Python 命令统一使用 `uv run`，不用裸 `python`。
- 不添加 `from __future__ import annotations`。
- 触碰到的注释和 docstring 尽量使用中文。
- 不恢复 `Config.when`、多语言资源、ResearchProjectJp、u2、FastInputIME 或多控制方式判断。
- 不直接 cherry-pick 上游提交；按当前个人架构手工移植。
- 新行为必须先看到对应测试按预期失败，再写实现。
- 提交信息使用英文 tag + 中文说明。

---

### Task 1: 船坞新版筛选布局

**Files:**
- Modify: `module/retire/dock.py`
- Modify: `module/tactical/tactical_class.py`
- Modify: `tests/test_retire_dock_options.py`
- Modify: `tests/test_tactical_class_receive.py`

**Interfaces:**
- Keeps: `Dock.dock_filter` 仍返回绑定当前模块的 `Setting`，调用方 API 不变。
- Produces: 固定国服新版布局：sort/index/faction/rarity/extra 的起始 y 坐标分别为 `36/109/239/427/499`。
- Produces: faction 使用 `7 x 3` 网格，加入 `pedreria`，其余空格仍用 `not_available` 占位。
- Produces: `DOCK_FILTER_CONFIRM_OFFSET = (20, 60)` 作为三处确认按钮识别范围的单一真相。
- Guarantees: 战术课堂构造可选阵营时排除 `all`、`meta` 和 `not_available`。

- [ ] **Step 1: 写新版布局、确认按钮 offset 和战术课堂空白项过滤测试**

```python
def test_dock_filter_uses_current_cn_layout() -> None:
    dock = object.__new__(Dock)
    setting = dock.dock_filter

    assert setting.settings[("sort", "rarity")].area[:2] == (218, 36)
    assert setting.settings[("index", "all")].area[:2] == (218, 109)
    assert setting.settings[("faction", "all")].area[:2] == (218, 239)
    assert ("faction", "pedreria") in setting.settings
    assert setting.settings[("rarity", "all")].area[:2] == (218, 427)
    assert setting.settings[("extra", "no_limit")].area[:2] == (218, 499)
```

- [ ] **Step 2: 运行定向测试并确认因旧坐标、缺少 `pedreria`、旧 offset 和空白阵营未过滤而失败**

Run: `uv run pytest tests/test_retire_dock_options.py tests/test_tactical_class_receive.py -q`

- [ ] **Step 3: 用固定 CN 布局替换旧布局，并统一确认按钮 offset**

- [ ] **Step 4: 排除战术课堂的 `not_available` 阵营项**

- [ ] **Step 5: 运行定向测试、Ruff 和 ty**

Run: `uv run pytest tests/test_retire_dock_options.py tests/test_tactical_class_receive.py -q`

- [ ] **Step 6: 提交**

Commit: `fix: 适配新版船坞筛选布局`

---

### Task 2: 科研九期运行数据

**Files:**
- Add from upstream: `assets/cn/research/TEMPLATE_S9.png`
- Modify: `module/research/assets.py`
- Modify: `module/research/series.py`
- Modify: `module/research/selector.py`
- Modify: `module/research/project.py`
- Modify: `module/research/project_data.py`
- Modify: `module/research/preset.py`
- Modify: `module/research/preset_generator.py`
- Modify: `dev_tools/research_extractor.py`
- Modify: `module/config/argument/argument.yaml`
- Regenerate: `module/config/argument/args.json`
- Regenerate: `module/config/config_generated.py`
- Regenerate: `module/config/i18n/zh-CN.json`
- Regenerate: `config/template.json`
- Test: `tests/test_research_s9.py`
- Modify: `tests/test_research_project.py`
- Modify: `tests/test_research_preset_generator.py`

**Interfaces:**
- Produces: `TEMPLATE_S9` 并把 `(TEMPLATE_S9, 9)` 放在科研系列模板表首位。
- Produces: selector 支持 `s9` 和 `valparaiso/maximmelmann/duncan/takahashi/orage`。
- Produces: 紧凑项目数据新增 65 个 S9 项目和 10 个 S8 E 类项目。
- Produces: S9 舰船映射，其中 `valparaiso`、`maximmelmann` 为 DR，其余三艘为 PRY。
- Produces: OCR 使用的 C/D 项目编号从 `LIST_RESEARCH_PROJECT` 派生，不再维护第二份手写编号表。
- Produces: `series_9_blueprint_ta152`、`series_9_blueprint_only`、`series_9_ta152_only` 及 cube 版本。
- Produces: 默认科研预设更新为 `series_9_blueprint_ta152`，自定义默认筛选更新为 S9。
- Guarantees: `dev_tools/research_extractor.py` 只在脚本入口执行写文件，导入常量和纯函数不会读取外部 Lua 或覆盖项目数据。
- Excludes: 全仓无运行时引用的 `assets/research_blueprint/*.png` 不移植。

- [ ] **Step 1: 写 S9 模板注册、selector、项目数据完整性、舰船稀有度和预设映射测试**

```python
def test_series_nine_project_data_is_complete() -> None:
    rows = [row for row in LIST_RESEARCH_PROJECT if row["series"] == 9]
    assert len(rows) == 65
    assert len({row["name"] for row in rows}) == 65


@pytest.mark.parametrize(
    ("name", "ship", "rarity"),
    [
        ("D-737-MI", "valparaiso", "dr"),
        ("D-781-MI", "maximmelmann", "dr"),
        ("D-732-MI", "duncan", "pry"),
        ("D-740-MI", "takahashi", "pry"),
        ("D-747-MI", "orage", "pry"),
    ],
)
def test_series_nine_ship_projects(name: str, ship: str, rarity: str) -> None:
    project = ResearchProject(name, 9)
    assert project.valid is True
    assert project.ship == ship
    assert project.ship_rarity == rarity
```

- [ ] **Step 2: 运行科研测试并确认因缺少 S9 模板、数据、筛选和预设而失败**

Run: `uv run pytest tests/test_research_s9.py tests/test_research_project.py tests/test_research_preset_generator.py tests/test_research_select.py -q`

- [ ] **Step 3: 添加唯一必需的 S9 模板并扩展系列识别、selector 和 OCR 编号表**

- [ ] **Step 4: 将上游 75 个项目机械投影为当前紧凑字段模型**

投影字段固定为：`name`、`series`、`time`、`need_coin`、`need_cube`、`need_part`、`ship`、`ship_rarity`、`equipment_amount`；没有值的可选字段不写入。

- [ ] **Step 5: 扩展 CN 数据抽取器和 S9 Ta152 预设生成映射**

- [ ] **Step 6: 修改 `argument.yaml` 后通过现有生成器刷新 CN-only 派生文件**

Run: `uv run python -m module.config.config_updater`

- [ ] **Step 7: 运行科研、配置生成、Ruff 和 ty 检查**

Run: `uv run pytest tests/test_research_s9.py tests/test_research_project.py tests/test_research_preset_generator.py tests/test_research_select.py tests/test_task_catalog_config.py tests/test_config_generator_i18n.py -q`

- [ ] **Step 8: 提交**

Commit: `feat: 支持科研九期`

---

### Task 3: 联合作战状态结束边界

**Files:**
- Modify: `module/combat/auto_search_combat.py`
- Modify: `module/coalition/combat.py`
- Create: `tests/test_coalition_combat.py`

**Interfaces:**
- Produces: `AutoSearchCombat.auto_search_combat_end() -> bool`，基类默认 `False`。
- Override: `CoalitionCombat.auto_search_combat_end()` 只识别联合作战专用 `BATTLE_STATUS`，offset 为 `(80, 20)`。
- Guarantees: `_handle_auto_search_combat_execute_end()` 在处理掉船之后调用窄 hook；普通自动搜索行为不变。
- Guarantees: `coalition_combat_re_enter()` 同时接受 combat loading 和 combat executing 作为下一场已开始信号。

- [ ] **Step 1: 写快速重进跳过 loading 和专用结算按钮测试**

```python
def test_coalition_re_enter_accepts_already_executing_state() -> None:
    combat = CoalitionCombatStub(loading=False, executing=True)
    combat.coalition_combat_re_enter()
    assert combat.device.screenshot_count == 0


def test_coalition_battle_status_ends_auto_search_execute() -> None:
    combat = CoalitionCombatStub(battle_status=True)
    assert combat._handle_auto_search_combat_execute_end() == (True, True)
    assert combat.appear_calls == [(BATTLE_STATUS, {"offset": (80, 20)})]
```

- [ ] **Step 2: 运行测试并确认前者多截一帧、后者返回 `(False, False)`**

Run: `uv run pytest tests/test_coalition_combat.py -q`

- [ ] **Step 3: 在当前已拆分的结束辅助方法中加入默认 hook 和 Coalition 覆盖**

- [ ] **Step 4: 在重进循环中增加 executing 结束条件，保持 loading 判断优先**

- [ ] **Step 5: 运行 Coalition、combat 和 campaign 定向测试**

Run: `uv run pytest tests/test_coalition_combat.py tests/test_campaign_run_flow.py tests/test_campaign_battle_policy_dispatch.py -q`

- [ ] **Step 6: 提交**

Commit: `fix: 修复联合作战快速续战状态`

---

### Task 4: 完整验证与审查

- [ ] **Step 1: 运行完整门禁**

```powershell
uv sync --check
uv run ruff check . --no-cache
uv run ruff format --check .
uv run ty check
uv run pytest
git diff --check
```

- [ ] **Step 2: 检查本分支只包含三块已批准的运行更新和计划文档**

- [ ] **Step 3: 独立审查整个分支，修复全部 Critical/Important 问题并复验**

## Completion Criteria

- 船坞筛选点击坐标对应当前国服新版 UI，确认按钮使用统一扩展范围。
- 战术课堂不会把新版布局的空白阵营格作为筛选条件。
- 科研九期 65 个项目、五艘舰船、系列识别、筛选预设和 CN 配置完整一致。
- 联合作战可处理直接进入 executing 的快速续战，并能在专用 `BATTLE_STATUS` 结束自动战斗循环。
- 没有恢复多平台、多服务器、多语言、u2 或旧全局配置分派。
- 全部门禁通过，独立审查无未解决 Critical/Important 问题。
