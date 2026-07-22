from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING, cast

from module.gameplay.composite import (
    DORM_FURNITURE_CHECK_KEY,
    DORM_FURNITURE_CHECK_SCHEMA_VERSION,
    DataKeyWorkflow,
    DormSettings,
    DormTask,
    FreebiesSettings,
    FreebiesTask,
    GuildSettings,
    GuildTask,
    MeowfficerSettings,
    MeowfficerTask,
    PrivateQuartersSettings,
    PrivateQuartersTask,
    RewardSettings,
    RewardTask,
)
from module.runtime import (
    ConfiguredTaskFactory,
    SettingsDecoder,
    SettingsDocumentError,
    TaskBuildContext,
    TaskStateDocumentError,
    require_task_settings,
)

if TYPE_CHECKING:
    from datetime import datetime

    from module.gameplay.composite import (
        DormWorkflow,
        FreebieCollectionWorkflow,
        GuildWorkflow,
        MailCollectionWorkflow,
        MeowfficerWorkflow,
        PrivateQuartersWorkflow,
        RewardWorkflow,
        SupplyPackWorkflow,
    )
    from module.runtime import FrozenTaskSettings, TaskFactory


def _require_method(value: object, method: str, *, field_name: str) -> None:
    if isinstance(value, type) or not callable(getattr(value, method, None)):
        message = f"{field_name} must implement {method}()"
        raise TypeError(message)


@dataclass(frozen=True, slots=True)
class CompositeWorkflows:
    dorm: DormWorkflow
    meowfficer: MeowfficerWorkflow
    guild: GuildWorkflow
    reward: RewardWorkflow
    battle_pass: FreebieCollectionWorkflow
    data_key: DataKeyWorkflow
    mail: MailCollectionWorkflow
    supply_pack: SupplyPackWorkflow
    private_quarters: PrivateQuartersWorkflow

    def __post_init__(self) -> None:
        for field_name in ("dorm", "meowfficer", "guild", "reward", "private_quarters"):
            _require_method(getattr(self, field_name), "execute", field_name=field_name)
        for field_name in ("battle_pass", "data_key", "mail", "supply_pack"):
            _require_method(getattr(self, field_name), "collect", field_name=field_name)


def _dorm_last_furniture_check(context: TaskBuildContext) -> datetime | None:
    unknown = sorted(set(context.task_state.entries) - {DORM_FURNITURE_CHECK_KEY})
    if unknown:
        message = f"unknown dorm task state keys: {unknown}"
        raise TaskStateDocumentError(message)
    entry = context.task_state.get(DORM_FURNITURE_CHECK_KEY)
    if entry is None:
        return None
    if entry.schema_version != DORM_FURNITURE_CHECK_SCHEMA_VERSION:
        message = (
            f"$.task_state.{DORM_FURNITURE_CHECK_KEY} schema version must be {DORM_FURNITURE_CHECK_SCHEMA_VERSION}"
        )
        raise TaskStateDocumentError(message)
    if not isinstance(entry.payload, Mapping):
        message = f"$.task_state.{DORM_FURNITURE_CHECK_KEY} must be an object"
        raise TaskStateDocumentError(message)
    try:
        decoder = SettingsDecoder(
            cast("FrozenTaskSettings", entry.payload),
            path=f"$.task_state.{DORM_FURNITURE_CHECK_KEY}",
        )
        checked_at = decoder.datetime("checked_at")
        decoder.finish()
    except (SettingsDocumentError, TypeError, ValueError) as error:
        message = f"invalid dorm furniture checkpoint: {error}"
        raise TaskStateDocumentError(message) from error
    return checked_at


class _DormTaskFactory:
    __slots__ = ("_workflow",)

    def __init__(self, workflow: DormWorkflow) -> None:
        self._workflow = workflow

    def build(self, context: TaskBuildContext) -> DormTask:
        if not isinstance(context, TaskBuildContext):
            message = "context must be a TaskBuildContext"
            raise TypeError(message)
        if context.spec.command != "dorm":
            message = "dorm factory requires the 'dorm' task definition"
            raise ValueError(message)
        settings = require_task_settings(context, DormSettings)
        return DormTask(
            self._workflow,
            settings,
            last_furniture_check_at=_dorm_last_furniture_check(context),
        )


def build_composite_factories(workflows: CompositeWorkflows) -> Mapping[str, TaskFactory]:
    if not isinstance(workflows, CompositeWorkflows):
        message = "workflows must be CompositeWorkflows"
        raise TypeError(message)
    factories: dict[str, TaskFactory] = {
        "dorm": _DormTaskFactory(workflows.dorm),
        "meowfficer": ConfiguredTaskFactory(
            MeowfficerSettings,
            lambda settings: MeowfficerTask(workflows.meowfficer, settings),
        ),
        "guild": ConfiguredTaskFactory(GuildSettings, lambda settings: GuildTask(workflows.guild, settings)),
        "reward": ConfiguredTaskFactory(RewardSettings, lambda settings: RewardTask(workflows.reward, settings)),
        "freebies": ConfiguredTaskFactory(
            FreebiesSettings,
            lambda settings: FreebiesTask(
                battle_pass=workflows.battle_pass,
                data_key=workflows.data_key,
                mail=workflows.mail,
                supply_pack=workflows.supply_pack,
                settings=settings,
            ),
        ),
        "private_quarters": ConfiguredTaskFactory(
            PrivateQuartersSettings,
            lambda settings: PrivateQuartersTask(workflows.private_quarters, settings),
        ),
    }
    return MappingProxyType(factories)
