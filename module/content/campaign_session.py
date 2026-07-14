from dataclasses import dataclass, replace
from enum import StrEnum
from typing import Never, assert_never

from module.content.battle_policy import (
    BattleIntent,
    BattlePlan,
    ClearAnyEnemy,
    ClearBoss,
    ClearBossRoadblock,
    ClearChosenEnemy,
    ClearEnemy,
    ClearFilteredEnemy,
    ClearPriorityEnemy,
    ClearSelectedEnemy,
    ClearSiren,
    DefaultBattle,
    GuardedBattleStep,
    TargetExpectation,
    is_battle_step,
)
from module.content.battle_program import ProgramFlag, ProgramMarker
from module.content.stage_definition import CampaignStageDefinition, RunVariant, SpawnWave


class CampaignSessionError(ValueError):
    pass


def _invalid(message: str) -> Never:
    raise CampaignSessionError(message)


class CampaignRunVariant(StrEnum):
    NORMAL = "normal"
    LOOP = "loop"


class CampaignSessionStatus(StrEnum):
    ACTIVE = "active"
    COMPLETED = "completed"
    FAILED = "failed"
    BLOCKED = "blocked"


class BattleTarget(StrEnum):
    ENEMY = "enemy"
    SIREN = "siren"
    BOSS = "boss"


class BattleInterruptionReason(StrEnum):
    GEMS_LOW_EMOTION = "gems_low_emotion"


@dataclass(frozen=True, slots=True)
class AutoSearchBattle:
    """由游戏自律寻敌选择目标的一次 battle；结果必须由战后观测确认。"""


type CampaignBattleIntent = BattleIntent | AutoSearchBattle


@dataclass(frozen=True, slots=True)
class RemainingSpawns:
    enemy: int = 0
    siren: int = 0
    mystery: int = 0
    boss: int = 0

    def __post_init__(self) -> None:
        values = (self.enemy, self.siren, self.mystery, self.boss)
        if any(type(value) is not int or value < 0 for value in values):
            message = "remaining spawn counts must be non-negative integers"
            raise CampaignSessionError(message)

    @classmethod
    def from_wave(cls, wave: SpawnWave) -> RemainingSpawns:
        if not isinstance(wave, SpawnWave):
            message = "remaining spawns require a SpawnWave"
            raise TypeError(message)
        return cls(enemy=wave.enemy, siren=wave.siren, mystery=wave.mystery, boss=wave.boss)

    def add_wave(self, wave: SpawnWave) -> RemainingSpawns:
        added = self.from_wave(wave)
        return RemainingSpawns(
            enemy=self.enemy + added.enemy,
            siren=self.siren + added.siren,
            mystery=self.mystery + added.mystery,
            boss=self.boss + added.boss,
        )

    def clear(self, target: BattleTarget) -> RemainingSpawns:
        if target is BattleTarget.ENEMY:
            if self.enemy == 0:
                _invalid("cannot clear an enemy when none remain")
            return replace(self, enemy=self.enemy - 1)
        if target is BattleTarget.SIREN:
            if self.siren == 0:
                _invalid("cannot clear a siren when none remain")
            return replace(self, siren=self.siren - 1)
        if target is BattleTarget.BOSS:
            if self.boss == 0:
                _invalid("cannot clear a boss when none remain")
            return replace(self, boss=self.boss - 1)
        assert_never(target)


@dataclass(frozen=True, slots=True)
class BattlefieldObservation:
    battle_index: int
    enemy: int = 0
    siren: int = 0
    boss: int = 0

    def __post_init__(self) -> None:
        values = (self.battle_index, self.enemy, self.siren, self.boss)
        if any(type(value) is not int or value < 0 for value in values):
            message = "battlefield observation counts must be non-negative integers"
            raise CampaignSessionError(message)


@dataclass(frozen=True, slots=True)
class BattleAttempt:
    battle_index: int
    attempt_id: int
    intent_index: int
    intent: CampaignBattleIntent

    def __post_init__(self) -> None:
        indexes = (self.battle_index, self.attempt_id, self.intent_index)
        if any(type(value) is not int or value < 0 for value in indexes):
            message = "battle attempt indexes must be non-negative integers"
            raise CampaignSessionError(message)
        if not (is_battle_step(self.intent) or isinstance(self.intent, AutoSearchBattle)):
            message = "battle attempt contains an invalid intent"
            raise TypeError(message)


@dataclass(frozen=True, slots=True)
class BattleSucceeded:
    attempt: BattleAttempt
    cleared: BattleTarget

    def __post_init__(self) -> None:
        if not isinstance(self.attempt, BattleAttempt):
            message = "battle success requires a BattleAttempt"
            raise TypeError(message)
        if not isinstance(self.cleared, BattleTarget):
            message = "battle success cleared target must be a BattleTarget"
            raise TypeError(message)


@dataclass(frozen=True, slots=True)
class BattleFailed:
    attempt: BattleAttempt
    reason: str

    def __post_init__(self) -> None:
        if not isinstance(self.attempt, BattleAttempt):
            message = "battle failure requires a BattleAttempt"
            raise TypeError(message)
        if not isinstance(self.reason, str) or not self.reason.strip():
            message = "battle failure reason must be a non-empty string"
            raise CampaignSessionError(message)


@dataclass(frozen=True, slots=True)
class NoBattleTarget:
    attempt: BattleAttempt

    def __post_init__(self) -> None:
        if not isinstance(self.attempt, BattleAttempt):
            message = "no-target result requires a BattleAttempt"
            raise TypeError(message)


@dataclass(frozen=True, slots=True)
class BattleInterrupted:
    attempt: BattleAttempt
    reason: BattleInterruptionReason

    def __post_init__(self) -> None:
        if not isinstance(self.attempt, BattleAttempt):
            message = "battle interruption requires a BattleAttempt"
            raise TypeError(message)
        if not isinstance(self.reason, BattleInterruptionReason):
            message = "battle interruption reason must be a BattleInterruptionReason"
            raise TypeError(message)


type BattleOutcome = BattleSucceeded | BattleFailed | NoBattleTarget | BattleInterrupted


@dataclass(frozen=True, slots=True)
class CampaignSessionState:
    variant: CampaignRunVariant
    status: CampaignSessionStatus
    battle_index: int
    remaining: RemainingSpawns
    next_attempt_id: int = 0
    next_intent_index: int = 0
    pending: BattleAttempt | None = None
    reason: str | None = None
    program_state_initialized: bool = False
    program_flags: frozenset[ProgramFlag] = frozenset()
    program_markers: frozenset[ProgramMarker] = frozenset()

    def __post_init__(self) -> None:
        if not isinstance(self.variant, CampaignRunVariant):
            message = "campaign state variant must be a CampaignRunVariant"
            raise TypeError(message)
        if not isinstance(self.status, CampaignSessionStatus):
            message = "campaign state status must be a CampaignSessionStatus"
            raise TypeError(message)
        if type(self.battle_index) is not int or self.battle_index < 0:
            _invalid("campaign battle index must be a non-negative integer")
        indexes = (self.next_attempt_id, self.next_intent_index)
        if any(type(value) is not int or value < 0 for value in indexes):
            message = "campaign cursor indexes must be non-negative integers"
            raise CampaignSessionError(message)
        if not isinstance(self.remaining, RemainingSpawns):
            message = "campaign remaining value must be RemainingSpawns"
            raise TypeError(message)
        if self.pending is not None and not isinstance(self.pending, BattleAttempt):
            message = "campaign pending value must be a BattleAttempt or None"
            raise TypeError(message)
        program_flags, program_markers = self._validated_program_state()
        object.__setattr__(self, "program_flags", program_flags)
        object.__setattr__(self, "program_markers", program_markers)
        self._validate_status()
        self._validate_pending()

    def _validated_program_state(
        self,
    ) -> tuple[frozenset[ProgramFlag], frozenset[ProgramMarker]]:
        if type(self.program_state_initialized) is not bool:
            message = "campaign program_state_initialized must be a bool"
            raise TypeError(message)
        program_flags = frozenset(self.program_flags)
        if any(not isinstance(flag, ProgramFlag) for flag in program_flags):
            message = "campaign program_flags must contain ProgramFlag values"
            raise TypeError(message)
        program_markers = frozenset(self.program_markers)
        if any(not isinstance(marker, ProgramMarker) for marker in program_markers):
            message = "campaign program_markers must contain ProgramMarker values"
            raise TypeError(message)
        if (program_flags or program_markers) and not self.program_state_initialized:
            _invalid("campaign program facts require initialized program state")
        return program_flags, program_markers

    def _validate_status(self) -> None:
        if self.status is CampaignSessionStatus.ACTIVE:
            if self.reason is not None:
                _invalid("active campaign state cannot have a terminal reason")
            return
        if self.pending is not None:
            _invalid("terminal campaign state cannot have a pending attempt")
        if self.status is CampaignSessionStatus.COMPLETED:
            if self.reason is not None:
                _invalid("completed campaign state cannot have a reason")
            return
        if not isinstance(self.reason, str) or not self.reason.strip():
            _invalid("failed or blocked campaign state requires a reason")

    def _validate_pending(self) -> None:
        if self.pending is None:
            return
        if self.pending.battle_index != self.battle_index:
            _invalid("pending attempt must belong to the current battle")
        if self.pending.attempt_id + 1 != self.next_attempt_id:
            _invalid("pending attempt id must immediately precede the next attempt id")
        if self.pending.intent_index < self.next_intent_index:
            _invalid("pending intent precedes the campaign intent cursor")


@dataclass(frozen=True, slots=True)
class CampaignDecision:
    state: CampaignSessionState
    command: BattleAttempt | None

    def __post_init__(self) -> None:
        if not isinstance(self.state, CampaignSessionState):
            message = "campaign decision state must be a CampaignSessionState"
            raise TypeError(message)
        if self.command is None:
            if self.state.status is not CampaignSessionStatus.BLOCKED or self.state.pending is not None:
                _invalid("an empty decision must produce a blocked state")
            return
        if not isinstance(self.command, BattleAttempt):
            message = "campaign decision command must be a BattleAttempt or None"
            raise TypeError(message)
        if self.state.pending != self.command:
            _invalid("campaign decision command must match the pending attempt")


@dataclass(frozen=True, slots=True)
class CampaignSession:
    definition: CampaignStageDefinition
    variant: CampaignRunVariant

    def __post_init__(self) -> None:
        if not isinstance(self.definition, CampaignStageDefinition):
            message = "campaign session definition must be a CampaignStageDefinition"
            raise TypeError(message)
        if not isinstance(self.variant, CampaignRunVariant):
            message = "campaign session variant must be a CampaignRunVariant"
            raise TypeError(message)

    @property
    def run_variant(self) -> RunVariant:
        if self.variant is CampaignRunVariant.NORMAL:
            return self.definition.map.normal
        if self.variant is CampaignRunVariant.LOOP:
            return self.definition.map.loop
        assert_never(self.variant)

    def initial_state(self) -> CampaignSessionState:
        if not self.run_variant.spawn_waves:
            _invalid("observation-driven campaign has no static initial spawn wave")
        first_wave = self.run_variant.spawn_waves[0]
        return CampaignSessionState(
            variant=self.variant,
            status=CampaignSessionStatus.ACTIVE,
            battle_index=0,
            remaining=RemainingSpawns.from_wave(first_wave),
        )

    def battle_plan(self, battle_index: int) -> BattlePlan:
        if type(battle_index) is not int or battle_index < 0:
            _invalid("battle index must be a non-negative integer")
        waves = self.run_variant.spawn_waves
        if battle_index >= len(waves):
            boss_battles = self.run_variant.boss_battles
            if boss_battles:
                return self.definition.battle_policies[max(boss_battles)].to_plan()
            return BattlePlan((DefaultBattle(),))
        policy = self.definition.battle_policies.get(battle_index)
        if policy is not None:
            return policy.to_plan()
        if waves[battle_index].is_boss:
            _invalid("boss battle has no explicit stage policy")
        return BattlePlan((DefaultBattle(),))

    def decide(
        self,
        state: CampaignSessionState,
        observation: BattlefieldObservation,
    ) -> CampaignDecision:
        self.validate_state(state)
        if not isinstance(observation, BattlefieldObservation):
            message = "campaign decision requires a BattlefieldObservation"
            raise TypeError(message)
        if state.status is not CampaignSessionStatus.ACTIVE:
            _invalid("cannot decide a battle for a terminal campaign state")
        if state.pending is not None:
            _invalid("cannot decide while a battle attempt is pending")
        self._validate_observation(state, observation)

        plan = self.battle_plan(state.battle_index)
        for intent_index in range(state.next_intent_index, len(plan.intents)):
            intent = plan.intents[intent_index]
            if _can_attempt(intent, observation):
                command = BattleAttempt(
                    battle_index=state.battle_index,
                    attempt_id=state.next_attempt_id,
                    intent_index=intent_index,
                    intent=intent,
                )
                decided = replace(state, next_attempt_id=state.next_attempt_id + 1, pending=command)
                return CampaignDecision(decided, command)

        blocked = replace(
            state,
            status=CampaignSessionStatus.BLOCKED,
            pending=None,
            reason=f"battle {state.battle_index} has no eligible target",
        )
        return CampaignDecision(blocked, None)

    def decide_auto_search(
        self,
        state: CampaignSessionState,
        observation: BattlefieldObservation,
    ) -> CampaignDecision:
        """为游戏自律寻敌记录一个开放目标 intent，目标类型由战后事实闭合。"""

        self.validate_state(state)
        if state.status is not CampaignSessionStatus.ACTIVE or state.pending is not None:
            _invalid("cannot decide auto search while campaign state is not at a safe point")
        self._validate_observation(state, observation)
        if observation.enemy + observation.siren + observation.boss == 0:
            return CampaignDecision(
                replace(
                    state,
                    status=CampaignSessionStatus.BLOCKED,
                    reason=f"battle {state.battle_index} has no auto-search target",
                ),
                None,
            )
        command = BattleAttempt(
            battle_index=state.battle_index,
            attempt_id=state.next_attempt_id,
            intent_index=0,
            intent=AutoSearchBattle(),
        )
        return CampaignDecision(replace(state, next_attempt_id=state.next_attempt_id + 1, pending=command), command)

    def reduce(self, state: CampaignSessionState, outcome: BattleOutcome) -> CampaignSessionState:
        self.validate_state(state)
        if state.status is not CampaignSessionStatus.ACTIVE or state.pending is None:
            _invalid("battle outcome requires an active pending attempt")
        if not isinstance(outcome, BattleSucceeded | BattleFailed | NoBattleTarget | BattleInterrupted):
            message = "campaign reducer received an invalid battle outcome"
            raise TypeError(message)
        if outcome.attempt != state.pending:
            _invalid("battle outcome does not match the pending attempt")
        self._validate_pending_plan(state.pending)

        if isinstance(outcome, BattleSucceeded):
            return self._succeed(state, outcome)
        if isinstance(outcome, BattleFailed):
            return replace(
                state,
                status=CampaignSessionStatus.FAILED,
                pending=None,
                reason=outcome.reason.strip(),
            )
        if isinstance(outcome, NoBattleTarget):
            next_intent = state.pending.intent_index + 1
            plan = self.battle_plan(state.battle_index)
            if next_intent >= len(plan.intents):
                return replace(
                    state,
                    status=CampaignSessionStatus.BLOCKED,
                    next_intent_index=next_intent,
                    pending=None,
                    reason=f"battle {state.battle_index} exhausted its battle plan",
                )
            return replace(state, next_intent_index=next_intent, pending=None)
        if isinstance(outcome, BattleInterrupted):
            _invalid("battle interruption must be handled by the campaign workflow")
        assert_never(outcome)

    def _succeed(self, state: CampaignSessionState, outcome: BattleSucceeded) -> CampaignSessionState:
        attempt = state.pending
        if attempt is None:
            _invalid("battle success requires a pending attempt")
        _validate_cleared_target(attempt.intent, outcome.cleared)
        intent = attempt.intent.step if isinstance(attempt.intent, GuardedBattleStep) else attempt.intent
        return self.settle_confirmed_battle(
            state,
            outcome.cleared,
            advances_wave=not isinstance(intent, ClearBossRoadblock),
        )

    def settle_confirmed_battle(
        self,
        state: CampaignSessionState,
        cleared: BattleTarget,
        *,
        advances_wave: bool = True,
    ) -> CampaignSessionState:
        """记录已确认战斗；刷新日程耗尽不等于含 Boss 地图结束。"""

        self.validate_state(state)
        if state.status is not CampaignSessionStatus.ACTIVE:
            _invalid("confirmed battle requires an active campaign state")
        if not isinstance(cleared, BattleTarget):
            message = "confirmed battle target must be a BattleTarget"
            raise TypeError(message)
        if type(advances_wave) is not bool:
            message = "confirmed battle advances_wave must be a bool"
            raise TypeError(message)

        remaining = state.remaining
        target_count = {
            BattleTarget.ENEMY: remaining.enemy,
            BattleTarget.SIREN: remaining.siren,
            BattleTarget.BOSS: remaining.boss,
        }[cleared]
        if target_count:
            remaining = remaining.clear(cleared)
        battle_index = state.battle_index + int(advances_wave)
        safe_state = replace(
            state,
            battle_index=battle_index,
            remaining=remaining,
            next_intent_index=0,
            pending=None,
        )
        schedule_exhausted_without_boss = (
            not self.run_variant.boss_battles and advances_wave and battle_index >= len(self.run_variant.spawn_waves)
        )
        if cleared is BattleTarget.BOSS or schedule_exhausted_without_boss:
            return replace(safe_state, status=CampaignSessionStatus.COMPLETED)
        if not advances_wave or battle_index >= len(self.run_variant.spawn_waves):
            return safe_state
        return replace(
            safe_state,
            remaining=remaining.add_wave(self.run_variant.spawn_waves[battle_index]),
        )

    def validate_state(self, state: CampaignSessionState) -> None:
        """验证可恢复状态确实属于当前编译关卡。"""
        if not isinstance(state, CampaignSessionState):
            message = "campaign session requires a CampaignSessionState"
            raise TypeError(message)
        if state.variant is not self.variant:
            _invalid("campaign state uses a different run variant")
        if state.status is CampaignSessionStatus.COMPLETED:
            self._validate_completed_state(state)
        if state.status is not CampaignSessionStatus.COMPLETED:
            plan = self.battle_plan(state.battle_index)
            if state.next_intent_index > len(plan.intents):
                _invalid("campaign intent cursor exceeds the current battle plan")
        if state.pending is not None:
            self._validate_pending_plan(state.pending)

    def _validate_completed_state(self, state: CampaignSessionState) -> None:
        boss_battles = self.run_variant.boss_battles
        if not boss_battles:
            if state.battle_index < len(self.run_variant.spawn_waves):
                _invalid("completed bossless campaign state must exhaust its spawn schedule")
            return
        if state.remaining.boss:
            _invalid("completed campaign state cannot retain a boss")
        if not any(battle <= state.battle_index for battle in boss_battles):
            _invalid("completed campaign state precedes its boss spawn")

    @staticmethod
    def _validate_observation(state: CampaignSessionState, observation: BattlefieldObservation) -> None:
        if observation.battle_index != state.battle_index:
            _invalid("battlefield observation is stale or from another battle")
        if observation.enemy > state.remaining.enemy:
            _invalid("observed enemy count exceeds remaining spawns")
        if observation.siren > state.remaining.siren:
            _invalid("observed siren count exceeds remaining spawns")
        if observation.boss > state.remaining.boss:
            _invalid("observed boss count exceeds remaining spawns")

    def _validate_pending_plan(self, attempt: BattleAttempt) -> None:
        if isinstance(attempt.intent, AutoSearchBattle):
            if attempt.intent_index != 0:
                _invalid("auto-search attempt must use intent index zero")
            return
        plan = self.battle_plan(attempt.battle_index)
        if attempt.intent_index >= len(plan.intents) or plan.intents[attempt.intent_index] != attempt.intent:
            _invalid("pending attempt does not belong to the battle plan")


def _can_attempt(intent: BattleIntent, observation: BattlefieldObservation) -> bool:
    if isinstance(intent, GuardedBattleStep):
        intent = intent.step
    if isinstance(intent, ClearSiren):
        eligible = observation.siren > 0
    elif isinstance(intent, ClearFilteredEnemy):
        eligible = observation.enemy > intent.preserve
    elif isinstance(intent, ClearAnyEnemy):
        eligible = observation.enemy > 0 or observation.siren > 0
    elif isinstance(intent, ClearEnemy | ClearPriorityEnemy | ClearBossRoadblock):
        eligible = observation.enemy > 0
    elif isinstance(intent, ClearChosenEnemy | ClearSelectedEnemy):
        eligible = observation.siren > 0 if intent.expected is TargetExpectation.SIREN else observation.enemy > 0
    elif isinstance(intent, DefaultBattle):
        eligible = observation.enemy > 0 or observation.siren > 0
    elif isinstance(intent, ClearBoss):
        eligible = observation.boss > 0
    else:
        assert_never(intent)
    return eligible


def _validate_cleared_target(intent: CampaignBattleIntent, target: BattleTarget) -> None:
    if isinstance(intent, GuardedBattleStep):
        intent = intent.step
    if isinstance(intent, AutoSearchBattle):
        is_valid = True
    elif isinstance(intent, ClearSiren):
        is_valid = target is BattleTarget.SIREN
    elif isinstance(intent, ClearAnyEnemy):
        is_valid = target in (BattleTarget.ENEMY, BattleTarget.SIREN)
    elif isinstance(intent, ClearFilteredEnemy | ClearEnemy | ClearPriorityEnemy | ClearBossRoadblock):
        is_valid = target is BattleTarget.ENEMY
    elif isinstance(intent, ClearChosenEnemy | ClearSelectedEnemy):
        expected = BattleTarget.SIREN if intent.expected is TargetExpectation.SIREN else BattleTarget.ENEMY
        is_valid = target is expected
    elif isinstance(intent, DefaultBattle):
        is_valid = target in (BattleTarget.ENEMY, BattleTarget.SIREN)
    elif isinstance(intent, ClearBoss):
        is_valid = target is BattleTarget.BOSS
    else:
        assert_never(intent)
    if not is_valid:
        message = f"{type(intent).__name__} cannot clear {target.value}"
        raise CampaignSessionError(message)
