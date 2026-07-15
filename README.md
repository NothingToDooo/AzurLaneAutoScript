# AzurLaneAutoScript Personal

这是只给自己使用的 AzurLaneAutoScript 分支：Windows、国服、一个 MuMu 12 模拟器、一个执行进程。

这个版本保留全部现有玩法和 WebUI，也保留 CLI 调试入口；不保留多实例、多平台、多区服、打包分发、自更新或旧配置兼容代码。截图固定使用 `nemu_ipc`，控制固定使用 `minitouch`。

## 运行

依赖与 Python 环境由 `uv` 管理：

```powershell
uv sync
```

启动 WebUI：

```powershell
uv run python gui.py
```

需要打开 WebUI 后立即启动调度器时，使用无参数开关 `uv run python gui.py --run`。

直接启动调度器：

```powershell
uv run python alas.py
```

首次运行会从 `config/template.json` 创建唯一的 `config/alas.json`。之后 WebUI、CLI、模拟器与 ADB 路径、调度状态和任务 checkpoint 都使用这一个文件。该分支只接受当前配置 schema；重复 JSON 字段、`NaN`/`Infinity`、未知字段、无效范围和失效的活动引用都会直接报错，不做旧配置迁移。

WebUI 保存和导入前会用当前内容定义离线构造全部 57 个任务进行校验，但不会连接或启动模拟器。跨字段修改如果暂时不完整，会保留在当前 WebUI 会话中，等后续字段组成合法候选后再一次写入。

CLI 也可以运行一个明确命令来复现问题，例如：

```powershell
uv run python alas.py benchmark
uv run python alas.py event_story
```

异常会在 `log/error/` 生成包含 traceback、最近 2000 行日志和最近游戏截图的 error bundle。SMTP 通知使用 `alas.json` 中的显式 `Smtp*` 字段，不使用 OnePush 配置。

## 游戏更新

活动、关卡和客户端行为的维护入口见 [架构说明](docs/architecture.md)。修改 manifest 或配置参数后运行：

```powershell
uv run python -m module.config.config_updater
uv run python -m dev_tools.campaign_runtime_profile_validator
```

## 开发检查

```powershell
uv run pytest
uv run ruff check . --no-cache
uv run ruff format --check .
uv run ty check
```
