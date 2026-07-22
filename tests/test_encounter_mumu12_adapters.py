from datetime import UTC, datetime, time, timedelta
from typing import TYPE_CHECKING, cast

import pytest

import module.adapters.encounter_mumu12 as adapters
from module.application import AbortToken, DailySchedule, DelayRange
from module.config.config import AzurLaneConfig
from module.device.device import Device
from module.exception import CampaignSelectionError, OilExhausted
from module.gameplay.encounter import (
    DailyMissionPlan,
    DailyMissionPlans,
    DailySettings,
    DailyStageSelection,
    DailyStopReason,
    ExerciseOpponentMode,
    ExerciseProgress,
    ExerciseSettings,
    ExerciseStrategy,
    HardBattleOutcome,
    HardFleet,
    HardSettings,
    HardStopReason,
)

if TYPE_CHECKING:
    from module.application import CancellationSource


_NOW = datetime(2026, 7, 13, 12, tzinfo=UTC)
_SCHEDULE = DailySchedule("Asia/Hong_Kong", (time(12),))
_MISSION = DailyMissionPlan(DailyStageSelection.FIRST, 1)
_DAILY_SETTINGS = DailySettings(
    schedule=_SCHEDULE,
    use_daily_skip=True,
    missions=DailyMissionPlans(
        escort=_MISSION,
        advance=DailyMissionPlan(DailyStageSelection.SECOND, 2),
        fierce_assault=DailyMissionPlan(DailyStageSelection.THIRD, 3),
        tactical_training=_MISSION,
        supply_line_disruption=DailyMissionPlan(DailyStageSelection.SECOND, None),
        module_development=DailyMissionPlan(DailyStageSelection.SKIP, 4),
        emergency_module_development=DailyMissionPlan(DailyStageSelection.FIRST, 5),
    ),
)
_HARD_SETTINGS = HardSettings(
    schedule=_SCHEDULE,
    failure_retry_delay=DelayRange(1_800, 1_800),
    resource_retry_delay=timedelta(hours=3),
    stage="11-4",
    fleet=HardFleet.FLEET_2,
)
_EXERCISE_SETTINGS = ExerciseSettings(
    schedule=_SCHEDULE,
    failure_retry_delay=DelayRange(1_800, 1_800),
    opponent_refresh_limit=5,
    opponent_mode=ExerciseOpponentMode.EASIEST_ELSE_EXP,
    opponent_trials=2,
    strategy=ExerciseStrategy.SUN_18,
    low_hp_threshold=0.35,
    low_hp_confirm_wait_seconds=0.2,
)


class _Clock:
    @staticmethod
    def now() -> datetime:
        return _NOW


@pytest.fixture
def runtime(monkeypatch: pytest.MonkeyPatch) -> tuple[AzurLaneConfig, Device]:
    config = object.__new__(AzurLaneConfig)
    device = object.__new__(Device)

    def activate(
        _config: AzurLaneConfig,
        _device: Device,
        _task_name: str,
        _overlay: object,
        cancellation: CancellationSource,
    ) -> Device:
        cancellation.raise_if_requested()
        return device

    monkeypatch.setattr(adapters, "activate_mumu12_task", activate)
    return config, device


def test_daily_projection_contains_every_gameplay_choice() -> None:
    assert dict(adapters.project_daily_settings(_DAILY_SETTINGS)) == {
        "Daily_UseDailySkip": True,
        "Daily_EscortMission": "first",
        "Daily_EscortMissionFleet": 1,
        "Daily_AdvanceMission": "second",
        "Daily_AdvanceMissionFleet": 2,
        "Daily_FierceAssault": "third",
        "Daily_FierceAssaultFleet": 3,
        "Daily_TacticalTraining": "first",
        "Daily_TacticalTrainingFleet": 1,
        "Daily_SupplyLineDisruption": "second",
        "Daily_ModuleDevelopment": "skip",
        "Daily_ModuleDevelopmentFleet": 4,
        "Daily_EmergencyModuleDevelopment": "first",
        "Daily_EmergencyModuleDevelopmentFleet": 5,
    }


def test_hard_projection_contains_stage_fleet_and_fixed_safety_policy() -> None:
    assert dict(adapters.project_hard_settings(_HARD_SETTINGS)) == {
        "Hard_HardStage": "11-4",
        "Hard_HardFleet": 2,
        "Campaign_Mode": "hard",
        "Campaign_UseFleetLock": True,
        "Campaign_UseAutoSearch": True,
        "Fleet_FleetOrder": "fleet1_standby_fleet2_all",
        "Emotion_Mode": "nothing",
    }


def test_exercise_projection_contains_every_combat_decision() -> None:
    assert dict(adapters.project_exercise_settings(_EXERCISE_SETTINGS)) == {
        "Exercise_OpponentChooseMode": "easiest_else_exp",
        "Exercise_OpponentTrial": 2,
        "Exercise_ExerciseStrategy": "sun18",
        "Exercise_LowHpThreshold": 0.35,
        "Exercise_LowHpConfirmWait": 0.2,
    }


class _DailyRunner:
    def __init__(self, *, attempted: bool, available: int, completed: int) -> None:
        self.category_attempted = attempted
        self.attempts_available = available
        self.attempts_completed = completed
        self.daily_checked: list[int] = []
        self.calls = 0

    def daily_run_one(self) -> None:
        self.calls += 1


def test_daily_advances_exactly_one_category_and_reports_continuation(
    runtime: tuple[AzurLaneConfig, Device],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config, device = runtime
    runner = _DailyRunner(attempted=True, available=3, completed=3)
    monkeypatch.setattr(adapters, "_ReportingDaily", lambda *_args, **_kwargs: runner)

    report = adapters.Mumu12DailyWorkflow(config, device).execute(_DAILY_SETTINGS, AbortToken())

    assert report.attempts_available == 3
    assert report.attempts_completed == 3
    assert report.stop_reason is DailyStopReason.IN_PROGRESS
    assert runner.calls == 1


def test_daily_terminal_scan_does_not_invent_attempts(
    runtime: tuple[AzurLaneConfig, Device],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config, device = runtime
    runner = _DailyRunner(attempted=False, available=0, completed=0)
    monkeypatch.setattr(adapters, "_ReportingDaily", lambda *_args, **_kwargs: runner)

    report = adapters.Mumu12DailyWorkflow(config, device).execute(_DAILY_SETTINGS, AbortToken())

    assert report.attempts_available == 0
    assert report.attempts_completed == 0
    assert report.stop_reason is DailyStopReason.COMPLETED


class _HardCampaign:
    def __init__(
        self,
        remaining: int,
        result: HardBattleOutcome | BaseException = HardBattleOutcome.SETTLED,
        *,
        release_error: BaseException | None = None,
    ) -> None:
        self.remaining = remaining
        self.result = result
        self.release_error = release_error
        self.calls: list[str] = []

    def remaining_attempts(self, settings: HardSettings, cancellation: CancellationSource) -> int:
        assert settings is _HARD_SETTINGS
        cancellation.raise_if_requested()
        self.calls.append("remaining")
        return self.remaining

    def advance_one(self, settings: HardSettings, cancellation: CancellationSource) -> HardBattleOutcome:
        assert settings is _HARD_SETTINGS
        cancellation.raise_if_requested()
        self.calls.append("advance")
        if isinstance(self.result, BaseException):
            raise self.result
        return self.result

    def exit_ui(self, settings: HardSettings, cancellation: CancellationSource) -> None:
        assert settings is _HARD_SETTINGS
        cancellation.raise_if_requested()
        self.calls.append("exit_ui")

    def release(self) -> None:
        self.calls.append("release")
        if self.release_error is not None:
            raise self.release_error


def test_hard_advances_one_confirmed_battle_and_releases_without_exiting_mid_batch(
    runtime: tuple[AzurLaneConfig, Device],
) -> None:
    config, device = runtime
    campaign = _HardCampaign(remaining=3)

    report = adapters.Mumu12HardWorkflow(config, device, campaign, _Clock()).execute(
        _HARD_SETTINGS,
        AbortToken(),
    )

    assert report.attempts_available == 3
    assert report.attempts_completed == 1
    assert report.stop_reason is HardStopReason.IN_PROGRESS
    assert campaign.calls == ["remaining", "advance", "release"]


def test_hard_final_battle_exits_explicitly(runtime: tuple[AzurLaneConfig, Device]) -> None:
    config, device = runtime
    campaign = _HardCampaign(remaining=1)

    report = adapters.Mumu12HardWorkflow(config, device, campaign, _Clock()).execute(
        _HARD_SETTINGS,
        AbortToken(),
    )

    assert report.stop_reason is HardStopReason.COMPLETED
    assert campaign.calls == ["remaining", "advance", "exit_ui", "release"]


@pytest.mark.parametrize(
    ("failure", "expected"),
    [
        (OilExhausted(), HardStopReason.RESOURCE_LIMIT),
        (CampaignSelectionError(), HardStopReason.FAILED),
    ],
)
def test_hard_maps_legacy_stop_semantics_without_reporting_success(
    runtime: tuple[AzurLaneConfig, Device],
    failure: BaseException,
    expected: HardStopReason,
) -> None:
    config, device = runtime
    campaign = _HardCampaign(remaining=3, result=failure)

    report = adapters.Mumu12HardWorkflow(config, device, campaign, _Clock()).execute(
        _HARD_SETTINGS,
        AbortToken(),
    )

    assert report.stop_reason is expected
    assert report.attempts_completed == 0
    assert campaign.calls == ["remaining", "advance", "release"]


def test_hard_releases_runtime_after_unexpected_error(runtime: tuple[AzurLaneConfig, Device]) -> None:
    config, device = runtime
    campaign = _HardCampaign(remaining=3, result=RuntimeError("unexpected hard failure"))

    with pytest.raises(RuntimeError, match="unexpected hard failure"):
        adapters.Mumu12HardWorkflow(config, device, campaign, _Clock()).execute(
            _HARD_SETTINGS,
            AbortToken(),
        )

    assert campaign.calls == ["remaining", "advance", "release"]


def test_hard_preserves_execution_and_release_failures(runtime: tuple[AzurLaneConfig, Device]) -> None:
    config, device = runtime
    execution_error = RuntimeError("unexpected hard failure")
    release_error = OSError("runtime release failed")
    campaign = _HardCampaign(
        remaining=3,
        result=execution_error,
        release_error=release_error,
    )

    with pytest.raises(BaseExceptionGroup) as raised:
        adapters.Mumu12HardWorkflow(config, device, campaign, _Clock()).execute(
            _HARD_SETTINGS,
            AbortToken(),
        )

    assert raised.value.exceptions == (execution_error, release_error)
    assert campaign.calls == ["remaining", "advance", "release"]


class _Screen:
    image = object()

    def screenshot(self) -> None:
        self.image = object()


class _ExerciseRunner:
    def __init__(self) -> None:
        self.opponent_change_count = 0
        self.calls: list[object] = []

    def ui_ensure(self, page: object) -> None:
        self.calls.append(("ui", page))

    def advance_one(self, settings: ExerciseSettings) -> bool:
        self.calls.append(("advance", settings, self.opponent_change_count))
        self.opponent_change_count = 2
        return True


class _OcrSequence:
    def __init__(self, *values: object) -> None:
        self.values = list(values)

    def ocr_single(self, _image: object) -> object:
        return self.values.pop(0)


def test_exercise_advances_one_settlement_from_typed_checkpoint(
    runtime: tuple[AzurLaneConfig, Device],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config, raw_device = runtime
    screen = _Screen()
    runner = _ExerciseRunner()

    def activate(
        _config: AzurLaneConfig,
        _device: Device,
        _task_name: str,
        _overlay: object,
        cancellation: CancellationSource,
    ) -> Device:
        cancellation.raise_if_requested()
        return cast("Device", screen)

    monkeypatch.setattr(adapters, "activate_mumu12_task", activate)
    monkeypatch.setattr(adapters, "_ReportingExercise", lambda *_args, **_kwargs: runner)
    monkeypatch.setattr(adapters, "OCR_PERIOD_REMAIN", _OcrSequence(timedelta(days=1)))
    monkeypatch.setattr(adapters, "OCR_EXERCISE_REMAIN", _OcrSequence(10, 9))

    report = adapters.Mumu12ExerciseWorkflow(config, raw_device, _Clock()).execute(
        _EXERCISE_SETTINGS,
        ExerciseProgress(1),
        AbortToken(),
    )

    assert report.attempts_remaining == 9
    assert report.attempts_completed == 1
    assert report.opponent_refreshes_used == 2
    assert runner.calls[-1] == ("advance", _EXERCISE_SETTINGS, 1)


def test_production_builder_executes_hard_with_the_injected_campaign_port(
    runtime: tuple[AzurLaneConfig, Device],
) -> None:
    config, device = runtime
    campaign = _HardCampaign(remaining=3)

    workflows = adapters.build_mumu12_encounter_workflows(
        config,
        device,
        hard_campaign=campaign,
        clock=_Clock(),
    )

    report = workflows.hard.execute(_HARD_SETTINGS, AbortToken())

    assert report.attempts_available == 3
    assert report.attempts_completed == 1
    assert report.stop_reason is HardStopReason.IN_PROGRESS
    assert campaign.calls == ["remaining", "advance", "release"]
