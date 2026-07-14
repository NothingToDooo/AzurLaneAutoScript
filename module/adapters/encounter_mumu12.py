from datetime import UTC, datetime, timedelta
from types import MappingProxyType
from typing import TYPE_CHECKING, Protocol, cast, override

from module.adapters.mumu12 import CancellationAwareMumu12Device
from module.config.config import AzurLaneConfig, name_to_function
from module.daily.daily import OCR_REMAIN, Daily
from module.device.device import Device
from module.exception import OilExhausted, RequestHumanTakeover, ScriptEnd
from module.exercise import assets as exercise_assets
from module.exercise.exercise import ADMIRAL_TRIAL_HOUR_INTERVAL, OCR_EXERCISE_REMAIN, OCR_PERIOD_REMAIN, Exercise
from module.gameplay.encounter import (
    DailyReport,
    DailySettings,
    DailyStopReason,
    ExerciseOpponentMode,
    ExerciseProgress,
    ExerciseReport,
    ExerciseSettings,
    ExerciseStrategy,
    HardBattleOutcome,
    HardCampaignPort,
    HardReport,
    HardSettings,
    HardStopReason,
)
from module.gameplay.encounter_factories import EncounterWorkflows
from module.logger import logger
from module.ui.page import page_exercise

if TYPE_CHECKING:
    from collections.abc import Mapping

    from module.config.config_generated import ConfigOverrides
    from module.interaction import CancellationSignal


class EncounterLiveClock(Protocol):
    def now(self) -> datetime: ...


class SystemEncounterLiveClock:
    @staticmethod
    def now() -> datetime:
        return datetime.now(tz=UTC)


def _require_clock(clock: EncounterLiveClock) -> None:
    if isinstance(clock, type) or not callable(getattr(clock, "now", None)):
        message = "clock must implement now()"
        raise TypeError(message)


def _observed_at(clock: EncounterLiveClock) -> datetime:
    value = clock.now()
    if not isinstance(value, datetime):
        message = "encounter live clock must return a datetime"
        raise TypeError(message)
    if value.utcoffset() is None:
        message = "encounter live clock must return a timezone-aware datetime"
        raise ValueError(message)
    return value.astimezone(UTC)


def _require_hard_campaign(port: HardCampaignPort) -> None:
    for method_name in ("remaining_attempts", "advance_one", "exit_ui", "release"):
        if isinstance(port, type) or not callable(getattr(port, method_name, None)):
            message = f"hard_campaign must implement {method_name}()"
            raise TypeError(message)


def _activate(
    config: AzurLaneConfig,
    device: Device,
    task_name: str,
    overlay: ConfigOverrides,
    cancellation: CancellationSignal,
) -> Device:
    cancellation.raise_if_requested()
    config.replace_runtime_overlay()
    task = name_to_function(task_name)
    config.task = task
    config.bind(task)
    config.apply_runtime_overlay(**overlay)
    device.config = config
    return cast("Device", CancellationAwareMumu12Device(device, cancellation))


def project_daily_settings(settings: DailySettings) -> Mapping[str, object]:
    if not isinstance(settings, DailySettings):
        message = "settings must be DailySettings"
        raise TypeError(message)
    missions = settings.missions
    return MappingProxyType(
        {
            "Daily_UseDailySkip": settings.use_daily_skip,
            "Daily_EscortMission": missions.escort.stage.value,
            "Daily_EscortMissionFleet": missions.escort.fleet,
            "Daily_AdvanceMission": missions.advance.stage.value,
            "Daily_AdvanceMissionFleet": missions.advance.fleet,
            "Daily_FierceAssault": missions.fierce_assault.stage.value,
            "Daily_FierceAssaultFleet": missions.fierce_assault.fleet,
            "Daily_TacticalTraining": missions.tactical_training.stage.value,
            "Daily_TacticalTrainingFleet": missions.tactical_training.fleet,
            "Daily_SupplyLineDisruption": missions.supply_line_disruption.stage.value,
            "Daily_ModuleDevelopment": missions.module_development.stage.value,
            "Daily_ModuleDevelopmentFleet": missions.module_development.fleet,
            "Daily_EmergencyModuleDevelopment": missions.emergency_module_development.stage.value,
            "Daily_EmergencyModuleDevelopmentFleet": missions.emergency_module_development.fleet,
        }
    )


def _daily_overlay(settings: DailySettings) -> ConfigOverrides:
    projected = project_daily_settings(settings)
    return cast("ConfigOverrides", dict(projected))


def project_hard_settings(settings: HardSettings) -> Mapping[str, object]:
    if not isinstance(settings, HardSettings):
        message = "settings must be HardSettings"
        raise TypeError(message)
    return MappingProxyType(
        {
            "Hard_HardStage": settings.stage,
            "Hard_HardFleet": settings.fleet.value,
            "Campaign_Mode": "hard",
            "Campaign_UseFleetLock": True,
            "Campaign_UseAutoSearch": True,
            "Fleet_FleetOrder": (
                "fleet1_all_fleet2_standby" if settings.fleet.value == 1 else "fleet1_standby_fleet2_all"
            ),
            "Emotion_Mode": "nothing",
        }
    )


def _hard_overlay(settings: HardSettings) -> ConfigOverrides:
    return cast("ConfigOverrides", dict(project_hard_settings(settings)))


def project_exercise_settings(settings: ExerciseSettings) -> Mapping[str, object]:
    if not isinstance(settings, ExerciseSettings):
        message = "settings must be ExerciseSettings"
        raise TypeError(message)
    return MappingProxyType(
        {
            "Exercise_OpponentChooseMode": settings.opponent_mode.value,
            "Exercise_OpponentTrial": settings.opponent_trials,
            "Exercise_ExerciseStrategy": settings.strategy.value,
            "Exercise_LowHpThreshold": settings.low_hp_threshold,
            "Exercise_LowHpConfirmWait": settings.low_hp_confirm_wait_seconds,
        }
    )


def _exercise_overlay(settings: ExerciseSettings) -> ConfigOverrides:
    return cast("ConfigOverrides", dict(project_exercise_settings(settings)))


class _ReportingDaily(Daily):
    category_attempted: bool
    attempts_available: int
    attempts_completed: int

    def __init__(self, config: AzurLaneConfig, device: Device) -> None:
        super().__init__(config, device=device)
        self.category_attempted = False
        self.attempts_available = 0
        self.attempts_completed = 0

    @override
    def daily_execute(self, remain: int = 3, stage: int = 1, fleet: int = 1) -> bool:
        self.category_attempted = True
        self.attempts_available = remain
        entered = super().daily_execute(remain=remain, stage=stage, fleet=fleet)
        if not entered:
            return False
        self.device.screenshot()
        remaining = OCR_REMAIN.ocr_single(self.device.image)
        if remaining > remain:
            message = "daily remaining attempts increased after category execution"
            raise RequestHumanTakeover(message)
        self.attempts_completed = remain - remaining
        return True


class Mumu12DailyWorkflow:
    __slots__ = ("_config", "_device")

    def __init__(self, config: AzurLaneConfig, device: Device) -> None:
        if not isinstance(config, AzurLaneConfig):
            message = "config must be an AzurLaneConfig"
            raise TypeError(message)
        if not isinstance(device, Device):
            message = "device must be a Device"
            raise TypeError(message)
        self._config = config
        self._device = device

    def execute(self, settings: DailySettings, cancellation: CancellationSignal) -> DailyReport:
        device = _activate(self._config, self._device, "Daily", _daily_overlay(settings), cancellation)
        runner = _ReportingDaily(self._config, device=device)
        runner.daily_checked = [0]
        cancellation.raise_if_requested()
        runner.daily_run_one()
        if not runner.category_attempted:
            return DailyReport(0, 0, DailyStopReason.COMPLETED)
        if runner.attempts_completed:
            return DailyReport(
                runner.attempts_available,
                runner.attempts_completed,
                DailyStopReason.IN_PROGRESS,
            )
        return DailyReport(runner.attempts_available, 0, DailyStopReason.UNAVAILABLE)


class Mumu12HardWorkflow:
    __slots__ = ("_clock", "_config", "_device", "_hard_campaign")

    def __init__(
        self,
        config: AzurLaneConfig,
        device: Device,
        hard_campaign: HardCampaignPort,
        clock: EncounterLiveClock | None = None,
    ) -> None:
        if not isinstance(config, AzurLaneConfig):
            message = "config must be an AzurLaneConfig"
            raise TypeError(message)
        if not isinstance(device, Device):
            message = "device must be a Device"
            raise TypeError(message)
        _require_hard_campaign(hard_campaign)
        selected_clock = SystemEncounterLiveClock() if clock is None else clock
        _require_clock(selected_clock)
        self._config = config
        self._device = device
        self._hard_campaign = hard_campaign
        self._clock = selected_clock

    def execute(self, settings: HardSettings, cancellation: CancellationSignal) -> HardReport:
        _activate(self._config, self._device, "Hard", _hard_overlay(settings), cancellation)
        try:
            cancellation.raise_if_requested()
            remaining = self._hard_campaign.remaining_attempts(settings, cancellation)
            if type(remaining) is not int or remaining < 0:
                message = "HardCampaignPort.remaining_attempts() must return a non-negative integer"
                raise TypeError(message)
            if remaining == 0:
                cancellation.raise_if_requested()
                self._hard_campaign.exit_ui(settings, cancellation)
                return HardReport(_observed_at(self._clock), 0, 0, HardStopReason.COMPLETED)

            try:
                cancellation.raise_if_requested()
                result = self._hard_campaign.advance_one(settings, cancellation)
            except OilExhausted:
                result = HardBattleOutcome.RESOURCE_LIMIT
            except ScriptEnd:
                result = HardBattleOutcome.FAILED
            if not isinstance(result, HardBattleOutcome):
                message = "HardCampaignPort.advance_one() must return a HardBattleOutcome"
                raise TypeError(message)

            observed_at = _observed_at(self._clock)
            if result is HardBattleOutcome.RESOURCE_LIMIT:
                return HardReport(observed_at, remaining, 0, HardStopReason.RESOURCE_LIMIT)
            if result is HardBattleOutcome.FAILED:
                return HardReport(observed_at, remaining, 0, HardStopReason.FAILED)
            if remaining > 1:
                return HardReport(observed_at, remaining, 1, HardStopReason.IN_PROGRESS)

            cancellation.raise_if_requested()
            self._hard_campaign.exit_ui(settings, cancellation)
            return HardReport(observed_at, 1, 1, HardStopReason.COMPLETED)
        finally:
            self._hard_campaign.release()


class _ReportingExercise(Exercise):
    @override
    def _new_opponent(self) -> None:
        logger.info("New opponent")
        self.appear_then_click(exercise_assets.NEW_OPPONENT)
        self.opponent_change_count += 1
        logger.attr("Change_opponent_count", self.opponent_change_count)
        self.ensure_no_info_bar(timeout=3)

    def advance_one(self, settings: ExerciseSettings) -> bool:
        if settings.opponent_mode is ExerciseOpponentMode.EASIEST_ELSE_EXP:
            return self._advance_easiest_else_exp(settings)
        return self._advance_standard(settings)

    def _advance_standard(self, settings: ExerciseSettings) -> bool:
        self._opponent_fleet_check_all()
        while True:
            for opponent in self._opponent_sort(method=settings.opponent_mode.value):
                logger.hr(f"Opponent {opponent}", level=2)
                if self._combat(opponent):
                    return True
            if self.opponent_change_count >= settings.opponent_refresh_limit:
                return False
            self._new_opponent()
            self._opponent_fleet_check_all()

    def _advance_easiest_else_exp(self, settings: ExerciseSettings) -> bool:
        method = ExerciseOpponentMode.EASIEST_ELSE_EXP.value
        threshold = settings.low_hp_threshold
        self._opponent_fleet_check_all()
        try:
            while True:
                opponents = self._opponent_sort(method=method)
                logger.hr(f"Opponent {opponents[0]}", level=2)
                self.config.apply_runtime_overlay(Exercise_LowHpThreshold=threshold)
                if self._combat(opponents[0]):
                    return True
                if self.opponent_change_count < settings.opponent_refresh_limit:
                    logger.info("Cannot beat calculated easiest opponent, refresh")
                    self._new_opponent()
                    self._opponent_fleet_check_all()
                    continue
                logger.info("Cannot beat calculated easiest opponent, MAX EXP then")
                method = ExerciseOpponentMode.MAX_EXP.value
                threshold = 0
        finally:
            self.config.apply_runtime_overlay(Exercise_LowHpThreshold=settings.low_hp_threshold)


def _exercise_preserve(settings: ExerciseSettings, period_remaining: timedelta) -> int:
    if settings.strategy is ExerciseStrategy.AGGRESSIVE:
        return 0
    preserve = 5
    if period_remaining:
        start, end = ADMIRAL_TRIAL_HOUR_INTERVAL[settings.strategy.value]
        hours = int(period_remaining.total_seconds() // 3600)
        if start > hours >= end or hours < 6:
            preserve = 0
    return preserve


class Mumu12ExerciseWorkflow:
    __slots__ = ("_clock", "_config", "_device")

    def __init__(
        self,
        config: AzurLaneConfig,
        device: Device,
        clock: EncounterLiveClock | None = None,
    ) -> None:
        if not isinstance(config, AzurLaneConfig):
            message = "config must be an AzurLaneConfig"
            raise TypeError(message)
        if not isinstance(device, Device):
            message = "device must be a Device"
            raise TypeError(message)
        selected_clock = SystemEncounterLiveClock() if clock is None else clock
        _require_clock(selected_clock)
        self._config = config
        self._device = device
        self._clock = selected_clock

    def execute(
        self,
        settings: ExerciseSettings,
        progress: ExerciseProgress,
        cancellation: CancellationSignal,
    ) -> ExerciseReport:
        if not isinstance(progress, ExerciseProgress):
            message = "progress must be an ExerciseProgress"
            raise TypeError(message)
        device = _activate(self._config, self._device, "Exercise", _exercise_overlay(settings), cancellation)
        runner = _ReportingExercise(self._config, device=device)
        runner.opponent_change_count = progress.opponent_refreshes_used

        cancellation.raise_if_requested()
        runner.ui_ensure(page_exercise)
        period_remaining = OCR_PERIOD_REMAIN.ocr_single(device.image)
        preserve = _exercise_preserve(settings, period_remaining)
        remaining_before = OCR_EXERCISE_REMAIN.ocr_single(device.image)
        if remaining_before <= preserve or progress.opponent_refreshes_used >= settings.opponent_refresh_limit:
            return ExerciseReport(
                observed_at=_observed_at(self._clock),
                attempts_remaining=remaining_before,
                attempts_preserved=preserve,
                attempts_completed=0,
                opponent_refreshes_used=progress.opponent_refreshes_used,
            )

        cancellation.raise_if_requested()
        settled = runner.advance_one(settings)
        cancellation.raise_if_requested()
        device.screenshot()
        remaining_after = OCR_EXERCISE_REMAIN.ocr_single(device.image)
        if remaining_after > remaining_before:
            message = "exercise remaining attempts increased after battle"
            raise RequestHumanTakeover(message)
        if settled and remaining_after >= remaining_before:
            message = "exercise battle settled without a confirmed remaining-attempt decrement"
            raise RequestHumanTakeover(message)
        return ExerciseReport(
            observed_at=_observed_at(self._clock),
            attempts_remaining=remaining_after,
            attempts_preserved=preserve,
            attempts_completed=int(settled),
            opponent_refreshes_used=runner.opponent_change_count,
        )


def build_mumu12_encounter_workflows(
    config: AzurLaneConfig,
    device: Device,
    *,
    hard_campaign: HardCampaignPort,
    clock: EncounterLiveClock | None = None,
) -> EncounterWorkflows:
    """组装每日、困难图和演习的 production MuMu12 workflows。"""

    return EncounterWorkflows(
        daily=Mumu12DailyWorkflow(config, device),
        hard=Mumu12HardWorkflow(config, device, hard_campaign, clock),
        exercise=Mumu12ExerciseWorkflow(config, device, clock),
    )
