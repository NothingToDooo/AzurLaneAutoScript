# 原项目 AzurLaneAutoScript 架构

本文记录原项目 `LmeSzinc/AzurLaneAutoScript` 的结构、运行时数据流、功能注册和内容组成，作为后续对照、迁移与重构的事实基线。

## 范围与核对基线

- 本地源码：`E:\alas\AzurLaneAutoScript`
- Git 分支：`master`
- 基线提交：`c535587c85b69e2c7834d22d2467318dade10a79`
- 提交日期：2026-07-18
- 核对方式：读取当前源码、配置定义和 Git 跟踪文件；没有启动 WebUI、worker、模拟器、OCR 或更新流程
- 下文源码路径均相对于 `E:\alas\AzurLaneAutoScript`

因此，本文确认的是该提交下的静态结构与代码路径。运行性能、设备兼容性、识别成功率和真实任务结果不在本次验证范围内。

## 总体定位

原项目是一个以 Python 为主体的碧蓝航线自动化平台。它把以下部分组合在同一个仓库中：

- `gui.py` WebUI 与 `alas.py` 脚本直跑两种入口
- 每个配置实例一个独立 worker 进程的调度模型
- 模拟器连接、截图、OCR、模板匹配和输入控制
- 通用 Campaign 执行引擎与大量可执行地图脚本
- 按服务器拆分的图片模板，以及通用、日文和繁中 OCR 模型
- Electron/Vue 桌面壳、部署脚本及两个外部自动化桥接模块

核心闭环不是“调用一个游戏 API”，而是反复执行“截图 → 识别 → 决策 → 点击或滑动 → 再截图”。

```text
可选 Electron 桌面壳
        │ 启动 Python WebUI，并用 iframe 显示
        ▼
gui.py ───────────────► module.webui.app
                              │
                              │ ProcessManager：每个配置一个子进程
                              ▼
                         alas.py worker
                              │
直接运行：python alas.py ────┘
          默认实例 alas
                              │
                 config/<name>.json
                              │
                              ▼
                     Scheduler 选择任务
                              │
                              ▼
                  业务模块 / Campaign 引擎
                              │
               ┌──────────────┴──────────────┐
               ▼                             ▼
       截图、OCR、模板和地图识别       点击、滑动、应用控制
               │                             │
               └──────────── 模拟器 ─────────┘
                              │
                              ▼
                 NextRun、配置、日志和截图
```

## 进程与入口

### 脚本直跑入口

直接执行 `python alas.py` 会创建默认 `config_name="alas"` 的 `AzurLaneAutoScript` 并进入 `loop()`。`alas.py` 没有 argparse 命令路由，额外 argv 不负责选择配置或任务；这种模式也没有 WebUI 进程管理层，当前进程就是默认实例的任务 worker。

### WebUI 入口

`gui.py` 解析 host、port、key、CDN、Electron、SSL 和 run 参数，然后由 Uvicorn 加载 `module.webui.app:app`。它同时承担 WebUI supervisor 的职责，可通过事件触发服务重载。

`module/webui/process_manager.py` 为每个配置实例维护一个独立子进程。子进程在功能名为 `alas` 时创建 `AzurLaneAutoScript(config)` 并进入调度循环。不同配置因此拥有各自的 Python 进程、配置对象、设备对象和模块级全局状态。

WebUI 与 worker 之间不是完整的业务 RPC：

- worker 通过 `multiprocessing.Manager().Queue()` 把 Rich 日志送回 WebUI
- WebUI 通过 `ProcessManager` 启动、停止和检查 worker
- updater 使用进程事件协调 worker 停止
- `gui.py` supervisor 使用 reload event 重启 WebUI；updater 另用临时文件 `config/reloadalas` 记录重启后要恢复的实例
- worker 是否“运行中”主要由进程存活和末尾日志文本推断，不是结构化状态协议

### Electron/Vue 桌面壳

`webapp/` 不承载自动化逻辑。Electron 主进程启动 `gui.py`、等待后端可用，渲染层再用 iframe 加载本机 WebUI。Electron 从 `config/deploy.yaml` 读取 `WebuiPort`，但 iframe host 固定为 `127.0.0.1`；`WebuiHost` 只控制 Uvicorn 的监听地址。

默认启用 reload 时，典型桌面进程树为：

```text
Electron
└─ gui.py supervisor
   └─ WebUI server process
      ├─ <配置 A> alas.py worker
      ├─ <配置 B> alas.py worker
      └─ ...
```

关闭 reload 时，`gui.py` supervisor 与 WebUI server 合并在同一个进程。Electron 是可选外壳；Python WebUI 和 `alas.py` 直跑模式均可独立工作。

## 主数据流

### 调度数据流

```text
task.yaml / argument.yaml / default.yaml / override.yaml
                         │ 生成
                         ▼
       menu.json / args.json / config_generated.py / template.json
                         │ 实例化和覆盖
                         ▼
                  config/<name>.json
                         │ AzurLaneConfig 读取并绑定为属性
                         ▼
          Enable + Command + NextRun 等实例调度字段
          + ConfigManual.SCHEDULER_PRIORITY 代码优先级
                         │
                         ▼
               AzurLaneAutoScript.loop()
                         │
                         ▼
          run(Command) → 同名任务适配方法 → 业务模块
                         │
                         ▼
     task_delay() / task_call() 更新调度，task_stop() 结束本次调用

gui.yaml + 既有 i18n/<lang>.json ──► 重新生成 i18n/<lang>.json
```

`module/config/argument/task.yaml` 是页面和任务注册的主要权威来源。`module/config/config_updater.py` 把它与参数定义、默认值和覆盖项合成为运行所需的配置文件；`gui.yaml` 则单独参与多语言 UI 文本的再生成。

`AzurLaneConfig` 读取 `config/<name>.json`，把嵌套参数绑定成业务模块可直接访问的属性。实例 JSON 持久化 `Enable`、`Command` 和 `NextRun`；任务优先级来自 `ConfigManual.SCHEDULER_PRIORITY` 代码常量。调度器从已启用任务中选择已经到期的任务并应用该优先级规则；没有任务到期时，等待最早的 `NextRun`。

`Scheduler.NextRun` 的下一次取值由任务生命周期方法写回，而不是由一个统一 cron 表计算：

- `task_delay()` 写入当前任务的后续运行时间
- `task_call()` 启用或唤起另一个任务
- `task_stop()` 抛出 `TaskEnd` 结束当前调用；它本身不改写 `NextRun`，也不禁用任务

配置保存通过临时文件和替换完成原子写入。调度等待期间还会监听配置变化，并按设置选择关闭游戏、返回主界面或停留当前页面。

### 单次自动化循环

```text
Device.screenshot()
        │
        ▼
device.image：当前 1280 × 720 图像
        │
        ├─ Button / Template：固定区域颜色与模板匹配
        ├─ OCR：裁剪、预处理、模型推理、结果后处理
        └─ Map Detection：透视校正、网格识别、地图状态更新
        │
        ▼
业务模块根据识别结果选择动作
        │
        ▼
Control.click() / swipe() / app_start() / app_stop()
        │
        ▼
模拟器画面变化，进入下一轮截图
```

`Device` 组合了 `Screenshot`、`Control` 和 `AppControl`。截图结果保存在共享的 `device.image` 上，业务模块通常继承 `ModuleBase`，通过 `appear()`、`appear_then_click()`、OCR 和地图对象读取这张图并推进状态循环。

截图后端包括 ADB、uiautomator2、aScreenCap、DroidCast、scrcpy、MuMu Nemu IPC 和 LDOpenGL 等实现；输入后端包括 ADB、uiautomator2、minitouch、Hermit、MaaTouch 和 Nemu IPC。自动 benchmark 可选择较合适的方法并写回配置。

原项目 OCR 使用仓库内的 CnOcr 1.2.2、MXNet 1.6.0 和 `bin/cnocr_models/` 模型，不是 ONNX OCR 管线。模型缺失时会要求人工处理，不会在该路径自动下载模型。

## 配置与状态所有权

| 数据 | 权威来源或所有者 | 作用 |
| --- | --- | --- |
| 页面、任务与参数定义 | `module/config/argument/*.yaml` | 定义菜单、任务、字段、默认值和覆盖规则 |
| 生成配置描述 | `module/config/argument/menu.json`、`args.json`、`config_generated.py` | 供 WebUI 和运行时消费 |
| 部署设置 | `config/deploy.yaml` | WebUI、Git、Python、ADB、更新等部署参数 |
| 实例设置与调度状态 | `config/<name>.json` | 用户设置、任务开关、`Command`、`NextRun` 和部分业务记录 |
| 当前画面 | 每个 worker 的 `device.image` | 识别和动作判断的共享图像状态 |
| 进程状态 | WebUI `ProcessManager` 内存 | worker 生命周期及日志队列 |
| 地图内容 | `campaign/**.py` | 地图布局、刷图配置和战斗策略 |
| 运行产物 | `log/`、`screenshots/` | 文本日志、异常截图和可选分类截图 |

核心运行时没有 SQLite、服务端数据库或事件存储。`config/<name>.json` 同时承载用户配置和相当一部分调度状态，是最重要的持久化事实源。

原项目也没有独立的强类型 schema 与语义验证层。`ConfigUpdater` 根据已知字段重建配置，处理默认值、基本解析和 option redirect；未知字段会在重建过程中被丢弃。WebUI 侧的输入检查主要是正则和日期时间格式检查。

## 任务注册与功能边界

当前基线的 `task.yaml` 共定义 8 个菜单、61 个页面。按页面的实际角色划分如下：

| 菜单 | 页面数 | Scheduler 任务 | 纯设置页 | 手动工具 |
| --- | ---: | ---: | ---: | ---: |
| Alas | 3 | 1 | 2 | 0 |
| Farm | 4 | 4 | 0 | 0 |
| Event | 8 | 7 | 1 | 0 |
| EventDaily | 7 | 7 | 0 | 0 |
| Reward | 8 | 8 | 0 | 0 |
| DailyMission | 10 | 10 | 0 | 0 |
| Opsi | 15 | 14 | 1 | 0 |
| Tool | 6 | 0 | 0 | 6 |
| 合计 | 61 | 51 | 4 | 6 |

这里的 51 个 Scheduler 页面包含 `Restart`。它是原项目注册口径，不等同于个人版 `TASK_CATALOG` 的任务数量，不能直接用两个数字判断功能增减。

主要业务范围为：

- Farm：主线多配置刷图和 Gems Farming
- Event：活动图、Raid、Hospital、Coalition、Maritime Escort、War Archives
- EventDaily：活动 A/B/C/D/SP、Raid Daily、Coalition SP 等每日入口
- Reward：Commission、Tactical、Research、Dorm、Meowfficer、Guild、Reward、Awaken
- DailyMission：Daily、Hard、Exercise、商店、Shipyard、Gacha、Freebies、Minigame、Private Quarters
- Opsi：Ash Beacon/Assist、Explore、Shop、Voucher、Daily、Obscure、Abyssal、Archive、Stronghold、Month Boss、Meowfficer Farming、Hazard 1 Leveling、Cross Month
- Tool：Daemon、OpsiDaemon、EventStory、Benchmark、AzurLaneUncensored、GameManager

### “代码存在”不等于“当前可用功能”

配置参数中有 83 个 argument group，但 `task.yaml` 当前只引用 77 个。以下 6 组没有接入当前页面：

- `C11AffinityFarming`
- `C72MysteryFarming`
- `C122MediumLeveling`
- `C124LargeLeveling`
- `Minigame`
- `Sos`

例如 `alas.py` 仍保留 SOS 和部分旧主线任务适配方法，但当前 `task.yaml` 没有相应任务页；`Minigame` 页面只挂载 Scheduler，没有挂载 `Minigame.Collect` 参数组。判断产品功能时应以“页面注册 + Command 路由 + 业务实现”三者同时成立为准，不能只按类名或方法名计数。

## Campaign 内容与执行引擎

Campaign 采用“通用引擎 + 可执行地图脚本”的结构。

`module/campaign/run.py` 根据配置动态导入 `campaign.<folder>.<name>`，合并地图脚本中的 `Config`，再创建该文件的 `Campaign` 实例。`module/campaign/campaign_base.py` 负责进入地图、初始化地图状态并推进战斗轮次。

单个地图文件通常同时包含：

- `CampaignMap`：地图尺寸、网格布局、出生点、敌人和机制等静态内容
- `Config`：该地图的识别与执行参数
- `Campaign`：`battle_0`、`battle_1` 等阶段策略，以及通用清图方法的覆写

运行时的主要链路为：

```text
配置给出 campaign folder/name
              │
              ▼
动态导入地图脚本，复制并合并地图 Config
              │
              ▼
进入地图并全图扫描
              │
              ▼
Camera → View → 透视/网格检测 → CampaignMap 逻辑状态
              │
              ▼
battle_n / clear_enemy / clear_chosen_enemy
              │
              ▼
舰队寻路 goto → Device 点击 → 再次截图和识别
```

在本基线中，`campaign/` 的静态规模为：

- 132 个目录
- 1,411 个文件，其中 1,410 个 Python 文件
- 1,343 个实际 `CampaignMap` 声明
- 主线 64 张、特殊 Hard 2 张、SOS 8 张、活动 814 张、War Archives 455 张

`campaign/Readme.md` 还是活动元数据输入之一，配置生成会读取它。活动目录上的 `_cn`、`_en`、`_tw` 后缀表示地图脚本或布局的来源及复用基准，不代表整套功能只能在该服务器运行；视觉素材仍在 `assets/<server>/`，相同地图布局会在不同服务器之间复用。

## 目录职责

| 路径 | 主要职责 |
| --- | --- |
| `alas.py` | 顶层调度循环、Command 动态分发、业务任务适配和异常边界 |
| `gui.py` | WebUI 启动参数、Uvicorn supervisor 和重载 |
| `module/config/` | 配置定义生成、实例绑定、调度状态、配置保存与迁移 |
| `module/webui/` | 控制面、配置编辑、worker 管理、日志展示和 updater UI |
| `module/device/` | 模拟器发现与连接、截图、输入、应用生命周期控制 |
| `module/base/` | `Button`、`Template`、资源加载和通用识别循环 |
| `module/ocr/` | OCR 预处理、模型调用和业务结果后处理 |
| `module/ui/` | 游戏页面关系和页面导航 |
| `module/campaign/` | 通用关卡加载与执行框架 |
| `module/map/` | 逻辑地图、路径选择、舰队移动和战斗决策 |
| `module/map_detection/` | 从截图恢复透视网格和格子状态 |
| `module/<feature>/` | Commission、Research、Opsi 等具体业务工作流 |
| `campaign/` | 可执行地图内容、每图配置和 battle 策略 |
| `assets/` | 按服务器和功能拆分的按钮、模板及识别图片 |
| `bin/` | OCR 模型和设备辅助二进制 |
| `config/` | 部署模板、实例模板和本地运行配置目录 |
| `webapp/` | Electron/Vue 桌面包装，不包含自动化核心 |
| `submodule/` | MAA 与 FGO-py 的 vendored bridge；目录名如此，但不是 Git submodule |
| `deploy/` | Windows installer，以及 Docker、headless Linux、AidLux 的 requirements 或部署 profile；后几者不是同等完整的安装器 |
| `dev_tools/` | 配置生成、素材提取、benchmark 等开发工具 |
| `doc/` | 原项目历史文档入口，主要内容指向项目 Wiki |

## 内容规模与服务器适配

按该提交的 Git 跟踪文件统计：

- 全仓库 8,763 个文件
- 5,821 个 PNG、1,811 个 Python 文件、955 个 GIF
- `assets/` 有 6,785 个文件，约 68.41 MiB
- `module/` 有 52 个一级目录、334 个 Python 文件
- `bin/` 有 32 个 OCR 模型或设备辅助文件

按服务器划分的主要 assets 数量为：

- CN：1,714
- EN：1,524
- JP：1,497
- TW：1,405

剩余 assets 主要是商店、科研蓝图、基础属性、mask、GUI 和地图检测等共享素材。由此可见，原项目不仅是业务代码仓库，也是一个较大的版本化视觉素材库。

`module/config/server.py` 定义 CN、EN、JP、TW 四类服务器；CN 还包含多个渠道包名。不同服务器主要通过包名、页面差异、OCR 文本和图片资产分流。

设备层包含多种 Windows 模拟器的发现和专用连接路径。非 Windows 环境可以连接已有 ADB 设备，但本次没有实测各平台部署配置。

## 持久化与运行产物

正常运行可能产生以下本地状态：

- `config/<name>.json`：实例配置、Scheduler 状态和部分业务记录
- `config/deploy.yaml`：部署与更新设置；干净源码中只有模板，需要本地生成
- `log/YYYY-MM-DD_<name>.txt`：按日期和配置实例记录的 worker 日志
- `log/error/<epoch-ms>/`：异常上下文、截图和清理后的 `log.txt`
- `screenshots/<genre>/<epoch>.png`：开启分类截图保存后产生

WebUI 只在内存中保留有限数量的近期日志；worker 日志队列不是持久化消息系统。原项目异常目录也没有个人版使用的结构化 `error.json`。

截图历史长度可配置，异常时会落盘相关画面。配置中仍保留 AzurStats 上传选项，但当前上传线程已被注释，实际路径只做本地保存，不能视为现行上传能力。上述目录在本次干净 checkout 中没有真实运行样本，因此这里只确认代码约定，没有验证实际产物内容。

## 更新与外部扩展边界

原项目有三条需要区分的更新路径：

- WebUI updater 停止 worker 后执行 Git 和 pip 更新。仅在 `EnableReload=true` 时，它才通过 `config/reloadalas` 与 reload event 重启 WebUI 并恢复实例；关闭 reload 时更新结束后不会自动恢复此前 worker。Git 更新路径会执行 `git reset --hard origin/<branch>`，直接丢弃 tracked 本地修改。
- Windows launcher 会先运行 installer，依次更新 Git、Python 依赖和 `app.asar`，然后才启动 Electron。
- Electron 另有自己的 `electron-updater.checkForUpdatesAndNotify()`；它与 WebUI 的 Git/pip updater 不是同一条路径。

这些流程会修改工作树、依赖或桌面壳并重启服务，属于部署控制面，不是普通业务任务。`deploy/installer.py` 通过 ADB/emulator 路径依赖 Windows `winreg`；Linux 和 AidLux 只有 requirements/deploy profile，没有等价的 systemd、supervisor 或平台安装脚本。

`submodule/` 提供两个扩展桥接：

- `maa` → `AlasMaaBridge`，接入 MAA/明日方舟任务
- `fpy` → `AlasFpyBridge`，接入 FGO-py

仓库没有 `.gitmodules`，这两部分是直接 vendored 的源码桥接，不应按 Git submodule 管理。对应实例模板为 `config/template.maa.json` 和 `config/template.fpy.json`。

## 关键结构特征

后续阅读或迁移原项目时，需要特别保留以下事实：

1. `alas.py` 同时承担 scheduler、Command dispatcher、任务 adapter 和顶层错误边界，是一个集中式编排 façade。
2. 任务入口由字符串 `Command` 动态调用同名方法，功能注册事实分散在 `task.yaml`、生成配置和 Python 方法之间。
3. 每个配置一个完整 worker 进程，隔离简单，但设备、配置和业务对象都在进程内重复创建。
4. `config/<name>.json` 既是用户配置也是调度状态，配置修改和任务推进共享同一个持久化文件。
5. 地图不是纯数据文件；每张地图可携带 Python 策略代码，因此 Campaign 内容与执行逻辑耦合。
6. 识别层以固定 1280 × 720 画面、模板资源和服务器差异为基础，素材是运行正确性的一部分。
7. WebUI 展示的进程状态与业务状态较弱耦合，不能仅凭 WebUI 存活判断 worker 正常完成任务。

这些特征既解释了原项目为什么能快速覆盖大量活动和设备，也标出了配置验证、任务所有权、结构化状态与可测试性方面的后续重构边界。

## 核对入口

需要重新验证本文时，优先从以下文件和符号进入：

| 主题 | 入口 |
| --- | --- |
| 顶层任务循环 | `alas.py`：`AzurLaneAutoScript.run()`、`loop()` |
| WebUI 启动 | `gui.py`、`module/webui/app.py` |
| worker 生命周期 | `module/webui/process_manager.py`：`ProcessManager` |
| 任务注册 | `module/config/argument/task.yaml` |
| 参数生成 | `module/config/config_updater.py` |
| 配置与 Scheduler | `module/config/config.py`：`AzurLaneConfig` |
| 截图和输入 | `module/device/device.py`、`screenshot.py`、`control.py` |
| 通用识别 | `module/base/base.py`、`button.py`、`module/ocr/ocr.py` |
| 地图识别 | `module/map/camera.py`、`module/map_detection/view.py` |
| Campaign 加载与循环 | `module/campaign/run.py`、`campaign_base.py` |
| 单图脚本示例 | `campaign/campaign_main/campaign_1_1.py` |
| Electron 包装 | `webapp/packages/main/src/index.ts`、`webapp/packages/renderer/src/components/Alas.vue` |

## 与个人版文档的关系

本文只描述嵌套目录中的原项目基线，不描述当前个人版的最终架构。

- 当前个人版结构见 [architecture.md](architecture.md)
- 已完成的选择性迁移及提交记录见 [2026-07-14-upstream-port.md](2026-07-14-upstream-port.md)

比较两者时，应按真实调用、状态所有权和行为测试判断是否迁移，而不是按同名文件、类名或任务数量机械对齐。
