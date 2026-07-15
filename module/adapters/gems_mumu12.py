from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

from module.adapters.campaign_live import CampaignActionInterrupted
from module.application import SafeUnitCancellation
from module.campaign.campaign_engine import CampaignEngine
from module.campaign.gems_farming import (
    GemsEmotion,
    GemsFleetReplacement,
    GemsShipReplacementDisposition,
    GemsShipReplacementFactSink,
    GemsShipReplacementResult,
)
from module.combat.assets import BATTLE_PREPARATION
from module.config.config import AzurLaneConfig
from module.content.campaign_session import BattleInterruptionReason
from module.device.device import Device
from module.gameplay.campaign import GemsFarmingPolicy
from module.gameplay.campaign_live import (
    GemsFleetReplacementCompleted,
    GemsFleetReplacementFailed,
    GemsFleetReplacementResult,
    GemsFleetReplacementTrigger,
)
from module.handler.assets import AUTO_SEARCH_MAP_OPTION_OFF
from module.map.assets import FLEET_PREPARATION, MAP_PREPARATION
from module.ui.assets import BACK_ARROW

if TYPE_CHECKING:
    from module.adapters.campaign_live import CommittedCampaignUnit
    from module.content.campaign_session import CampaignSession
    from module.gameplay.campaign import CampaignJobSpec
    from module.interaction import CancellationSignal


class GemsFleetReplacementBridge(Protocol):
    """换舰 UI primitive 在已提交安全单元内需要的最小显式接口。"""

    config: AzurLaneConfig
    device: Device
    campaign: CampaignEngine

    def flagship_change(self, fact_sink: GemsShipReplacementFactSink) -> GemsShipReplacementResult: ...

    def vanguard_change(self, fact_sink: GemsShipReplacementFactSink) -> GemsShipReplacementResult: ...

    def hard_fleet_prepare(
        self,
        fact_sink: GemsShipReplacementFactSink,
    ) -> Iterator[GemsShipReplacementResult]: ...


class GemsReplacementUnitSource(Protocol):
    def commit_replacement_unit(
        self,
        session: CampaignSession,
        cancellation: CancellationSignal,
    ) -> CommittedCampaignUnit: ...


type GemsFleetReplacementFactory = Callable[[AzurLaneConfig, Device], GemsFleetReplacementBridge]
_HARD_PREPARATION_NO_REPLACEMENT = "hard fleet preparation found no valid replacement"


class GemsHardPreparationFailed(RuntimeError):
    pass


class Mumu12GemsRuntimeBehavior:
    """固定 runtime 的 Gems 心情账本与低心情撤图行为。"""

    __slots__ = ("_runner_factory", "_unit_cancellation", "emotion", "policy")

    def __init__(
        self,
        config: AzurLaneConfig,
        policy: GemsFarmingPolicy,
        unit_cancellation: SafeUnitCancellation,
        *,
        runner_factory: GemsFleetReplacementFactory | None = None,
    ) -> None:
        if not isinstance(config, AzurLaneConfig):
            message = "gems runtime behavior requires AzurLaneConfig"
            raise TypeError(message)
        if not isinstance(policy, GemsFarmingPolicy):
            message = "gems runtime behavior requires GemsFarmingPolicy"
            raise TypeError(message)
        if not isinstance(unit_cancellation, SafeUnitCancellation):
            message = "gems runtime behavior requires SafeUnitCancellation"
            raise TypeError(message)
        self.policy = policy
        self.emotion = GemsEmotion(config=config)
        self._unit_cancellation = unit_cancellation
        self._runner_factory = _default_runner_factory if runner_factory is None else runner_factory

    def replacement_required_before_entry(self, battle_count: int) -> bool:
        if type(battle_count) is not int or battle_count < 0:
            message = "gems map battle count must be a non-negative integer"
            raise ValueError(message)
        return self.emotion.replacement_required(battle_count)

    def handle_low_emotion(self, runtime: CampaignEngine) -> bool:
        if not self.policy.changes_vanguard:
            result = runtime.handle_popup_confirm("IGNORE_LOW_EMOTION")
            if result:
                runtime.interval_reset(AUTO_SEARCH_MAP_OPTION_OFF)
            return result
        if not runtime.handle_popup_cancel("IGNORE_LOW_EMOTION"):
            return False
        self._withdraw(runtime)
        raise CampaignActionInterrupted(BattleInterruptionReason.GEMS_LOW_EMOTION)

    def prepare_hard_fleet(self, runtime: CampaignEngine) -> bool:
        cancellation = self._unit_cancellation
        cancellation.raise_if_requested()
        cancellation.commit()
        runner = self._runner_factory(runtime.config, runtime.device)
        bound = _BoundGemsFleetReplacement.bind(runner, runtime, self.policy, cancellation)
        if bound.prepare_hard_fleet(cancellation):
            return True
        raise GemsHardPreparationFailed(_HARD_PREPARATION_NO_REPLACEMENT)

    @staticmethod
    def _withdraw(runtime: CampaignEngine) -> None:
        while True:
            runtime.device.screenshot()
            if runtime.handle_story_skip() or runtime.handle_popup_cancel("IGNORE_LOW_EMOTION"):
                continue
            if runtime.appear(BATTLE_PREPARATION, offset=(20, 20), interval=2):
                runtime.device.click(BACK_ARROW)
                continue
            if runtime.handle_auto_search_exit():
                continue
            if runtime.is_in_stage():
                return
            if runtime.is_in_map():
                runtime.withdraw()
                return
            if runtime.appear(FLEET_PREPARATION, offset=(20, 50), interval=2) or runtime.appear(
                MAP_PREPARATION,
                offset=(20, 20),
                interval=2,
            ):
                runtime.enter_map_cancel()
                return


@dataclass(slots=True)
class _BoundGemsFleetReplacement:
    runner: GemsFleetReplacementBridge
    runtime: CampaignEngine
    minimum_emotion: int

    @classmethod
    def bind(
        cls,
        runner: GemsFleetReplacementBridge,
        runtime: CampaignEngine,
        policy: GemsFarmingPolicy,
        cancellation: CancellationSignal,
    ) -> _BoundGemsFleetReplacement:
        cancellation.raise_if_requested()
        runtime.config.apply_runtime_overlay(
            GemsFarming_ChangeFlagship=policy.flagship_change.value,
            GemsFarming_CommonCV=policy.common_carrier.value,
            GemsFarming_ChangeVanguard=policy.vanguard_change.value,
            GemsFarming_CommonDD=policy.common_destroyer.value,
            EquipmentCode_Config=policy.equipment_code_config,
        )
        runner.campaign = runtime
        return cls(runner, runtime, policy.emotion_after_replacement)

    @staticmethod
    def _validated_result(
        result: object,
        *,
        operation: str,
    ) -> GemsShipReplacementResult:
        if not isinstance(result, GemsShipReplacementResult):
            message = f"gems fleet replacement {operation}() must return GemsShipReplacementResult"
            raise TypeError(message)
        return result

    def _merge_result(
        self,
        result: object,
        *,
        operation: str,
    ) -> GemsShipReplacementResult:
        result = self._validated_result(result, operation=operation)
        selected_emotion = result.selected_emotion
        if selected_emotion is None:
            self.minimum_emotion = 0
        else:
            self.minimum_emotion = min(self.minimum_emotion, selected_emotion)
        return result

    def _record_replacement_result(
        self,
        result: object,
        *,
        operation: str,
    ) -> GemsShipReplacementResult:
        merged = self._merge_result(result, operation=operation)
        # UI 换舰已经生效；必须先记录事实，取消只能阻止下一次操作。
        self.runtime.config.set_record(
            Emotion_Fleet1Value=self.minimum_emotion,
        )
        return merged

    def _match_reported_fact(
        self,
        returned: object,
        reported: GemsShipReplacementResult | None,
        *,
        operation: str,
    ) -> GemsShipReplacementResult:
        validated = self._validated_result(returned, operation=operation)
        if reported is None:
            # bridge 违约也不能让已经返回的真实换舰事实丢失。
            self._record_replacement_result(validated, operation=operation)
            message = f"gems fleet replacement {operation}() did not report its completion fact"
            raise TypeError(message)
        if reported != validated:
            message = f"gems fleet replacement {operation}() returned a different completion fact"
            raise ValueError(message)
        return validated

    def _replace_one(
        self,
        operation: Callable[[GemsShipReplacementFactSink], object],
        *,
        operation_name: str,
        cancellation: CancellationSignal,
    ) -> GemsShipReplacementResult:
        cancellation.raise_if_requested()
        pending_fact: GemsShipReplacementResult | None = None
        callback_violation: TypeError | None = None

        def persist_fact(result: GemsShipReplacementResult) -> None:
            nonlocal callback_violation, pending_fact
            if pending_fact is not None:
                callback_violation = TypeError(
                    f"gems fleet replacement {operation_name}() reported more than one completion fact"
                )
                raise callback_violation
            pending_fact = self._record_replacement_result(result, operation=operation_name)

        returned = operation(persist_fact)
        if callback_violation is not None:
            raise callback_violation
        return self._match_reported_fact(returned, pending_fact, operation=operation_name)

    def replace_flagship(self, cancellation: CancellationSignal) -> GemsShipReplacementResult:
        return self._replace_one(
            self.runner.flagship_change,
            operation_name="flagship_change",
            cancellation=cancellation,
        )

    def replace_vanguard(self, cancellation: CancellationSignal) -> GemsShipReplacementResult:
        return self._replace_one(
            self.runner.vanguard_change,
            operation_name="vanguard_change",
            cancellation=cancellation,
        )

    def prepare_hard_fleet(self, cancellation: CancellationSignal) -> bool:
        cancellation.raise_if_requested()
        self.runtime.emotion.update()
        self.minimum_emotion = min(self.minimum_emotion, self.runtime.emotion.fleet_1.current)
        pending_fact: GemsShipReplacementResult | None = None
        callback_violation: TypeError | None = None

        def persist_fact(result: GemsShipReplacementResult) -> None:
            nonlocal callback_violation, pending_fact
            if pending_fact is not None:
                callback_violation = TypeError(
                    "gems fleet replacement hard_fleet_prepare() reported multiple facts before one result"
                )
                raise callback_violation
            pending_fact = self._record_replacement_result(result, operation="hard_fleet_prepare")

        results = self.runner.hard_fleet_prepare(persist_fact)
        if not isinstance(results, Iterator):
            message = "gems fleet replacement hard_fleet_prepare() must return an iterator"
            raise TypeError(message)
        has_result = False
        all_satisfied = True
        for result in results:
            has_result = True
            if callback_violation is not None:
                raise callback_violation
            returned = self._match_reported_fact(result, pending_fact, operation="hard_fleet_prepare")
            pending_fact = None
            if returned.disposition is not GemsShipReplacementDisposition.POLICY_SATISFIED:
                all_satisfied = False
            cancellation.raise_if_requested()
        if callback_violation is not None:
            raise callback_violation
        if pending_fact is not None:
            message = "gems fleet replacement hard_fleet_prepare() reported a fact without yielding its result"
            raise TypeError(message)
        return has_result and all_satisfied


def _default_runner_factory(config: AzurLaneConfig, device: Device) -> GemsFleetReplacementBridge:
    return GemsFleetReplacement(config=config, device=device)


class Mumu12GemsFleetReplacementExecutor:
    """在已提交的地图安全单元内复用 MuMu12 换船 UI primitive。"""

    __slots__ = ("_runner_factory", "_runtimes")

    def __init__(
        self,
        runtimes: GemsReplacementUnitSource,
        *,
        runner_factory: GemsFleetReplacementFactory = _default_runner_factory,
    ) -> None:
        if isinstance(runtimes, type):
            message = "gems fleet replacement runtimes must be an instance"
            raise TypeError(message)
        if not callable(runner_factory):
            message = "gems farming runner factory must be callable"
            raise TypeError(message)
        self._runtimes = runtimes
        self._runner_factory = runner_factory

    @staticmethod
    def _policy(job: CampaignJobSpec) -> GemsFarmingPolicy:
        policy = job.gems_farming
        if policy is None:
            message = "gems fleet replacement requires GemsFarmingPolicy"
            raise ValueError(message)
        return policy

    @staticmethod
    def _validate_trigger(trigger: GemsFleetReplacementTrigger) -> None:
        if not isinstance(trigger, GemsFleetReplacementTrigger):
            message = "gems fleet replacement trigger must be a GemsFleetReplacementTrigger"
            raise TypeError(message)

    def replace(
        self,
        job: CampaignJobSpec,
        session: CampaignSession,
        trigger: GemsFleetReplacementTrigger,
        cancellation: CancellationSignal,
    ) -> GemsFleetReplacementResult:
        policy = self._policy(job)
        self._validate_trigger(trigger)
        committed = self._runtimes.commit_replacement_unit(session, cancellation)
        if not isinstance(committed.runtime, CampaignEngine):
            message = "gems fleet replacement requires an active CampaignEngine runtime"
            raise TypeError(message)
        unit_cancellation = committed.cancellation
        runtime = committed.runtime
        unit_cancellation.raise_if_requested()
        runner = self._runner_factory(runtime.config, runtime.device)
        bound = _BoundGemsFleetReplacement.bind(runner, runtime, policy, unit_cancellation)

        if trigger is GemsFleetReplacementTrigger.HARD_PREPARATION:
            if not bound.prepare_hard_fleet(unit_cancellation):
                return GemsFleetReplacementFailed("hard fleet preparation failed")
            runtime.config.LV32_TRIGGERED = False
            runtime.config.GEMS_EMOTION_TRIGGERED = False
            return GemsFleetReplacementCompleted()

        flagship_result = bound.replace_flagship(unit_cancellation)
        if flagship_result.disposition is not GemsShipReplacementDisposition.POLICY_SATISFIED:
            unit_cancellation.raise_if_requested()
            return GemsFleetReplacementFailed("flagship replacement failed")
        if policy.changes_vanguard:
            vanguard_result = bound.replace_vanguard(unit_cancellation)
            if vanguard_result.disposition is not GemsShipReplacementDisposition.POLICY_SATISFIED:
                unit_cancellation.raise_if_requested()
                return GemsFleetReplacementFailed("vanguard replacement failed")

        unit_cancellation.raise_if_requested()
        runtime.config.LV32_TRIGGERED = False
        runtime.config.GEMS_EMOTION_TRIGGERED = False
        return GemsFleetReplacementCompleted()
