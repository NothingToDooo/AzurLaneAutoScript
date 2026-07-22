from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING

from module.gameplay.facility import (
    CommissionSettings,
    CommissionTask,
    ResearchSettings,
    ResearchTask,
    TacticalSettings,
    TacticalTask,
)
from module.runtime import ConfiguredTaskFactory

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


def build_facility_factories(workflows: FacilityWorkflows) -> Mapping[str, TaskFactory]:
    if not isinstance(workflows, FacilityWorkflows):
        message = "workflows must be FacilityWorkflows"
        raise TypeError(message)
    factories: dict[str, TaskFactory] = {
        "research": ConfiguredTaskFactory(
            ResearchSettings,
            lambda settings: ResearchTask(workflows.research, settings),
        ),
        "commission": ConfiguredTaskFactory(
            CommissionSettings,
            lambda settings: CommissionTask(workflows.commission, settings),
        ),
        "tactical": ConfiguredTaskFactory(
            TacticalSettings,
            lambda settings: TacticalTask(workflows.tactical, settings),
        ),
    }
    return MappingProxyType(factories)
