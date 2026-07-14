import re
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import TYPE_CHECKING

from module.application import ExecutionMode
from module.base.naming import camel_to_snake

if TYPE_CHECKING:
    from collections.abc import Mapping


class LaunchSurface(StrEnum):
    SCHEDULER = "scheduler"
    TOOL = "tool"


class TaskDomain(StrEnum):
    CAMPAIGN = "campaign"
    ENCOUNTER = "encounter"
    EXERCISE = "exercise"
    OPSI = "opsi"
    FACILITY = "facility"
    MARKET = "market"
    COMPOSITE_DAILY = "composite_daily"
    ACTIVITY = "activity"
    ASSIST = "assist"
    MAINTENANCE = "maintenance"


SCHEDULER_LAUNCHES = frozenset({LaunchSurface.SCHEDULER})
TOOL_LAUNCHES = frozenset({LaunchSurface.TOOL})


TASK_COMMAND_PATTERN = re.compile(r"[a-z][a-z0-9]*(?:_[a-z][a-z0-9]*)*", flags=re.ASCII)


@dataclass(frozen=True, slots=True)
class TaskDefinition:
    command: str
    config_scopes: tuple[str, ...]
    priority: int | None
    domain: TaskDomain
    execution_mode: ExecutionMode
    allowed_launches: frozenset[LaunchSurface]

    def __post_init__(self) -> None:
        self._validate_command()
        self._validate_config_scopes()
        self._validate_priority()
        self._validate_domain()
        self._validate_execution_mode()
        self._validate_allowed_launches()

    def _validate_command(self) -> None:
        if not isinstance(self.command, str):
            message = f"task command must be a string: {self.command!r}"
            raise TypeError(message)
        if TASK_COMMAND_PATTERN.fullmatch(self.command) is None:
            message = f"invalid task command: {self.command!r}"
            raise ValueError(message)

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

    def _validate_domain(self) -> None:
        if not isinstance(self.domain, TaskDomain):
            message = f"task domain must be a TaskDomain: {self.command}"
            raise TypeError(message)

    def _validate_execution_mode(self) -> None:
        if not isinstance(self.execution_mode, ExecutionMode):
            message = f"execution mode must be an ExecutionMode: {self.command}"
            raise TypeError(message)

    def _validate_allowed_launches(self) -> None:
        if not isinstance(self.allowed_launches, frozenset):
            message = f"allowed launches must be a frozenset: {self.command}"
            raise TypeError(message)
        if not self.allowed_launches:
            message = f"allowed launches must not be empty: {self.command}"
            raise ValueError(message)
        if any(not isinstance(surface, LaunchSurface) for surface in self.allowed_launches):
            message = f"allowed launches must contain only LaunchSurface values: {self.command}"
            raise TypeError(message)

    @property
    def config_name(self) -> str:
        return command_to_config_name(self.command)


def command_to_config_name(command: str) -> str:
    if not isinstance(command, str):
        message = f"task command must be a string: {command!r}"
        raise TypeError(message)
    if TASK_COMMAND_PATTERN.fullmatch(command) is None:
        message = f"invalid task command: {command!r}"
        raise ValueError(message)
    return "".join(part.capitalize() for part in command.split("_"))


def config_name_to_command(config_name: str) -> str:
    return camel_to_snake(config_name)


def _task(  # noqa: PLR0913 - 目录项的独立元数据轴必须在定义处显式可见。
    command: str,
    *,
    domain: TaskDomain,
    execution_mode: ExecutionMode,
    priority: int | None,
    config_scopes: tuple[str, ...] = (),
    allowed_launches: frozenset[LaunchSurface] = SCHEDULER_LAUNCHES,
) -> TaskDefinition:
    return TaskDefinition(
        command=command,
        config_scopes=config_scopes,
        priority=priority,
        domain=domain,
        execution_mode=execution_mode,
        allowed_launches=allowed_launches,
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
    _task(
        "restart",
        domain=TaskDomain.MAINTENANCE,
        execution_mode=ExecutionMode.SCHEDULED_JOB,
        priority=0,
    ),
    _task(
        "research",
        domain=TaskDomain.FACILITY,
        execution_mode=ExecutionMode.SCHEDULED_JOB,
        priority=4,
    ),
    _task(
        "commission",
        domain=TaskDomain.FACILITY,
        execution_mode=ExecutionMode.SCHEDULED_JOB,
        priority=2,
    ),
    _task(
        "tactical",
        domain=TaskDomain.FACILITY,
        execution_mode=ExecutionMode.SCHEDULED_JOB,
        priority=3,
    ),
    _task(
        "dorm",
        domain=TaskDomain.COMPOSITE_DAILY,
        execution_mode=ExecutionMode.SCHEDULED_JOB,
        priority=6,
    ),
    _task(
        "meowfficer",
        domain=TaskDomain.COMPOSITE_DAILY,
        execution_mode=ExecutionMode.SCHEDULED_JOB,
        priority=7,
    ),
    _task(
        "guild",
        domain=TaskDomain.COMPOSITE_DAILY,
        execution_mode=ExecutionMode.SCHEDULED_JOB,
        priority=8,
    ),
    _task(
        "reward",
        domain=TaskDomain.COMPOSITE_DAILY,
        execution_mode=ExecutionMode.SCHEDULED_JOB,
        priority=10,
    ),
    _task(
        "awaken",
        domain=TaskDomain.MARKET,
        execution_mode=ExecutionMode.SCHEDULED_JOB,
        priority=18,
    ),
    _task(
        "shipyard",
        domain=TaskDomain.MARKET,
        execution_mode=ExecutionMode.SCHEDULED_JOB,
        priority=13,
    ),
    _task(
        "gacha",
        domain=TaskDomain.MARKET,
        execution_mode=ExecutionMode.SCHEDULED_JOB,
        priority=9,
    ),
    _task(
        "freebies",
        domain=TaskDomain.COMPOSITE_DAILY,
        execution_mode=ExecutionMode.SCHEDULED_JOB,
        priority=14,
    ),
    _task(
        "minigame",
        domain=TaskDomain.ACTIVITY,
        execution_mode=ExecutionMode.SCHEDULED_JOB,
        priority=17,
    ),
    _task(
        "private_quarters",
        domain=TaskDomain.COMPOSITE_DAILY,
        execution_mode=ExecutionMode.SCHEDULED_JOB,
        priority=15,
    ),
    _task(
        "daily",
        domain=TaskDomain.ENCOUNTER,
        execution_mode=ExecutionMode.SCHEDULED_JOB,
        priority=27,
    ),
    _task(
        "hard",
        domain=TaskDomain.CAMPAIGN,
        execution_mode=ExecutionMode.SCHEDULED_JOB,
        priority=28,
    ),
    _task(
        "exercise",
        domain=TaskDomain.EXERCISE,
        execution_mode=ExecutionMode.SCHEDULED_JOB,
        priority=5,
    ),
    _task(
        "raid_daily",
        domain=TaskDomain.ENCOUNTER,
        execution_mode=ExecutionMode.SCHEDULED_JOB,
        priority=36,
        config_scopes=EVENT_SCOPES,
    ),
    _task(
        "event_sp",
        domain=TaskDomain.CAMPAIGN,
        execution_mode=ExecutionMode.SCHEDULED_JOB,
        priority=31,
        config_scopes=EVENT_SCOPES,
    ),
    _task(
        "maritime_escort",
        domain=TaskDomain.ENCOUNTER,
        execution_mode=ExecutionMode.SCHEDULED_JOB,
        priority=39,
        config_scopes=EVENT_SCOPES,
    ),
    _task(
        "opsi_ash_assist",
        domain=TaskDomain.OPSI,
        execution_mode=ExecutionMode.SCHEDULED_JOB,
        priority=29,
        config_scopes=OPSI_SCOPES,
    ),
    _task(
        "opsi_ash_beacon",
        domain=TaskDomain.OPSI,
        execution_mode=ExecutionMode.SCHEDULED_JOB,
        priority=19,
        config_scopes=OPSI_SCOPES,
    ),
    _task(
        "raid",
        domain=TaskDomain.ENCOUNTER,
        execution_mode=ExecutionMode.SCHEDULED_JOB,
        priority=42,
        config_scopes=EVENT_SCOPES,
    ),
    _task(
        "hospital",
        domain=TaskDomain.ENCOUNTER,
        execution_mode=ExecutionMode.SCHEDULED_JOB,
        priority=43,
    ),
    _task(
        "coalition",
        domain=TaskDomain.ENCOUNTER,
        execution_mode=ExecutionMode.SCHEDULED_JOB,
        priority=44,
        config_scopes=EVENT_SCOPES,
    ),
    _task(
        "coalition_sp",
        domain=TaskDomain.ENCOUNTER,
        execution_mode=ExecutionMode.SCHEDULED_JOB,
        priority=37,
        config_scopes=EVENT_SCOPES,
    ),
    _task(
        "shop_frequent",
        domain=TaskDomain.MARKET,
        execution_mode=ExecutionMode.SCHEDULED_JOB,
        priority=11,
    ),
    _task(
        "shop_once",
        domain=TaskDomain.MARKET,
        execution_mode=ExecutionMode.SCHEDULED_JOB,
        priority=12,
    ),
    _task(
        "event_a",
        domain=TaskDomain.CAMPAIGN,
        execution_mode=ExecutionMode.SCHEDULED_JOB,
        priority=32,
        config_scopes=EVENT_SCOPES,
    ),
    _task(
        "event_b",
        domain=TaskDomain.CAMPAIGN,
        execution_mode=ExecutionMode.SCHEDULED_JOB,
        priority=33,
        config_scopes=EVENT_SCOPES,
    ),
    _task(
        "event_c",
        domain=TaskDomain.CAMPAIGN,
        execution_mode=ExecutionMode.SCHEDULED_JOB,
        priority=34,
        config_scopes=EVENT_SCOPES,
    ),
    _task(
        "event_d",
        domain=TaskDomain.CAMPAIGN,
        execution_mode=ExecutionMode.SCHEDULED_JOB,
        priority=35,
        config_scopes=EVENT_SCOPES,
    ),
    _task(
        "opsi_explore",
        domain=TaskDomain.OPSI,
        execution_mode=ExecutionMode.SCHEDULED_JOB,
        priority=16,
        config_scopes=OPSI_SCOPES,
    ),
    _task(
        "opsi_shop",
        domain=TaskDomain.OPSI,
        execution_mode=ExecutionMode.SCHEDULED_JOB,
        priority=21,
        config_scopes=OPSI_SCOPES,
    ),
    _task(
        "opsi_voucher",
        domain=TaskDomain.OPSI,
        execution_mode=ExecutionMode.SCHEDULED_JOB,
        priority=22,
        config_scopes=OPSI_SCOPES,
    ),
    _task(
        "opsi_daily",
        domain=TaskDomain.OPSI,
        execution_mode=ExecutionMode.SCHEDULED_JOB,
        priority=20,
        config_scopes=OPSI_SCOPES,
    ),
    _task(
        "opsi_obscure",
        domain=TaskDomain.OPSI,
        execution_mode=ExecutionMode.SCHEDULED_JOB,
        priority=25,
        config_scopes=OPSI_SCOPES,
    ),
    _task(
        "opsi_month_boss",
        domain=TaskDomain.OPSI,
        execution_mode=ExecutionMode.SCHEDULED_JOB,
        priority=30,
        config_scopes=OPSI_SCOPES,
    ),
    _task(
        "opsi_abyssal",
        domain=TaskDomain.OPSI,
        execution_mode=ExecutionMode.SCHEDULED_JOB,
        priority=23,
        config_scopes=OPSI_SCOPES,
    ),
    _task(
        "opsi_archive",
        domain=TaskDomain.OPSI,
        execution_mode=ExecutionMode.SCHEDULED_JOB,
        priority=26,
        config_scopes=OPSI_SCOPES,
    ),
    _task(
        "opsi_stronghold",
        domain=TaskDomain.OPSI,
        execution_mode=ExecutionMode.SCHEDULED_JOB,
        priority=24,
        config_scopes=OPSI_SCOPES,
    ),
    _task(
        "opsi_meowfficer_farming",
        domain=TaskDomain.OPSI,
        execution_mode=ExecutionMode.SCHEDULED_JOB,
        priority=48,
        config_scopes=OPSI_SCOPES,
    ),
    _task(
        "opsi_hazard1_leveling",
        domain=TaskDomain.OPSI,
        execution_mode=ExecutionMode.SCHEDULED_JOB,
        priority=50,
        config_scopes=OPSI_SCOPES,
    ),
    _task(
        "opsi_cross_month",
        domain=TaskDomain.OPSI,
        execution_mode=ExecutionMode.SCHEDULED_JOB,
        priority=1,
        config_scopes=OPSI_SCOPES,
    ),
    _task(
        "main",
        domain=TaskDomain.CAMPAIGN,
        execution_mode=ExecutionMode.SCHEDULED_JOB,
        priority=45,
    ),
    _task(
        "main2",
        domain=TaskDomain.CAMPAIGN,
        execution_mode=ExecutionMode.SCHEDULED_JOB,
        priority=46,
    ),
    _task(
        "main3",
        domain=TaskDomain.CAMPAIGN,
        execution_mode=ExecutionMode.SCHEDULED_JOB,
        priority=47,
    ),
    _task(
        "event",
        domain=TaskDomain.CAMPAIGN,
        execution_mode=ExecutionMode.SCHEDULED_JOB,
        priority=40,
        config_scopes=EVENT_SCOPES,
    ),
    _task(
        "event2",
        domain=TaskDomain.CAMPAIGN,
        execution_mode=ExecutionMode.SCHEDULED_JOB,
        priority=41,
        config_scopes=EVENT_SCOPES,
    ),
    _task(
        "war_archives",
        domain=TaskDomain.CAMPAIGN,
        execution_mode=ExecutionMode.SCHEDULED_JOB,
        priority=38,
    ),
    _task(
        "gems_farming",
        domain=TaskDomain.CAMPAIGN,
        execution_mode=ExecutionMode.SCHEDULED_JOB,
        priority=49,
        config_scopes=EVENT_SCOPES,
    ),
    _task(
        "daemon",
        domain=TaskDomain.ASSIST,
        execution_mode=ExecutionMode.ASSIST_SESSION,
        priority=None,
        allowed_launches=TOOL_LAUNCHES,
    ),
    _task(
        "opsi_daemon",
        domain=TaskDomain.ASSIST,
        execution_mode=ExecutionMode.ASSIST_SESSION,
        priority=None,
        config_scopes=OPSI_SCOPES,
        allowed_launches=TOOL_LAUNCHES,
    ),
    _task(
        "event_story",
        domain=TaskDomain.ACTIVITY,
        execution_mode=ExecutionMode.DIRECT_COMMAND,
        priority=None,
        config_scopes=EVENT_SCOPES,
        allowed_launches=TOOL_LAUNCHES,
    ),
    _task(
        "azur_lane_uncensored",
        domain=TaskDomain.MAINTENANCE,
        execution_mode=ExecutionMode.DIRECT_COMMAND,
        priority=None,
        allowed_launches=TOOL_LAUNCHES,
    ),
    _task(
        "game_manager",
        domain=TaskDomain.MAINTENANCE,
        execution_mode=ExecutionMode.DIRECT_COMMAND,
        priority=None,
        allowed_launches=TOOL_LAUNCHES,
    ),
    _task(
        "benchmark",
        domain=TaskDomain.MAINTENANCE,
        execution_mode=ExecutionMode.DIRECT_COMMAND,
        priority=None,
        allowed_launches=TOOL_LAUNCHES,
    ),
)


def get_task_definition(command: str) -> TaskDefinition | None:
    return TASK_CATALOG.get(command)


def get_task_by_config_name(config_name: str) -> TaskDefinition | None:
    command = config_name_to_command(config_name)
    definition = get_task_definition(command)
    if definition is None or definition.config_name != config_name:
        return None
    return definition


def get_tool_task_command(config_name: str) -> str | None:
    definition = get_task_by_config_name(config_name)
    if definition is None or LaunchSurface.TOOL not in definition.allowed_launches:
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
