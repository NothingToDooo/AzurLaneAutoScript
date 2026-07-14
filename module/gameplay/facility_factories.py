from dataclasses import dataclass
from datetime import timedelta
from types import MappingProxyType
from typing import TYPE_CHECKING

from module.gameplay.facility import (
    CommissionPreset,
    CommissionSelectionPolicy,
    CommissionSettings,
    CommissionTask,
    ResearchResourcePolicy,
    ResearchSelectionPolicy,
    ResearchSettings,
    ResearchTask,
    TacticalExperienceOverflowPolicy,
    TacticalRapidTrainingSlot,
    TacticalSettings,
    TacticalStudentPolicy,
    TacticalTask,
)
from module.runtime import SettingsDecoder, TypedTaskFactory

if TYPE_CHECKING:
    from collections.abc import Mapping

    from module.gameplay.facility import CommissionWorkflow, ResearchWorkflow, TacticalWorkflow
    from module.runtime import TaskFactory


def _require_execute(value: object, *, field_name: str) -> None:
    if isinstance(value, type) or not callable(getattr(value, "execute", None)):
        message = f"{field_name} must implement execute()"
        raise TypeError(message)


@dataclass(frozen=True, slots=True)
class FacilityWorkflows:
    research: ResearchWorkflow
    commission: CommissionWorkflow
    tactical: TacticalWorkflow

    def __post_init__(self) -> None:
        _require_execute(self.research, field_name="research")
        _require_execute(self.commission, field_name="commission")
        _require_execute(self.tactical, field_name="tactical")


def _research_settings(decoder: SettingsDecoder) -> ResearchSettings:
    schedule = decoder.daily_schedule("schedule")
    selection = decoder.object("selection")
    settings = ResearchSettings(
        schedule=schedule,
        selection=ResearchSelectionPolicy(
            use_cube=selection.enum("use_cube", ResearchResourcePolicy),
            use_coin=selection.enum("use_coin", ResearchResourcePolicy),
            use_part=selection.enum("use_part", ResearchResourcePolicy),
            allow_delay=selection.boolean("allow_delay"),
            preset_filter=selection.string("preset_filter"),
            custom_filter=selection.string("custom_filter"),
        ),
    )
    selection.finish()
    return settings


def _commission_settings(decoder: SettingsDecoder) -> CommissionSettings:
    selection = decoder.object("selection")
    settings = CommissionSettings(
        failure_retry_delay=timedelta(seconds=decoder.integer("failure_retry_seconds", minimum=1)),
        commission_limit_enabled=decoder.boolean("commission_limit_enabled"),
        selection=CommissionSelectionPolicy(
            preset_filter=selection.enum("preset_filter", CommissionPreset),
            custom_filter=selection.string("custom_filter"),
            do_major_commission=selection.boolean("do_major_commission"),
        ),
        gems_farming_deferral=timedelta(seconds=decoder.integer("gems_farming_deferral_seconds", minimum=1)),
    )
    selection.finish()
    return settings


def _tactical_settings(decoder: SettingsDecoder) -> TacticalSettings:
    experience_overflow = decoder.object("experience_overflow")
    student = decoder.object("student")
    settings = TacticalSettings(
        failure_retry_delay=timedelta(seconds=decoder.integer("failure_retry_seconds", minimum=1)),
        server_update_schedule=decoder.daily_schedule("server_update_schedule"),
        tactical_filter=decoder.string("tactical_filter"),
        rapid_training_slot=decoder.enum("rapid_training_slot", TacticalRapidTrainingSlot),
        experience_overflow=TacticalExperienceOverflowPolicy(
            enabled=experience_overflow.boolean("enabled"),
            t1_allow=experience_overflow.integer("t1_allow", minimum=0),
            t2_allow=experience_overflow.integer("t2_allow", minimum=0),
            t3_allow=experience_overflow.integer("t3_allow", minimum=0),
            t4_allow=experience_overflow.integer("t4_allow", minimum=0),
        ),
        student=TacticalStudentPolicy(
            enabled=student.boolean("enabled"),
            favorite=student.boolean("favorite"),
            minimum_level=student.integer("minimum_level", minimum=1, maximum=125),
        ),
    )
    experience_overflow.finish()
    student.finish()
    return settings


def build_facility_factories(workflows: FacilityWorkflows) -> Mapping[str, TaskFactory]:
    if not isinstance(workflows, FacilityWorkflows):
        message = "workflows must be FacilityWorkflows"
        raise TypeError(message)
    factories: dict[str, TaskFactory] = {
        "research": TypedTaskFactory(
            _research_settings,
            lambda settings: ResearchTask(workflows.research, settings),
        ),
        "commission": TypedTaskFactory(
            _commission_settings,
            lambda settings: CommissionTask(workflows.commission, settings),
        ),
        "tactical": TypedTaskFactory(
            _tactical_settings,
            lambda settings: TacticalTask(workflows.tactical, settings),
        ),
    }
    return MappingProxyType(factories)
