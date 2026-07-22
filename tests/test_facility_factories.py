from datetime import UTC, datetime, timedelta
from types import MappingProxyType
from typing import TYPE_CHECKING, cast

import pytest

from module.application import AbortToken, DelayRange, ExecutionMode, RunMetadata, TaskContext, TaskId
from module.gameplay.facility import (
    CommissionPreset,
    CommissionReport,
    CommissionSelectionPolicy,
    CommissionSettings,
)
from module.gameplay.facility_factories import FacilityWorkflows, build_facility_factories
from module.runtime import FrozenJsonValue, SettingsDocumentError, TaskBuildContext, TaskStateDocument
from module.task_registry import TASK_SPECS

if TYPE_CHECKING:
    from module.application import CancellationSource
    from module.gameplay.facility import CommissionWorkflow, ResearchWorkflow, TacticalWorkflow

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


class _RecordingWorkflow[SettingsT, ReportT]:
    def __init__(self, report: ReportT) -> None:
        self._report = report
        self.settings: SettingsT | None = None

    def execute(self, settings: SettingsT, cancellation: CancellationSource) -> ReportT:
        cancellation.raise_if_requested()
        self.settings = settings
        return self._report


def _workflows(
    commission: _RecordingWorkflow[CommissionSettings, CommissionReport] | None = None,
) -> FacilityWorkflows:
    port = _RecordingWorkflow(object())
    return FacilityWorkflows(
        research=cast("ResearchWorkflow", port),
        commission=cast("CommissionWorkflow", port if commission is None else commission),
        tactical=cast("TacticalWorkflow", port),
    )


def _context(command: str, settings: dict[str, FrozenJsonValue]) -> TaskBuildContext:
    return TaskBuildContext(
        spec=TASK_SPECS[command],
        settings_revision=2,
        content_revision="content-1",
        settings=MappingProxyType(settings),
        task_state=TaskStateDocument.empty(command),
    )


def _task_context(command: str) -> TaskContext:
    return TaskContext(
        task_id=TaskId(command),
        started_at=_NOW,
        mode=ExecutionMode.SCHEDULED_JOB,
        metadata=RunMetadata(settings_revision=2, content_revision="content-1"),
        abort=AbortToken(),
    )


def test_commission_factory_passes_decoded_settings_to_workflow() -> None:
    workflow = _RecordingWorkflow[CommissionSettings, CommissionReport](CommissionReport(_NOW, (), 0, 0))
    task = build_facility_factories(_workflows(workflow))["commission"].build(
        _context(
            "commission",
            {
                "failure_retry_seconds": {"lower_seconds": 347, "upper_seconds": 911},
                "commission_limit_enabled": True,
                "gems_farming_deferral_seconds": 5_432,
                "selection": {
                    "preset_filter": "oil",
                    "custom_filter": "Gem-8 > Oil-10 > shortest",
                    "do_major_commission": True,
                },
            },
        )
    )

    task.run(_task_context("commission"))

    assert workflow.settings == CommissionSettings(
        failure_retry_delay=DelayRange(347, 911),
        commission_limit_enabled=True,
        selection=CommissionSelectionPolicy(
            preset_filter=CommissionPreset.OIL,
            custom_filter="Gem-8 > Oil-10 > shortest",
            do_major_commission=True,
        ),
        gems_farming_deferral=timedelta(seconds=5_432),
    )


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
    port = _RecordingWorkflow(object())
    with pytest.raises(TypeError, match=r"research must implement execute\(\)"):
        FacilityWorkflows(
            research=cast("ResearchWorkflow", object()),
            commission=cast("CommissionWorkflow", port),
            tactical=cast("TacticalWorkflow", port),
        )
