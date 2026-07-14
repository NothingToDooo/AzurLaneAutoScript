from collections.abc import Mapping
from dataclasses import dataclass
from datetime import timedelta
from types import MappingProxyType
from typing import TYPE_CHECKING, cast

from module.gameplay.encounter import (
    EXERCISE_PROGRESS_KEY,
    EXERCISE_PROGRESS_SCHEMA_VERSION,
    DailyMissionPlan,
    DailyMissionPlans,
    DailySettings,
    DailyStageSelection,
    DailyTask,
    ExerciseOpponentMode,
    ExerciseProgress,
    ExerciseSettings,
    ExerciseStrategy,
    ExerciseTask,
    HardFleet,
    HardSettings,
    HardTask,
)
from module.runtime import (
    SettingsDecoder,
    SettingsDocumentError,
    TaskBuildContext,
    TaskStateDocumentError,
    TypedTaskFactory,
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


def _duration(decoder: SettingsDecoder, name: str) -> timedelta:
    return timedelta(seconds=decoder.integer(name, minimum=1))


def _daily_settings(decoder: SettingsDecoder) -> DailySettings:
    schedule = decoder.daily_schedule("schedule")
    use_daily_skip = decoder.boolean("use_daily_skip")
    missions = decoder.object("missions")

    def mission(name: str, *, fleet_required: bool) -> DailyMissionPlan:
        plan = missions.object(name)
        fleet = plan.integer("fleet", minimum=1, maximum=6) if fleet_required else plan.nullable_integer("fleet")
        result = DailyMissionPlan(
            stage=plan.enum("stage", DailyStageSelection),
            fleet=fleet,
        )
        plan.finish()
        return result

    plans = DailyMissionPlans(
        escort=mission("escort", fleet_required=True),
        advance=mission("advance", fleet_required=True),
        fierce_assault=mission("fierce_assault", fleet_required=True),
        tactical_training=mission("tactical_training", fleet_required=True),
        supply_line_disruption=mission("supply_line_disruption", fleet_required=False),
        module_development=mission("module_development", fleet_required=True),
        emergency_module_development=mission("emergency_module_development", fleet_required=True),
    )
    missions.finish()
    return DailySettings(
        schedule=schedule,
        use_daily_skip=use_daily_skip,
        missions=plans,
    )


def _hard_settings(decoder: SettingsDecoder) -> HardSettings:
    return HardSettings(
        schedule=decoder.daily_schedule("schedule"),
        failure_retry_delay=decoder.delay_range("failure_retry_seconds"),
        resource_retry_delay=_duration(decoder, "resource_retry_seconds"),
        stage=decoder.string("stage"),
        fleet=HardFleet(decoder.integer("fleet", minimum=1, maximum=2)),
    )


def _exercise_settings(decoder: SettingsDecoder) -> ExerciseSettings:
    return ExerciseSettings(
        schedule=decoder.daily_schedule("schedule"),
        failure_retry_delay=decoder.delay_range("failure_retry_seconds"),
        opponent_refresh_limit=decoder.integer("opponent_refresh_limit", minimum=1),
        opponent_mode=decoder.enum("opponent_mode", ExerciseOpponentMode),
        opponent_trials=decoder.integer("opponent_trials", minimum=1),
        strategy=decoder.enum("strategy", ExerciseStrategy),
        low_hp_threshold=decoder.number("low_hp_threshold", minimum=0, maximum=1),
        low_hp_confirm_wait_seconds=decoder.number("low_hp_confirm_wait_seconds", minimum=0),
    )


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
        decoder = SettingsDecoder(context.settings, path=f"$.tasks.{context.definition.command}")
        settings = _exercise_settings(decoder)
        decoder.finish()
        return ExerciseTask(self._workflow, settings, _exercise_progress(context))


def build_encounter_factories(workflows: EncounterWorkflows) -> Mapping[str, TaskFactory]:
    if not isinstance(workflows, EncounterWorkflows):
        message = "workflows must be EncounterWorkflows"
        raise TypeError(message)
    factories: dict[str, TaskFactory] = {
        "daily": TypedTaskFactory(_daily_settings, lambda settings: DailyTask(workflows.daily, settings)),
        "hard": TypedTaskFactory(_hard_settings, lambda settings: HardTask(workflows.hard, settings)),
        "exercise": _ExerciseFactory(workflows.exercise),
    }
    return MappingProxyType(factories)
