from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import TYPE_CHECKING, cast

import pytest

from module.adapters.campaign_live import CampaignActionInterrupted, CommittedCampaignUnit
from module.adapters.gems_mumu12 import Mumu12GemsFleetReplacementExecutor, Mumu12GemsRuntimeBehavior
from module.application import AbortToken, SafeUnitCancellation
from module.campaign.campaign_engine import CampaignEngine
from module.campaign.gems_farming import (
    GemsShipReplacementDisposition,
    GemsShipReplacementFactSink,
    GemsShipReplacementResult,
)
from module.config.config import AzurLaneConfig
from module.content.campaign_session import BattleInterruptionReason, CampaignSession
from module.gameplay.campaign import (
    GemsCommonCarrier,
    GemsCommonDestroyer,
    GemsFarmingPolicy,
    GemsFlagshipChange,
    GemsVanguardChange,
)
from module.gameplay.campaign_live import (
    GemsFleetReplacementCompleted,
    GemsFleetReplacementFailed,
    GemsFleetReplacementTrigger,
)
from module.handler.assets import AUTO_SEARCH_MAP_OPTION_OFF

if TYPE_CHECKING:
    from collections.abc import Iterator

    from module.adapters.campaign_live import CampaignMapRuntime
    from module.device.device import Device
    from module.gameplay.campaign import CampaignJobSpec
    from module.interaction import CancellationSignal


@dataclass(slots=True)
class _Cancellation:
    name: str
    events: list[str]
    requested: bool = False

    def raise_if_requested(self) -> None:
        self.events.append(f"{self.name}:check")
        if self.requested:
            message = f"{self.name} cancellation requested"
            raise RuntimeError(message)


@dataclass(slots=True)
class _Config:
    events: list[str]
    LV32_TRIGGERED: bool = False
    GEMS_EMOTION_TRIGGERED: bool = False
    overlays: list[dict[str, object]] = field(default_factory=list)
    records: list[dict[str, object]] = field(default_factory=list)

    def apply_runtime_overlay(self, **values: object) -> None:
        self.events.append("config:overlay")
        self.overlays.append(values)

    def set_record(self, **values: object) -> None:
        self.events.append("config:record")
        self.records.append(values)


@dataclass(slots=True)
class _Device:
    events: list[str]


class _Runtime(CampaignEngine):
    pass


class _Runner:
    config: AzurLaneConfig
    device: Device
    campaign: CampaignEngine

    def __init__(
        self,
        events: list[str],
        *,
        flagship_result: GemsShipReplacementResult,
        vanguard_result: GemsShipReplacementResult,
        hard_results: tuple[GemsShipReplacementResult, ...],
    ) -> None:
        self.events = events
        self.flagship_result = flagship_result
        self.vanguard_result = vanguard_result
        self.calls: list[str] = []
        self.hard_results = hard_results
        self.flagship_fact_mode = "normal"
        self.flagship_return_result: GemsShipReplacementResult | None = None
        self.cancel_after_flagship: _Cancellation | None = None
        self.cancel_after_vanguard: _Cancellation | None = None
        self.vanguard_error: RuntimeError | None = None
        self.flagship_cleanup_error: RuntimeError | None = None
        self.vanguard_cleanup_error: RuntimeError | None = None
        self.hard_error_after_first: RuntimeError | None = None

    def flagship_change(self, fact_sink: GemsShipReplacementFactSink) -> GemsShipReplacementResult:
        self.events.append("runner:flagship")
        self.calls.append("flagship")
        if self.flagship_fact_mode != "missing":
            fact_sink(self.flagship_result)
        if self.flagship_fact_mode == "duplicate":
            fact_sink(self.flagship_result)
        if self.flagship_cleanup_error is not None:
            raise self.flagship_cleanup_error
        if self.cancel_after_flagship is not None:
            self.cancel_after_flagship.requested = True
        return self.flagship_result if self.flagship_return_result is None else self.flagship_return_result

    def vanguard_change(self, fact_sink: GemsShipReplacementFactSink) -> GemsShipReplacementResult:
        self.events.append("runner:vanguard")
        self.calls.append("vanguard")
        if self.vanguard_error is not None:
            raise self.vanguard_error
        fact_sink(self.vanguard_result)
        if self.vanguard_cleanup_error is not None:
            raise self.vanguard_cleanup_error
        if self.cancel_after_vanguard is not None:
            self.cancel_after_vanguard.requested = True
        return self.vanguard_result

    def hard_fleet_prepare(
        self,
        fact_sink: GemsShipReplacementFactSink,
    ) -> Iterator[GemsShipReplacementResult]:
        self.events.append("runner:hard_prepare")
        self.calls.append("hard_prepare")
        for index, result in enumerate(self.hard_results):
            fact_sink(result)
            if index == 0 and self.hard_error_after_first is not None:
                raise self.hard_error_after_first
            yield result


@dataclass(slots=True)
class _RunnerFactory:
    runner: _Runner
    expected_config: _Config
    expected_device: _Device

    def __call__(self, config: AzurLaneConfig, device: Device) -> _Runner:
        assert config is self.expected_config
        assert device is self.expected_device
        self.runner.events.append("runner:factory")
        self.runner.config = config
        self.runner.device = device
        return self.runner


@dataclass(slots=True)
class _SafeUnitSource:
    runtime: _Runtime
    committed_cancellation: CancellationSignal
    calls: list[tuple[object, CancellationSignal]] = field(default_factory=list)

    def commit_replacement_unit(
        self,
        session: CampaignSession,
        cancellation: CancellationSignal,
    ) -> CommittedCampaignUnit:
        cancellation.raise_if_requested()
        self.calls.append((session, cancellation))
        return CommittedCampaignUnit(
            cast("CampaignMapRuntime", self.runtime),
            self.committed_cancellation,
        )


@dataclass(slots=True)
class _Job:
    gems_farming: GemsFarmingPolicy | None


@dataclass(slots=True)
class _Harness:
    events: list[str]
    config: _Config
    device: _Device
    runtime: _Runtime
    original_cancellation: _Cancellation
    committed_cancellation: _Cancellation
    runner: _Runner
    source: _SafeUnitSource
    executor: Mumu12GemsFleetReplacementExecutor


def _policy(*, vanguard: GemsVanguardChange = GemsVanguardChange.SHIP) -> GemsFarmingPolicy:
    return GemsFarmingPolicy(
        object.__new__(CampaignSession),
        GemsFlagshipChange.SHIP_AND_EQUIPMENT,
        GemsCommonCarrier.BOGUE,
        vanguard,
        GemsCommonDestroyer.Z20_OR_Z21,
        "DD: test-code",
    )


def _job(policy: GemsFarmingPolicy | None) -> CampaignJobSpec:
    return cast("CampaignJobSpec", _Job(policy))


def _session() -> CampaignSession:
    return cast("CampaignSession", object())


_FLAGSHIP_POLICY_RESULT = GemsShipReplacementResult(GemsShipReplacementDisposition.POLICY_SATISFIED, 140)
_VANGUARD_POLICY_RESULT = GemsShipReplacementResult(GemsShipReplacementDisposition.POLICY_SATISFIED, 132)
_HARD_POLICY_RESULTS = (GemsShipReplacementResult(GemsShipReplacementDisposition.POLICY_SATISFIED, 70),)


def _harness(
    *,
    level_triggered: bool = True,
    emotion_triggered: bool = False,
    flagship_result: GemsShipReplacementResult = _FLAGSHIP_POLICY_RESULT,
    vanguard_result: GemsShipReplacementResult = _VANGUARD_POLICY_RESULT,
    hard_results: tuple[GemsShipReplacementResult, ...] = _HARD_POLICY_RESULTS,
) -> _Harness:
    events: list[str] = []
    config = _Config(
        events,
        LV32_TRIGGERED=level_triggered,
        GEMS_EMOTION_TRIGGERED=emotion_triggered,
    )
    device = _Device(events)
    runtime = object.__new__(_Runtime)
    runtime.config = cast("AzurLaneConfig", config)
    runtime.device = cast("Device", device)
    runtime.emotion = SimpleNamespace(
        fleet_1=SimpleNamespace(current=80),
        update=lambda: events.append("emotion:update"),
    )
    original_cancellation = _Cancellation("original", events)
    committed_cancellation = _Cancellation("committed", events)
    runner = _Runner(
        events,
        flagship_result=flagship_result,
        vanguard_result=vanguard_result,
        hard_results=hard_results,
    )
    source = _SafeUnitSource(runtime, committed_cancellation)
    factory = _RunnerFactory(runner, config, device)
    executor = Mumu12GemsFleetReplacementExecutor(source, runner_factory=factory)
    return _Harness(
        events,
        config,
        device,
        runtime,
        original_cancellation,
        committed_cancellation,
        runner,
        source,
        executor,
    )


def test_replacement_projects_policy_and_closes_level_trigger() -> None:
    harness = _harness()
    session = _session()
    policy = _policy()

    result = harness.executor.replace(
        _job(policy),
        session,
        GemsFleetReplacementTrigger.LEVEL,
        harness.original_cancellation,
    )

    assert isinstance(result, GemsFleetReplacementCompleted)
    assert harness.source.calls == [(session, harness.original_cancellation)]
    assert harness.runner.campaign is harness.runtime
    assert harness.runner.calls == ["flagship", "vanguard"]
    assert harness.config.overlays == [
        {
            "GemsFarming_ChangeFlagship": "ship_equip",
            "GemsFarming_CommonCV": "bogue",
            "GemsFarming_ChangeVanguard": "ship",
            "GemsFarming_CommonDD": "z20_or_z21",
            "EquipmentCode_Config": "DD: test-code",
        }
    ]
    assert harness.config.records == [
        {"Emotion_Fleet1Value": 140},
        {"Emotion_Fleet1Value": 132},
    ]
    assert not harness.config.LV32_TRIGGERED
    assert not harness.config.GEMS_EMOTION_TRIGGERED


def test_disabled_vanguard_only_replaces_mandatory_flagship() -> None:
    harness = _harness()

    result = harness.executor.replace(
        _job(_policy(vanguard=GemsVanguardChange.DISABLED)),
        _session(),
        GemsFleetReplacementTrigger.LEVEL,
        harness.original_cancellation,
    )

    assert isinstance(result, GemsFleetReplacementCompleted)
    assert harness.runner.calls == ["flagship"]
    assert harness.config.records == [{"Emotion_Fleet1Value": 140}]


def test_vanguard_failure_records_emotion_and_preserves_triggers() -> None:
    harness = _harness(
        level_triggered=False,
        emotion_triggered=True,
        vanguard_result=GemsShipReplacementResult(GemsShipReplacementDisposition.NO_CANDIDATE, None),
    )

    result = harness.executor.replace(
        _job(_policy()),
        _session(),
        GemsFleetReplacementTrigger.EMOTION,
        harness.original_cancellation,
    )

    assert result == GemsFleetReplacementFailed("vanguard replacement failed")
    assert harness.runner.calls == ["flagship", "vanguard"]
    assert harness.config.records == [
        {"Emotion_Fleet1Value": 140},
        {"Emotion_Fleet1Value": 0},
    ]
    assert harness.config.GEMS_EMOTION_TRIGGERED


def test_flagship_is_mandatory_and_failure_skips_vanguard() -> None:
    harness = _harness(
        flagship_result=GemsShipReplacementResult(GemsShipReplacementDisposition.NO_CANDIDATE, None),
    )

    result = harness.executor.replace(
        _job(_policy()),
        _session(),
        GemsFleetReplacementTrigger.LEVEL,
        harness.original_cancellation,
    )

    assert result == GemsFleetReplacementFailed("flagship replacement failed")
    assert harness.runner.calls == ["flagship"]
    assert harness.config.records == [{"Emotion_Fleet1Value": 0}]
    assert harness.config.LV32_TRIGGERED


def test_invalid_trigger_is_rejected_before_safe_unit_commit() -> None:
    harness = _harness()

    with pytest.raises(TypeError, match="GemsFleetReplacementTrigger"):
        harness.executor.replace(
            _job(_policy()),
            _session(),
            cast("GemsFleetReplacementTrigger", "level"),
            harness.original_cancellation,
        )

    assert harness.source.calls == []
    assert harness.events == []


def test_typed_request_does_not_depend_on_process_local_trigger_flags() -> None:
    harness = _harness(level_triggered=False)

    result = harness.executor.replace(
        _job(_policy()),
        _session(),
        GemsFleetReplacementTrigger.LEVEL,
        harness.original_cancellation,
    )

    assert isinstance(result, GemsFleetReplacementCompleted)
    assert harness.runner.calls == ["flagship", "vanguard"]
    assert harness.config.overlays


def test_committed_cancellation_guards_every_followup_io() -> None:
    harness = _harness()

    harness.executor.replace(
        _job(_policy()),
        _session(),
        GemsFleetReplacementTrigger.LEVEL,
        harness.original_cancellation,
    )

    assert harness.events == [
        "original:check",
        "committed:check",
        "runner:factory",
        "committed:check",
        "config:overlay",
        "committed:check",
        "runner:flagship",
        "config:record",
        "committed:check",
        "runner:vanguard",
        "config:record",
        "committed:check",
    ]


@pytest.mark.parametrize("succeeds", [True, False])
def test_hard_preparation_uses_its_dedicated_typed_request(*, succeeds: bool) -> None:
    disposition = (
        GemsShipReplacementDisposition.POLICY_SATISFIED if succeeds else GemsShipReplacementDisposition.FALLBACK_USED
    )
    emotion = 70 if succeeds else 55
    harness = _harness(hard_results=(GemsShipReplacementResult(disposition, emotion),))

    result = harness.executor.replace(
        _job(_policy()),
        _session(),
        GemsFleetReplacementTrigger.HARD_PREPARATION,
        harness.original_cancellation,
    )

    assert harness.runner.calls == ["hard_prepare"]
    assert harness.config.records == [{"Emotion_Fleet1Value": emotion}]
    if succeeds:
        assert isinstance(result, GemsFleetReplacementCompleted)
    else:
        assert result == GemsFleetReplacementFailed("hard fleet preparation failed")


def test_fallback_ship_records_its_emotion_but_keeps_replacement_failed() -> None:
    harness = _harness(
        vanguard_result=GemsShipReplacementResult(GemsShipReplacementDisposition.FALLBACK_USED, 55),
    )

    result = harness.executor.replace(
        _job(_policy()),
        _session(),
        GemsFleetReplacementTrigger.EMOTION,
        harness.original_cancellation,
    )

    assert result == GemsFleetReplacementFailed("vanguard replacement failed")
    assert harness.runner.calls == ["flagship", "vanguard"]
    assert harness.config.records == [
        {"Emotion_Fleet1Value": 140},
        {"Emotion_Fleet1Value": 55},
    ]
    assert harness.config.LV32_TRIGGERED


def test_completed_flagship_emotion_is_recorded_before_vanguard_error() -> None:
    vanguard_error = RuntimeError("vanguard replacement crashed")
    harness = _harness(
        flagship_result=GemsShipReplacementResult(GemsShipReplacementDisposition.POLICY_SATISFIED, 17),
    )
    harness.runner.vanguard_error = vanguard_error

    with pytest.raises(RuntimeError) as raised:
        harness.executor.replace(
            _job(_policy()),
            _session(),
            GemsFleetReplacementTrigger.LEVEL,
            harness.original_cancellation,
        )

    assert raised.value is vanguard_error
    assert harness.runner.calls == ["flagship", "vanguard"]
    assert harness.config.records == [{"Emotion_Fleet1Value": 17}]
    assert harness.config.LV32_TRIGGERED
    assert not harness.config.GEMS_EMOTION_TRIGGERED


@pytest.mark.parametrize("position", ["flagship", "vanguard"])
def test_completed_replacement_is_recorded_before_primitive_cleanup_error(position: str) -> None:
    cleanup_error = RuntimeError(f"{position} equipment restoration failed")
    harness = _harness(level_triggered=False, emotion_triggered=True)
    if position == "flagship":
        harness.runner.flagship_cleanup_error = cleanup_error
    else:
        harness.runner.vanguard_cleanup_error = cleanup_error

    with pytest.raises(RuntimeError) as raised:
        harness.executor.replace(
            _job(_policy()),
            _session(),
            GemsFleetReplacementTrigger.EMOTION,
            harness.original_cancellation,
        )

    assert raised.value is cleanup_error
    assert harness.config.records == (
        [{"Emotion_Fleet1Value": 140}]
        if position == "flagship"
        else [
            {"Emotion_Fleet1Value": 140},
            {"Emotion_Fleet1Value": 132},
        ]
    )
    assert not harness.config.LV32_TRIGGERED
    assert harness.config.GEMS_EMOTION_TRIGGERED


@pytest.mark.parametrize(
    ("fact_mode", "return_result", "error_type", "message"),
    [
        ("missing", None, TypeError, "did not report"),
        ("duplicate", None, TypeError, "more than one"),
        (
            "normal",
            GemsShipReplacementResult(GemsShipReplacementDisposition.POLICY_SATISFIED, 99),
            ValueError,
            "different completion fact",
        ),
    ],
)
def test_replacement_bridge_fact_contract_fails_closed_after_preserving_the_reported_fact(
    fact_mode: str,
    return_result: GemsShipReplacementResult | None,
    error_type: type[Exception],
    message: str,
) -> None:
    harness = _harness()
    harness.runner.flagship_fact_mode = fact_mode
    harness.runner.flagship_return_result = return_result

    with pytest.raises(error_type, match=message):
        harness.executor.replace(
            _job(_policy()),
            _session(),
            GemsFleetReplacementTrigger.LEVEL,
            harness.original_cancellation,
        )

    assert harness.config.records == [{"Emotion_Fleet1Value": 140}]
    assert harness.config.LV32_TRIGGERED
    assert not harness.config.GEMS_EMOTION_TRIGGERED


def test_completed_flagship_emotion_is_recorded_before_vanguard_cancellation() -> None:
    harness = _harness(
        flagship_result=GemsShipReplacementResult(GemsShipReplacementDisposition.POLICY_SATISFIED, 17),
    )
    harness.runner.cancel_after_flagship = harness.committed_cancellation

    with pytest.raises(RuntimeError, match="committed cancellation requested"):
        harness.executor.replace(
            _job(_policy()),
            _session(),
            GemsFleetReplacementTrigger.LEVEL,
            harness.original_cancellation,
        )

    assert harness.runner.calls == ["flagship"]
    assert harness.config.records == [{"Emotion_Fleet1Value": 17}]
    assert harness.config.LV32_TRIGGERED
    assert not harness.config.GEMS_EMOTION_TRIGGERED


def test_completed_vanguard_emotion_is_recorded_before_final_cancellation() -> None:
    harness = _harness(level_triggered=False, emotion_triggered=True)
    harness.runner.cancel_after_vanguard = harness.committed_cancellation

    with pytest.raises(RuntimeError, match="committed cancellation requested"):
        harness.executor.replace(
            _job(_policy()),
            _session(),
            GemsFleetReplacementTrigger.EMOTION,
            harness.original_cancellation,
        )

    assert harness.runner.calls == ["flagship", "vanguard"]
    assert harness.config.records == [
        {"Emotion_Fleet1Value": 140},
        {"Emotion_Fleet1Value": 132},
    ]
    assert not harness.config.LV32_TRIGGERED
    assert harness.config.GEMS_EMOTION_TRIGGERED


def test_hard_preparation_records_each_completed_result_before_later_error() -> None:
    hard_error = RuntimeError("hard vanguard replacement crashed")
    harness = _harness(
        hard_results=(
            GemsShipReplacementResult(GemsShipReplacementDisposition.POLICY_SATISFIED, 70),
            GemsShipReplacementResult(GemsShipReplacementDisposition.POLICY_SATISFIED, 60),
        ),
    )
    harness.runner.hard_error_after_first = hard_error

    with pytest.raises(RuntimeError) as raised:
        harness.executor.replace(
            _job(_policy()),
            _session(),
            GemsFleetReplacementTrigger.HARD_PREPARATION,
            harness.original_cancellation,
        )

    assert raised.value is hard_error
    assert harness.config.records == [{"Emotion_Fleet1Value": 70}]
    assert harness.config.LV32_TRIGGERED
    assert not harness.config.GEMS_EMOTION_TRIGGERED


def test_success_records_each_completion_without_a_final_duplicate() -> None:
    harness = _harness(
        vanguard_result=GemsShipReplacementResult(GemsShipReplacementDisposition.POLICY_SATISFIED, 145),
    )

    result = harness.executor.replace(
        _job(_policy()),
        _session(),
        GemsFleetReplacementTrigger.LEVEL,
        harness.original_cancellation,
    )

    assert isinstance(result, GemsFleetReplacementCompleted)
    assert harness.config.records == [
        {"Emotion_Fleet1Value": 140},
        {"Emotion_Fleet1Value": 140},
    ]
    assert not harness.config.LV32_TRIGGERED
    assert not harness.config.GEMS_EMOTION_TRIGGERED


class _LowEmotionRuntime:
    def __init__(self, *, confirm: bool = False, cancel: tuple[bool, ...] = (), in_stage: bool = False) -> None:
        self.confirm = confirm
        self.cancel = list(cancel)
        self.in_stage = in_stage
        self.calls: list[tuple[object, ...]] = []
        self.device = self

    def handle_popup_confirm(self, name: str) -> bool:
        self.calls.append(("confirm", name))
        return self.confirm

    def interval_reset(self, button: object) -> None:
        self.calls.append(("interval_reset", button))

    def handle_popup_cancel(self, name: str) -> bool:
        self.calls.append(("cancel", name))
        return self.cancel.pop(0) if self.cancel else False

    def screenshot(self) -> None:
        self.calls.append(("screenshot",))

    @staticmethod
    def handle_story_skip() -> bool:
        return False

    @staticmethod
    def appear(_button: object, **_kwargs: object) -> bool:
        return False

    @staticmethod
    def handle_auto_search_exit() -> bool:
        return False

    def is_in_stage(self) -> bool:
        return self.in_stage

    @staticmethod
    def is_in_map() -> bool:
        return False


def _gems_behavior(*, vanguard: GemsVanguardChange) -> Mumu12GemsRuntimeBehavior:
    config = AzurLaneConfig.from_snapshot("gems-runtime-behavior", {})
    return Mumu12GemsRuntimeBehavior(
        config,
        _policy(vanguard=vanguard),
        SafeUnitCancellation(AbortToken()),
    )


def test_low_emotion_without_vanguard_change_confirms_ignore() -> None:
    runtime = _LowEmotionRuntime(confirm=True)

    result = _gems_behavior(vanguard=GemsVanguardChange.DISABLED).handle_low_emotion(
        cast("CampaignEngine", runtime),
    )

    assert result is True
    assert runtime.calls == [
        ("confirm", "IGNORE_LOW_EMOTION"),
        ("interval_reset", AUTO_SEARCH_MAP_OPTION_OFF),
    ]


def test_low_emotion_with_vanguard_change_exits_to_safe_stage_boundary() -> None:
    runtime = _LowEmotionRuntime(cancel=(True, False), in_stage=True)

    with pytest.raises(CampaignActionInterrupted) as exc_info:
        _gems_behavior(vanguard=GemsVanguardChange.SHIP).handle_low_emotion(
            cast("CampaignEngine", runtime),
        )

    assert exc_info.value.reason is BattleInterruptionReason.GEMS_LOW_EMOTION
    assert runtime.calls == [
        ("cancel", "IGNORE_LOW_EMOTION"),
        ("screenshot",),
        ("cancel", "IGNORE_LOW_EMOTION"),
    ]
