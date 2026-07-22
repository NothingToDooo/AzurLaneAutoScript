import copy
from datetime import datetime
from typing import TYPE_CHECKING, cast

import pywebio

from module.bootstrap.configuration_compiler import CurrentConfigurationSchema
from module.config.config_generated import ConfigOverrides, GeneratedConfig
from module.config.config_manual import ManualConfig, OutputConfig
from module.config.configuration_file import read_config_file, write_config_file
from module.config.deep import deep_get, deep_set
from module.config.resolved import ResolvedTaskConfig, resolve_task_config
from module.config.utils import (
    DEFAULT_TIME,
    dict_to_kv,
    filepath_config,
)
from module.logger import logger
from module.task_registry import get_task_by_config_name

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable
    from types import TracebackType
    from typing import Self, Unpack

    from module.config.config_generated import ConfigValue, RecordUpdates
    from module.config.deep import DeepPath, DeepValue, MutableDeepData

RUNTIME_OVERLAY_INTERNALS = {
    "_published_config_fields",
    "_runtime_overlay",
    "_runtime_overlay_values",
}


class Function:
    def __init__(self, data: DeepValue) -> None:
        self.enable = deep_get(data, keys="Scheduler.Enable", default=False)
        self.command = deep_get(data, keys="Scheduler.Command", default="Unknown")
        next_run = deep_get(data, keys="Scheduler.NextRun")
        self.next_run: ConfigValue = DEFAULT_TIME if next_run is None else cast("ConfigValue", next_run)

    def __str__(self) -> str:
        enable = "Enable" if self.enable else "Disable"
        return f"{self.command} ({enable}, {self.next_run!s})"

    __repr__ = __str__

    def __eq__[T](self, other: T) -> bool:
        if not isinstance(other, Function):
            return False

        return self.command == other.command and self.next_run == other.next_run

    __hash__ = None


def name_to_function(name: str) -> Function:
    function = Function({})
    function.command = name
    function.enable = True
    return function


class AzurLaneConfig(ManualConfig, GeneratedConfig):
    # 旧装备切换任务在运行期注入的舰队和装备记录。
    FLEET_DAILY: int | list[int]
    FLEET_DAILY_EQUIPMENT: list[int] | None
    EXERCISE_FLEET_EQUIPMENT: list[int] | None
    EventDaily_LastStage: int | str

    def __setattr__[T](self, key: str, value: T) -> None:
        bound = self.__dict__.get("bound")
        if bound is not None and key in bound:
            path = bound[key]
            self.modified[path] = cast("ConfigValue", value)
            if self.auto_update:
                self.update()
        else:
            super().__setattr__(key, value)

    def _initialize_state(self, config_name: str) -> None:
        logger.attr("Server", self.SERVER)
        self.config_name = config_name
        # 原始配置树。
        self.data: MutableDeepData = {}
        # 待持久化修改，键为配置路径，值为新值；save() 必须原地清空此对象。
        self.modified: dict[str, ConfigValue] = {}
        # GeneratedConfig 属性名到原始配置路径的绑定。
        self.bound: dict[str, str] = {}
        # 关卡和大世界等仅在当前运行会话生效的配置覆盖。
        self._runtime_overlay: dict[str, ConfigValue] = {}
        self._published_config_fields: set[str] = set()
        # 属性修改后是否立即更新并写回。
        self.auto_update = True
        # 固定的个人配置只能由 PersonalRuntimeConfig 通过 ConfigStateRepository 写入。
        self._file_writes_enabled = config_name != "alas"
        if type(self) is AzurLaneConfig and not self._file_writes_enabled:
            self.auto_update = False
        # 跨配置重载持续生效的强制覆盖。
        self.overridden: dict[str, ConfigValue] = {}
        # 当前任务名对应 typed task registry 的 command。
        self.task: Function
        self.is_template_config = config_name.startswith("template")

    def __init__(self, config_name: str, task: str | None = None) -> None:
        self._initialize_state(config_name)

        if self.is_template_config:
            logger.info("Using template config, which is read only")
            self.auto_update = False
            self.task = name_to_function("template")
        self.init_task(task)

    def init_task(self, task: str | None = None) -> None:
        if self.is_template_config:
            return

        self.load()
        task_name = "Alas" if task is None else task
        function = name_to_function(task_name)
        self.bind(function)
        self.task = function
        self.save()

    def load(self) -> None:
        self.data = CurrentConfigurationSchema().parse(read_config_file(self.config_name))

        for path, value in self.modified.items():
            deep_set(self.data, keys=path, value=value)

    @staticmethod
    def _task_name(func: Function | str) -> str:
        if isinstance(func, Function):
            return func.command
        return func

    @staticmethod
    def _prepend_missing(items: list[str], item: str) -> None:
        if item not in items:
            items.insert(0, item)

    @classmethod
    def task_bind_chain(
        cls,
        func: Function | str,
        func_list: Iterable[str] | None = None,
    ) -> list[str]:
        task = cls._task_name(func)
        tasks = [] if func_list is None else list(func_list)

        cls._prepend_missing(tasks, task)
        definition = get_task_by_config_name(task)
        if definition is not None:
            for scope in reversed(definition.config_scopes):
                cls._prepend_missing(tasks, scope)
        cls._prepend_missing(tasks, "Alas")
        cls._prepend_missing(tasks, "General")
        return tasks

    def _runtime_overlay_values(self) -> dict[str, ConfigValue]:
        overlay = self.__dict__.get("_runtime_overlay")
        if isinstance(overlay, dict):
            return cast("dict[str, ConfigValue]", overlay)
        overlay: dict[str, ConfigValue] = {}
        self.__dict__["_runtime_overlay"] = overlay
        return overlay

    def _publish_resolved(self, snapshot: ResolvedTaskConfig) -> None:
        fields = snapshot.fields
        runtime_overlay = self._runtime_overlay_values()
        forced_values = self.__dict__.get("overridden", {})
        old_snapshot = self.__dict__.get("resolved")
        old_names = set(self.__dict__.get("_published_config_fields", ()))
        old_names.update(self.__dict__.get("bound", {}))
        if isinstance(old_snapshot, ResolvedTaskConfig):
            old_names.update(old_snapshot.field_names)

        published = {name: field.value for name, field in fields.items()}
        published.update(copy.deepcopy(runtime_overlay))
        published.update(copy.deepcopy(forced_values))
        instance_state = self.__dict__
        for name in old_names - set(published):
            instance_state.pop(name, None)
        instance_state.update(published)
        instance_state["bound"] = snapshot.bound_paths
        instance_state["resolved"] = snapshot
        instance_state["_published_config_fields"] = set(published)

    @staticmethod
    def _validate_runtime_overlay_fields(values: dict[str, object]) -> None:
        allowed = ConfigOverrides.__required_keys__ | ConfigOverrides.__optional_keys__
        unknown = sorted(set(values) - allowed)
        if unknown:
            message = f"unknown runtime config field: {unknown[0]}"
            raise KeyError(message)

    def _republish_runtime_overlay(self) -> None:
        snapshot = self.__dict__.get("resolved")
        if isinstance(snapshot, ResolvedTaskConfig):
            self._publish_resolved(snapshot)
            return

        runtime_overlay = copy.deepcopy(self._runtime_overlay_values())
        runtime_overlay.update(copy.deepcopy(self.__dict__.get("overridden", {})))
        old_names = set(self.__dict__.get("_published_config_fields", ()))
        instance_state = self.__dict__
        for name in old_names - set(runtime_overlay):
            instance_state.pop(name, None)
        instance_state.update(runtime_overlay)
        instance_state["_published_config_fields"] = set(runtime_overlay)

    def replace_runtime_overlay(self, **kwargs: Unpack[ConfigOverrides]) -> None:
        """用本次 UI 会话的配置投影替换旧投影，不触碰持久配置和调度状态。"""

        values = dict(kwargs)
        self._validate_runtime_overlay_fields(values)
        runtime_overlay = self._runtime_overlay_values()
        runtime_overlay.clear()
        runtime_overlay.update(copy.deepcopy(cast("dict[str, ConfigValue]", values)))
        self._republish_runtime_overlay()

    def apply_runtime_overlay(self, **kwargs: Unpack[ConfigOverrides]) -> None:
        """追加当前 UI 步骤的配置投影，不触碰持久配置和调度状态。"""

        values = dict(kwargs)
        self._validate_runtime_overlay_fields(values)
        self._runtime_overlay_values().update(copy.deepcopy(cast("dict[str, ConfigValue]", values)))
        self._republish_runtime_overlay()

    def bind(self, func: Function | str, func_list: Iterable[str] | None = None) -> None:
        """按 General、Alas、任务通用作用域、当前任务、func_list 额外作用域依次绑定。"""
        task_name = self._task_name(func)
        bind_chain = self.task_bind_chain(func, func_list=func_list)
        logger.info(f"Bind task {bind_chain}")
        snapshot = resolve_task_config(
            task_name=task_name,
            bind_chain=bind_chain,
            data=self.data,
            overrides=self.overridden,
        )
        self._publish_resolved(snapshot)

    @property
    def is_actual_task(self) -> bool:
        return self.task.command.lower() not in ["alas", "template"]

    def save(self) -> bool:
        if not self.modified:
            return False
        if not self._file_writes_enabled:
            message = "generic AzurLaneConfig cannot write the personal alas.json"
            raise RuntimeError(message)

        for path, value in self.modified.items():
            deep_set(self.data, keys=path, value=value)

        logger.info(f"Save config {filepath_config(self.config_name)}, {dict_to_kv(self.modified)}")
        # 不要用 self.modified = {}，否则会创建新对象。
        self.modified.clear()
        write_config_file(self.config_name, data=self.data)
        return True

    def update(self) -> None:
        self.load()
        self.bind(self.task)
        self.save()

    def override(self, **kwargs: Unpack[ConfigOverrides]) -> None:
        """只覆盖当前运行对象，不修改持久配置或任务调度。"""

        for arg, value in kwargs.items():
            self.overridden[arg] = cast("ConfigValue", value)
            super().__setattr__(arg, value)
        previous = self.__dict__.get("resolved")
        if kwargs and isinstance(previous, ResolvedTaskConfig):
            snapshot = resolve_task_config(
                task_name=previous.task_name,
                bind_chain=previous.bind_chain,
                data=self.data,
                overrides=self.overridden,
            )
            self._publish_resolved(snapshot)

    def set_record(self, **kwargs: Unpack[RecordUpdates]) -> None:
        """设置 `*_Value` 时同步把对应 `*_Record` 更新为当前时间。"""
        with self.multi_set():
            for arg, value in kwargs.items():
                record = arg.replace("Value", "Record")
                setattr(self, arg, value)
                setattr(self, record, datetime.now().replace(microsecond=0))

    def multi_set(self) -> MultiSetWrapper:
        """返回批量设置上下文，退出时只更新并保存一次。"""
        return MultiSetWrapper(main=self)

    def cross_get[T: DeepValue](
        self,
        keys: DeepPath,
        default: T | None = None,
    ) -> DeepValue | T | None:
        """按点分隔字符串或键序列指定的深层路径读取其他任务配置。"""
        return deep_get(self.data, keys=keys, default=default)

    def is_task_enabled(self, task: str) -> bool:
        return bool(self.cross_get(keys=[task, "Scheduler", "Enable"], default=False))

    @property
    def campaign_name(self) -> str:
        """返回掉落记录子目录名；数字开头时加 `campaign_`，困难模式再加 `_hard`。"""
        name = self.Campaign_Name.lower().replace("-", "_")
        if name[0].isdigit():
            name = "campaign_" + str(name)
        if self.Campaign_Mode == "hard":
            name += "_hard"
        return name

    def merge[T](self, other: T) -> Self:
        """合并关卡或任务提供的运行期覆盖，并返回当前配置门面。

        覆盖不属于持久解析结果，不能触发配置写回。
        """
        config = self
        runtime_overlay = config._runtime_overlay_values()

        for attr in dir(config):
            if attr.endswith("__") or attr in RUNTIME_OVERLAY_INTERNALS:
                continue
            if hasattr(other, attr):
                value = getattr(other, attr)
                if value is not None:
                    runtime_overlay[attr] = cast("ConfigValue", copy.deepcopy(value))

        snapshot = config.__dict__.get("resolved")
        if isinstance(snapshot, ResolvedTaskConfig):
            config._publish_resolved(snapshot)
        else:
            published = copy.deepcopy(runtime_overlay)
            published.update(copy.deepcopy(config.__dict__.get("overridden", {})))
            config.__dict__.update(published)
            config.__dict__["_published_config_fields"] = set(published)

        return config

    @property
    def fleet_1(self) -> int:
        return self.Fleet_Fleet1

    @property
    def fleet_2(self) -> int:
        return self.Fleet_Fleet2

    @property
    def submarine(self) -> int:
        return self.Submarine_Fleet

    @property
    def fleet_boss(self) -> int:
        if self.Fleet_Fleet2 and self.Fleet_FleetOrder in [
            "fleet1_mob_fleet2_boss",
            "fleet1_boss_fleet2_mob",
        ]:
            return 2
        return 1

    def temporary(self, **kwargs: Unpack[ConfigOverrides]) -> ConfigBackup:
        """通过运行期投影临时覆盖属性，不触碰持久配置。"""
        values = dict(kwargs)
        self._validate_runtime_overlay_fields(values)
        runtime_overlay = self._runtime_overlay_values()
        overlay_backup = {key: copy.deepcopy(runtime_overlay[key]) for key in values if key in runtime_overlay}
        missing_overlay_fields = set(values) - set(overlay_backup)
        self.apply_runtime_overlay(**kwargs)

        def recover() -> None:
            current_overlay = self._runtime_overlay_values()
            for key in missing_overlay_fields:
                current_overlay.pop(key, None)
            current_overlay.update(copy.deepcopy(overlay_backup))
            self._republish_runtime_overlay()

        return ConfigBackup(recover)


vars(pywebio.output)["Output"] = OutputConfig
vars(pywebio.pin)["Output"] = OutputConfig


class ConfigBackup:
    def __init__(self, recover: Callable[[], None]) -> None:
        self._recover: Callable[[], None] | None = recover

    def recover(self) -> None:
        recover = self._recover
        if recover is None:
            return
        recover()
        self._recover = None

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        self.recover()


class MultiSetWrapper:
    def __init__(self, main: AzurLaneConfig) -> None:
        self.main = main
        self.in_wrapper = False

    def __enter__(self) -> Self:
        if self.main.auto_update:
            self.main.auto_update = False
        else:
            self.in_wrapper = True
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        if not self.in_wrapper:
            try:
                self.main.update()
            finally:
                self.main.auto_update = True
