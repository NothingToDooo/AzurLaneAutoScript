from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Protocol, override

from module.application import AbortRequested
from module.base.failure import preserve_cleanup_failure
from module.content import battle_program as program_model
from module.content.campaign_session import (
    BattleAttempt,
    BattleFailed,
    BattlefieldObservation,
    BattleInterrupted,
    BattleInterruptionReason,
    BattleOutcome,
    BattleSucceeded,
    BattleTarget,
    CampaignRunVariant,
    CampaignSession,
    CampaignSessionState,
    CampaignSessionStatus,
    NoBattleTarget,
)
from module.content.stage_rules import OneTimeCompletion
from module.gameplay.battle_program import BattleProgramExecution, BattleProgramReducer
from module.gameplay.campaign import (
    CampaignJobKind,
    CampaignJobSpec,
    CampaignRunReport,
    CampaignStopReason,
    CampaignWorkflow,
    GemsFleetReplacementBoundary,
    GemsFleetReplacementRequest,
    GemsFleetReplacementTrigger,
)
from module.gameplay.campaign_battle_program import (
    default_mode_battle_program,
    select_battle_program,
)

if TYPE_CHECKING:
    from module.application import CancellationSource
    from module.content.battle_program import BattleProgram
    from module.content.models import StageRef


def _require_method(value: object, method_name: str, *, field_name: str) -> None:
    if isinstance(value, type) or not callable(getattr(value, method_name, None)):
        message = f"{field_name} must implement {method_name}()"
        raise TypeError(message)


def _validate_observed_at(value: datetime) -> None:
    if not isinstance(value, datetime):
        message = "campaign live clock must return a datetime"
        raise TypeError(message)
    if value.tzinfo is None or value.utcoffset() is None:
        message = "campaign live clock must return a timezone-aware datetime"
        raise ValueError(message)


class CampaignBattlefieldObserver(Protocol):
    def observe(
        self,
        session: CampaignSession,
        state: CampaignSessionState,
        cancellation: CancellationSource,
    ) -> BattlefieldObservation: ...


class CampaignBattleIntentDriver(Protocol):
    def issue_and_confirm(
        self,
        session: CampaignSession,
        state: CampaignSessionState,
        cancellation: CancellationSource,
    ) -> BattleOutcome: ...


class CampaignAutoSearchBattleExecutor(Protocol):
    def execute(
        self,
        session: CampaignSession,
        state: CampaignSessionState,
        cancellation: CancellationSource,
    ) -> BattleTarget: ...


class CampaignBattleProgramExecutor(Protocol):
    def mode(
        self,
        session: CampaignSession,
        state: CampaignSessionState,
        cancellation: CancellationSource,
    ) -> program_model.BattleProgramMode: ...

    def execute(
        self,
        program: BattleProgram,
        session: CampaignSession,
        state: CampaignSessionState,
        cancellation: CancellationSource,
    ) -> BattleProgramExecution: ...


class CampaignRuntimeLifecycle(Protocol):
    def discard_checkpoint(self) -> None: ...

    def finish(
        self,
        session: CampaignSession,
        state: CampaignSessionState,
        stop_reason: CampaignStopReason,
    ) -> None: ...


class CampaignGuardPhase(StrEnum):
    PRE_ENTRY = "pre_entry"
    POST_BATTLE = "post_battle"


@dataclass(frozen=True, slots=True)
class CampaignGuardEvidence:
    """边界适配器采集事实；所有停止规则都在纯 policy 中解释。"""

    phase: CampaignGuardPhase
    oil: int | None = None
    event_points: int | None = None
    event_available: bool | None = None
    data_keys_remaining: int | None = None
    coin: int | None = None
    resuming_checkpoint: bool = False
    reach_level_limit: bool = False
    new_ship: bool = False
    auto_search_oil_limit: bool = False
    auto_search_coin_limit: bool = False
    emotion_bug: bool = False
    one_time_stage: bool = False
    gems_level_limit: bool = False
    gems_emotion_limit: bool = False
    map_is_100_percent_clear: bool = False
    map_is_3_stars: bool = False
    map_is_threat_safe: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.phase, CampaignGuardPhase):
            message = "campaign guard phase must be a CampaignGuardPhase"
            raise TypeError(message)
        for field_name in ("oil", "event_points", "data_keys_remaining", "coin"):
            value = getattr(self, field_name)
            if value is not None and (type(value) is not int or value < 0):
                message = f"campaign guard {field_name} must be a non-negative integer or None"
                raise ValueError(message)
        if self.event_available is not None and type(self.event_available) is not bool:
            message = "campaign guard event_available must be a bool or None"
            raise TypeError(message)
        boolean_fields = (
            "resuming_checkpoint",
            "reach_level_limit",
            "new_ship",
            "auto_search_oil_limit",
            "auto_search_coin_limit",
            "emotion_bug",
            "one_time_stage",
            "gems_level_limit",
            "gems_emotion_limit",
            "map_is_100_percent_clear",
            "map_is_3_stars",
            "map_is_threat_safe",
        )
        if any(type(getattr(self, field_name)) is not bool for field_name in boolean_fields):
            message = "campaign guard flags must be bool values"
            raise TypeError(message)
        if self.phase is CampaignGuardPhase.PRE_ENTRY and any(
            getattr(self, field_name)
            for field_name in (
                "reach_level_limit",
                "new_ship",
                "auto_search_oil_limit",
                "auto_search_coin_limit",
                "emotion_bug",
                "one_time_stage",
                "gems_level_limit",
                "map_is_100_percent_clear",
                "map_is_3_stars",
                "map_is_threat_safe",
            )
        ):
            message = "pre-entry campaign evidence cannot contain post-battle flags"
            raise ValueError(message)
        if self.phase is CampaignGuardPhase.POST_BATTLE and any(
            value is not None
            for value in (
                self.oil,
                self.event_points,
                self.event_available,
                self.data_keys_remaining,
                self.coin,
            )
        ):
            message = "post-battle campaign evidence cannot contain pre-entry resources"
            raise ValueError(message)
        if self.phase is CampaignGuardPhase.POST_BATTLE and self.resuming_checkpoint:
            message = "post-battle campaign evidence cannot resume a checkpoint"
            raise ValueError(message)


class CampaignGuardEvidenceSource(Protocol):
    def before_entry(
        self,
        job: CampaignJobSpec,
        session: CampaignSession,
        state: CampaignSessionState,
        cancellation: CancellationSource,
    ) -> CampaignGuardEvidence:
        """在尚未消耗本局资源时采集 UI/OCR 事实。"""

    def after_battle(
        self,
        job: CampaignJobSpec,
        session: CampaignSession,
        state: CampaignSessionState,
    ) -> CampaignGuardEvidence:
        """只读取已闭合 battle 的内存事实，不执行外部 I/O。"""


@dataclass(frozen=True, slots=True)
class GemsFleetReplacementCompleted:
    """旗舰及可选前排已经全部替换，配置记录也已闭合。"""


@dataclass(frozen=True, slots=True)
class GemsFleetReplacementFailed:
    reason: str

    def __post_init__(self) -> None:
        if not isinstance(self.reason, str) or not self.reason.strip():
            message = "gems fleet replacement failure requires a non-empty reason"
            raise TypeError(message)


type GemsFleetReplacementResult = GemsFleetReplacementCompleted | GemsFleetReplacementFailed


class GemsFleetReplacementExecutor(Protocol):
    def replace(
        self,
        job: CampaignJobSpec,
        session: CampaignSession,
        trigger: GemsFleetReplacementTrigger,
        cancellation: CancellationSource,
    ) -> GemsFleetReplacementResult: ...


@dataclass(frozen=True, slots=True)
class CampaignGuardDecision:
    stop_reason: CampaignStopReason | None = None
    gems_replacement: GemsFleetReplacementTrigger | None = None
    use_gems_fallback: bool = False

    def __post_init__(self) -> None:
        if self.stop_reason is not None and not isinstance(self.stop_reason, CampaignStopReason):
            message = "campaign guard stop_reason must be a CampaignStopReason or None"
            raise TypeError(message)
        if self.gems_replacement is not None and not isinstance(
            self.gems_replacement,
            GemsFleetReplacementTrigger,
        ):
            message = "campaign guard gems_replacement must be a GemsFleetReplacementTrigger or None"
            raise TypeError(message)
        if type(self.use_gems_fallback) is not bool:
            message = "campaign guard use_gems_fallback must be a bool"
            raise TypeError(message)
        selected = sum(
            (
                self.stop_reason is not None,
                self.gems_replacement is not None,
                self.use_gems_fallback,
            )
        )
        if selected > 1:
            message = "campaign guard decision must contain at most one action"
            raise ValueError(message)


class CampaignGuardPolicy:
    @staticmethod
    def evaluate(
        job: CampaignJobSpec,
        session: CampaignSession,
        state: CampaignSessionState,
        evidence: CampaignGuardEvidence,
        observed_at: datetime,
    ) -> CampaignGuardDecision:
        if not isinstance(job, CampaignJobSpec):
            message = "campaign guard policy requires a CampaignJobSpec"
            raise TypeError(message)
        if not isinstance(session, CampaignSession):
            message = "campaign guard policy requires a CampaignSession"
            raise TypeError(message)
        session.validate_state(state)
        if not isinstance(evidence, CampaignGuardEvidence):
            message = "campaign guard policy requires CampaignGuardEvidence"
            raise TypeError(message)
        _validate_observed_at(observed_at)
        if evidence.phase is CampaignGuardPhase.PRE_ENTRY:
            return CampaignGuardPolicy._pre_entry(job, session, evidence, observed_at)
        return CampaignGuardPolicy._post_battle(job, session, state, evidence)

    @staticmethod
    def _event_limits_apply(job: CampaignJobSpec, session: CampaignSession) -> bool:
        return (
            job.kind
            in (
                CampaignJobKind.EVENT,
                CampaignJobKind.EVENT_SP,
                CampaignJobKind.EVENT_DAILY,
                CampaignJobKind.GEMS_FARMING,
            )
            and session.definition.ref.pack_id != "campaign_main"
        )

    @staticmethod
    def _event_decision(job: CampaignJobSpec, reason: CampaignStopReason) -> CampaignGuardDecision:
        if job.kind is CampaignJobKind.GEMS_FARMING:
            return CampaignGuardDecision(use_gems_fallback=True)
        return CampaignGuardDecision(stop_reason=reason)

    @staticmethod
    def _pre_entry(
        job: CampaignJobSpec,
        session: CampaignSession,
        evidence: CampaignGuardEvidence,
        observed_at: datetime,
    ) -> CampaignGuardDecision:
        if evidence.resuming_checkpoint:
            return CampaignGuardDecision()
        event_limits_apply = CampaignGuardPolicy._event_limits_apply(job, session)
        deadline = job.limits.event_deadline_at
        runs_completed = 0 if job.progress is None else job.progress.runs_completed
        balancer = job.task_balancer
        completion = job.completion_for(session.definition.ref)
        checks = (
            (
                event_limits_apply and deadline is not None and observed_at > deadline,
                CampaignGuardPolicy._event_decision(job, CampaignStopReason.EVENT_TIME_LIMIT),
            ),
            (
                event_limits_apply and evidence.event_available is False,
                CampaignGuardPolicy._event_decision(job, CampaignStopReason.EVENT_UNAVAILABLE),
            ),
            (
                job.kind is CampaignJobKind.WAR_ARCHIVES and evidence.data_keys_remaining == 0,
                CampaignGuardDecision(stop_reason=CampaignStopReason.DATA_KEYS_EXHAUSTED),
            ),
            (
                not completion.resource_free
                and evidence.oil is not None
                and evidence.oil < job.limits.effective_oil_limit,
                CampaignGuardDecision(stop_reason=CampaignStopReason.OIL_LIMIT),
            ),
            (
                event_limits_apply
                and bool(job.limits.event_points)
                and evidence.event_points is not None
                and evidence.event_points >= job.limits.event_points,
                CampaignGuardPolicy._event_decision(job, CampaignStopReason.EVENT_POINT_LIMIT),
            ),
            (
                balancer is not None
                and runs_completed >= 1
                and evidence.coin not in (None, 0)
                and evidence.coin < balancer.coin_limit,
                CampaignGuardDecision(stop_reason=CampaignStopReason.COIN_LIMIT),
            ),
        )
        for triggered, decision in checks:
            if triggered:
                return decision
        if evidence.gems_emotion_limit and job.kind is CampaignJobKind.GEMS_FARMING:
            return CampaignGuardDecision(gems_replacement=GemsFleetReplacementTrigger.EMOTION)
        return CampaignGuardDecision()

    @staticmethod
    def _post_battle(
        job: CampaignJobSpec,
        session: CampaignSession,
        state: CampaignSessionState,
        evidence: CampaignGuardEvidence,
    ) -> CampaignGuardDecision:
        if state.status is not CampaignSessionStatus.COMPLETED:
            return CampaignGuardDecision()
        selection = job.selection_for(session.definition.ref)
        checks = (
            (
                evidence.gems_level_limit and job.kind is CampaignJobKind.GEMS_FARMING,
                CampaignGuardDecision(gems_replacement=GemsFleetReplacementTrigger.LEVEL),
            ),
            (
                evidence.gems_emotion_limit and job.kind is CampaignJobKind.GEMS_FARMING,
                CampaignGuardDecision(gems_replacement=GemsFleetReplacementTrigger.EMOTION),
            ),
            (
                bool(job.limits.reach_level) and evidence.reach_level_limit,
                CampaignGuardDecision(stop_reason=CampaignStopReason.REACH_LEVEL_LIMIT),
            ),
            (
                evidence.auto_search_oil_limit,
                CampaignGuardDecision(stop_reason=CampaignStopReason.AUTO_SEARCH_OIL_LIMIT),
            ),
            (
                job.limits.stop_on_new_ship and evidence.new_ship,
                CampaignGuardDecision(stop_reason=CampaignStopReason.NEW_SHIP),
            ),
            (
                job.task_balancer is not None and evidence.auto_search_coin_limit,
                CampaignGuardDecision(stop_reason=CampaignStopReason.COIN_LIMIT),
            ),
            (
                evidence.emotion_bug,
                CampaignGuardDecision(stop_reason=CampaignStopReason.EMOTION_BUG),
            ),
            (
                evidence.one_time_stage or isinstance(session.definition.rules.completion, OneTimeCompletion),
                CampaignGuardDecision(stop_reason=CampaignStopReason.ONE_TIME_STAGE),
            ),
            (
                selection is not None and selection.loop_stage_switch,
                CampaignGuardDecision(stop_reason=CampaignStopReason.LOOP_STAGE_SWITCH),
            ),
        )
        for triggered, decision in checks:
            if triggered:
                return decision
        return CampaignGuardDecision()


@dataclass(frozen=True, slots=True)
class CampaignCheckpointUnavailable:
    reason: str

    def __post_init__(self) -> None:
        if not isinstance(self.reason, str) or not self.reason.strip():
            message = "campaign checkpoint unavailable reason must be non-empty"
            raise ValueError(message)


@dataclass(frozen=True, slots=True)
class CampaignMapAchievementReached:
    full_clear: bool
    three_stars: bool
    threat_safe: bool

    def __post_init__(self) -> None:
        if any(type(value) is not bool for value in (self.full_clear, self.three_stars, self.threat_safe)):
            message = "campaign map achievement evidence must contain booleans"
            raise TypeError(message)


@dataclass(frozen=True, slots=True)
class CampaignGemsReplacementFailed:
    request: GemsFleetReplacementRequest
    reason: str

    def __post_init__(self) -> None:
        if not isinstance(self.request, GemsFleetReplacementRequest):
            message = "campaign gems replacement failure requires a typed request"
            raise TypeError(message)
        if not isinstance(self.reason, str) or not self.reason.strip():
            message = "campaign gems replacement failure requires a non-empty reason"
            raise TypeError(message)


class CampaignSessionActivator(Protocol):
    def activate(
        self,
        job: CampaignJobSpec,
        cancellation: CancellationSource,
    ) -> (
        CampaignSession | CampaignCheckpointUnavailable | CampaignMapAchievementReached | CampaignGemsReplacementFailed
    ):
        """进入目标关卡并返回客户端实际启用的 normal/loop session。"""


class CampaignLiveClock(Protocol):
    def now(self) -> datetime: ...


class SystemCampaignLiveClock:
    @staticmethod
    def now() -> datetime:
        return datetime.now().astimezone()


@dataclass(frozen=True, slots=True)
class CampaignLiveServices:
    activator: CampaignSessionActivator | None = None
    guards: CampaignGuardEvidenceSource | None = None
    programs: CampaignBattleProgramExecutor | None = None
    gems_fleets: GemsFleetReplacementExecutor | None = None
    lifecycle: CampaignRuntimeLifecycle | None = None

    def __post_init__(self) -> None:
        if self.activator is not None:
            _require_method(self.activator, "activate", field_name="activator")
        if self.guards is not None:
            _require_method(self.guards, "before_entry", field_name="guards")
            _require_method(self.guards, "after_battle", field_name="guards")
        if self.programs is not None:
            _require_method(self.programs, "mode", field_name="programs")
            _require_method(self.programs, "execute", field_name="programs")
        if self.gems_fleets is not None:
            _require_method(self.gems_fleets, "replace", field_name="gems_fleets")
        if self.lifecycle is not None:
            _require_method(self.lifecycle, "finish", field_name="lifecycle")
            _require_method(self.lifecycle, "discard_checkpoint", field_name="lifecycle")


@dataclass(frozen=True, slots=True)
class _CampaignProgramRun:
    job: CampaignJobSpec
    session: CampaignSession
    state: CampaignSessionState
    program: BattleProgram
    mode: program_model.BattleProgramMode
    cancellation: CancellationSource
    is_default_mode: bool = False


class LiveCampaignWorkflow(CampaignWorkflow):
    """把一个真实、已确认的 battle attempt 收敛成可持久化的安全点。"""

    __slots__ = (
        "_activator",
        "_clock",
        "_driver",
        "_gems_fleets",
        "_guards",
        "_lifecycle",
        "_observer",
        "_programs",
    )

    def __init__(
        self,
        observer: CampaignBattlefieldObserver,
        driver: CampaignBattleIntentDriver,
        clock: CampaignLiveClock | None = None,
        *,
        services: CampaignLiveServices | None = None,
    ) -> None:
        selected_clock = SystemCampaignLiveClock() if clock is None else clock
        selected_services = CampaignLiveServices() if services is None else services
        _require_method(observer, "observe", field_name="observer")
        _require_method(driver, "issue_and_confirm", field_name="driver")
        _require_method(selected_clock, "now", field_name="clock")
        if not isinstance(selected_services, CampaignLiveServices):
            message = "services must be CampaignLiveServices"
            raise TypeError(message)
        self._observer = observer
        self._driver = driver
        self._clock = selected_clock
        self._activator = selected_services.activator
        self._guards = selected_services.guards
        self._programs = selected_services.programs
        self._gems_fleets = selected_services.gems_fleets
        self._lifecycle = selected_services.lifecycle

    @override
    def discard_checkpoint(self) -> None:
        if self._lifecycle is not None:
            self._lifecycle.discard_checkpoint()

    @override
    def execute(
        self,
        job: CampaignJobSpec,
        cancellation: CancellationSource,
    ) -> CampaignRunReport:
        if not isinstance(job, CampaignJobSpec):
            message = "live campaign workflow requires a CampaignJobSpec"
            raise TypeError(message)
        cancellation.raise_if_requested()
        session, initial_state = self._current_session(job)
        try:
            pre_entry = self._pre_entry_guard(job, session, initial_state, cancellation)
            if pre_entry is not None:
                report = pre_entry
            else:
                activation = self._activate(job, session, initial_state, cancellation)
                if isinstance(activation, CampaignRunReport):
                    report = activation
                else:
                    session, initial_state = activation
                    report = self._execute_battle(
                        job,
                        session,
                        initial_state,
                        cancellation,
                    )
        except BaseException as error:
            stop_reason = (
                CampaignStopReason.CANCELLED if isinstance(error, AbortRequested) else CampaignStopReason.FAILED
            )
            preserve_cleanup_failure(
                error,
                lambda: self._finish_session(session, initial_state, stop_reason),
                message="campaign execution and lifecycle cleanup both failed",
            )
            raise
        return self._finish_report(job, report)

    def _finish_report(self, job: CampaignJobSpec, report: CampaignRunReport) -> CampaignRunReport:
        if self._lifecycle is None:
            return report
        session = job.session_for(report.stage_ref, report.session_state.variant)
        if session is None:
            message = "campaign runtime report session does not belong to the current job"
            raise ValueError(message)
        self._finish_session(session, report.session_state, report.stop_reason)
        return report

    def _finish_session(
        self,
        session: CampaignSession,
        state: CampaignSessionState,
        stop_reason: CampaignStopReason,
    ) -> None:
        if self._lifecycle is not None:
            self._lifecycle.finish(session, state, stop_reason)

    def _execute_battle(
        self,
        job: CampaignJobSpec,
        session: CampaignSession,
        initial_state: CampaignSessionState,
        cancellation: CancellationSource,
    ) -> CampaignRunReport:

        stage_program = session.definition.battle_programs.get(initial_state.battle_index)
        programs = self._programs
        if programs is not None:
            cancellation.raise_if_requested()
            mode = programs.mode(session, initial_state, cancellation)
            if not isinstance(mode, program_model.BattleProgramMode):
                message = "CampaignBattleProgramExecutor.mode() must return a BattleProgramMode"
                raise TypeError(message)
            program = select_battle_program(
                mode,
                initial_state.battle_index,
                stage_program,
                session.definition.boss_approaches.get(initial_state.battle_index),
            )
            if program is not None:
                return self._execute_program(
                    _CampaignProgramRun(
                        job,
                        session,
                        initial_state,
                        program,
                        mode,
                        cancellation,
                    )
                )
        elif stage_program is not None:
            message = "campaign stage requires a BattleProgram executor"
            raise ValueError(message)

        return self._execute_standard_battle(
            job,
            session,
            initial_state,
            cancellation,
        )

    def _execute_standard_battle(
        self,
        job: CampaignJobSpec,
        session: CampaignSession,
        initial_state: CampaignSessionState,
        cancellation: CancellationSource,
    ) -> CampaignRunReport:

        # observe 是第一个外部 I/O；取消只在 I/O 前中断，已确认动作之后必须先完成 reduce。
        cancellation.raise_if_requested()
        observation = self._observer.observe(session, initial_state, cancellation)
        if not isinstance(observation, BattlefieldObservation):
            message = "CampaignBattlefieldObserver.observe() must return a BattlefieldObservation"
            raise TypeError(message)

        decision = (
            session.decide_auto_search(initial_state, observation)
            if job.execution.automation.use_auto_search
            else session.decide(initial_state, observation)
        )
        if decision.command is None:
            return self._report(session, decision.state, CampaignStopReason.BLOCKED)

        cancellation.raise_if_requested()
        outcome = self._driver.issue_and_confirm(
            session,
            decision.state,
            cancellation,
        )
        if not isinstance(outcome, BattleSucceeded | BattleFailed | NoBattleTarget | BattleInterrupted):
            message = "CampaignBattleIntentDriver.issue_and_confirm() must return a BattleOutcome"
            raise TypeError(message)
        if isinstance(outcome, BattleInterrupted):
            report = self._interrupted_battle_report(job, session, decision.command, outcome, cancellation)
        else:
            # 此处故意不再检查取消：外部动作一旦得到确认，领域状态必须先闭合并交给 Task checkpoint。
            reduced = session.reduce(decision.state, outcome)
            stop_reason = self._stop_reason(reduced)
            if (
                stop_reason is not CampaignStopReason.IN_PROGRESS
                or reduced.status is not CampaignSessionStatus.COMPLETED
            ):
                return self._report(session, reduced, stop_reason)
            stop_reason, replacement = self._post_battle_stop_reason(job, session, reduced, cancellation)
            report = self._report(
                session,
                reduced,
                stop_reason,
                gems_replacement=replacement,
            )
        return report

    def _execute_program(
        self,
        run: _CampaignProgramRun,
    ) -> CampaignRunReport:
        if self._programs is None:
            message = "campaign stage requires a BattleProgram executor"
            raise ValueError(message)
        run.cancellation.raise_if_requested()
        execution = self._programs.execute(
            run.program,
            run.session,
            run.state,
            run.cancellation,
        )
        if not isinstance(execution, BattleProgramExecution):
            message = "CampaignBattleProgramExecutor.execute() must return a BattleProgramExecution"
            raise TypeError(message)

        # executor 一旦开始执行 program，就必须把已确认的复合动作闭合到一个安全点。
        reduced = BattleProgramReducer.reduce(run.session, run.state, execution)
        result = execution.result
        if isinstance(result, program_model.ProgramDelegated):
            return self._execute_program_delegation(run, reduced, result)
        return self._program_result_report(run, reduced, result)

    def _execute_program_delegation(
        self,
        run: _CampaignProgramRun,
        reduced: CampaignSessionState,
        result: program_model.ProgramDelegated,
    ) -> CampaignRunReport:
        if result.target is program_model.BattleProgramDelegation.DEFAULT_MODE:
            if run.is_default_mode:
                message = "default-mode battle program cannot delegate to itself"
                raise ValueError(message)
            default_program = default_mode_battle_program(
                run.mode,
                reduced.battle_index,
                run.session.definition.boss_approaches.get(reduced.battle_index),
            )
            if default_program is not None:
                return self._execute_program(
                    replace(
                        run,
                        state=reduced,
                        program=default_program,
                        is_default_mode=True,
                    )
                )
        return self._execute_standard_battle(
            run.job,
            run.session,
            reduced,
            run.cancellation,
        )

    def _program_result_report(
        self,
        run: _CampaignProgramRun,
        reduced: CampaignSessionState,
        result: program_model.CompleteBattleProgramResult,
    ) -> CampaignRunReport:
        if isinstance(result, program_model.ProgramContinue):
            return self._report(run.session, reduced, CampaignStopReason.PROGRAM_CONTINUE)
        if isinstance(result, program_model.ProgramCampaignEnded):
            return self._report(run.session, reduced, CampaignStopReason.ONE_TIME_STAGE)

        stop_reason = self._stop_reason(reduced)
        if (
            stop_reason is CampaignStopReason.IN_PROGRESS
            and isinstance(result, program_model.ProgramBattleSettled)
            and reduced.status is CampaignSessionStatus.COMPLETED
        ):
            stop_reason, replacement = self._post_battle_stop_reason(
                run.job,
                run.session,
                reduced,
                run.cancellation,
            )
            return self._report(
                run.session,
                reduced,
                stop_reason,
                gems_replacement=replacement,
            )
        return self._report(run.session, reduced, stop_reason)

    def _interrupted_battle_report(
        self,
        job: CampaignJobSpec,
        session: CampaignSession,
        attempt: BattleAttempt,
        outcome: BattleInterrupted,
        cancellation: CancellationSource,
    ) -> CampaignRunReport:
        if outcome.attempt != attempt:
            message = "battle interruption does not match the issued attempt"
            raise ValueError(message)
        if (
            outcome.reason is not BattleInterruptionReason.GEMS_LOW_EMOTION
            or job.kind is not CampaignJobKind.GEMS_FARMING
        ):
            message = "unsupported campaign battle interruption"
            raise ValueError(message)
        return self._gems_replacement_report(
            job,
            session,
            session.initial_state(),
            GemsFleetReplacementRequest(
                GemsFleetReplacementTrigger.EMOTION,
                GemsFleetReplacementBoundary.MAP_WITHDRAWN,
            ),
            cancellation,
        )

    def _post_battle_stop_reason(
        self,
        job: CampaignJobSpec,
        session: CampaignSession,
        state: CampaignSessionState,
        cancellation: CancellationSource,
    ) -> tuple[CampaignStopReason, GemsFleetReplacementRequest | None]:
        guard_decision, _observed_at = self._post_battle_guard(job, session, state)
        trigger = guard_decision.gems_replacement
        request = None
        failure_reason = None
        if trigger is not None:
            request = GemsFleetReplacementRequest(trigger, GemsFleetReplacementBoundary.POST_MAP)
            if self._gems_fleets is None:
                message = "gems-farming campaign requires a fleet replacement executor"
                raise ValueError(message)
            replacement = self._gems_fleets.replace(job, session, trigger, cancellation)
            if isinstance(replacement, GemsFleetReplacementFailed):
                failure_reason = self._gems_replacement_failure_reason(trigger)
            elif not isinstance(replacement, GemsFleetReplacementCompleted):
                message = "GemsFleetReplacementExecutor.replace() returned an invalid result"
                raise TypeError(message)
        if self._run_budget_exhausted(job, state):
            return CampaignStopReason.RUN_COUNT_LIMIT, request
        if failure_reason is not None:
            return failure_reason, request
        if guard_decision.stop_reason is not None:
            return guard_decision.stop_reason, None
        if guard_decision.use_gems_fallback:
            message = "post-battle guard cannot request an event fallback"
            raise ValueError(message)
        return CampaignStopReason.IN_PROGRESS, request

    @staticmethod
    def _run_budget_exhausted(job: CampaignJobSpec, state: CampaignSessionState) -> bool:
        if state.status is not CampaignSessionStatus.COMPLETED or not job.limits.run_count:
            return False
        completed = 1 + (0 if job.progress is None else job.progress.runs_completed)
        return completed == job.limits.run_count

    @staticmethod
    def _gems_replacement_failure_reason(
        trigger: GemsFleetReplacementTrigger,
    ) -> CampaignStopReason:
        if trigger is GemsFleetReplacementTrigger.LEVEL:
            return CampaignStopReason.GEMS_LEVEL_REPLACEMENT_FAILED
        if trigger is GemsFleetReplacementTrigger.EMOTION:
            return CampaignStopReason.GEMS_EMOTION_REPLACEMENT_FAILED
        return CampaignStopReason.GEMS_HARD_PREPARATION_FAILED

    def _pre_entry_guard(
        self,
        job: CampaignJobSpec,
        session: CampaignSession,
        state: CampaignSessionState,
        cancellation: CancellationSource,
    ) -> CampaignRunReport | None:
        if state != session.initial_state():
            return None
        if self._guards is None:
            evidence = CampaignGuardEvidence(CampaignGuardPhase.PRE_ENTRY)
        else:
            cancellation.raise_if_requested()
            evidence = self._guards.before_entry(job, session, state, cancellation)
        self._validate_guard_phase(evidence, CampaignGuardPhase.PRE_ENTRY)
        observed_at = self._now()
        progress = job.progress
        pending_replacement = None if progress is None else progress.pending_gems_replacement
        if pending_replacement is not None:
            return self._gems_replacement_report(
                job,
                session,
                state,
                pending_replacement,
                cancellation,
            )
        decision = CampaignGuardPolicy.evaluate(job, session, state, evidence, observed_at)
        if decision.use_gems_fallback:
            return self._gems_fallback_report(job, observed_at)
        if decision.stop_reason is not None:
            return self._report(session, state, decision.stop_reason, observed_at=observed_at)
        if decision.gems_replacement is not None:
            return self._gems_replacement_report(
                job,
                session,
                state,
                GemsFleetReplacementRequest(
                    decision.gems_replacement,
                    GemsFleetReplacementBoundary.PRE_ENTRY,
                ),
                cancellation,
            )
        return None

    def _gems_replacement_report(
        self,
        job: CampaignJobSpec,
        session: CampaignSession,
        state: CampaignSessionState,
        request: GemsFleetReplacementRequest,
        cancellation: CancellationSource,
    ) -> CampaignRunReport:
        if self._gems_fleets is None:
            message = "gems-farming campaign requires a fleet replacement executor"
            raise ValueError(message)
        replacement = self._gems_fleets.replace(job, session, request.trigger, cancellation)
        if isinstance(replacement, GemsFleetReplacementCompleted):
            reason = CampaignStopReason.GEMS_FLEET_REPLACED
        elif isinstance(replacement, GemsFleetReplacementFailed):
            reason = self._gems_replacement_failure_reason(request.trigger)
        else:
            message = "GemsFleetReplacementExecutor.replace() returned an invalid result"
            raise TypeError(message)
        return self._report(
            session,
            state,
            reason,
            gems_replacement=request,
        )

    def _post_battle_guard(
        self,
        job: CampaignJobSpec,
        session: CampaignSession,
        state: CampaignSessionState,
    ) -> tuple[CampaignGuardDecision, datetime]:
        if self._guards is None:
            evidence = CampaignGuardEvidence(CampaignGuardPhase.POST_BATTLE)
        else:
            evidence = self._guards.after_battle(job, session, state)
        self._validate_guard_phase(evidence, CampaignGuardPhase.POST_BATTLE)
        observed_at = self._now()
        return CampaignGuardPolicy.evaluate(job, session, state, evidence, observed_at), observed_at

    @staticmethod
    def _validate_guard_phase(evidence: object, expected: CampaignGuardPhase) -> None:
        if not isinstance(evidence, CampaignGuardEvidence):
            message = "campaign guard source must return CampaignGuardEvidence"
            raise TypeError(message)
        if evidence.phase is not expected:
            message = f"campaign guard source returned {evidence.phase.value} evidence during {expected.value}"
            raise ValueError(message)

    def _gems_fallback_report(self, job: CampaignJobSpec, observed_at: datetime) -> CampaignRunReport:
        policy = job.gems_farming
        if job.kind is not CampaignJobKind.GEMS_FARMING or policy is None:
            message = "gems fallback transition requires GemsFarmingPolicy"
            raise ValueError(message)
        fallback = job.session_for(policy.fallback_session.definition.ref, CampaignRunVariant.NORMAL)
        if fallback is None:
            message = "gems fallback transition session does not belong to the job"
            raise ValueError(message)
        return self._report(
            fallback,
            fallback.initial_state(),
            CampaignStopReason.GEMS_EVENT_FALLBACK,
            observed_at=observed_at,
        )

    def _activate(
        self,
        job: CampaignJobSpec,
        session: CampaignSession,
        state: CampaignSessionState,
        cancellation: CancellationSource,
    ) -> tuple[CampaignSession, CampaignSessionState] | CampaignRunReport:
        if self._activator is None:
            return session, state
        cancellation.raise_if_requested()
        activated = self._activator.activate(job, cancellation)
        if isinstance(activated, CampaignGemsReplacementFailed):
            if state != session.initial_state():
                message = "gems preparation failure must occur at a fresh map boundary"
                raise ValueError(message)
            return self._report(
                session,
                state,
                self._gems_replacement_failure_reason(activated.request.trigger),
                gems_replacement=activated.request,
            )
        if isinstance(activated, CampaignMapAchievementReached):
            if state != session.initial_state():
                message = "map achievement can only be reported at a fresh map boundary"
                raise ValueError(message)
            completion = job.completion_for(session.definition.ref)
            if not completion.reached(
                full_clear=activated.full_clear,
                three_stars=activated.three_stars,
                threat_safe=activated.threat_safe,
            ):
                message = "campaign activator reported unmet map achievement evidence"
                raise ValueError(message)
            stop_reason = (
                CampaignStopReason.STAGE_INCREASE
                if completion.next_stage_ref is not None
                else CampaignStopReason.MAP_ACHIEVEMENT
            )
            return self._report(
                session,
                state,
                stop_reason,
                next_stage_ref=completion.next_stage_ref,
            )
        if not isinstance(activated, CampaignCheckpointUnavailable):
            return self._activated_session(job, activated)
        if job.progress is None:
            message = "fresh campaign activation cannot report an unavailable checkpoint"
            raise ValueError(message)
        return self._report(session, state, CampaignStopReason.CHECKPOINT_UNAVAILABLE)

    @staticmethod
    def _current_session(job: CampaignJobSpec) -> tuple[CampaignSession, CampaignSessionState]:
        progress = job.progress
        if progress is not None:
            session = job.session_for(progress.stage_ref, progress.variant)
            if session is None:
                message = "campaign progress does not belong to the current job"
                raise ValueError(message)
            session.validate_state(progress.session_state)
            return session, progress.session_state
        if not job.sessions:
            message = "live campaign workflow cannot select a session from an empty job"
            raise ValueError(message)
        first_ref = job.stage_refs[0]
        session = job.session_for(first_ref, CampaignRunVariant.NORMAL)
        if session is None:
            message = "campaign job does not provide a normal session for its first stage"
            raise ValueError(message)
        return session, session.initial_state()

    @staticmethod
    def _activated_session(
        job: CampaignJobSpec,
        session: CampaignSession,
    ) -> tuple[CampaignSession, CampaignSessionState]:
        if not isinstance(session, CampaignSession):
            message = "CampaignSessionActivator.activate() must return a CampaignSession"
            raise TypeError(message)
        selected = job.session_for(session.definition.ref, session.variant)
        if selected is None:
            message = "activated campaign session does not belong to the current job"
            raise ValueError(message)
        progress = job.progress
        if progress is None:
            return selected, selected.initial_state()
        if progress.stage_ref != selected.definition.ref or progress.variant is not selected.variant:
            message = "activated campaign session does not match the resumable checkpoint"
            raise ValueError(message)
        selected.validate_state(progress.session_state)
        return selected, progress.session_state

    @staticmethod
    def _stop_reason(state: CampaignSessionState) -> CampaignStopReason:
        if state.status is CampaignSessionStatus.FAILED:
            return CampaignStopReason.FAILED
        if state.status is CampaignSessionStatus.BLOCKED:
            return CampaignStopReason.BLOCKED
        return CampaignStopReason.IN_PROGRESS

    def _report(  # ruff:ignore[too-many-arguments] - report 元数据保持显式，避免无类型字典。
        self,
        session: CampaignSession,
        state: CampaignSessionState,
        stop_reason: CampaignStopReason,
        *,
        observed_at: datetime | None = None,
        next_stage_ref: StageRef | None = None,
        gems_replacement: GemsFleetReplacementRequest | None = None,
    ) -> CampaignRunReport:
        selected_observed_at = self._now() if observed_at is None else observed_at
        _validate_observed_at(selected_observed_at)
        return CampaignRunReport(
            stage_ref=session.definition.ref,
            observed_at=selected_observed_at,
            stop_reason=stop_reason,
            session_state=state,
            runs_completed=1 if state.status is CampaignSessionStatus.COMPLETED else 0,
            next_stage_ref=next_stage_ref,
            gems_replacement=gems_replacement,
        )

    def _now(self) -> datetime:
        observed_at = self._clock.now()
        _validate_observed_at(observed_at)
        return observed_at
