from datetime import UTC, datetime
from typing import TYPE_CHECKING, Protocol, override

from module.adapters.mumu12 import activate_mumu12_task, emotion_runtime_overlay
from module.application import DelaySampler, runtime_delay_sampler
from module.coalition.coalition import Coalition
from module.coalition.profile import (
    COALITION_CLIENT_PROFILES,
    CoalitionClientSession,
    CoalitionOilReadLocation,
    CoalitionPageMode,
)
from module.config.config import AzurLaneConfig
from module.config.utils import DEFAULT_TIME
from module.daemon.daemon import AzurLaneDaemon as StandardDaemon
from module.daemon.os_daemon import AzurLaneDaemon as OpsiDaemon
from module.device.device import Device
from module.event import assets as event_assets
from module.event_hospital.hospital import HOSPITAL_TAB, Hospital
from module.eventstory.eventstory import EventStory
from module.eventstory.profile import EVENT_STORY_CLIENT_PROFILES
from module.exception import CampaignSelectionError, HumanTakeoverRequiredError, OilExhausted
from module.gameplay.activity import (
    ActivityCommand,
    ActivityDisposition,
    ActivityReport,
    ActivitySpec,
    ActivityWorkflow,
    AssistSessionCommand,
    AssistSessionReport,
    AssistSessionSpec,
    AssistSessionState,
    AssistSessionWorkflow,
    CoalitionOptions,
    DaemonOptions,
    EncounterBalancerPolicy,
    EncounterCommand,
    EncounterPolicy,
    EncounterReport,
    EncounterSpec,
    EncounterStopReason,
    EncounterWorkflow,
    HospitalOptions,
    MaritimeEscortOptions,
    MinigameKind,
    OpsiDaemonOptions,
    RaidDailyOptions,
    RaidMode,
    RaidOptions,
)
from module.gameplay.activity_factories import ActivityWorkflows
from module.maritime_escort.result import MaritimeEscortExecutionResult, MaritimeEscortExecutionStatus
from module.maritime_escort.run import OCR_REMAIN, MaritimeEscort
from module.minigame.minigame import Minigame
from module.minigame.new_year_challenge import NewYearChallenge
from module.raid.profile import RAID_CLIENT_PROFILES, RaidRunPlan
from module.raid.run import RaidRun
from module.reward.reward import Reward
from module.task_registry import command_to_config_name
from module.ui.assets import CAMPAIGN_MENU_NO_EVENT
from module.ui.page import page_campaign_menu, page_hospital

if TYPE_CHECKING:
    from module.application import CancellationSource
    from module.config.config_generated import ConfigOverrides
    from module.gameplay.emotion import EmotionSettings


class ActivityLiveClock(Protocol):
    def now(self) -> datetime: ...


class SystemActivityLiveClock:
    @staticmethod
    def now() -> datetime:
        return datetime.now(tz=UTC)


def _require_clock(clock: ActivityLiveClock) -> None:
    if isinstance(clock, type) or not callable(getattr(clock, "now", None)):
        message = "clock must implement now()"
        raise TypeError(message)


def _observed_at(clock: ActivityLiveClock) -> datetime:
    value = clock.now()
    if not isinstance(value, datetime):
        message = "activity live clock must return a datetime"
        raise TypeError(message)
    if value.utcoffset() is None:
        message = "activity live clock must return a timezone-aware datetime"
        raise ValueError(message)
    return value.astimezone(UTC)


def _legacy_deadline(value: datetime | None) -> datetime:
    if value is None:
        return DEFAULT_TIME
    return value.astimezone().replace(tzinfo=None)


def _apply_emotion_settings(config: AzurLaneConfig, settings: EmotionSettings) -> None:
    config.apply_runtime_overlay(**emotion_runtime_overlay(settings))


def _apply_encounter_policy(config: AzurLaneConfig, policy: EncounterPolicy) -> None:
    config.apply_runtime_overlay(
        StopCondition_OilLimit=policy.oil_limit,
        EventGeneral_PtLimit=policy.event_point_limit,
        EventGeneral_TimeLimit=_legacy_deadline(policy.event_deadline_at),
        Campaign_Use2xBook=policy.use_2x_book,
    )
    if policy.emotion is not None:
        _apply_emotion_settings(config, policy.emotion)


def _apply_balancer(config: AzurLaneConfig, policy: EncounterBalancerPolicy | None) -> None:
    if policy is None:
        config.apply_runtime_overlay(TaskBalancer_Enable=False)
        return
    config.apply_runtime_overlay(
        TaskBalancer_Enable=True,
        TaskBalancer_CoinLimit=policy.coin_limit,
        TaskBalancer_TaskCall=command_to_config_name(policy.target_task_id.value),
    )


def _recovery_at(value: datetime) -> datetime:
    if value.utcoffset() is None:
        value = value.astimezone()
    return value.astimezone(UTC)


class _Mumu12ActivityAdapter:
    __slots__ = ("_clock", "_config", "_delay_sampler", "_device")

    def __init__(
        self,
        config: AzurLaneConfig,
        device: Device,
        clock: ActivityLiveClock | None = None,
        *,
        delay_sampler: DelaySampler = runtime_delay_sampler,
    ) -> None:
        if not isinstance(config, AzurLaneConfig):
            message = "config must be an AzurLaneConfig"
            raise TypeError(message)
        if not isinstance(device, Device):
            message = "device must be a Device"
            raise TypeError(message)
        selected_clock = SystemActivityLiveClock() if clock is None else clock
        _require_clock(selected_clock)
        if not isinstance(delay_sampler, DelaySampler):
            message = "delay_sampler must be a DelaySampler"
            raise TypeError(message)
        self._config = config
        self._device = device
        self._clock = selected_clock
        self._delay_sampler = delay_sampler

    def _device_for(
        self,
        task_name: str,
        cancellation: CancellationSource,
        overlay: ConfigOverrides | None = None,
    ) -> Device:
        selected_overlay: ConfigOverrides = {} if overlay is None else overlay
        return activate_mumu12_task(self._config, self._device, task_name, selected_overlay, cancellation)

    def _now(self) -> datetime:
        return _observed_at(self._clock)

    def _failed(
        self,
        command: EncounterCommand,
        policy: EncounterPolicy,
        *,
        runs_completed: int = 0,
    ) -> EncounterReport:
        observed_at = self._now()
        return EncounterReport(
            command=command,
            stop_reason=EncounterStopReason.FAILED,
            observed_at=observed_at,
            runs_completed=runs_completed,
            resume_at=observed_at + self._delay_sampler.sample(policy.failure_retry_delay),
        )

    def _resource_limited(
        self,
        command: EncounterCommand,
        policy: EncounterPolicy,
        *,
        runs_completed: int = 0,
    ) -> EncounterReport:
        observed_at = self._now()
        return EncounterReport(
            command=command,
            stop_reason=EncounterStopReason.RESOURCE_LIMIT,
            observed_at=observed_at,
            runs_completed=runs_completed,
            resume_at=observed_at + policy.resource_retry_delay,
        )

    def _recovery_required(
        self,
        command: EncounterCommand,
        policy: EncounterPolicy,
        recovered_at: datetime,
    ) -> EncounterReport:
        observed_at = self._now()
        resume_at = _recovery_at(recovered_at)
        if resume_at <= observed_at:
            resume_at = observed_at + self._delay_sampler.sample(policy.failure_retry_delay)
        return EncounterReport(
            command=command,
            stop_reason=EncounterStopReason.RECOVERY_REQUIRED,
            observed_at=observed_at,
            runs_completed=0,
            resume_at=resume_at,
        )

    def _event_terminal(
        self,
        command: EncounterCommand,
        policy: EncounterPolicy,
    ) -> EncounterReport | None:
        deadline = policy.event_deadline_at
        observed_at = self._now()
        if deadline is None or observed_at <= deadline:
            return None
        return EncounterReport(command, EncounterStopReason.EVENT_LIMIT, observed_at, 0)

    @staticmethod
    def _event_available(
        runner: RaidRun | Coalition | Hospital,
        cancellation: CancellationSource,
    ) -> bool:
        cancellation.raise_if_requested()
        runner.ui_ensure(page_campaign_menu)
        cancellation.raise_if_requested()
        return not runner.appear(CAMPAIGN_MENU_NO_EVENT, offset=(20, 20))

    @staticmethod
    def _oil_limited(
        runner: RaidRun | Coalition,
        policy: EncounterPolicy,
        cancellation: CancellationSource,
    ) -> bool:
        cancellation.raise_if_requested()
        oil = runner.get_oil()
        return oil > 0 and oil < policy.effective_oil_limit

    @staticmethod
    def _points_limited(
        runner: RaidRun | Coalition | Hospital,
        policy: EncounterPolicy,
        cancellation: CancellationSource,
    ) -> bool:
        if policy.event_point_limit <= 0:
            return False
        cancellation.raise_if_requested()
        points = runner.get_event_pt()
        return points > 0 and points >= policy.event_point_limit

    @staticmethod
    def _balancer_limited(
        runner: RaidRun | Coalition,
        policy: EncounterBalancerPolicy | None,
        cancellation: CancellationSource,
    ) -> bool:
        if policy is None:
            return False
        cancellation.raise_if_requested()
        coin = runner.get_coin()
        return coin > 0 and coin < policy.coin_limit


class Mumu12MinigameWorkflow(_Mumu12ActivityAdapter, ActivityWorkflow):
    __slots__ = ()

    @override
    def execute(
        self,
        spec: ActivitySpec,
        cancellation: CancellationSource,
    ) -> ActivityReport:
        if spec.command is not ActivityCommand.MINIGAME:
            message = "minigame workflow requires a minigame spec"
            raise ValueError(message)
        runner = Minigame(self._config, device=self._device_for("Minigame", cancellation))
        cancellation.raise_if_requested()
        runner.minigame_enter_game_room()
        cancellation.raise_if_requested()
        runner.go_to_main_page()
        cancellation.raise_if_requested()
        coin_count = runner.get_coin_amount()
        if coin_count <= 30:
            cancellation.raise_if_requested()
            if runner.collect_coin():
                cancellation.raise_if_requested()
                coin_count = runner.get_coin_amount(skip_first_screenshot=False)

        if coin_count <= 0 or spec.remaining_operations == 0:
            return ActivityReport(ActivityCommand.MINIGAME, ActivityDisposition.COMPLETED, self._now(), 0)
        if spec.minigame_kind is not MinigameKind.NEW_YEAR_CHALLENGE:
            message = f"unsupported minigame: {spec.minigame_kind}"
            raise ValueError(message)

        player = NewYearChallenge(config=self._config, device=runner.device)
        cancellation.raise_if_requested()
        played = player.minigame_run()
        if not played:
            return ActivityReport(ActivityCommand.MINIGAME, ActivityDisposition.COMPLETED, self._now(), 0)
        disposition = ActivityDisposition.IN_PROGRESS
        if spec.remaining_operations == 1:
            disposition = ActivityDisposition.COMPLETED
        return ActivityReport(ActivityCommand.MINIGAME, disposition, self._now(), 1)


class Mumu12EventStoryWorkflow(_Mumu12ActivityAdapter, ActivityWorkflow):
    __slots__ = ()

    @override
    def execute(
        self,
        spec: ActivitySpec,
        cancellation: CancellationSource,
    ) -> ActivityReport:
        if spec.command is not ActivityCommand.EVENT_STORY or spec.activity is None or spec.skip_battle is None:
            message = "event story workflow requires an event_story spec"
            raise ValueError(message)
        definition = spec.activity.definition
        if not definition.available:
            return ActivityReport(ActivityCommand.EVENT_STORY, ActivityDisposition.UNAVAILABLE, self._now(), 0)
        profile_id = definition.profile_id
        if profile_id is None:
            message = "available event story definition requires a profile id"
            raise ValueError(message)
        profile = EVENT_STORY_CLIENT_PROFILES.resolve(profile_id)
        runner = EventStory(
            self._config,
            profile=profile,
            device=self._device_for(
                "EventStory",
                cancellation,
                {
                    "Campaign_Event": spec.activity.content_id.value,
                    "EventStory_SkipBattle": spec.skip_battle,
                    "STORY_ALLOW_SKIP": True,
                },
            ),
        )
        cancellation.raise_if_requested()
        if not runner.device.app_is_running():
            cancellation.raise_if_requested()
            runner.app_start()

        for _ in range(100):
            cancellation.raise_if_requested()
            state = runner.ui_goto_event_story()
            if state == "finish":
                return ActivityReport(ActivityCommand.EVENT_STORY, ActivityDisposition.COMPLETED, self._now(), 0)
            cancellation.raise_if_requested()
            result = runner.event_story()
            if result == "finish":
                continue
            if spec.skip_battle:
                self._config.apply_runtime_overlay(Error_HandleError=True)
                cancellation.raise_if_requested()
                runner.app_stop()
                cancellation.raise_if_requested()
                runner.app_start()
                continue
            cancellation.raise_if_requested()
            runner.combat(balance_hp=False)
        message = "event story exceeded the bounded 100-unit execution budget"
        raise HumanTakeoverRequiredError(message)


class Mumu12RaidDailyWorkflow(_Mumu12ActivityAdapter, EncounterWorkflow):
    __slots__ = ()

    @override
    def execute(self, spec: EncounterSpec, cancellation: CancellationSource) -> EncounterReport:
        if spec.command is not EncounterCommand.RAID_DAILY or not isinstance(spec.options, RaidDailyOptions):
            message = "raid daily workflow requires a raid_daily spec"
            raise ValueError(message)
        options = spec.options
        resolved = RAID_CLIENT_PROFILES.bind(options.activity)
        if not options.activity.definition.supports_daily:
            return EncounterReport(spec.command, EncounterStopReason.NO_DAILY_CONTENT, self._now(), 0)
        plans = tuple(
            resolved.daily_plan(
                stage,
                use_ticket=options.use_ticket and stage in options.activity.definition.ticket_modes,
            )
            for stage in options.stages
        )
        runner = RaidRun(
            self._config,
            profile=resolved,
            device=self._device_for("RaidDaily", cancellation),
        )
        preflight = self._prepare(runner, spec, options, cancellation)
        if preflight is not None:
            return preflight
        return self._advance_stage(runner, plans, spec, options, cancellation)

    def _prepare(
        self,
        runner: RaidRun,
        spec: EncounterSpec,
        options: RaidDailyOptions,
        cancellation: CancellationSource,
    ) -> EncounterReport | None:
        policy = options.policy
        terminal = self._event_terminal(spec.command, policy)
        if terminal is not None:
            return terminal
        self._config.apply_runtime_overlay(
            Campaign_Event=options.activity.content_id.value,
        )
        _apply_encounter_policy(self._config, policy)
        _apply_balancer(self._config, None)
        if not self._event_available(runner, cancellation):
            return EncounterReport(spec.command, EncounterStopReason.EVENT_UNAVAILABLE, self._now(), 0)
        if self._oil_limited(runner, policy, cancellation):
            return self._resource_limited(spec.command, policy)
        cancellation.raise_if_requested()
        runner.ensure_landing()
        if self._points_limited(runner, policy, cancellation):
            return EncounterReport(spec.command, EncounterStopReason.EVENT_LIMIT, self._now(), 0)
        return None

    def _advance_stage(
        self,
        runner: RaidRun,
        plans: tuple[RaidRunPlan, ...],
        spec: EncounterSpec,
        options: RaidDailyOptions,
        cancellation: CancellationSource,
    ) -> EncounterReport:
        standard_plans = tuple(plan for plan in plans if plan.mode is not RaidMode.EX)
        for plan in standard_plans:
            cancellation.raise_if_requested()
            if runner.get_attempt_status(plan).exhausted:
                continue
            return self._execute_one(runner, plan, spec, options, cancellation)

        ex_plan = next((plan for plan in plans if plan.mode is RaidMode.EX), None)
        if ex_plan is not None:
            cancellation.raise_if_requested()
            runner.ui_goto_main()
            cancellation.raise_if_requested()
            Reward(self._config, runner.device).reward_mission(
                daily=options.collect_daily_mission,
                weekly=False,
            )
            cancellation.raise_if_requested()
            runner.ensure_landing()
            cancellation.raise_if_requested()
            if not runner.get_attempt_status(ex_plan).exhausted:
                return self._execute_one(runner, ex_plan, spec, options, cancellation)
        return EncounterReport(spec.command, EncounterStopReason.COMPLETED, self._now(), 0)

    def _execute_one(
        self,
        runner: RaidRun,
        plan: RaidRunPlan,
        spec: EncounterSpec,
        options: RaidDailyOptions,
        cancellation: CancellationSource,
    ) -> EncounterReport:
        recovered_at = runner.emotion.recovery_at(1)
        if recovered_at is not None:
            return self._recovery_required(spec.command, options.policy, recovered_at)
        cancellation.raise_if_requested()
        try:
            runner.execute_once(plan)
        except OilExhausted:
            return self._resource_limited(spec.command, options.policy)
        except CampaignSelectionError:
            return self._failed(spec.command, options.policy)
        return EncounterReport(spec.command, EncounterStopReason.IN_PROGRESS, self._now(), 1)


class Mumu12MaritimeEscortWorkflow(_Mumu12ActivityAdapter, EncounterWorkflow):
    __slots__ = ()

    @override
    def execute(self, spec: EncounterSpec, cancellation: CancellationSource) -> EncounterReport:
        if spec.command is not EncounterCommand.MARITIME_ESCORT or not isinstance(spec.options, MaritimeEscortOptions):
            message = "maritime escort workflow requires a maritime_escort spec"
            raise ValueError(message)
        policy = spec.options.policy
        terminal = self._event_terminal(spec.command, policy)
        if terminal is not None:
            return terminal
        runner = MaritimeEscort(self._config, device=self._device_for("MaritimeEscort", cancellation))
        _apply_encounter_policy(self._config, policy)
        _apply_balancer(self._config, None)
        try:
            cancellation.raise_if_requested()
            runner.ui_goto_main()
            cancellation.raise_if_requested()
            runner.ui_click(
                event_assets.MAIN_GOTO_ESCORT,
                check_button=event_assets.ESCORT_CHECK,
                offset=(20, 150),
                skip_first_screenshot=True,
            )
            cancellation.raise_if_requested()
            current, _, _ = OCR_REMAIN.ocr(runner.device.image)
            if current <= 0:
                return EncounterReport(spec.command, EncounterStopReason.COMPLETED, self._now(), 0)
            cancellation.raise_if_requested()
            result = runner.execute_once()
        except CampaignSelectionError:
            return self._failed(spec.command, policy)
        if not isinstance(result, MaritimeEscortExecutionResult):
            message = "MaritimeEscort.execute_once() must return MaritimeEscortExecutionResult"
            raise TypeError(message)
        if result.status is MaritimeEscortExecutionStatus.WITHDRAWAL_COMPLETED:
            runs_completed = 1
        elif result.status is MaritimeEscortExecutionStatus.ATTEMPTS_EXHAUSTED:
            runs_completed = 0
        else:
            message = f"unsupported maritime escort execution status: {result.status}"
            raise RuntimeError(message)
        return EncounterReport(spec.command, EncounterStopReason.COMPLETED, self._now(), runs_completed)


class Mumu12RaidWorkflow(_Mumu12ActivityAdapter, EncounterWorkflow):
    __slots__ = ()

    @override
    def execute(self, spec: EncounterSpec, cancellation: CancellationSource) -> EncounterReport:
        if spec.command is not EncounterCommand.RAID or not isinstance(spec.options, RaidOptions):
            message = "raid workflow requires a raid spec"
            raise ValueError(message)
        options = spec.options
        resolved = RAID_CLIENT_PROFILES.bind(options.activity)
        plan = resolved.plan(options.mode, use_ticket=options.use_ticket)
        runner = RaidRun(
            self._config,
            profile=resolved,
            device=self._device_for("Raid", cancellation),
        )
        preflight = self._prepare(runner, plan, spec, options, cancellation)
        if preflight is not None:
            return preflight
        return self._execute_one(runner, plan, spec, options, cancellation)

    def _prepare(
        self,
        runner: RaidRun,
        plan: RaidRunPlan,
        spec: EncounterSpec,
        options: RaidOptions,
        cancellation: CancellationSource,
    ) -> EncounterReport | None:
        policy = options.policy
        terminal = self._event_terminal(spec.command, policy)
        if terminal is not None:
            return terminal
        self._config.apply_runtime_overlay(
            Campaign_Event=options.activity.content_id.value,
            Raid_Mode=options.mode.value,
        )
        _apply_encounter_policy(self._config, policy)
        _apply_balancer(self._config, spec.balancer)
        if not self._event_available(runner, cancellation):
            return EncounterReport(spec.command, EncounterStopReason.EVENT_UNAVAILABLE, self._now(), 0)
        if self._oil_limited(runner, policy, cancellation):
            return self._resource_limited(spec.command, policy)
        if self._balancer_limited(runner, spec.balancer, cancellation):
            return self._balanced(spec)
        cancellation.raise_if_requested()
        runner.ensure_landing()
        return self._page_terminal(runner, plan, spec, options, cancellation)

    def _page_terminal(
        self,
        runner: RaidRun,
        plan: RaidRunPlan,
        spec: EncounterSpec,
        options: RaidOptions,
        cancellation: CancellationSource,
    ) -> EncounterReport | None:
        if self._points_limited(runner, options.policy, cancellation):
            return EncounterReport(spec.command, EncounterStopReason.EVENT_LIMIT, self._now(), 0)
        if plan.mode is RaidMode.EX:
            cancellation.raise_if_requested()
            if runner.get_attempt_status(plan).exhausted:
                return EncounterReport(spec.command, EncounterStopReason.ATTEMPTS_EXHAUSTED, self._now(), 0)
        return None

    def _execute_one(
        self,
        runner: RaidRun,
        plan: RaidRunPlan,
        spec: EncounterSpec,
        options: RaidOptions,
        cancellation: CancellationSource,
    ) -> EncounterReport:
        policy = options.policy
        recovered_at = runner.emotion.recovery_at(1)
        if recovered_at is not None:
            return self._recovery_required(spec.command, policy, recovered_at)
        cancellation.raise_if_requested()
        try:
            runner.execute_once(plan)
        except OilExhausted:
            return self._resource_limited(spec.command, policy)
        except CampaignSelectionError:
            return self._failed(spec.command, policy)
        stop = EncounterStopReason.RUN_LIMIT if spec.remaining_runs == 1 else EncounterStopReason.IN_PROGRESS
        return EncounterReport(spec.command, stop, self._now(), 1)

    def _balanced(self, spec: EncounterSpec) -> EncounterReport:
        policy = spec.balancer
        if policy is None:
            message = "balanced report requires a balancer policy"
            raise ValueError(message)
        observed_at = self._now()
        return EncounterReport(
            spec.command,
            EncounterStopReason.BALANCER_SWITCH,
            observed_at,
            0,
            resume_at=observed_at + policy.retry_delay,
        )


class Mumu12HospitalWorkflow(_Mumu12ActivityAdapter, EncounterWorkflow):
    __slots__ = ()

    @override
    def execute(self, spec: EncounterSpec, cancellation: CancellationSource) -> EncounterReport:
        if spec.command is not EncounterCommand.HOSPITAL or not isinstance(spec.options, HospitalOptions):
            message = "hospital workflow requires a hospital spec"
            raise ValueError(message)
        options = spec.options
        runner = Hospital(self._config, device=self._device_for("Hospital", cancellation))
        preflight = self._prepare(runner, spec, options, cancellation)
        if preflight is not None:
            return preflight
        return self._advance_investigation(runner, spec, options, cancellation)

    def _prepare(
        self,
        runner: Hospital,
        spec: EncounterSpec,
        options: HospitalOptions,
        cancellation: CancellationSource,
    ) -> EncounterReport | None:
        policy = options.policy
        terminal = self._event_terminal(spec.command, policy)
        if terminal is not None:
            return terminal
        self._config.apply_runtime_overlay(
            Hospital_UseRecommendFleet=options.use_recommended_fleet,
            TaskBalancer_Enable=False,
        )
        _apply_encounter_policy(self._config, policy)
        if not self._event_available(runner, cancellation):
            return EncounterReport(spec.command, EncounterStopReason.EVENT_UNAVAILABLE, self._now(), 0)
        cancellation.raise_if_requested()
        runner.ui_goto(page_hospital)
        if self._points_limited(runner, policy, cancellation):
            return EncounterReport(spec.command, EncounterStopReason.EVENT_LIMIT, self._now(), 0)
        cancellation.raise_if_requested()
        if runner.daily_reward_receive():
            return EncounterReport(spec.command, EncounterStopReason.IN_PROGRESS, self._now(), 0)
        cancellation.raise_if_requested()
        runner.clue_enter()
        return None

    def _advance_investigation(
        self,
        runner: Hospital,
        spec: EncounterSpec,
        options: HospitalOptions,
        cancellation: CancellationSource,
    ) -> EncounterReport:
        for tab, swipe in (("LOCATION", False), ("CHARACTER", False), ("CHARACTER", True)):
            cancellation.raise_if_requested()
            HOSPITAL_TAB.set(tab, main=runner)
            if swipe:
                cancellation.raise_if_requested()
                runner.aside_swipe_down()
            cancellation.raise_if_requested()
            if not runner.select_aside():
                continue
            return self._execute_selected(runner, spec, options.policy, cancellation)
        cancellation.raise_if_requested()
        runner.clue_exit()
        return EncounterReport(spec.command, EncounterStopReason.COMPLETED, self._now(), 0)

    def _execute_selected(
        self,
        runner: Hospital,
        spec: EncounterSpec,
        policy: EncounterPolicy,
        cancellation: CancellationSource,
    ) -> EncounterReport:
        recovered_at = runner.emotion.recovery_at(1)
        if recovered_at is not None:
            return self._recovery_required(spec.command, policy, recovered_at)
        try:
            cancellation.raise_if_requested()
            executed = runner.execute_selected_investigation_once()
        except OilExhausted:
            return self._resource_limited(spec.command, policy)
        except CampaignSelectionError:
            return self._failed(spec.command, policy)
        stop = EncounterStopReason.IN_PROGRESS if executed else EncounterStopReason.COMPLETED
        return EncounterReport(spec.command, stop, self._now(), int(executed))


class Mumu12CoalitionWorkflow(_Mumu12ActivityAdapter, EncounterWorkflow):
    __slots__ = ("_command",)

    def __init__(
        self,
        config: AzurLaneConfig,
        device: Device,
        command: EncounterCommand,
        clock: ActivityLiveClock | None = None,
    ) -> None:
        if command not in {EncounterCommand.COALITION, EncounterCommand.COALITION_SP}:
            message = "coalition workflow command must be coalition or coalition_sp"
            raise ValueError(message)
        super().__init__(config, device, clock)
        self._command = command

    @override
    def execute(self, spec: EncounterSpec, cancellation: CancellationSource) -> EncounterReport:
        if spec.command is not self._command or not isinstance(spec.options, CoalitionOptions):
            message = f"coalition workflow requires a {self._command.value} spec"
            raise ValueError(message)
        options = spec.options
        client = COALITION_CLIENT_PROFILES.resolve(
            options.activity,
            options.stage,
            options.fleet,
        )
        task_name = "Coalition" if self._command is EncounterCommand.COALITION else "CoalitionSp"
        runner = Coalition(
            self._config,
            device=self._device_for(task_name, cancellation),
            client=client,
        )
        preflight = self._prepare(runner, client, spec, options, cancellation)
        if preflight is not None:
            return preflight
        return self._execute_one(runner, client, spec, options, cancellation)

    def _prepare(
        self,
        runner: Coalition,
        client: CoalitionClientSession,
        spec: EncounterSpec,
        options: CoalitionOptions,
        cancellation: CancellationSource,
    ) -> EncounterReport | None:
        policy = options.policy
        terminal = self._event_terminal(spec.command, policy)
        if terminal is not None:
            return terminal
        self._config.apply_runtime_overlay(
            Campaign_Event=options.activity.content_id.value,
            Coalition_Mode=options.stage.value,
            Coalition_Fleet=options.fleet.value,
            StopCondition_RunCount=spec.remaining_runs or 0,
        )
        _apply_encounter_policy(self._config, policy)
        _apply_balancer(self._config, spec.balancer)
        campaign_menu_stop = self._campaign_menu_stop(runner, client, spec, cancellation)
        if campaign_menu_stop is not None:
            return campaign_menu_stop
        cancellation.raise_if_requested()
        runner.device.stuck_record_clear()
        cancellation.raise_if_requested()
        runner.device.click_record_clear()
        cancellation.raise_if_requested()
        runner.ui_goto_coalition()
        cancellation.raise_if_requested()
        runner.coalition_ensure_mode(CoalitionPageMode.BATTLE)
        return self._coalition_page_stop(runner, client, spec, cancellation)

    def _campaign_menu_stop(
        self,
        runner: Coalition,
        client: CoalitionClientSession,
        spec: EncounterSpec,
        cancellation: CancellationSource,
    ) -> EncounterReport | None:
        if not self._event_available(runner, cancellation):
            return EncounterReport(spec.command, EncounterStopReason.EVENT_UNAVAILABLE, self._now(), 0)
        if client.profile.oil_read_location is CoalitionOilReadLocation.CAMPAIGN_MENU and self._oil_limited(
            runner, spec.options.policy, cancellation
        ):
            return self._resource_limited(spec.command, spec.options.policy)
        if self._balancer_limited(runner, spec.balancer, cancellation):
            return self._balanced(spec)
        return None

    def _coalition_page_stop(
        self,
        runner: Coalition,
        client: CoalitionClientSession,
        spec: EncounterSpec,
        cancellation: CancellationSource,
    ) -> EncounterReport | None:
        options = spec.options
        if not isinstance(options, CoalitionOptions):
            message = "coalition page stop requires coalition options"
            raise TypeError(message)
        if client.profile.oil_read_location is CoalitionOilReadLocation.COALITION and self._oil_limited(
            runner, options.policy, cancellation
        ):
            return self._resource_limited(spec.command, options.policy)
        if self._points_limited(runner, options.policy, cancellation):
            return EncounterReport(spec.command, EncounterStopReason.EVENT_LIMIT, self._now(), 0)
        return None

    def _execute_one(
        self,
        runner: Coalition,
        client: CoalitionClientSession,
        spec: EncounterSpec,
        options: CoalitionOptions,
        cancellation: CancellationSource,
    ) -> EncounterReport:
        policy = options.policy
        recovered_at = runner.emotion.recovery_at(client.stage.battle_count)
        if recovered_at is not None:
            return self._recovery_required(spec.command, policy, recovered_at)
        try:
            cancellation.raise_if_requested()
            runner.coalition_execute_once()
        except OilExhausted:
            return self._resource_limited(spec.command, policy)
        except CampaignSelectionError:
            return self._failed(spec.command, policy)
        if spec.command is EncounterCommand.COALITION_SP:
            return EncounterReport(spec.command, EncounterStopReason.COMPLETED, self._now(), 1)
        stop = EncounterStopReason.RUN_LIMIT if spec.remaining_runs == 1 else EncounterStopReason.IN_PROGRESS
        return EncounterReport(spec.command, stop, self._now(), 1)

    def _balanced(self, spec: EncounterSpec) -> EncounterReport:
        policy = spec.balancer
        if policy is None:
            message = "balanced report requires a balancer policy"
            raise ValueError(message)
        observed_at = self._now()
        return EncounterReport(
            spec.command,
            EncounterStopReason.BALANCER_SWITCH,
            observed_at,
            0,
            resume_at=observed_at + policy.retry_delay,
        )


class Mumu12DaemonWorkflow(_Mumu12ActivityAdapter, AssistSessionWorkflow):
    __slots__ = ()

    @override
    def advance_to_safe_point(
        self,
        spec: AssistSessionSpec,
        cancellation: CancellationSource,
    ) -> AssistSessionReport:
        if spec.command is not AssistSessionCommand.DAEMON or not isinstance(spec.options, DaemonOptions):
            message = "daemon workflow requires a daemon spec"
            raise ValueError(message)
        runner = StandardDaemon(self._config, device=self._device_for("Daemon", cancellation))
        self._config.apply_runtime_overlay(Daemon_EnterMap=spec.options.enter_map)
        cancellation.raise_if_requested()
        completed = runner.advance_once()
        state = AssistSessionState.COMPLETED if completed else AssistSessionState.CONTINUE
        return AssistSessionReport(spec.command, state)


class Mumu12OpsiDaemonWorkflow(_Mumu12ActivityAdapter, AssistSessionWorkflow):
    __slots__ = ()

    @override
    def advance_to_safe_point(
        self,
        spec: AssistSessionSpec,
        cancellation: CancellationSource,
    ) -> AssistSessionReport:
        if spec.command is not AssistSessionCommand.OPSI_DAEMON or not isinstance(spec.options, OpsiDaemonOptions):
            message = "opsi daemon workflow requires an opsi_daemon spec"
            raise ValueError(message)
        runner = OpsiDaemon(self._config, device=self._device_for("OpsiDaemon", cancellation))
        runner.prepare_os_daemon_config()
        self._config.apply_runtime_overlay(
            OpsiDaemon_RepairShip=spec.options.repair_ship,
            OpsiDaemon_SelectEnemy=spec.options.select_enemy,
        )
        cancellation.raise_if_requested()
        runner.advance_once()
        return AssistSessionReport(spec.command, AssistSessionState.CONTINUE)


def build_mumu12_activity_workflows(
    config: AzurLaneConfig,
    device: Device,
    *,
    clock: ActivityLiveClock | None = None,
) -> ActivityWorkflows:
    """组装十个 activity/encounter/assist 的生产 MuMu12 workflow。"""
    return ActivityWorkflows(
        minigame=Mumu12MinigameWorkflow(config, device, clock),
        event_story=Mumu12EventStoryWorkflow(config, device, clock),
        raid_daily=Mumu12RaidDailyWorkflow(config, device, clock),
        maritime_escort=Mumu12MaritimeEscortWorkflow(config, device, clock),
        raid=Mumu12RaidWorkflow(config, device, clock),
        hospital=Mumu12HospitalWorkflow(config, device, clock),
        coalition=Mumu12CoalitionWorkflow(config, device, EncounterCommand.COALITION, clock),
        coalition_sp=Mumu12CoalitionWorkflow(config, device, EncounterCommand.COALITION_SP, clock),
        daemon=Mumu12DaemonWorkflow(config, device, clock),
        opsi_daemon=Mumu12OpsiDaemonWorkflow(config, device, clock),
    )
