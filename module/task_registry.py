import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from importlib import import_module
from types import MappingProxyType
from typing import Literal, Protocol

from module.base.naming import camel_to_snake


class CampaignConfig(Protocol):
    Campaign_Name: str
    Campaign_Event: str
    Campaign_Mode: str


class TaskRunner(Protocol):
    config: CampaignConfig
    device: object


type TaskArgsFactory = Callable[[TaskRunner], tuple[tuple[object, ...], dict[str, object]]]
type LaunchMode = Literal["scheduled", "direct", "both"]


@dataclass(frozen=True, slots=True)
class ClassTaskExecutor:
    module_name: str
    class_name: str
    method_name: str = "run"
    args_factory: TaskArgsFactory | None = None
    task_name: str | None = None

    def execute(self, runner: TaskRunner) -> None:
        module = import_module(self.module_name)
        task_class = getattr(module, self.class_name)
        init_kwargs = {
            "config": runner.config,
            "device": runner.device,
        }
        if self.task_name is not None:
            init_kwargs["task"] = self.task_name
        task = task_class(**init_kwargs)
        args, kwargs = self.args_factory(runner) if self.args_factory is not None else ((), {})
        getattr(task, self.method_name)(*args, **kwargs)


@dataclass(frozen=True, slots=True)
class FunctionTaskExecutor:
    module_name: str
    function_name: str

    def execute(self, runner: TaskRunner) -> None:
        module = import_module(self.module_name)
        function = getattr(module, self.function_name)
        function(config=runner.config)


@dataclass(frozen=True, slots=True)
class RunnerMethodExecutor:
    method_name: str

    def execute(self, runner: TaskRunner) -> None:
        getattr(runner, self.method_name)()


type TaskExecutor = ClassTaskExecutor | FunctionTaskExecutor | RunnerMethodExecutor
TASK_EXECUTOR_TYPES = (ClassTaskExecutor, FunctionTaskExecutor, RunnerMethodExecutor)
TASK_COMMAND_PATTERN = re.compile(r"[a-z][a-z0-9]*(?:_[a-z][a-z0-9]*)*", flags=re.ASCII)


@dataclass(frozen=True, slots=True)
class TaskDefinition:
    command: str
    executor: TaskExecutor
    config_scopes: tuple[str, ...]
    priority: int | None
    launch_mode: LaunchMode

    def __post_init__(self) -> None:
        self._validate_command()
        self._validate_executor()
        self._validate_config_scopes()
        self._validate_priority()
        self._validate_launch_mode()

    def _validate_command(self) -> None:
        if not isinstance(self.command, str):
            message = f"task command must be a string: {self.command!r}"
            raise TypeError(message)
        if TASK_COMMAND_PATTERN.fullmatch(self.command) is None:
            message = f"invalid task command: {self.command!r}"
            raise ValueError(message)

    def _validate_executor(self) -> None:
        if not isinstance(self.executor, TASK_EXECUTOR_TYPES):
            message = f"invalid task executor: {type(self.executor).__name__}"
            raise TypeError(message)

    def _validate_config_scopes(self) -> None:
        if not isinstance(self.config_scopes, tuple):
            message = f"config scopes must be a tuple: {self.command}"
            raise TypeError(message)
        if any(not isinstance(scope, str) or not scope for scope in self.config_scopes):
            message = f"config scopes must contain non-empty strings: {self.command}"
            raise TypeError(message)
        if len(set(self.config_scopes)) != len(self.config_scopes):
            message = f"config scopes must not contain duplicates: {self.command}"
            raise ValueError(message)

    def _validate_priority(self) -> None:
        if self.priority is not None and type(self.priority) is not int:
            message = f"task priority must be an integer or None: {self.command}"
            raise TypeError(message)
        if self.priority is not None and self.priority < 0:
            message = f"task priority must not be negative: {self.command}"
            raise ValueError(message)

    def _validate_launch_mode(self) -> None:
        if not isinstance(self.launch_mode, str):
            message = f"launch mode must be a string: {self.command}"
            raise TypeError(message)
        if self.launch_mode not in {"scheduled", "direct", "both"}:
            message = f"invalid launch mode for task {self.command}: {self.launch_mode}"
            raise ValueError(message)

    @property
    def config_name(self) -> str:
        return command_to_config_name(self.command)

    def execute(self, runner: TaskRunner) -> None:
        self.executor.execute(runner)


# 历史调用方只依赖名字和 execute()；别名避免复制另一份目录。
TaskSpec = TaskDefinition
FunctionTaskSpec = FunctionTaskExecutor


def command_to_config_name(command: str) -> str:
    """把 catalog 命令转换成配置节点名。"""
    if not isinstance(command, str):
        message = f"task command must be a string: {command!r}"
        raise TypeError(message)
    if TASK_COMMAND_PATTERN.fullmatch(command) is None:
        message = f"invalid task command: {command!r}"
        raise ValueError(message)
    return "".join(part.capitalize() for part in command.split("_"))


def config_name_to_command(config_name: str) -> str:
    """把配置节点名转换成 catalog 命令。"""
    return camel_to_snake(config_name)


def _campaign_args(runner: TaskRunner) -> tuple[tuple[object, ...], dict[str, object]]:
    config = runner.config
    return (
        (),
        {
            "name": config.Campaign_Name,
            "folder": config.Campaign_Event,
            "mode": config.Campaign_Mode,
        },
    )


def _class_executor(
    module_name: str,
    class_name: str,
    method_name: str = "run",
    args_factory: TaskArgsFactory | None = None,
    task_name: str | None = None,
) -> ClassTaskExecutor:
    return ClassTaskExecutor(
        module_name=module_name,
        class_name=class_name,
        method_name=method_name,
        args_factory=args_factory,
        task_name=task_name,
    )


def _campaign_executor(module_name: str, class_name: str) -> ClassTaskExecutor:
    return _class_executor(module_name, class_name, args_factory=_campaign_args)


def _task(
    command: str,
    executor: TaskExecutor,
    *,
    priority: int | None,
    config_scopes: tuple[str, ...] = (),
    launch_mode: LaunchMode = "scheduled",
) -> TaskDefinition:
    return TaskDefinition(
        command=command,
        executor=executor,
        config_scopes=config_scopes,
        priority=priority,
        launch_mode=launch_mode,
    )


def _build_catalog(*definitions: TaskDefinition) -> Mapping[str, TaskDefinition]:
    catalog: dict[str, TaskDefinition] = {}
    config_names: dict[str, str] = {}
    priorities: set[int] = set()
    for definition in definitions:
        if definition.command in catalog:
            message = f"duplicate task command: {definition.command}"
            raise ValueError(message)
        config_name = definition.config_name
        if config_name in config_names:
            message = f"task config name collision: {config_names[config_name]} and {definition.command}"
            raise ValueError(message)
        if definition.priority is not None:
            if definition.priority in priorities:
                message = f"duplicate task priority: {definition.priority}"
                raise ValueError(message)
            priorities.add(definition.priority)
        catalog[definition.command] = definition
        config_names[config_name] = definition.command

    if sorted(priorities) != list(range(len(priorities))):
        message = "task priorities must be contiguous from zero"
        raise ValueError(message)
    return MappingProxyType(catalog)


EVENT_SCOPES = ("TaskBalancer", "EventGeneral")
OPSI_SCOPES = ("OpsiGeneral",)


TASK_CATALOG: Mapping[str, TaskDefinition] = _build_catalog(
    _task("restart", RunnerMethodExecutor(method_name="restart"), priority=0),
    # 普通任务：构造任务类后直接调用指定方法。
    _task("research", _class_executor("module.research.research", "RewardResearch"), priority=4),
    _task("commission", _class_executor("module.commission.commission", "RewardCommission"), priority=2),
    _task("tactical", _class_executor("module.tactical.tactical_class", "RewardTacticalClass"), priority=3),
    _task("dorm", _class_executor("module.dorm.dorm", "RewardDorm"), priority=6),
    _task("meowfficer", _class_executor("module.meowfficer.meowfficer", "RewardMeowfficer"), priority=7),
    _task("guild", _class_executor("module.guild.guild_reward", "RewardGuild"), priority=8),
    _task("reward", _class_executor("module.reward.reward", "Reward"), priority=10),
    _task("awaken", _class_executor("module.awaken.awaken", "Awaken"), priority=18),
    _task("shipyard", _class_executor("module.shipyard.shipyard_reward", "RewardShipyard"), priority=13),
    _task("gacha", _class_executor("module.gacha.gacha_reward", "RewardGacha"), priority=9),
    _task("freebies", _class_executor("module.freebies.freebies", "Freebies"), priority=14),
    _task("minigame", _class_executor("module.minigame.minigame", "Minigame"), priority=17),
    _task(
        "private_quarters", _class_executor("module.private_quarters.private_quarters", "PrivateQuarters"), priority=15
    ),
    _task("daily", _class_executor("module.daily.daily", "Daily"), priority=27),
    _task("hard", _class_executor("module.hard.hard", "CampaignHard"), priority=28),
    _task("exercise", _class_executor("module.exercise.exercise", "Exercise"), priority=5),
    _task("sos", _class_executor("module.sos.sos", "CampaignSos"), priority=31),
    _task("raid_daily", _class_executor("module.raid.daily", "RaidDaily"), priority=37, config_scopes=EVENT_SCOPES),
    _task(
        "event_sp", _class_executor("module.event.campaign_sp", "CampaignSP"), priority=32, config_scopes=EVENT_SCOPES
    ),
    _task(
        "maritime_escort",
        _class_executor("module.event.maritime_escort", "MaritimeEscort"),
        priority=40,
        config_scopes=EVENT_SCOPES,
    ),
    _task(
        "opsi_ash_assist",
        _class_executor("module.os_ash.meta", "AshBeaconAssist"),
        priority=29,
        config_scopes=OPSI_SCOPES,
    ),
    _task(
        "opsi_ash_beacon",
        _class_executor("module.os_ash.meta", "OpsiAshBeacon"),
        priority=19,
        config_scopes=OPSI_SCOPES,
    ),
    _task("raid", _class_executor("module.raid.run", "RaidRun"), priority=43, config_scopes=EVENT_SCOPES),
    _task("hospital", _class_executor("module.event_hospital.hospital", "Hospital"), priority=44),
    _task(
        "coalition", _class_executor("module.coalition.coalition", "Coalition"), priority=45, config_scopes=EVENT_SCOPES
    ),
    _task(
        "coalition_sp",
        _class_executor("module.coalition.coalition_sp", "CoalitionSP"),
        priority=38,
        config_scopes=EVENT_SCOPES,
    ),
    # 商店任务共用 RewardShop，只切换执行方法。
    _task(
        "shop_frequent",
        _class_executor("module.shop.shop_reward", "RewardShop", method_name="run_frequent"),
        priority=11,
    ),
    _task("shop_once", _class_executor("module.shop.shop_reward", "RewardShop", method_name="run_once"), priority=12),
    # 活动 ABCD 入口共用一个任务类，具体章节由配置决定。
    _task(
        "event_a",
        _class_executor("module.event.campaign_abcd", "CampaignABCD"),
        priority=33,
        config_scopes=EVENT_SCOPES,
    ),
    _task(
        "event_b",
        _class_executor("module.event.campaign_abcd", "CampaignABCD"),
        priority=34,
        config_scopes=EVENT_SCOPES,
    ),
    _task(
        "event_c",
        _class_executor("module.event.campaign_abcd", "CampaignABCD"),
        priority=35,
        config_scopes=EVENT_SCOPES,
    ),
    _task(
        "event_d",
        _class_executor("module.event.campaign_abcd", "CampaignABCD"),
        priority=36,
        config_scopes=EVENT_SCOPES,
    ),
    # 大世界任务集中在 OSCampaignRun，这里只声明调用的方法。
    _task(
        "opsi_explore",
        _class_executor("module.campaign.os_run", "OSCampaignRun", method_name="opsi_explore"),
        priority=16,
        config_scopes=OPSI_SCOPES,
    ),
    _task(
        "opsi_shop",
        _class_executor("module.campaign.os_run", "OSCampaignRun", method_name="opsi_shop"),
        priority=21,
        config_scopes=OPSI_SCOPES,
    ),
    _task(
        "opsi_voucher",
        _class_executor("module.campaign.os_run", "OSCampaignRun", method_name="opsi_voucher"),
        priority=22,
        config_scopes=OPSI_SCOPES,
    ),
    _task(
        "opsi_daily",
        _class_executor("module.campaign.os_run", "OSCampaignRun", method_name="opsi_daily"),
        priority=20,
        config_scopes=OPSI_SCOPES,
    ),
    _task(
        "opsi_obscure",
        _class_executor("module.campaign.os_run", "OSCampaignRun", method_name="opsi_obscure"),
        priority=25,
        config_scopes=OPSI_SCOPES,
    ),
    _task(
        "opsi_month_boss",
        _class_executor("module.campaign.os_run", "OSCampaignRun", method_name="opsi_month_boss"),
        priority=30,
        config_scopes=OPSI_SCOPES,
    ),
    _task(
        "opsi_abyssal",
        _class_executor("module.campaign.os_run", "OSCampaignRun", method_name="opsi_abyssal"),
        priority=23,
        config_scopes=OPSI_SCOPES,
    ),
    _task(
        "opsi_archive",
        _class_executor("module.campaign.os_run", "OSCampaignRun", method_name="opsi_archive"),
        priority=26,
        config_scopes=OPSI_SCOPES,
    ),
    _task(
        "opsi_stronghold",
        _class_executor("module.campaign.os_run", "OSCampaignRun", method_name="opsi_stronghold"),
        priority=24,
        config_scopes=OPSI_SCOPES,
    ),
    _task(
        "opsi_meowfficer_farming",
        _class_executor("module.campaign.os_run", "OSCampaignRun", method_name="opsi_meowfficer_farming"),
        priority=49,
        config_scopes=OPSI_SCOPES,
    ),
    _task(
        "opsi_hazard1_leveling",
        _class_executor("module.campaign.os_run", "OSCampaignRun", method_name="opsi_hazard1_leveling"),
        priority=51,
        config_scopes=OPSI_SCOPES,
    ),
    _task(
        "opsi_cross_month",
        _class_executor("module.campaign.os_run", "OSCampaignRun", method_name="opsi_cross_month"),
        priority=1,
        config_scopes=OPSI_SCOPES,
    ),
    # 这些入口都是 CampaignRun，只在执行时读取当前战役配置。
    _task("main", _campaign_executor("module.campaign.run", "CampaignRun"), priority=46),
    _task("main2", _campaign_executor("module.campaign.run", "CampaignRun"), priority=47),
    _task("main3", _campaign_executor("module.campaign.run", "CampaignRun"), priority=48),
    _task("event", _campaign_executor("module.campaign.run", "CampaignRun"), priority=41, config_scopes=EVENT_SCOPES),
    _task("event2", _campaign_executor("module.campaign.run", "CampaignRun"), priority=42, config_scopes=EVENT_SCOPES),
    _task("c72_mystery_farming", _campaign_executor("module.campaign.run", "CampaignRun"), priority=None),
    _task("c122_medium_leveling", _campaign_executor("module.campaign.run", "CampaignRun"), priority=None),
    _task("c124_large_leveling", _campaign_executor("module.campaign.run", "CampaignRun"), priority=None),
    _task("war_archives", _campaign_executor("module.war_archives.war_archives", "CampaignWarArchives"), priority=39),
    _task(
        "gems_farming",
        _campaign_executor("module.campaign.gems_farming", "GemsFarming"),
        priority=50,
        config_scopes=EVENT_SCOPES,
    ),
    # WebUI 工具保留原任务名绑定，但只允许直接启动。
    _task(
        "daemon",
        _class_executor("module.daemon.daemon", "AzurLaneDaemon", task_name="Daemon"),
        priority=None,
        launch_mode="direct",
    ),
    _task(
        "opsi_daemon",
        _class_executor("module.daemon.os_daemon", "AzurLaneDaemon", task_name="OpsiDaemon"),
        priority=None,
        config_scopes=OPSI_SCOPES,
        launch_mode="direct",
    ),
    _task(
        "event_story",
        _class_executor("module.eventstory.eventstory", "EventStory", task_name="EventStory"),
        priority=None,
        config_scopes=EVENT_SCOPES,
        launch_mode="direct",
    ),
    _task(
        "azur_lane_uncensored",
        _class_executor("module.daemon.uncensored", "AzurLaneUncensored", task_name="AzurLaneUncensored"),
        priority=None,
        launch_mode="direct",
    ),
    _task(
        "game_manager",
        _class_executor("module.daemon.game_manager", "GameManager", task_name="GameManager"),
        priority=None,
        launch_mode="direct",
    ),
    _task(
        "benchmark",
        FunctionTaskExecutor(module_name="module.daemon.benchmark", function_name="run_benchmark"),
        priority=None,
        launch_mode="direct",
    ),
)

# 兼容旧名字；与 catalog 共用同一只读映射，不维护第二份目录。
TASK_REGISTRY = TASK_CATALOG


def get_task_spec(command: str) -> TaskDefinition | None:
    return TASK_CATALOG.get(command)


def get_task_by_config_name(config_name: str) -> TaskDefinition | None:
    command = config_name_to_command(config_name)
    definition = get_task_spec(command)
    if definition is None or definition.config_name != config_name:
        return None
    return definition


def get_direct_task_command(config_name: str) -> str | None:
    definition = get_task_by_config_name(config_name)
    if definition is None or definition.launch_mode not in {"direct", "both"}:
        return None
    return definition.command


def _scheduler_priority_filter() -> str:
    definitions = sorted(
        (definition for definition in TASK_CATALOG.values() if definition.priority is not None),
        key=lambda definition: definition.priority,
    )
    return "\n".join(
        definition.config_name if index == 0 else f"> {definition.config_name}"
        for index, definition in enumerate(definitions)
    )


SCHEDULER_PRIORITY_FILTER = _scheduler_priority_filter()
