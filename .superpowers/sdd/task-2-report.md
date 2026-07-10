# Task 2 实施报告：内容与截图回放契约

## 结果

已建立独立的内容模型与截图回放基础契约，未接入 `CampaignRun`、WebUI、ADB、`nemu_ipc` 或 `minitouch`，也未引入 Pydantic、运行时包发现、插件框架或通用 DSL。

实现范围严格限于 Task 2 指定文件和本报告：

- `module/content/__init__.py`
- `module/content/errors.py`
- `module/content/models.py`
- `module/content/validation.py`
- `module/replay/__init__.py`
- `module/replay/trace.py`
- `module/replay/device.py`
- `tests/test_content_models.py`
- `tests/test_replay_device.py`
- `.superpowers/sdd/task-2-report.md`

## RED 证据

先只创建两份测试，没有创建生产模块，然后运行：

```text
uv run pytest tests/test_content_models.py tests/test_replay_device.py -q
```

结果为退出码 1，测试在收集阶段按预期失败：

```text
ERROR tests/test_content_models.py
ModuleNotFoundError: No module named 'module.content'

ERROR tests/test_replay_device.py
ModuleNotFoundError: No module named 'module.replay'

2 errors during collection
```

失败原因正是 Task 2 契约尚不存在，而不是测试拼写、fixture 或环境错误。

## GREEN 证据

内容模型最小实现完成后的中间检查：

```text
uv run pytest tests/test_content_models.py -q
10 passed in 0.07s
```

trace 与 `ReplayDevice` 最小实现完成后的定向检查：

```text
uv run pytest tests/test_content_models.py tests/test_replay_device.py -q
19 passed in 0.38s
```

## 契约说明

### 内容模型

- `ContentId`、`EventPack`、`StageRef`、`StageSpec`、`AssetRef`、`ValidationIssue` 均为 frozen/slotted dataclass。
- `ContentId.value`、`StageRef.pack_id`、`StageRef.stage_id` 在构造时拒绝空值和纯空白值。
- `EventPack.stages` 固定暴露为 tuple，并保留显式声明顺序，不扫描包或目录。
- `StageSpec` 仅携带 `StageRef`、显式 source 和 asset tuple；`AssetRef` 仅携带内容 ID 与路径。
- `ContentValidationError` 继承 `ValueError`，既提供明确内容边界，也符合计划中的 `pytest.raises(ValueError)` 契约。

### JSON trace

- 顶层写入固定 `version: 1` 与有序 frame 数组。
- click 仅记录语义 target；swipe 仅记录整数 start/end；不记录随机点击坐标、时长或设备后端信息。
- 写入使用稳定缩进、排序键、UTF-8 和 LF 结尾；相同输入重复写入得到完全相同的字节。
- 图片与 trace 位于可计算相对路径的位置时写入 POSIX 风格相对路径；读取时相对 trace 文件解析回实际 `Path`。
- round-trip 测试只在 pytest `tmp_path` 内生成 1280×720 RGB 图片，没有复制或提交游戏截图。

### ReplayDevice 状态机

- `screenshot()` 先确认上一帧动作已经消费，再激活下一帧、加载图片并设置 `.image`。
- `click(button)` 以 `str(button)` 和下一条 `ClickAction.target` 比较。
- `swipe(start, end)` 按现有控制语义用 `int()` 规范化端点，再与下一条 `SwipeAction` 比较。
- 动作类型、顺序或值不一致时不消费期望动作。
- 不完整上一帧、帧耗尽、动作不匹配、最终回放不完整分别使用清晰的专用异常。
- `assert_complete()` 同时检查当前帧未消费动作和仍未激活的后续帧。

## 最终验证

全量测试：

```text
uv run pytest -q
907 passed, 1 skipped in 5.68s
```

全仓质量门禁：

```text
uv run ruff check . --no-cache
All checks passed!

uv run ruff format --check .
1763 files already formatted

uv run ty check
All checks passed!
```

运行时隔离扫描：

```text
import module.content, module.replay
forbidden_loaded= []
```

其中 forbidden 集合为 `module.webui`、`module.device`、`module.campaign`。静态文本扫描也未发现 ADB、`nemu_ipc`、`minitouch`、Pydantic、动态 entry point 或包发现依赖。

提交主题：`feat: 建立内容与截图回放契约`
