from datetime import UTC, datetime
from types import MappingProxyType
from typing import TYPE_CHECKING, cast

import pytest

from module.gameplay import (
    CommissionReport,
    CommissionSettings,
    CommissionTask,
    CommissionWorkflow,
    FacilityWorkflows,
    ResearchReport,
    ResearchSettings,
    ResearchTask,
    ResearchWorkflow,
    TacticalReport,
    TacticalSettings,
    TacticalTask,
    TacticalWorkflow,
    build_facility_factories,
)
from module.runtime import FrozenJsonValue, SettingsDocumentError, TaskBuildContext, TaskStateDocument
from module.task_registry import TASK_CATALOG

if TYPE_CHECKING:
    from module.interaction import CancellationSignal

_NOW = datetime(2026, 7, 13, 8, tzinfo=UTC)
_SERVER_UPDATE_SCHEDULE: dict[str, FrozenJsonValue] = {
    "timezone": "Asia/Hong_Kong",
    "triggers": ("12:00",),
}
_RESEARCH_SELECTION: dict[str, FrozenJsonValue] = {
    "use_cube": "only_05_hour",
    "use_coin": "always_use",
    "use_part": "always_use",
    "allow_delay": True,
    "preset_filter": "series_9_blueprint_only",
    "custom_filter": "Q > G > shortest",
}
_COMMISSION_SELECTION: dict[str, FrozenJsonValue] = {
    "preset_filter": "cube",
    "custom_filter": "DailyEvent > Gem-4 > shortest",
    "do_major_commission": False,
}
_TACTICAL_OVERFLOW: dict[str, FrozenJsonValue] = {
    "enabled": True,
    "t1_allow": 200,
    "t2_allow": 200,
    "t3_allow": 100,
    "t4_allow": 100,
}
_TACTICAL_STUDENT: dict[str, FrozenJsonValue] = {
    "enabled": False,
    "favorite": False,
    "minimum_level": 50,
}


class _ResearchWorkflow:
    @staticmethod
    def execute(settings: ResearchSettings, cancellation: CancellationSignal) -> ResearchReport:
        assert isinstance(settings, ResearchSettings)
        cancellation.raise_if_requested()
        return ResearchReport(observed_at=_NOW, available_slots=5, first_finish_at=None)


class _CommissionWorkflow:
    @staticmethod
    def execute(settings: CommissionSettings, cancellation: CancellationSignal) -> CommissionReport:
        assert isinstance(settings, CommissionSettings)
        cancellation.raise_if_requested()
        return CommissionReport(_NOW, (), 0, 0)


class _TacticalWorkflow:
    @staticmethod
    def execute(settings: TacticalSettings, cancellation: CancellationSignal) -> TacticalReport:
        assert isinstance(settings, TacticalSettings)
        cancellation.raise_if_requested()
        return TacticalReport(_NOW, None)


def _workflows() -> FacilityWorkflows:
    return FacilityWorkflows(_ResearchWorkflow(), _CommissionWorkflow(), _TacticalWorkflow())


def _context(command: str, settings: dict[str, FrozenJsonValue]) -> TaskBuildContext:
    return TaskBuildContext(
        TASK_CATALOG[command],
        2,
        MappingProxyType(settings),
        TaskStateDocument.empty(command),
    )


@pytest.mark.parametrize(
    ("command", "settings", "task_type"),
    [
        (
            "research",
            {"schedule": _SERVER_UPDATE_SCHEDULE, "selection": _RESEARCH_SELECTION},
            ResearchTask,
        ),
        (
            "commission",
            {
                "failure_retry_seconds": {"lower_seconds": 600, "upper_seconds": 600},
                "commission_limit_enabled": True,
                "gems_farming_deferral_seconds": 7200,
                "selection": _COMMISSION_SELECTION,
            },
            CommissionTask,
        ),
        (
            "tactical",
            {
                "failure_retry_seconds": {"lower_seconds": 600, "upper_seconds": 600},
                "server_update_schedule": _SERVER_UPDATE_SCHEDULE,
                "tactical_filter": "SameT4 > SameT3 > first",
                "rapid_training_slot": "do_not_use",
                "experience_overflow": _TACTICAL_OVERFLOW,
                "student": _TACTICAL_STUDENT,
            },
            TacticalTask,
        ),
    ],
)
def test_facility_factories_decode_strict_settings(
    command: str,
    settings: dict[str, FrozenJsonValue],
    task_type: type[object],
) -> None:
    factories = build_facility_factories(_workflows())

    task = factories[command].build(_context(command, settings))

    assert isinstance(task, task_type)
    assert set(factories) == {"research", "commission", "tactical"}


def test_facility_factories_reject_missing_and_unknown_settings() -> None:
    factories = build_facility_factories(_workflows())
    with pytest.raises(SettingsDocumentError, match="missing required setting"):
        factories["commission"].build(
            _context(
                "commission",
                {
                    "failure_retry_seconds": {"lower_seconds": 600, "upper_seconds": 600},
                    "commission_limit_enabled": True,
                },
            )
        )
    with pytest.raises(SettingsDocumentError, match="unknown settings"):
        factories["tactical"].build(
            _context(
                "tactical",
                {
                    "failure_retry_seconds": {"lower_seconds": 600, "upper_seconds": 600},
                    "server_update_schedule": _SERVER_UPDATE_SCHEDULE,
                    "tactical_filter": "SameT4 > SameT3 > first",
                    "rapid_training_slot": "do_not_use",
                    "experience_overflow": _TACTICAL_OVERFLOW,
                    "student": _TACTICAL_STUDENT,
                    "obsolete": True,
                },
            )
        )

    with pytest.raises(SettingsDocumentError, match=r"missing required setting.*schedule"):
        factories["research"].build(_context("research", {"next_server_update_at": "2026-07-14T00:00:00+00:00"}))


def test_facility_workflows_fail_fast_for_missing_execute_port() -> None:
    with pytest.raises(TypeError, match=r"research must implement execute\(\)"):
        FacilityWorkflows(
            research=cast("ResearchWorkflow", object()),
            commission=cast("CommissionWorkflow", _CommissionWorkflow()),
            tactical=cast("TacticalWorkflow", _TacticalWorkflow()),
        )
