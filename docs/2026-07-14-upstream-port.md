# 上游功能迁移记录（2026-07-14）

> 分支：`feat/upstream-2026-07-13-port`
> 范围：个人版 ALAS，Windows + MuMu 12 + 国区

## 1. 节点边界

本次迁移以个人分支当前主线为实施起点，以 2026-07-13 拉取到的上游节点为核对终点。
由于个人分支已经完成模块化 runtime 重构，本地起点不是上游目标节点的直接祖先；上游差异应从共同祖先开始核对，
不能把 `d6a99017..7c3531e7` 当作可直接合并的线性区间。

| 角色 | 提交节点 | 日期 | 说明 |
|---|---|---|---|
| 本地功能分支起点 | [`d6a99017f5f75c320da115b06d28893aa39f17cd`](https://github.com/NothingToDooo/AzurLaneAutoScript/commit/d6a99017f5f75c320da115b06d28893aa39f17cd) | 2026-07-14 | `origin/master`，模块化游戏 runtime 重构合并节点 |
| fork 与上游共同祖先 | [`3f9bb288fb79f63059a458b7093f491152ecf92a`](https://github.com/LmeSzinc/AzurLaneAutoScript/commit/3f9bb288fb79f63059a458b7093f491152ecf92a) | 2026-07-06 | `Upd: [CN] goc url` |
| 上游核对终点 | [`7c3531e7bc4eec8003582ea590ad0ff2cf255f24`](https://github.com/LmeSzinc/AzurLaneAutoScript/commit/7c3531e7bc4eec8003582ea590ad0ff2cf255f24) | 2026-07-13 | `Merge pull request #5816 from LmeSzinc/dev` |

“全部迁入”指共同祖先之后经核对、且当前个人版尚未具备的国区 / MuMu 功能改进，以及重构过程中确认遗失的
上游既有行为。它不表示合并上游全部历史，也不恢复已经从个人版删除的多服务器、多截图、多控制后端或
uiautomator2 兼容层。

## 2. 上游功能来源提交

下表中的链接均锁定完整 SHA。“直接移植”表示数据或窄逻辑与上游一致；“语义适配”表示保留上游修复目标，
但按当前分支架构重新实现。本次没有执行 `git cherry-pick`。

| 功能 | 上游提交 | 上游说明 | 本地处理 |
|---|---|---|---|
| hard 14-4 | [`04e99d57d`](https://github.com/LmeSzinc/AzurLaneAutoScript/commit/04e99d57d37f7a034a1b7fcdab39be38e0e11547) | `Add: campaign_14_4 hard (#5809)` | 语义适配：旧式 Campaign 类转换为 schema v4 YAML、manifest、typed definition、compiler 和测试 |
| main 14-4 `map_covered: A4` | [`fa8d29059`](https://github.com/LmeSzinc/AzurLaneAutoScript/commit/fa8d29059b2e0186948c61fc14d21daf307182e4) | `Opt: W14 mechanism` | 恢复重构时遗失的既有行为，并建立通用 `map_covered` 契约；该提交早于本次分叉 |
| S8/S9 彩装研究优先级 | [`f6255afd6`](https://github.com/LmeSzinc/AzurLaneAutoScript/commit/f6255afd62da5f907ddbb4a469fc7e9a321a3934) | `Upd: S8/S9 preset priority for E-880/E-180 rainbow gear projects (#5802)` | 直接移植 12 个 preset 的插入位置，并同步个人版默认 `CustomFilter` 生成产物 |
| 排除 `not_available` 设置项 | [`9323a3a03`](https://github.com/LmeSzinc/AzurLaneAutoScript/commit/9323a3a03c63b3174147fb6d58f015b3f29e5437) | `Fix: exclude 'not_available' entries from Setting.settings (#5813)` | 近似原样移植到当前 `Setting.add_setting()` |
| 私宅互动按钮识别范围 | [`f0d7241be`](https://github.com/LmeSzinc/AzurLaneAutoScript/commit/f0d7241be4a623c8f19f3b042d0bc27e50e0fc91) | `Fix: [EN][JP] private quarters interact button detection restrict to offset top_x and bottom_y (#5800)` | 轻度适配：四处调用统一使用共享常量 `(-10, 0, 0, 65)` |
| `OCR_DATA_KEY` | [`34d5282c0`](https://github.com/LmeSzinc/AzurLaneAutoScript/commit/34d5282c071eb26c970d15fdb632548b6462d347) | `Upd: asset OCR_DATA_KEY (#5815)` | 只同步 CN 图片及 area、color、button 元数据 |
| `FLEET_ENTER` 两项资源 | [`d6995678a`](https://github.com/LmeSzinc/AzurLaneAutoScript/commit/d6995678aabae3f216e81cb83d9cc1c76ee8b5d2) | `Upd: asset FLEET_ENTER and FLEET_ENTER_FLAGSHIP` | 恢复重构后缺失的 CN 图片和 color 元数据；该提交日期早于共同祖先 |
| FastInputIME 静默失败 | [`cf4800ba3`](https://github.com/LmeSzinc/AzurLaneAutoScript/commit/cf4800ba351d3f7c2f8959461b20ffca5ae5f879) | `Fix: u2's set_fastinput_ime may fail silently (#5806)` | 语义重实现：使用纯 ADB `shell2` 退出码检查，不恢复 uiautomator2 和系统设置 UI fallback |

## 3. 本次更新内容

### 3.1 hard 14-4 与声明式地图语义

- 在 [`campaign_hard.yaml`](../content/events/campaign_hard.yaml) 注册 `14-4`、alias 和 progression，并复用当前
  `profile_d7a2fbda6723ab71` runtime profile。
- 新增完整的 [`campaign_hard/stages/14-4.yaml`](../content/events/campaign_hard/stages/14-4.yaml)：
  camera、普通 / 周回地图、weight、spawn、道路清理、灯塔 / 弹药 / 照明弹拾取和 battle program 均按上游语义声明；
  周回模式在 battle 0 直接刷新 Boss。
- 为 [`MapDefinition`](../module/content/stage_definition.py)、
  [`StageSpecLoader`](../module/content/stage_loader.py) 和
  [`compile_campaign_map()`](../module/adapters/campaign_mumu12.py) 增加可选 `map_covered`，统一完成类型校验、
  范围校验和 legacy `CampaignMap` 投影，不为 14-4 增加特殊分支。
- 在 [`campaign_main/stages/14-4.yaml`](../content/events/campaign_main/stages/14-4.yaml) 同时恢复 `A4` manual covered，
  防止普通 14-4 在声明式迁移后丢失既有地图遮挡语义。
- hard 定义不继承只属于普通 14-4 非周回刷怪机制的 map mutations；hard attempt overlay 仍由现有 runtime 动态组合。

### 3.2 研究优先级和默认配置

- 在 [`module/research/preset.py`](../module/research/preset.py) 的 12 个 S8/S9 preset 中加入
  `S8-E-880 > S8-E-180`，插入位置与上游一致。
- 同步默认 `series_9_blueprint_ta152` 的 `CustomFilter`，避免 UI 新建配置仍使用旧优先级。
- 对应生成产物一并更新：
  [`argument.yaml`](../module/config/argument/argument.yaml)、
  [`args.json`](../module/config/argument/args.json)、
  [`config_generated.py`](../module/config/config_generated.py) 和
  [`config/template.json`](../config/template.json)。

### 3.3 设置与私宅识别

- [`Setting.add_setting()`](../module/ui/setting.py) 不再把占位值 `not_available` 注册为真实可选项，避免 Dock 等设置
  出现不可点击的 phantom option。
- [`PQInteract`](../module/private_quarters/interact.py) 的四处互动按钮检测统一使用
  `PRIVATE_QUARTERS_INTERACT_OFFSET = (-10, 0, 0, 65)`，限制左上角和底边扩展范围，减少邻近 UI 误识别。

### 3.4 国区资源更新

- 更新 [`OCR_DATA_KEY.png`](../assets/cn/freebies/OCR_DATA_KEY.png) 及
  [`module/freebies/assets.py`](../module/freebies/assets.py) 中的识别区域和颜色。
- 更新 [`FLEET_ENTER.png`](../assets/cn/equipment/FLEET_ENTER.png)、
  [`FLEET_ENTER_FLAGSHIP.png`](../assets/cn/equipment/FLEET_ENTER_FLAGSHIP.png) 及
  [`module/equipment/assets.py`](../module/equipment/assets.py) 中的颜色元数据。
- 三个工作区 PNG 的 Git blob 均与上游核对终点完全一致：

| 资源 | Git blob |
|---|---|
| `OCR_DATA_KEY.png` | `371df7fcc749fbfa9e98ec6c0efe08760f836f4d` |
| `FLEET_ENTER.png` | `ea390f9656e72eec799f990348ed0a84609f90cf` |
| `FLEET_ENTER_FLAGSHIP.png` | `b6925b5507ab709eea9dd4eaa7909e09375ec713` |

### 3.5 纯 ADB FastInputIME 失败检测

上游通过 uiautomator2 的 `d.shell()` 检查退出码，并在失败时尝试进入 Android 系统设置。本分支已经删除
uiautomator2 控制栈，直接复制该实现会重新引入第二套设备控制路径。

本次在 [`AdbSession`](../module/device/adb_session.py) 新增 `adb_shell_checked()`，使用 `adbutils.shell2()` 获取
Android shell 的真实退出码、stdout 和 stderr；[`EquipmentCodeHandler`](../module/equipment/equipment_code.py) 在执行
`ime enable` / `ime set` 时使用该入口。命令非零退出时记录原因并抛出 `ScriptError`，不再继续广播装备码，也不把失败
伪装成 FastInputIME 已成功启用。

## 4. 未迁入范围

- 不恢复 EN、JP、TW 的资源和服务器切换逻辑；当前个人版只支持国区。
- 不恢复 uiautomator2、Hierarchy 点击或 Android 设置页 fallback；当前设备控制边界是纯 ADB + MuMu 12。
- 不批量合并共同祖先后的全部上游提交；已经在个人分支实现、与当前平台无关或属于旧架构的提交不重复搬运。
- 不改变现有模块化 runtime、typed content、配置 schema 和任务调度边界。

## 5. 验证结果与开放项

已运行：

```powershell
uv sync --check
uv run ruff check . --no-cache
uv run ruff format --check .
uv run ty check
uv run pytest
git diff --check
```

结果：

- Ruff、格式检查、ty、依赖锁检查和 `git diff --check` 全部通过。
- 全量测试：`3005 passed, 1 skipped`。
- hard 14-4 的 manifest 解析、normal / loop 编译、alias、runtime profile 和 `map_covered` 有独立回归测试。
- 研究优先级、`not_available`、私宅 offset、资源元数据和 FastInputIME 非零退出均有定向测试。

## 6. 2026-07-17 增量同步

本次从上一轮上游核对终点继续检查到 `a97e76cab94598d5ef270372d6457b7faac073ad`，仍按国区、MuMu 12
和当前模块化架构做选择性移植，没有合并上游历史。

| 功能 | 上游提交 | 本地处理 |
|---|---|---|
| Gems farming 船坞升序 | [`d09a98873`](https://github.com/LmeSzinc/AzurLaneAutoScript/commit/d09a98873846dbc97cfc2c82f1d783dc0722220c) | 当前 `get_common_rarity_cv()` 已使用升序，无需重复修改 |
| 国区纳希莫夫私宅支持 | [`d70c983ff`](https://github.com/LmeSzinc/AzurLaneAutoScript/commit/d70c983ff7aedde4f3a6a6569768425d93eb92c6) | 移除 CN-only runtime 中的 Nakhimov 禁用项，直接同步 Villa / Nakhimov 元数据和两张 CN PNG |
| Filter 连字符规范化 | [`0f85c251a`](https://github.com/LmeSzinc/AzurLaneAutoScript/commit/0f85c251a4e5c67056fa1281283ecb110bef5a58) | 在当前泛型 `Filter.load()` 中规范化 11 种 Unicode 类连字符，并增加参数化回归测试 |
| 上游合并节点 | [`a97e76cab`](https://github.com/LmeSzinc/AzurLaneAutoScript/commit/a97e76cab94598d5ef270372d6457b7faac073ad) | 只作为新的上游核对终点，无独立功能改动 |

两张同步资源的 Git blob：

| 资源 | Git blob |
|---|---|
| `PRIVATE_QUARTERS_PAGE_LOCALE_VILLA.png` | `4f738c80d32118eca70d5136b2b592d0f89749b9` |
| `PRIVATE_QUARTERS_SHIP_NAKHIMOV.png` | `71487f9a28c38b03b07069a0df4444872b52c5ef` |

验证结果：

- 新增及相关定向测试：`24 passed`。
- 全量测试：`2837 passed`。
- 本次修改的 Python 文件通过 Ruff 和格式检查；全仓格式检查通过（683 files）。
- `uv lock --check`、campaign runtime profile validator、`alas.py --help` 和 `gui.py --help` 通过。
- 全仓 Ruff 仍有 152 个既有规则迁移问题（127 个 `RUF105`、25 个 `RUF201`）；全仓 `ty` 仍有
  `module/device/device.py:66` 和 `module/os_handler/os_status.py:40` 两个既有诊断。本次同步路径没有新增对应错误。

## 7. 2026-07-18 增量同步与资源生成器修复

本次从上一轮终点 `a97e76cab94598d5ef270372d6457b7faac073ad` 继续核对到
`c535587c85b69e2c7834d22d2467318dade10a79`。仍只迁入国区、Windows + MuMu 12 单实例运行需要的行为，
不恢复已经删除的平台和设备后端。

| 功能 | 上游提交 | 本地处理 |
|---|---|---|
| Nier 战斗界面 | [`b053630e4`](https://github.com/LmeSzinc/AzurLaneAutoScript/commit/b053630e48b310b9b17bee2d52e75fdcade61523) | 语义适配：同步两张 CN 资源，将暂停、退出和演习新版血条布局接入当前表驱动识别链，并用真实资源执行 matcher 与点击回归测试 |
| MuMu Pro macOS serial | [`372d94c82`](https://github.com/LmeSzinc/AzurLaneAutoScript/commit/372d94c821488e0f8c946f433930b0cd90b51dca)、[`513fbb3cc`](https://github.com/LmeSzinc/AzurLaneAutoScript/commit/513fbb3cc23a456c1f23b839f554da96defacf74) | 不迁入：只处理 macOS MuMu Pro 的 `emulator-*` serial；当前运行边界是 Windows MuMu 12，不存在多实例或 macOS 探测需求 |
| 新条茜舰队卡片识别 | [`6df8bbb88`](https://github.com/LmeSzinc/AzurLaneAutoScript/commit/6df8bbb88bf394f3f679c7a03e2304f8563165ea) | 语义适配：在低方差空舰队 fallback 前识别该皮肤的蓝色底部区域，同时保留英仙座、高方差和真实空舰队回归样本 |
| 上游合并节点 | [`c535587c8`](https://github.com/LmeSzinc/AzurLaneAutoScript/commit/c535587c85b69e2c7834d22d2467318dade10a79) | 只作为新的 `upstream/master` 核对终点，无独立功能改动 |

`upstream/dev` 另有两个尚未进入上述 master 终点的提交，也已核对：

- [`c0770475e`](https://github.com/LmeSzinc/AzurLaneAutoScript/commit/c0770475ef5b685fbef3e212067c58ec116cfd40)
  只修改 vanguard 卸载日志；当前 `_hard_unmount(..., ship_name=...)` 已通过通用参数实现等价信息，不重复迁入。
- [`c2b242650`](https://github.com/LmeSzinc/AzurLaneAutoScript/commit/c2b2426504a9ac3fb2fd83fb23d056db42635fed)
  为高 Android 版本的 DroidCast 增加自动 fallback；当前设备边界不包含 DroidCast，不迁入。

两张同步资源与上游 blob 完全一致：

| 资源 | Git blob |
|---|---|
| `PAUSE_Nier.png` | `1c238b2bd2d9eb0cc132358a1408c6f07108db19` |
| `QUIT_Nier.png` | `525b83a4865acba7c5c3b9d54fa5535e2a634c71` |

### 7.1 国区资源生成契约

同步 Nier 资源时发现 [`dev_tools/button_extract.py`](../dev_tools/button_extract.py) 仍会输出
`{"cn": ...}`：运行时和全部生成文件早已裁剪为国区标量，`Resource.parse_property()` 也只原样返回输入；因此旧输出会在
`Button` 构造时把字典路径用作资源表 key，并直接抛出 `TypeError`。这不是需要保留的兼容行为。

本次将生成器内部的 area、color、button 和 file 一并改为标量，并稳定输出 `./assets/...` 相对路径；生成文件引用校验
拒绝非字符串 `file`，端到端测试会实际生成并加载 `Button` / `Template`。同时删除两处仍宣称支持 server mapping 的
失真 docstring。全量重建 40 个资源模块后，仅将 `module/equipment/assets.py` 中原本未按字母排序的
`EQUIPMENT_CLOSE` 移回规范位置，资源数值没有变化。

### 7.2 验证结果

- Nier、舰队卡片和资源生成器定向测试：`26 passed`。
- 全量测试：`2896 passed`。
- 全仓 Ruff 通过；格式检查通过（690 files）。
- `uv lock --check`、完整 40 模块资源生成与引用校验、campaign runtime profile validator 和
  `git diff --check` 通过。
- 本次修改文件的 ty 检查通过。全仓 ty 仍有 17 条既有诊断，均位于
  `module/device/minitouch_service.py`、`module/device/nemu_ipc_service.py`、
  `tests/test_device_minitouch_retry.py` 和 `tests/test_device_nemu_ipc_retry.py`；本次没有修改这些文件。
