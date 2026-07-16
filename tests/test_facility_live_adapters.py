from datetime import UTC, datetime, time, timedelta
from typing import TYPE_CHECKING, cast

import pytest

from module.adapters.facility_live import (
    CommissionEvidence,
    LiveCommissionWorkflow,
    LiveResearchWorkflow,
    LiveTacticalWorkflow,
    ResearchQueueEvidence,
    TacticalEvidence,
)
from module.application import AbortRequested, AbortToken, DailySchedule, DelayRange
from module.gameplay.facility import (
    CommissionPreset,
    CommissionReport,
    CommissionSelectionPolicy,
    CommissionSettings,
    ResearchReport,
    ResearchResourcePolicy,
    ResearchSelectionPolicy,
    ResearchSettings,
    TacticalExperienceOverflowPolicy,
    TacticalRapidTrainingSlot,
    TacticalReport,
    TacticalSettings,
    TacticalStudentPolicy,
)

if TYPE_CHECKING:
    from module.adapters.facility_live import CommissionUiDriver, ResearchUiDriver, TacticalUiDriver
    from module.application import CancellationSource


_NOW = datetime(2026, 7, 13, 12, tzinfo=UTC)
_SCHEDULE = DailySchedule("Asia/Hong_Kong", (time(12),))
_RESEARCH_SETTINGS = ResearchSettings(
    _SCHEDULE,
    ResearchSelectionPolicy(
        ResearchResourcePolicy.ONLY_HALF_HOUR,
        ResearchResourcePolicy.ALWAYS_USE,
        ResearchResourcePolicy.ALWAYS_USE,
        allow_delay=True,
        preset_filter="series_9_blueprint_only",
        custom_filter="Q > G > shortest",
    ),
)
_COMMISSION_SETTINGS = CommissionSettings(
    DelayRange(1_800, 1_800),
    commission_limit_enabled=False,
    selection=CommissionSelectionPolicy(
        CommissionPreset.CUBE,
        "DailyEvent > shortest",
        do_major_commission=False,
    ),
)
_TACTICAL_SETTINGS = TacticalSettings(
    DelayRange(1_200, 1_200),
    _SCHEDULE,
    "SameT4 > SameT3 > first",
    TacticalRapidTrainingSlot.DISABLED,
    TacticalExperienceOverflowPolicy(
        enabled=True,
        t1_allow=200,
        t2_allow=200,
        t3_allow=100,
        t4_allow=100,
    ),
    TacticalStudentPolicy(enabled=False, favorite=False, minimum_level=50),
)


class _Driver[EvidenceT]:
    def __init__(self, evidence: EvidenceT) -> None:
        self.evidence = evidence
        self.calls = 0
        self.settings: object | None = None

    def execute(self, settings: object, cancellation: CancellationSource) -> EvidenceT:
        cancellation.raise_if_requested()
        self.settings = settings
        self.calls += 1
        return self.evidence


class _Clock:
    @staticmethod
    def now() -> datetime:
        return _NOW


def test_live_research_converts_confirmed_queue_evidence_to_typed_report() -> None:
    finish_at = datetime(2026, 7, 13, 18)
    driver = _Driver(ResearchQueueEvidence(available_slots=4, first_finish_at=finish_at))

    report = LiveResearchWorkflow(driver, _Clock()).execute(_RESEARCH_SETTINGS, AbortToken())

    assert report == ResearchReport(
        observed_at=_NOW,
        available_slots=4,
        first_finish_at=finish_at.astimezone(),
    )
    assert driver.calls == 1


def test_live_commission_preserves_all_finish_and_pending_facts() -> None:
    first = datetime(2026, 7, 13, 13)
    second = datetime(2026, 7, 13, 14, tzinfo=UTC)
    driver = _Driver(CommissionEvidence((first, second), daily_pending=1, filtered_urgent_pending=3))

    report = LiveCommissionWorkflow(driver, _Clock()).execute(_COMMISSION_SETTINGS, AbortToken())

    assert report == CommissionReport(
        observed_at=_NOW,
        finish_times=(first.astimezone(), second),
        daily_pending=1,
        filtered_urgent_pending=3,
    )


def test_live_tactical_selects_the_nearest_confirmed_finish() -> None:
    nearer = _NOW + timedelta(hours=1)
    later = _NOW + timedelta(hours=3)
    driver = _Driver(TacticalEvidence((later, nearer)))

    report = LiveTacticalWorkflow(driver, _Clock()).execute(_TACTICAL_SETTINGS, AbortToken())

    assert report == TacticalReport(observed_at=_NOW, finish_at=nearer)


def test_live_tactical_empty_evidence_reports_no_running_training() -> None:
    report = LiveTacticalWorkflow(_Driver(TacticalEvidence(())), _Clock()).execute(_TACTICAL_SETTINGS, AbortToken())

    assert report == TacticalReport(observed_at=_NOW, finish_at=None)


def test_live_facility_workflows_reject_driver_contract_drift() -> None:
    with pytest.raises(TypeError, match="ResearchQueueEvidence"):
        LiveResearchWorkflow(cast("ResearchUiDriver", _Driver(object())), _Clock()).execute(
            _RESEARCH_SETTINGS,
            AbortToken(),
        )
    with pytest.raises(TypeError, match="CommissionEvidence"):
        LiveCommissionWorkflow(cast("CommissionUiDriver", _Driver(object())), _Clock()).execute(
            _COMMISSION_SETTINGS,
            AbortToken(),
        )
    with pytest.raises(TypeError, match="TacticalEvidence"):
        LiveTacticalWorkflow(cast("TacticalUiDriver", _Driver(object())), _Clock()).execute(
            _TACTICAL_SETTINGS,
            AbortToken(),
        )


def test_live_facility_checks_cancellation_before_ui_driver() -> None:
    abort = AbortToken()
    abort.request("manual stop")
    driver = _Driver(TacticalEvidence(()))

    with pytest.raises(AbortRequested, match="manual stop"):
        LiveTacticalWorkflow(driver, _Clock()).execute(_TACTICAL_SETTINGS, abort)

    assert driver.calls == 0


def test_facility_evidence_rejects_impossible_observations() -> None:
    with pytest.raises(ValueError, match="empty research queue"):
        ResearchQueueEvidence(5, _NOW)
    with pytest.raises(ValueError, match="non-empty research queue"):
        ResearchQueueEvidence(4, None)
    with pytest.raises(ValueError, match="non-negative"):
        CommissionEvidence((), daily_pending=-1, filtered_urgent_pending=0)
    with pytest.raises(TypeError, match="datetime"):
        TacticalEvidence((cast("datetime", "tomorrow"),))
