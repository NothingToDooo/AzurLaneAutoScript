from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING

from module.application import TaskId
from module.gameplay.opsi import (
    WORLD_TASK_DEFINITIONS,
    AbyssalSettings,
    ArchiveSettings,
    AshAssistSettings,
    AshBeaconSettings,
    CrossMonthSettings,
    ExploreSettings,
    Hazard1LevelingSettings,
    MeowfficerFarmingSettings,
    MonthBossSettings,
    ObscureSettings,
    OperationSirenTask,
    OperationSirenWorkflow,
    OpsiDailySettings,
    ShopSettings,
    StrongholdSettings,
    VoucherSettings,
    WorldCheckpointMode,
    WorldOperation,
    WorldProgress,
    WorldTaskSettings,
    create_operation_siren_task,
)
from module.gameplay.opsi_progress import hydrate_world_progress
from module.runtime import (
    FactoryCoverageError,
    TaskBuildContext,
    TaskStateDocumentError,
    require_task_settings,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

    from module.runtime import TaskFactory


def _require_execute(value: object, *, field_name: str) -> None:
    if isinstance(value, type) or not callable(getattr(value, "execute", None)):
        message = f"{field_name} must implement execute()"
        raise TypeError(message)


@dataclass(frozen=True, slots=True)
class OpsiWorkflows:
    world: OperationSirenWorkflow

    def __post_init__(self) -> None:
        _require_execute(self.world, field_name="world")


def _task(
    task_id: str,
    workflow: OperationSirenWorkflow,
    settings: WorldTaskSettings,
    progress: WorldProgress | None,
) -> OperationSirenTask:
    return create_operation_siren_task(TaskId(task_id), workflow, settings, progress)


class _OpsiTaskFactory:
    __slots__ = ("_operation", "_settings_type", "_workflow")

    def __init__(
        self,
        operation: WorldOperation,
        workflow: OperationSirenWorkflow,
        settings_type: type[WorldTaskSettings],
    ) -> None:
        self._operation = operation
        self._workflow = workflow
        self._settings_type = settings_type

    def build(self, context: TaskBuildContext) -> OperationSirenTask:
        if not isinstance(context, TaskBuildContext):
            message = "context must be a TaskBuildContext"
            raise TypeError(message)
        if context.spec.command != self._operation.value:
            message = "TaskBuildContext spec does not match Operation Siren factory"
            raise ValueError(message)
        settings = require_task_settings(context, self._settings_type)

        definition = WORLD_TASK_DEFINITIONS[TaskId(self._operation.value)]
        if definition.checkpoint_mode is WorldCheckpointMode.ONE_SHOT:
            if context.task_state.entries:
                message = f"one-shot operation must not contain task state: {self._operation.value}"
                raise TaskStateDocumentError(message)
            progress = None
        else:
            progress = hydrate_world_progress(self._operation, context.task_state)
        return _task(self._operation.value, self._workflow, settings, progress)


def _factory(
    operation: WorldOperation,
    workflow: OperationSirenWorkflow,
    settings_type: type[WorldTaskSettings],
) -> _OpsiTaskFactory:
    return _OpsiTaskFactory(operation, workflow, settings_type)


def build_opsi_factories(workflows: OpsiWorkflows) -> Mapping[str, TaskFactory]:
    if not isinstance(workflows, OpsiWorkflows):
        message = "workflows must be OpsiWorkflows"
        raise TypeError(message)
    factories: dict[str, TaskFactory] = {
        "opsi_ash_assist": _factory(WorldOperation.ASH_ASSIST, workflows.world, AshAssistSettings),
        "opsi_ash_beacon": _factory(WorldOperation.ASH_BEACON, workflows.world, AshBeaconSettings),
        "opsi_explore": _factory(WorldOperation.EXPLORE, workflows.world, ExploreSettings),
        "opsi_shop": _factory(WorldOperation.SHOP, workflows.world, ShopSettings),
        "opsi_voucher": _factory(WorldOperation.VOUCHER, workflows.world, VoucherSettings),
        "opsi_daily": _factory(WorldOperation.DAILY, workflows.world, OpsiDailySettings),
        "opsi_obscure": _factory(WorldOperation.OBSCURE, workflows.world, ObscureSettings),
        "opsi_month_boss": _factory(WorldOperation.MONTH_BOSS, workflows.world, MonthBossSettings),
        "opsi_abyssal": _factory(WorldOperation.ABYSSAL, workflows.world, AbyssalSettings),
        "opsi_archive": _factory(WorldOperation.ARCHIVE, workflows.world, ArchiveSettings),
        "opsi_stronghold": _factory(WorldOperation.STRONGHOLD, workflows.world, StrongholdSettings),
        "opsi_meowfficer_farming": _factory(
            WorldOperation.MEOWFFICER_FARMING,
            workflows.world,
            MeowfficerFarmingSettings,
        ),
        "opsi_hazard1_leveling": _factory(
            WorldOperation.HAZARD1_LEVELING,
            workflows.world,
            Hazard1LevelingSettings,
        ),
        "opsi_cross_month": _factory(WorldOperation.CROSS_MONTH, workflows.world, CrossMonthSettings),
    }
    expected = {task_id.value for task_id in WORLD_TASK_DEFINITIONS}
    if set(factories) != expected:
        missing = sorted(expected - set(factories))
        unknown = sorted(set(factories) - expected)
        message = f"OpSi factory coverage mismatch: missing={missing}, unknown={unknown}"
        raise FactoryCoverageError(message)
    return MappingProxyType(factories)
