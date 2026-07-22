from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING, cast

from module.gameplay.encounter import (
    EXERCISE_PROGRESS_KEY,
    EXERCISE_PROGRESS_SCHEMA_VERSION,
    DailySettings,
    DailyTask,
    ExerciseProgress,
    ExerciseSettings,
    ExerciseTask,
    HardSettings,
    HardTask,
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
    from module.gameplay.encounter import DailyWorkflow, ExerciseWorkflow, HardWorkflow
    from module.runtime import FrozenTaskSettings, TaskFactory


def _require_execute(value: object, *, field_name: str) -> None:
    if isinstance(value, type) or not callable(getattr(value, "execute", None)):
        message = f"{field_name} must implement execute()"
        raise TypeError(message)


@dataclass(frozen=True, slots=True)
class EncounterWorkflows:
    daily: DailyWorkflow
    hard: HardWorkflow
    exercise: ExerciseWorkflow

    def __post_init__(self) -> None:
        _require_execute(self.daily, field_name="daily")
        _require_execute(self.hard, field_name="hard")
        _require_execute(self.exercise, field_name="exercise")


def _exercise_progress(context: TaskBuildContext) -> ExerciseProgress:
    unknown = sorted(set(context.task_state.entries) - {EXERCISE_PROGRESS_KEY})
    if unknown:
        message = f"unknown exercise task state keys: {unknown}"
        raise TaskStateDocumentError(message)
    entry = context.task_state.get(EXERCISE_PROGRESS_KEY)
    if entry is None:
        return ExerciseProgress()
    if entry.schema_version != EXERCISE_PROGRESS_SCHEMA_VERSION:
        message = f"$.task_state.{EXERCISE_PROGRESS_KEY} schema version must be {EXERCISE_PROGRESS_SCHEMA_VERSION}"
        raise TaskStateDocumentError(message)
    if not isinstance(entry.payload, Mapping):
        message = f"$.task_state.{EXERCISE_PROGRESS_KEY} must be an object"
        raise TaskStateDocumentError(message)
    try:
        decoder = SettingsDecoder(
            cast("FrozenTaskSettings", entry.payload),
            path=f"$.task_state.{EXERCISE_PROGRESS_KEY}",
        )
        progress = ExerciseProgress(decoder.integer("opponent_refreshes_used", minimum=0))
        decoder.finish()
    except (SettingsDocumentError, TypeError, ValueError) as error:
        message = f"invalid exercise progress checkpoint: {error}"
        raise TaskStateDocumentError(message) from error
    return progress


class _ExerciseFactory:
    __slots__ = ("_workflow",)

    def __init__(self, workflow: ExerciseWorkflow) -> None:
        self._workflow = workflow

    def build(self, context: TaskBuildContext) -> ExerciseTask:
        settings = require_task_settings(context, ExerciseSettings)
        return ExerciseTask(self._workflow, settings, _exercise_progress(context))


def build_encounter_factories(workflows: EncounterWorkflows) -> Mapping[str, TaskFactory]:
    if not isinstance(workflows, EncounterWorkflows):
        message = "workflows must be EncounterWorkflows"
        raise TypeError(message)
    factories: dict[str, TaskFactory] = {
        "daily": ConfiguredTaskFactory(DailySettings, lambda settings: DailyTask(workflows.daily, settings)),
        "hard": ConfiguredTaskFactory(HardSettings, lambda settings: HardTask(workflows.hard, settings)),
        "exercise": _ExerciseFactory(workflows.exercise),
    }
    return MappingProxyType(factories)
