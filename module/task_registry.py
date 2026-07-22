import re
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import TYPE_CHECKING, cast

from module.application import ExecutionMode
from module.base.naming import camel_to_snake

if TYPE_CHECKING:
    from collections.abc import Mapping


TASK_COMMAND_PATTERN = re.compile(r"[a-z][a-z0-9]*(?:_[a-z][a-z0-9]*)*", flags=re.ASCII)


class TaskDomain(StrEnum):
    MAINTENANCE = "maintenance"
    FACILITY = "facility"
    COMPOSITE = "composite"
    MARKET = "market"
    ENCOUNTER = "encounter"
    CAMPAIGN = "campaign"
    OPSI = "opsi"
    ACTIVITY = "activity"


class ContentRevisionPolicy(StrEnum):
    BUILTIN = "builtin"
    EVENT = "event"
    CAMPAIGN = "campaign"


@dataclass(frozen=True, slots=True)
class TaskSpec:
    command: str
    config_scopes: tuple[str, ...]
    priority: int | None
    execution_mode: ExecutionMode
    domain: TaskDomain
    content_revision_policy: ContentRevisionPolicy = ContentRevisionPolicy.BUILTIN

    def __post_init__(self) -> None:
        self._validate_command()
        self._validate_config_scopes()
        self._validate_execution_mode()
        self._validate_priority()
        if not isinstance(self.domain, TaskDomain):
            message = f"task domain must be a TaskDomain: {self.command}"
            raise TypeError(message)
        if not isinstance(self.content_revision_policy, ContentRevisionPolicy):
            message = f"content revision policy must be a ContentRevisionPolicy: {self.command}"
            raise TypeError(message)

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
        if self.execution_mode is ExecutionMode.SCHEDULED_JOB:
            if type(self.priority) is not int:
                message = f"scheduled task priority must be an integer: {self.command}"
                raise TypeError(message)
            if self.priority < 0:
                message = f"task priority must not be negative: {self.command}"
                raise ValueError(message)
            return
        if self.priority is not None:
            message = f"non-scheduled task priority must be None: {self.command}"
            raise ValueError(message)

    def _validate_execution_mode(self) -> None:
        if not isinstance(self.execution_mode, ExecutionMode):
            message = f"execution mode must be an ExecutionMode: {self.command}"
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


# 这里完整镜像 TaskSpec 的声明字段；额外包装 options 只会把静态事实藏深一层。
def _task(  # ruff:ignore[too-many-arguments]
    command: str,
    *,
    execution_mode: ExecutionMode,
    priority: int | None,
    domain: TaskDomain,
    config_scopes: tuple[str, ...] = (),
    content_revision_policy: ContentRevisionPolicy = ContentRevisionPolicy.BUILTIN,
) -> TaskSpec:
    return TaskSpec(
        command=command,
        config_scopes=config_scopes,
        priority=priority,
        execution_mode=execution_mode,
        domain=domain,
        content_revision_policy=content_revision_policy,
    )


def _build_specs(*specs: TaskSpec) -> Mapping[str, TaskSpec]:
    catalog: dict[str, TaskSpec] = {}
    config_names: dict[str, str] = {}
    priorities: set[int] = set()
    for spec in specs:
        if spec.command in catalog:
            message = f"duplicate task command: {spec.command}"
            raise ValueError(message)
        config_name = spec.config_name
        if config_name in config_names:
            message = f"task config name collision: {config_names[config_name]} and {spec.command}"
            raise ValueError(message)
        if spec.priority is not None:
            if spec.priority in priorities:
                message = f"duplicate task priority: {spec.priority}"
                raise ValueError(message)
            priorities.add(spec.priority)
        catalog[spec.command] = spec
        config_names[config_name] = spec.command

    if sorted(priorities) != list(range(len(priorities))):
        message = "task priorities must be contiguous from zero"
        raise ValueError(message)
    return MappingProxyType(catalog)


EVENT_SCOPES = ("TaskBalancer", "EventGeneral")
OPSI_SCOPES = ("OpsiGeneral",)


TASK_SPECS: Mapping[str, TaskSpec] = _build_specs(
    _task(
        "restart",
        execution_mode=ExecutionMode.SCHEDULED_JOB,
        priority=0,
        domain=TaskDomain.MAINTENANCE,
    ),
    _task(
        "research",
        execution_mode=ExecutionMode.SCHEDULED_JOB,
        priority=4,
        domain=TaskDomain.FACILITY,
    ),
    _task(
        "commission",
        execution_mode=ExecutionMode.SCHEDULED_JOB,
        priority=2,
        domain=TaskDomain.FACILITY,
    ),
    _task(
        "tactical",
        execution_mode=ExecutionMode.SCHEDULED_JOB,
        priority=3,
        domain=TaskDomain.FACILITY,
    ),
    _task(
        "dorm",
        execution_mode=ExecutionMode.SCHEDULED_JOB,
        priority=6,
        domain=TaskDomain.COMPOSITE,
    ),
    _task(
        "meowfficer",
        execution_mode=ExecutionMode.SCHEDULED_JOB,
        priority=7,
        domain=TaskDomain.COMPOSITE,
    ),
    _task(
        "guild",
        execution_mode=ExecutionMode.SCHEDULED_JOB,
        priority=8,
        domain=TaskDomain.COMPOSITE,
    ),
    _task(
        "reward",
        execution_mode=ExecutionMode.SCHEDULED_JOB,
        priority=10,
        domain=TaskDomain.COMPOSITE,
    ),
    _task(
        "awaken",
        execution_mode=ExecutionMode.SCHEDULED_JOB,
        priority=18,
        domain=TaskDomain.MARKET,
    ),
    _task(
        "shipyard",
        execution_mode=ExecutionMode.SCHEDULED_JOB,
        priority=13,
        domain=TaskDomain.MARKET,
    ),
    _task(
        "gacha",
        execution_mode=ExecutionMode.SCHEDULED_JOB,
        priority=9,
        domain=TaskDomain.MARKET,
    ),
    _task(
        "freebies",
        execution_mode=ExecutionMode.SCHEDULED_JOB,
        priority=14,
        domain=TaskDomain.COMPOSITE,
    ),
    _task(
        "minigame",
        execution_mode=ExecutionMode.SCHEDULED_JOB,
        priority=17,
        domain=TaskDomain.ACTIVITY,
    ),
    _task(
        "private_quarters",
        execution_mode=ExecutionMode.SCHEDULED_JOB,
        priority=15,
        domain=TaskDomain.COMPOSITE,
    ),
    _task(
        "daily",
        execution_mode=ExecutionMode.SCHEDULED_JOB,
        priority=27,
        domain=TaskDomain.ENCOUNTER,
    ),
    _task(
        "hard",
        execution_mode=ExecutionMode.SCHEDULED_JOB,
        priority=28,
        domain=TaskDomain.ENCOUNTER,
        content_revision_policy=ContentRevisionPolicy.CAMPAIGN,
    ),
    _task(
        "exercise",
        execution_mode=ExecutionMode.SCHEDULED_JOB,
        priority=5,
        domain=TaskDomain.ENCOUNTER,
    ),
    _task(
        "raid_daily",
        execution_mode=ExecutionMode.SCHEDULED_JOB,
        priority=36,
        domain=TaskDomain.ACTIVITY,
        config_scopes=EVENT_SCOPES,
        content_revision_policy=ContentRevisionPolicy.EVENT,
    ),
    _task(
        "event_sp",
        execution_mode=ExecutionMode.SCHEDULED_JOB,
        priority=31,
        domain=TaskDomain.CAMPAIGN,
        config_scopes=EVENT_SCOPES,
        content_revision_policy=ContentRevisionPolicy.CAMPAIGN,
    ),
    _task(
        "maritime_escort",
        execution_mode=ExecutionMode.SCHEDULED_JOB,
        priority=39,
        domain=TaskDomain.ACTIVITY,
        config_scopes=EVENT_SCOPES,
        content_revision_policy=ContentRevisionPolicy.EVENT,
    ),
    _task(
        "opsi_ash_assist",
        execution_mode=ExecutionMode.SCHEDULED_JOB,
        priority=29,
        domain=TaskDomain.OPSI,
        config_scopes=OPSI_SCOPES,
    ),
    _task(
        "opsi_ash_beacon",
        execution_mode=ExecutionMode.SCHEDULED_JOB,
        priority=19,
        domain=TaskDomain.OPSI,
        config_scopes=OPSI_SCOPES,
    ),
    _task(
        "raid",
        execution_mode=ExecutionMode.SCHEDULED_JOB,
        priority=42,
        domain=TaskDomain.ACTIVITY,
        config_scopes=EVENT_SCOPES,
        content_revision_policy=ContentRevisionPolicy.EVENT,
    ),
    _task(
        "hospital",
        execution_mode=ExecutionMode.SCHEDULED_JOB,
        priority=43,
        domain=TaskDomain.ACTIVITY,
        content_revision_policy=ContentRevisionPolicy.EVENT,
    ),
    _task(
        "coalition",
        execution_mode=ExecutionMode.SCHEDULED_JOB,
        priority=44,
        domain=TaskDomain.ACTIVITY,
        config_scopes=EVENT_SCOPES,
        content_revision_policy=ContentRevisionPolicy.EVENT,
    ),
    _task(
        "coalition_sp",
        execution_mode=ExecutionMode.SCHEDULED_JOB,
        priority=37,
        domain=TaskDomain.ACTIVITY,
        config_scopes=EVENT_SCOPES,
        content_revision_policy=ContentRevisionPolicy.EVENT,
    ),
    _task(
        "shop_frequent",
        execution_mode=ExecutionMode.SCHEDULED_JOB,
        priority=11,
        domain=TaskDomain.MARKET,
    ),
    _task(
        "shop_once",
        execution_mode=ExecutionMode.SCHEDULED_JOB,
        priority=12,
        domain=TaskDomain.MARKET,
    ),
    _task(
        "event_a",
        execution_mode=ExecutionMode.SCHEDULED_JOB,
        priority=32,
        domain=TaskDomain.CAMPAIGN,
        config_scopes=EVENT_SCOPES,
        content_revision_policy=ContentRevisionPolicy.CAMPAIGN,
    ),
    _task(
        "event_b",
        execution_mode=ExecutionMode.SCHEDULED_JOB,
        priority=33,
        domain=TaskDomain.CAMPAIGN,
        config_scopes=EVENT_SCOPES,
        content_revision_policy=ContentRevisionPolicy.CAMPAIGN,
    ),
    _task(
        "event_c",
        execution_mode=ExecutionMode.SCHEDULED_JOB,
        priority=34,
        domain=TaskDomain.CAMPAIGN,
        config_scopes=EVENT_SCOPES,
        content_revision_policy=ContentRevisionPolicy.CAMPAIGN,
    ),
    _task(
        "event_d",
        execution_mode=ExecutionMode.SCHEDULED_JOB,
        priority=35,
        domain=TaskDomain.CAMPAIGN,
        config_scopes=EVENT_SCOPES,
        content_revision_policy=ContentRevisionPolicy.CAMPAIGN,
    ),
    _task(
        "opsi_explore",
        execution_mode=ExecutionMode.SCHEDULED_JOB,
        priority=16,
        domain=TaskDomain.OPSI,
        config_scopes=OPSI_SCOPES,
    ),
    _task(
        "opsi_shop",
        execution_mode=ExecutionMode.SCHEDULED_JOB,
        priority=21,
        domain=TaskDomain.OPSI,
        config_scopes=OPSI_SCOPES,
    ),
    _task(
        "opsi_voucher",
        execution_mode=ExecutionMode.SCHEDULED_JOB,
        priority=22,
        domain=TaskDomain.OPSI,
        config_scopes=OPSI_SCOPES,
    ),
    _task(
        "opsi_daily",
        execution_mode=ExecutionMode.SCHEDULED_JOB,
        priority=20,
        domain=TaskDomain.OPSI,
        config_scopes=OPSI_SCOPES,
    ),
    _task(
        "opsi_obscure",
        execution_mode=ExecutionMode.SCHEDULED_JOB,
        priority=25,
        domain=TaskDomain.OPSI,
        config_scopes=OPSI_SCOPES,
    ),
    _task(
        "opsi_month_boss",
        execution_mode=ExecutionMode.SCHEDULED_JOB,
        priority=30,
        domain=TaskDomain.OPSI,
        config_scopes=OPSI_SCOPES,
    ),
    _task(
        "opsi_abyssal",
        execution_mode=ExecutionMode.SCHEDULED_JOB,
        priority=23,
        domain=TaskDomain.OPSI,
        config_scopes=OPSI_SCOPES,
    ),
    _task(
        "opsi_archive",
        execution_mode=ExecutionMode.SCHEDULED_JOB,
        priority=26,
        domain=TaskDomain.OPSI,
        config_scopes=OPSI_SCOPES,
    ),
    _task(
        "opsi_stronghold",
        execution_mode=ExecutionMode.SCHEDULED_JOB,
        priority=24,
        domain=TaskDomain.OPSI,
        config_scopes=OPSI_SCOPES,
    ),
    _task(
        "opsi_meowfficer_farming",
        execution_mode=ExecutionMode.SCHEDULED_JOB,
        priority=48,
        domain=TaskDomain.OPSI,
        config_scopes=OPSI_SCOPES,
    ),
    _task(
        "opsi_hazard1_leveling",
        execution_mode=ExecutionMode.SCHEDULED_JOB,
        priority=50,
        domain=TaskDomain.OPSI,
        config_scopes=OPSI_SCOPES,
    ),
    _task(
        "opsi_cross_month",
        execution_mode=ExecutionMode.SCHEDULED_JOB,
        priority=1,
        domain=TaskDomain.OPSI,
        config_scopes=OPSI_SCOPES,
    ),
    _task(
        "main",
        execution_mode=ExecutionMode.SCHEDULED_JOB,
        priority=45,
        domain=TaskDomain.CAMPAIGN,
        content_revision_policy=ContentRevisionPolicy.CAMPAIGN,
    ),
    _task(
        "main2",
        execution_mode=ExecutionMode.SCHEDULED_JOB,
        priority=46,
        domain=TaskDomain.CAMPAIGN,
        content_revision_policy=ContentRevisionPolicy.CAMPAIGN,
    ),
    _task(
        "main3",
        execution_mode=ExecutionMode.SCHEDULED_JOB,
        priority=47,
        domain=TaskDomain.CAMPAIGN,
        content_revision_policy=ContentRevisionPolicy.CAMPAIGN,
    ),
    _task(
        "event",
        execution_mode=ExecutionMode.SCHEDULED_JOB,
        priority=40,
        domain=TaskDomain.CAMPAIGN,
        config_scopes=EVENT_SCOPES,
        content_revision_policy=ContentRevisionPolicy.CAMPAIGN,
    ),
    _task(
        "event2",
        execution_mode=ExecutionMode.SCHEDULED_JOB,
        priority=41,
        domain=TaskDomain.CAMPAIGN,
        config_scopes=EVENT_SCOPES,
        content_revision_policy=ContentRevisionPolicy.CAMPAIGN,
    ),
    _task(
        "war_archives",
        execution_mode=ExecutionMode.SCHEDULED_JOB,
        priority=38,
        domain=TaskDomain.CAMPAIGN,
        content_revision_policy=ContentRevisionPolicy.CAMPAIGN,
    ),
    _task(
        "gems_farming",
        execution_mode=ExecutionMode.SCHEDULED_JOB,
        priority=49,
        domain=TaskDomain.CAMPAIGN,
        config_scopes=EVENT_SCOPES,
        content_revision_policy=ContentRevisionPolicy.CAMPAIGN,
    ),
    _task(
        "daemon",
        execution_mode=ExecutionMode.ASSIST_SESSION,
        priority=None,
        domain=TaskDomain.ACTIVITY,
    ),
    _task(
        "opsi_daemon",
        execution_mode=ExecutionMode.ASSIST_SESSION,
        priority=None,
        domain=TaskDomain.ACTIVITY,
        config_scopes=OPSI_SCOPES,
    ),
    _task(
        "event_story",
        execution_mode=ExecutionMode.DIRECT_COMMAND,
        priority=None,
        domain=TaskDomain.ACTIVITY,
        config_scopes=EVENT_SCOPES,
        content_revision_policy=ContentRevisionPolicy.EVENT,
    ),
    _task(
        "azur_lane_uncensored",
        execution_mode=ExecutionMode.DIRECT_COMMAND,
        priority=None,
        domain=TaskDomain.MAINTENANCE,
    ),
    _task(
        "game_manager",
        execution_mode=ExecutionMode.DIRECT_COMMAND,
        priority=None,
        domain=TaskDomain.MAINTENANCE,
    ),
    _task(
        "benchmark",
        execution_mode=ExecutionMode.DIRECT_COMMAND,
        priority=None,
        domain=TaskDomain.MAINTENANCE,
    ),
)


def get_task_spec(command: str) -> TaskSpec | None:
    return TASK_SPECS.get(command)


def get_task_by_config_name(config_name: str) -> TaskSpec | None:
    command = config_name_to_command(config_name)
    spec = get_task_spec(command)
    if spec is None or spec.config_name != config_name:
        return None
    return spec


def get_tool_task_command(config_name: str) -> str | None:
    spec = get_task_by_config_name(config_name)
    if spec is None or spec.execution_mode is ExecutionMode.SCHEDULED_JOB:
        return None
    return spec.command


def _scheduler_priority_filter() -> str:
    specs = sorted(
        (spec for spec in TASK_SPECS.values() if spec.priority is not None),
        key=lambda spec: cast("int", spec.priority),
    )
    return "\n".join(spec.config_name if index == 0 else f"> {spec.config_name}" for index, spec in enumerate(specs))


SCHEDULER_PRIORITY_FILTER = _scheduler_priority_filter()
