from datetime import UTC, datetime, timedelta
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
from module.runtime import TaskBuildContext, TaskStateDocument
from module.task_registry import TASK_SPECS

if TYPE_CHECKING:
    from module.application import CancellationSource
    from module.gameplay.facility import CommissionWorkflow, ResearchWorkflow, TacticalWorkflow

_NOW = datetime(2026, 7, 13, 8, tzinfo=UTC)


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


def _context(command: str, settings: object) -> TaskBuildContext:
    return TaskBuildContext(
        spec=TASK_SPECS[command],
        settings_revision=2,
        content_revision="content-1",
        settings=settings,
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


def test_commission_factory_passes_typed_settings_to_workflow() -> None:
    workflow = _RecordingWorkflow[CommissionSettings, CommissionReport](CommissionReport(_NOW, (), 0, 0))
    settings = CommissionSettings(
        failure_retry_delay=DelayRange(347, 911),
        commission_limit_enabled=True,
        selection=CommissionSelectionPolicy(
            preset_filter=CommissionPreset.OIL,
            custom_filter="Gem-8 > Oil-10 > shortest",
            do_major_commission=True,
        ),
        gems_farming_deferral=timedelta(seconds=5_432),
    )
    task = build_facility_factories(_workflows(workflow))["commission"].build(_context("commission", settings))

    task.run(_task_context("commission"))

    assert workflow.settings == settings


def test_facility_factories_reject_wrong_settings_type() -> None:
    factories = build_facility_factories(_workflows())
    settings = CommissionSettings(
        failure_retry_delay=DelayRange(600, 600),
        commission_limit_enabled=True,
        selection=CommissionSelectionPolicy(
            preset_filter=CommissionPreset.OIL,
            custom_filter="Oil-10 > shortest",
            do_major_commission=True,
        ),
    )

    with pytest.raises(TypeError, match="tactical settings must be TacticalSettings"):
        factories["tactical"].build(_context("tactical", settings))


def test_facility_workflows_fail_fast_for_missing_execute_port() -> None:
    port = _RecordingWorkflow(object())
    with pytest.raises(TypeError, match=r"research must implement execute\(\)"):
        FacilityWorkflows(
            research=cast("ResearchWorkflow", object()),
            commission=cast("CommissionWorkflow", port),
            tactical=cast("TacticalWorkflow", port),
        )
