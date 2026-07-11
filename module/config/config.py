import copy
from dataclasses import replace
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

import pywebio

from module.config.config_generated import GeneratedConfig
from module.config.config_manual import ManualConfig, OutputConfig
from module.config.config_updater import ConfigUpdater
from module.config.deep import deep_get, deep_set
from module.config.resolved import ResolvedTaskConfig, resolve_task_config
from module.config.schedule import ScheduleDecision, ScheduleEntry, SchedulePlanner
from module.config.utils import (
    DEFAULT_TIME,
    dict_to_kv,
    ensure_time,
    filepath_config,
    get_os_reset_remain,
    get_server_next_update,
    nearest_future,
)
from module.config.watcher import ConfigWatcher
from module.exception import RequestHumanTakeover, ScriptError
from module.logger import logger
from module.map.map_grids import SelectedGrids
from module.task_registry import TASK_CATALOG, get_task_by_config_name

if TYPE_CHECKING:
    from module.base.stop_event import StopEvent

MISSING_DELAY_ARGUMENT_MESSAGE = "Missing argument in delay_next_run, should set at least one"
TASK_CALL_MISSING_TEMPLATE = "Task to call: `{task}` does not exist in user config"
RUNTIME_OVERLAY_INTERNALS = {
    "_published_config_fields",
    "_runtime_overlay",
    "_runtime_overlay_values",
}


class TaskEnd(Exception):
    pass


class Function:
    def __init__(self, data):
        self.enable = deep_get(data, keys="Scheduler.Enable", default=False)
        self.command = deep_get(data, keys="Scheduler.Command", default="Unknown")
        self.next_run = deep_get(data, keys="Scheduler.NextRun", default=DEFAULT_TIME)

    def __str__(self):
        enable = "Enable" if self.enable else "Disable"
        return f"{self.command} ({enable}, {self.next_run!s})"

    __repr__ = __str__

    def __eq__(self, other):
        if not isinstance(other, Function):
            return False

        return self.command == other.command and self.next_run == other.next_run

    __hash__ = None


def _function_from_entry(entry: ScheduleEntry, *, next_run: object | None = None) -> Function:
    function = Function({})
    function.enable = entry.enable
    function.command = entry.command
    function.next_run = entry.next_run if next_run is None else next_run
    return function


def _schedule_priority() -> dict[str, int]:
    return {
        definition.config_name: definition.priority
        for definition in TASK_CATALOG.values()
        if definition.priority is not None
    }


def name_to_function(name):
    function = Function({})
    function.command = name
    function.enable = True
    return function


class AzurLaneConfig(ConfigUpdater, ManualConfig, GeneratedConfig, ConfigWatcher):
    stop_event: StopEvent | None = None

    is_hoarding_task = True

    # 旧装备切换任务在运行期注入的舰队和装备记录。
    FLEET_DAILY: int | list[int]
    FLEET_DAILY_EQUIPMENT: list[int] | None
    FLEET_HARD_EQUIPMENT: list[int] | None
    EXERCISE_FLEET_EQUIPMENT: list[int] | None
    EventDaily_LastStage: int | str

    def __setattr__(self, key, value):
        bound = self.__dict__.get("bound")
        if bound is not None and key in bound:
            path = bound[key]
            self.modified[path] = value
            if self.auto_update:
                self.update()
        else:
            super().__setattr__(key, value)

    def __init__(self, config_name, task=None):
        logger.attr("Server", self.SERVER)
        self.config_name = config_name
        # 原始配置树。
        self.data = {}
        # 待持久化修改，键为配置路径，值为新值；save() 必须原地清空此对象。
        self.modified = {}
        # GeneratedConfig 属性名到原始配置路径的绑定。
        self.bound = {}
        # 关卡和大世界等仅在当前运行会话生效的配置覆盖。
        self._runtime_overlay: dict[str, object] = {}
        self._published_config_fields: set[str] = set()
        # 属性修改后是否立即更新并写回。
        self.auto_update = True
        # 跨配置重载持续生效的强制覆盖。
        self.overridden = {}
        # pending_task 已到运行时间；waiting_task 尚未到运行时间。
        self.pending_task = []
        self.waiting_task = []
        # 兼容保留类属性默认值，实际调度状态始终由当前配置实例持有。
        self.is_hoarding_task = type(self).is_hoarding_task
        # 当前任务名对应 AzurLaneAutoScript 的入口方法。
        self.task: Function
        self.is_template_config = config_name.startswith("template")

        if self.is_template_config:
            logger.info("Using template config, which is read only")
            self.auto_update = False
            self.task = name_to_function("template")
        self.init_task(task)

    def init_task(self, task=None):
        if self.is_template_config:
            return

        self.load()
        task_name = "Alas" if task is None else task
        task = name_to_function(task_name)
        self.bind(task)
        self.task = task
        self.save()

    def load(self):
        self.data = self.read_file(self.config_name)
        self.config_override()

        for path, value in self.modified.items():
            deep_set(self.data, keys=path, value=value)

    @staticmethod
    def _task_name(func):
        if isinstance(func, Function):
            return func.command
        return func

    @staticmethod
    def _prepend_missing(items, item) -> None:
        if item not in items:
            items.insert(0, item)

    @classmethod
    def task_bind_chain(cls, func, func_list=None) -> list[str]:
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

    def _runtime_overlay_values(self) -> dict[str, object]:
        overlay = self.__dict__.get("_runtime_overlay")
        if isinstance(overlay, dict):
            return overlay
        overlay = {}
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

    def bind(self, func, func_list=None):
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
    def hoarding(self):
        minutes = int(deep_get(self.data, keys="Alas.Optimization.TaskHoardingDuration", default=0))
        return timedelta(minutes=max(minutes, 0))

    @property
    def close_game(self):
        return deep_get(self.data, keys="Alas.Optimization.CloseGameDuringWait", default=False)

    @property
    def is_actual_task(self):
        return self.task.command.lower() not in ["alas", "template"]

    def get_next_task(self, *, now: datetime | None = None) -> ScheduleDecision:
        """计算任务队列，并保留 WebUI 依赖的旧式 Function 视图。"""
        current_time = datetime.now() if now is None else now
        if self.is_hoarding_task:
            current_time -= self.hoarding
        entries = tuple(
            ScheduleEntry(enable=func.enable, command=func.command, next_run=func.next_run)
            for func in (Function(func_data) for func_data in self.data.values())
        )
        decision = SchedulePlanner.select(
            entries,
            now=current_time,
            priority=_schedule_priority(),
        )
        self.pending_task = [
            *(_function_from_entry(entry) for entry in decision.errors),
            *(_function_from_entry(entry) for entry in decision.pending),
        ]
        self.waiting_task = [_function_from_entry(entry) for entry in decision.waiting]
        return decision

    def get_next_decision(self, *, now: datetime | None = None) -> ScheduleDecision:
        decision = self.get_next_task(now=now)
        if decision.state in {"ready", "error"}:
            entry = decision.entry
            if entry is None:
                raise RequestHumanTakeover
            self.is_hoarding_task = False
            logger.info(f"Pending tasks: {[func.command for func in self.pending_task]}")
            logger.attr("Task", _function_from_entry(entry))
            return decision
        if decision.state == "waiting":
            entry = decision.entry
            wake_time = decision.wake_at
            if entry is None or wake_time is None:
                raise RequestHumanTakeover
            self.is_hoarding_task = True
            wake_at = (wake_time + self.hoarding).replace(microsecond=0)
            waiting = replace(decision, wake_at=wake_at)
            logger.info("No task pending")
            logger.attr("Task", _function_from_entry(entry, next_run=wake_at))
            return waiting

        logger.critical("No task waiting or pending")
        logger.critical("Please enable at least one task")
        raise RequestHumanTakeover

    def mark_task_started(self) -> None:
        self.is_hoarding_task = False

    @staticmethod
    def function_from_decision(decision: ScheduleDecision) -> Function:
        if decision.entry is None:
            raise RequestHumanTakeover
        next_run = decision.wake_at if decision.state == "waiting" else decision.entry.next_run
        return _function_from_entry(decision.entry, next_run=next_run)

    def get_next(self):
        return self.function_from_decision(self.get_next_decision())

    def save(self):
        if not self.modified:
            return False

        for path, value in self.modified.items():
            deep_set(self.data, keys=path, value=value)

        logger.info(f"Save config {filepath_config(self.config_name)}, {dict_to_kv(self.modified)}")
        # 不要用 self.modified = {}，否则会创建新对象。
        self.modified.clear()
        self.write_file(self.config_name, data=self.data)
        return True

    def update(self):
        self.load()
        self.bind(self.task)
        self.save()

    def override(self, **kwargs):
        now = datetime.now().replace(microsecond=0)
        limited = set()

        def limit_next_run(tasks, limit):
            for task in tasks:
                if task in limited:
                    continue
                limited.add(task)
                next_run = deep_get(self.data, keys=f"{task}.Scheduler.NextRun", default=None)
                if isinstance(next_run, datetime) and next_run > limit:
                    deep_set(self.data, keys=f"{task}.Scheduler.NextRun", value=now)

        for task in ["Commission", "Research", "Reward"]:
            if not self.is_task_enabled(task):
                self.modified[f"{task}.Scheduler.Enable"] = True
        force_enable = list

        force_enable(
            [
                "Commission",
                "Research",
                "Reward",
            ]
        )
        limit_next_run(["Commission", "Reward"], limit=now + timedelta(hours=12, seconds=-1))
        limit_next_run(["Research"], limit=now + timedelta(hours=24, seconds=-1))
        limit_next_run(
            ["OpsiExplore", "OpsiCrossMonth", "OpsiVoucher", "OpsiMonthBoss", "OpsiShop"],
            limit=now + timedelta(days=31, seconds=-1),
        )
        limit_next_run(["OpsiArchive"], limit=now + timedelta(days=7, seconds=-1))
        limit_next_run(self.args.keys(), limit=now + timedelta(hours=24, seconds=-1))

        # 强制覆盖在配置重载后仍然生效，且没有自动恢复入口。
        for arg, value in kwargs.items():
            self.overridden[arg] = value
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

    config_override = override

    def set_record(self, **kwargs):
        """设置 `*_Value` 时同步把对应 `*_Record` 更新为当前时间。"""
        with self.multi_set():
            for arg, value in kwargs.items():
                record = arg.replace("Value", "Record")
                self.__setattr__(arg, value)
                self.__setattr__(record, datetime.now().replace(microsecond=0))

    def multi_set(self):
        """返回批量设置上下文，退出时只更新并保存一次。"""
        return MultiSetWrapper(main=self)

    def cross_get(self, keys, default=None):
        """按点分隔字符串或键序列指定的深层路径读取其他任务配置。"""
        return deep_get(self.data, keys=keys, default=default)

    def cross_set(self, keys, value):
        """按点分隔字符串或键序列指定的深层路径修改其他任务配置，并按 auto_update 决定是否立即写回。"""
        self.modified[keys] = value
        if self.auto_update:
            self.update()

    def task_delay(self, success=None, server_update=None, target=None, minute=None, task=None):
        """设置当前或指定任务的 Scheduler.NextRun；多个候选取最近时间。

        success 选择成功或失败间隔；server_update=True 使用配置触发点，也可直接传触发点；
        target 接受时间或列表，minute 接受分钟数或范围。至少应提供一个候选。
        """

        def ensure_delta(delay):
            return timedelta(seconds=int(ensure_time(delay, precision=3) * 60))

        run = []
        if success is not None:
            interval = self.Scheduler_SuccessInterval if success else self.Scheduler_FailureInterval
            run.append(datetime.now() + ensure_delta(interval))
        if server_update is not None:
            if server_update is True:
                server_update = self.Scheduler_ServerUpdate
            run.append(get_server_next_update(server_update))
        if target is not None:
            target = [target] if not isinstance(target, list) else target
            target = nearest_future(target)
            run.append(target)
        if minute is not None:
            run.append(datetime.now() + ensure_delta(minute))

        if run:
            run = min(run).replace(microsecond=0)
            kv = dict_to_kv(
                {
                    "success": success,
                    "server_update": server_update,
                    "target": target,
                    "minute": minute,
                },
                allow_none=False,
            )
            if task is None:
                task = self.task.command
            logger.info(f"Delay task `{task}` to {run} ({kv})")
            self.modified[f"{task}.Scheduler.NextRun"] = run
            self.update()
        else:
            raise ScriptError(MISSING_DELAY_ARGUMENT_MESSAGE)

    def _delay_opsi_tasks(self, task_list, minutes, kv) -> None:
        next_run = datetime.now().replace(microsecond=0) + timedelta(minutes=minutes)
        for task in task_list:
            keys = f"{task}.Scheduler.NextRun"
            current = deep_get(self.data, keys=keys, default=DEFAULT_TIME)
            if current < next_run:
                logger.info(f"Delay task `{task}` to {next_run} ({kv})")
                self.modified[keys] = next_run

    def _is_opsi_submarine_call(self, task):
        return (
            deep_get(self.data, keys=f"{task}.OpsiFleet.Submarine", default=False)
            or "submarine" in deep_get(self.data, keys=f"{task}.OpsiFleetFilter.Filter", default="").lower()
        )

    def _is_opsi_force_run(self, task):
        return (
            deep_get(self.data, keys=f"{task}.OpsiExplore.ForceRun", default=False)
            or deep_get(self.data, keys=f"{task}.OpsiObscure.ForceRun", default=False)
            or deep_get(self.data, keys=f"{task}.OpsiAbyssal.ForceRun", default=False)
            or deep_get(self.data, keys=f"{task}.OpsiStronghold.ForceRun", default=False)
        )

    def _is_opsi_special_radar(self, task):
        return deep_get(self.data, keys=f"{task}.OpsiExplore.SpecialRadar", default=False)

    def _opsi_recon_scan_tasks(self):
        tasks = SelectedGrids(["OpsiExplore", "OpsiObscure", "OpsiStronghold"])
        return tasks.delete(tasks.filter(self._is_opsi_force_run)).delete(tasks.filter(self._is_opsi_special_radar))

    def _opsi_submarine_call_tasks(self):
        tasks = SelectedGrids(
            [
                "OpsiExplore",
                "OpsiDaily",
                "OpsiObscure",
                "OpsiAbyssal",
                "OpsiArchive",
                "OpsiStronghold",
                "OpsiMeowfficerFarming",
                "OpsiMonthBoss",
            ]
        )
        return tasks.filter(self._is_opsi_submarine_call).delete(tasks.filter(self._is_opsi_force_run))

    @staticmethod
    def _opsi_ap_limit_tasks():
        return SelectedGrids(
            [
                "OpsiExplore",
                "OpsiDaily",
                "OpsiObscure",
                "OpsiAbyssal",
                "OpsiStronghold",
                # 延迟 OpsiArchive，因为 OpsiArchive 和 OpsiDaily 共用任务列表。
                "OpsiArchive",
                "OpsiMeowfficerFarming",
            ]
        )

    @staticmethod
    def _opsi_cl1_preserve_tasks():
        return SelectedGrids(
            [
                "OpsiObscure",
                "OpsiAbyssal",
                "OpsiStronghold",
                "OpsiMeowfficerFarming",
            ]
        )

    def opsi_task_delay(self, recon_scan=False, submarine_call=False, ap_limit=False, cl1_preserve=False):
        """批量延迟大世界任务：侦察 27 分钟、潜艇 60 分钟、行动力或 CL1 保留 360 分钟。

        距离月重置不足一天时，行动力限制改为 150 分钟。
        """
        if not recon_scan and not submarine_call and not ap_limit and not cl1_preserve:
            return
        kv = dict_to_kv(
            {
                "recon_scan": recon_scan,
                "submarine_call": submarine_call,
                "ap_limit": ap_limit,
                "cl1_preserve": cl1_preserve,
            }
        )

        if recon_scan:
            self._delay_opsi_tasks(self._opsi_recon_scan_tasks(), minutes=27, kv=kv)
        if submarine_call:
            self._delay_opsi_tasks(self._opsi_submarine_call_tasks(), minutes=60, kv=kv)
        if ap_limit:
            if get_os_reset_remain() > 0:
                self._delay_opsi_tasks(self._opsi_ap_limit_tasks(), minutes=360, kv=kv)
            else:
                logger.info("Just less than 1 day to OpSi reset, delay 2.5 hours")
                self._delay_opsi_tasks(self._opsi_ap_limit_tasks(), minutes=150, kv=kv)
        if cl1_preserve:
            self._delay_opsi_tasks(self._opsi_cl1_preserve_tasks(), minutes=360, kv=kv)

        self.update()

    def task_call(self, task, force_call=True):
        """把目标任务设为立即到期；force_call=False 时尊重用户的禁用状态。

        返回是否成功入队；实际执行仍可能被调度优先级推迟。
        """
        if deep_get(self.data, keys=f"{task}.Scheduler.NextRun", default=None) is None:
            message = TASK_CALL_MISSING_TEMPLATE.format(task=task)
            raise ScriptError(message)

        if force_call or self.is_task_enabled(task):
            logger.info(f"Task call: {task}")
            self.modified[f"{task}.Scheduler.NextRun"] = datetime.now().replace(microsecond=0)
            self.modified[f"{task}.Scheduler.Enable"] = True
            if self.auto_update:
                self.update()
            return True
        logger.info(f"Task call: {task} (skipped because disabled by user)")
        return False

    @staticmethod
    def task_stop(message=""):
        """抛出 TaskEnd 终止当前任务。"""
        if message:
            raise TaskEnd(message)
        raise TaskEnd

    def task_switched(self):
        """停止信号已设置或重载配置后下一任务变化时返回 True。"""
        if self.stop_event is not None and self.stop_event.is_set():
            return True
        prev = self.task
        self.load()
        new = self.get_next()
        if prev == new:
            logger.info(f"Continue task `{new}`")
            return False
        logger.info(f"Switch task `{prev}` to `{new}`")
        return True

    def check_task_switch(self, message=""):
        """任务已切换时抛出 TaskEnd。"""
        if self.task_switched():
            self.task_stop(message=message)

    def is_task_enabled(self, task):
        return bool(self.cross_get(keys=[task, "Scheduler", "Enable"], default=False))

    @property
    def campaign_name(self):
        """返回掉落记录子目录名；数字开头时加 `campaign_`，困难模式再加 `_hard`。"""
        name = self.Campaign_Name.lower().replace("-", "_")
        if name[0].isdigit():
            name = "campaign_" + str(name)
        if self.Campaign_Mode == "hard":
            name += "_hard"
        return name

    def merge(self, other):
        """合并关卡或任务提供的运行期覆盖，并返回当前配置门面。

        覆盖不属于持久解析结果，不能触发配置写回。
        """
        config = self
        runtime_overlay = config._runtime_overlay_values()

        for attr in dir(config):
            if attr.endswith("__") or attr in RUNTIME_OVERLAY_INTERNALS:
                continue
            if hasattr(other, attr):
                value = other.__getattribute__(attr)
                if value is not None:
                    runtime_overlay[attr] = copy.deepcopy(value)

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
    def FLEET_1(self):
        return self.Fleet_Fleet1

    @property
    def FLEET_2(self):
        return self.Fleet_Fleet2

    @FLEET_2.setter
    def FLEET_2(self, value):
        self.override(Fleet_Fleet2=value)

    @property
    def SUBMARINE(self):
        return self.Submarine_Fleet

    @SUBMARINE.setter
    def SUBMARINE(self, value):
        self.override(Submarine_Fleet=value)

    _fleet_boss = 0

    @property
    def FLEET_BOSS(self):
        if self._fleet_boss:
            return self._fleet_boss
        if self.Fleet_Fleet2 and self.Fleet_FleetOrder in [
            "fleet1_mob_fleet2_boss",
            "fleet1_boss_fleet2_mob",
        ]:
            return 2
        return 1

    @FLEET_BOSS.setter
    def FLEET_BOSS(self, value):
        self._fleet_boss = value

    def temporary(self, **kwargs):
        """临时覆盖属性并返回可手动 recover 或作为上下文使用的 ConfigBackup。"""
        backup = ConfigBackup(config=self)
        backup.cover(**kwargs)
        return backup


vars(pywebio.output)["Output"] = OutputConfig
vars(pywebio.pin)["Output"] = OutputConfig


class ConfigBackup:
    def __init__(self, config):
        self.config = config
        self.backup = {}
        self.kwargs = {}

    def cover(self, **kwargs):
        self.kwargs = kwargs
        for key, value in kwargs.items():
            self.backup[key] = self.config.__getattribute__(key)
            self.config.__setattr__(key, value)

    def recover(self):
        for key, value in self.backup.items():
            self.config.__setattr__(key, value)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.recover()


class MultiSetWrapper:
    def __init__(self, main):
        self.main = main
        self.in_wrapper = False

    def __enter__(self):
        if self.main.auto_update:
            self.main.auto_update = False
        else:
            self.in_wrapper = True
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if not self.in_wrapper:
            self.main.update()
            self.main.auto_update = True
