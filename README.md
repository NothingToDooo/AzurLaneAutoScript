# AzurLaneAutoScript Personal

这是一个只给自己使用的 AzurLaneAutoScript 分支。

当前分支的目标不是继续兼容上游的多人、多平台、多区服、多分发场景，而是把项目收敛成一个清楚、好维护、能直接运行的个人版本：

- 只保留国区。
- 只保留 Windows。
- 只保留 MuMu。
- 设备截图固定 `nemu_ipc`。
- 设备控制固定 `minitouch`。
- WebUI 只监听本机，作为主要入口。
- 保留 SMTP 邮件通知；旧配置键 `OnePushConfig` 仅用于兼容已有配置。
- `GemsFarming` 保留困难模式、装备码、潜艇和独立心情控制。
- Python 固定 3.14.6。
- 依赖和运行环境由 `uv` 管理。
- 项目直接运行，不做打包、安装器、自更新或通用分发。

## 运行

先同步依赖：

```powershell
uv sync
```

从旧版本迁移时，将原 `config/alas.json` 复制到当前仓库。配置加载会保留 SMTP 与
`GemsFarming` 增强字段，并把旧 `EmulatorInfo.path` 迁移到 MuMu 专用路径。

启动 WebUI：

```powershell
uv run python gui.py
```

直接运行调度器：

```powershell
uv run python alas.py
```

## 开发检查

常用检查命令：

```powershell
uv run ruff check .
uv run ty check
uv run pytest
```

## 配置生成

修改 `module/config/argument/*.yaml` 后，在仓库根目录运行：

```powershell
uv run python -m module.config.config_updater
```

这个分支会继续小步清理旧结构。清理优先级是：先删已经不可达的分发、语言、资源和设备后端，再把仍然有运行职责的代码迁到更合适的位置。
