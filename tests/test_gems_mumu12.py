from dataclasses import dataclass, field
from typing import TYPE_CHECKING, cast

import pytest

from module.adapters.campaign_live import CampaignActionInterrupted, CommittedCampaignUnit
from module.adapters.gems_mumu12 import Mumu12GemsFleetReplacementExecutor, Mumu12GemsRuntimeBehavior
from module.application import AbortToken, SafeUnitCancellation
from module.campaign.campaign_engine import CampaignEngine
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
    _new_fleet_emotion: int

    def __init__(
        self,
        events: list[str],
        *,
        flagship_result: bool,
        vanguard_result: bool,
    ) -> None:
        self.events = events
        self.flagship_result = flagship_result
        self.vanguard_result = vanguard_result
        self.calls: list[str] = []

    def flagship_change(self) -> bool:
        self.events.append("runner:flagship")
        self.calls.append("flagship")
        self._new_fleet_emotion = 140 if self.flagship_result else 0
        return self.flagship_result

    def vanguard_change(self) -> bool:
        self.events.append("runner:vanguard")
        self.calls.append("vanguard")
        self._new_fleet_emotion = 132 if self.vanguard_result else 0
        return self.vanguard_result

    def hard_fleet_prepare(self) -> bool:
        self.events.append("runner:hard_prepare")
        self.calls.append("hard_prepare")
        return self.flagship_result


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


def _harness(
    *,
    level_triggered: bool = True,
    emotion_triggered: bool = False,
    flagship_result: bool = True,
    vanguard_result: bool = True,
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
    original_cancellation = _Cancellation("original", events)
    committed_cancellation = _Cancellation("committed", events)
    runner = _Runner(
        events,
        flagship_result=flagship_result,
        vanguard_result=vanguard_result,
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
    assert harness.config.records == [{"Emotion_Fleet1Value": 132}]
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
        vanguard_result=False,
    )

    result = harness.executor.replace(
        _job(_policy()),
        _session(),
        GemsFleetReplacementTrigger.EMOTION,
        harness.original_cancellation,
    )

    assert result == GemsFleetReplacementFailed("vanguard replacement failed")
    assert harness.runner.calls == ["flagship", "vanguard"]
    assert harness.config.records == [{"Emotion_Fleet1Value": 0}]
    assert harness.config.GEMS_EMOTION_TRIGGERED


def test_flagship_is_mandatory_and_failure_skips_vanguard() -> None:
    harness = _harness(flagship_result=False)

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
        "committed:check",
        "runner:vanguard",
        "committed:check",
        "config:record",
        "committed:check",
    ]


@pytest.mark.parametrize("succeeds", [True, False])
def test_hard_preparation_uses_its_dedicated_typed_request(*, succeeds: bool) -> None:
    harness = _harness(flagship_result=succeeds)

    result = harness.executor.replace(
        _job(_policy()),
        _session(),
        GemsFleetReplacementTrigger.HARD_PREPARATION,
        harness.original_cancellation,
    )

    assert harness.runner.calls == ["hard_prepare"]
    if succeeds:
        assert isinstance(result, GemsFleetReplacementCompleted)
    else:
        assert result == GemsFleetReplacementFailed("hard fleet preparation failed")


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
