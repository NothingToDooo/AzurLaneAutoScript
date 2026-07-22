from dataclasses import dataclass
from types import SimpleNamespace
from typing import TYPE_CHECKING, cast

import pytest
from config_factory import in_memory_config

from module.adapters.campaign_map_initialization import CampaignMapInitializationService
from module.adapters.campaign_mumu12 import DeclarativeCampaignMapRuntime, Mumu12CampaignAttempt
from module.adapters.campaign_program_capabilities import CampaignProgramCapabilityReader
from module.adapters.campaign_runtime_implementations import (
    load_default_campaign_runtime_executor_registry,
)
from module.adapters.campaign_runtime_profile import (
    CampaignRuntimeProfileError,
    CampaignRuntimeProfileManager,
    RuntimeSessionOutcome,
)
from module.adapters.campaign_runtime_session import RuntimeProfileLease, RuntimeProfileLeaseState
from module.adapters.campaign_submarine import (
    STANDARD_CAMPAIGN_SUBMARINE_SERVICES,
    CampaignSubmarineFreshCombatContributor,
    CampaignSubmarineFreshCombatService,
    CampaignSubmarineSupportPopupContributor,
    SubmarineFreshCombatRuntime,
    build_campaign_submarine_services,
)
from module.application import AbortRequested, AbortToken
from module.content.campaign_session import CampaignRunVariant
from module.content.models import StageRef
from module.content.runtime_profile import (
    CampaignRuntimeExtension,
    CampaignRuntimeExtensionId,
    CampaignRuntimeProfile,
    CampaignRuntimeProfileId,
    RuntimeExecutorBinding,
    RuntimeExecutorKind,
    RuntimeImplementationId,
)
from module.content.stage_loader import load_default_stage
from module.device.device import Device
from module.gameplay.campaign import CampaignJobKind
from module.map.map_base import CampaignMap
from module.map.support_fleet import SupportFleetAttemptState, SupportFleetStateSource, SupportFleetStatus

if TYPE_CHECKING:
    from collections.abc import Callable

    from module.combat.combat import CombatEnd
    from module.content.campaign_session import CampaignSession
    from module.gameplay.campaign import CampaignJobSpec
_SUPPORT_ID = "map_mechanic/support_fleet"
_POPUP_ID = "map_mechanic/submarine_support_popup"
_FRESH_COMBAT_ID = "map_mechanic/submarine_fresh_combat"


class _SubmarineRuntime:
    FUNCTION_NAME_BASE = "TEST_"

    def __init__(self) -> None:
        self.popup_results: list[bool] = []
        self.popup_calls = 0
        self.combat_calls: list[tuple[bool, bool, CombatEnd | None]] = []

    def handle_popup_confirm(self, name: str) -> bool:
        assert name == "SUBMARINE_SUPPORT"
        self.popup_calls += 1
        return self.popup_results.pop(0)

    def combat(
        self,
        *,
        balance_hp: bool,
        emotion_reduce: bool,
        expected_end: CombatEnd | None,
    ) -> object:
        self.combat_calls.append((balance_hp, emotion_reduce, expected_end))
        return None


def _binding(implementation: str) -> RuntimeExecutorBinding:
    return RuntimeExecutorBinding(
        RuntimeExecutorKind.MAP_MECHANIC,
        RuntimeImplementationId(implementation),
        {},
    )


def _manager(*implementations: str) -> CampaignRuntimeProfileManager:
    extensions = tuple(
        CampaignRuntimeExtension(
            CampaignRuntimeExtensionId(f"submarine-test-{index}"),
            (_binding(implementation),),
        )
        for index, implementation in enumerate(implementations)
    )
    return CampaignRuntimeProfileManager(
        CampaignRuntimeProfile(
            CampaignRuntimeProfileId("submarine-test"),
            extensions,
        ),
        load_default_campaign_runtime_executor_registry(),
    )


def _bind_services(
    *implementations: str,
) -> tuple[CampaignRuntimeProfileManager, _SubmarineRuntime, SupportFleetAttemptState]:
    manager = _manager(*implementations)
    runtime = _SubmarineRuntime()
    manager.bind(runtime, CampaignMap("submarine-test"))
    instances = manager.executor_instances(RuntimeExecutorKind.MAP_MECHANIC)
    sources = [instance for instance in instances if isinstance(instance, SupportFleetStateSource)]
    assert len(sources) == 1
    return manager, runtime, sources[0].support_fleet_state


def _begin(manager: CampaignRuntimeProfileManager) -> None:
    manager.begin_session()


def test_popup_service_retries_and_reads_ready_or_sealed_support_state() -> None:
    manager, runtime, state = _bind_services(_SUPPORT_ID, _POPUP_ID)
    services = build_campaign_submarine_services(manager.executor_instances(RuntimeExecutorKind.MAP_MECHANIC))
    runtime.popup_results = [False, True, True]

    assert not services.popup.handle(runtime)
    assert services.popup.handle(runtime)

    state.observe(SupportFleetStatus.EMPTY)
    assert not services.popup.handle(runtime)
    assert runtime.popup_calls == 2

    state.observe(SupportFleetStatus.PRESENT)
    _begin(manager)
    assert state.sealed
    assert services.popup.handle(runtime)
    assert runtime.popup_calls == 3


@pytest.mark.parametrize(
    ("status", "expected_calls"),
    [
        (None, 1),
        (SupportFleetStatus.PRESENT, 1),
        (SupportFleetStatus.EMPTY, 0),
    ],
)
def test_fresh_combat_requires_sealed_state_and_uses_final_support_fact(
    status: SupportFleetStatus | None,
    expected_calls: int,
) -> None:
    manager, runtime, state = _bind_services(_SUPPORT_ID, _FRESH_COMBAT_ID)
    services = build_campaign_submarine_services(manager.executor_instances(RuntimeExecutorKind.MAP_MECHANIC))
    if status is not None:
        state.observe(status)

    with pytest.raises(CampaignRuntimeProfileError, match="sealed"):
        services.fresh_combat.start(runtime)

    _begin(manager)
    assert runtime.combat_calls == []
    services.fresh_combat.start(runtime)

    assert runtime.combat_calls == [(False, False, "no_searching")] * expected_calls


class _PopupContributorSource:
    submarine_support_popup_contributor = CampaignSubmarineSupportPopupContributor(bool)


def _ignore_fresh_combat(runtime: SubmarineFreshCombatRuntime) -> None:
    del runtime


class _FreshContributorSource:
    submarine_fresh_combat_contributor = CampaignSubmarineFreshCombatContributor(_ignore_fresh_combat)


@dataclass(slots=True)
class _SupportStateSource:
    support_fleet_state: object


class _InvalidPopupContributorSource:
    submarine_support_popup_contributor = object()


class _InvalidFreshContributorSource:
    submarine_fresh_combat_contributor = object()


def test_submarine_contributors_require_one_support_state_source() -> None:
    with pytest.raises(CampaignRuntimeProfileError, match="exactly one support fleet"):
        build_campaign_submarine_services((_PopupContributorSource(),))

    state = SupportFleetAttemptState()
    with pytest.raises(CampaignRuntimeProfileError, match="exactly one support fleet"):
        build_campaign_submarine_services(
            (
                _PopupContributorSource(),
                _SupportStateSource(state),
                _SupportStateSource(state),
            )
        )

    with pytest.raises(CampaignRuntimeProfileError, match="must provide SupportFleetAttemptState"):
        build_campaign_submarine_services(
            (
                _PopupContributorSource(),
                _SupportStateSource(object()),
            )
        )

    assert build_campaign_submarine_services(()) is STANDARD_CAMPAIGN_SUBMARINE_SERVICES


@pytest.mark.parametrize(
    ("contributors", "match"),
    [
        ((_PopupContributorSource(), _PopupContributorSource()), "popup"),
        ((_FreshContributorSource(), _FreshContributorSource()), "fresh combat"),
    ],
)
def test_submarine_services_reject_duplicate_contributors(
    contributors: tuple[object, ...],
    match: str,
) -> None:
    with pytest.raises(CampaignRuntimeProfileError, match=match):
        build_campaign_submarine_services((*contributors, _SupportStateSource(SupportFleetAttemptState())))


@pytest.mark.parametrize(
    ("source", "match"),
    [
        (_InvalidPopupContributorSource(), "popup source"),
        (_InvalidFreshContributorSource(), "fresh combat source"),
    ],
)
def test_submarine_services_reject_untyped_contributors(source: object, match: str) -> None:
    with pytest.raises(CampaignRuntimeProfileError, match=match):
        build_campaign_submarine_services((source, _SupportStateSource(SupportFleetAttemptState())))


class _SessionManager:
    def __init__(self, events: list[object]) -> None:
        self.events = events

    def begin_session(self) -> None:
        self.events.append("lease.start")

    def end_session(self, outcome: RuntimeSessionOutcome) -> None:
        self.events.append(("lease.close", outcome))

    def reset(self) -> None:
        self.events.append("reset")


class _SessionRuntime(DeclarativeCampaignMapRuntime):
    FUNCTION_NAME_BASE = "SESSION_TEST_"
    _map_initialization_service: CampaignMapInitializationService
    _program_capabilities: CampaignProgramCapabilityReader
    _runtime_profile: _SessionManager
    _runtime_profile_lease: RuntimeProfileLease
    _submarine_services: SimpleNamespace
    device: Device

    def __init__(self, events: list[object]) -> None:
        self.MAP = CampaignMap("submarine-session")
        self.map = self.MAP
        self.session_variant = CampaignRunVariant.NORMAL
        self.map_is_clear_mode = False
        self.config = in_memory_config("submarine-session", {})
        self.battle_count = 0
        self.events = events

    def map_data_init(self, map_: CampaignMap | None) -> None:
        assert map_ is self.MAP
        self.events.append("map_data_init")

    def map_control_init(self) -> None:
        self.events.append("map_control_init")

    def combat(
        self,
        *,
        balance_hp: bool | None = None,
        emotion_reduce: bool | None = None,
        submarine_mode: str | None = None,
        expected_end: CombatEnd | None = None,
        fleet_index: int = 1,
    ) -> None:
        del self, balance_hp, emotion_reduce, submarine_mode, expected_end, fleet_index
        message = "campaign attempt test injects its fresh combat handler"
        raise AssertionError(message)


def _attempt(
    events: list[object],
    handler: Callable[[SubmarineFreshCombatRuntime], None],
) -> tuple[Mumu12CampaignAttempt, _SessionRuntime]:
    runtime = _SessionRuntime(events)
    service = CampaignSubmarineFreshCombatService(handler)
    manager = _SessionManager(events)
    runtime._runtime_profile_lease = RuntimeProfileLease(manager)  # ruff:ignore[private-member-access] - fake runtime 注入真实 lease。
    runtime._submarine_services = SimpleNamespace(fresh_combat=service)  # ruff:ignore[private-member-access] - 注入被测 fresh service。
    runtime._map_initialization_service = CampaignMapInitializationService()  # ruff:ignore[private-member-access] - 使用标准初始化服务。
    runtime._runtime_profile = manager  # ruff:ignore[private-member-access] - program state 不参与本测试。
    runtime._program_capabilities = CampaignProgramCapabilityReader()  # ruff:ignore[private-member-access] - program 能力不参与本测试。
    device = object.__new__(Device)
    attempt = Mumu12CampaignAttempt(
        cast("DeclarativeCampaignMapRuntime", runtime),
        runtime.take_profile_lease(),
        cast("CampaignJobSpec", SimpleNamespace(kind=CampaignJobKind.STANDARD)),
        cast("CampaignSession", SimpleNamespace()),
        device,
        AbortToken(),
    )
    return attempt, runtime


def test_campaign_attempt_runs_fresh_hook_before_fixed_map_initialization() -> None:
    events: list[object] = []
    attempt, _runtime = _attempt(events, lambda _runtime: events.append("fresh_combat"))

    attempt.initialize(CampaignRunVariant.NORMAL)
    attempt.release(RuntimeSessionOutcome.COMPLETED)

    assert events == [
        "lease.start",
        "fresh_combat",
        "map_data_init",
        "map_control_init",
        ("lease.close", RuntimeSessionOutcome.COMPLETED),
        "reset",
    ]


@pytest.mark.parametrize(
    ("error", "outcome"),
    [
        (AbortRequested("cancelled"), RuntimeSessionOutcome.INTERRUPTED),
        (RuntimeError("failed"), RuntimeSessionOutcome.FAILED),
    ],
)
def test_fresh_hook_failure_closes_the_started_session(
    error: BaseException,
    outcome: RuntimeSessionOutcome,
) -> None:
    events: list[object] = []

    def fail(runtime: object) -> None:
        del runtime
        raise error

    attempt, _runtime = _attempt(events, fail)

    with pytest.raises(type(error)) as raised:
        attempt.initialize(CampaignRunVariant.NORMAL)

    assert raised.value is error
    assert events == [
        "lease.start",
        ("lease.close", outcome),
        "reset",
    ]
    assert attempt.profile_state is RuntimeProfileLeaseState.CLOSED
    assert not attempt.active


@pytest.mark.parametrize(
    ("stage_id", "expected_submarine"),
    [("16-1", True), ("16-2", True), ("16-3", False), ("16-4", False)],
)
def test_real_chapter_16_profiles_wire_only_the_early_submarine_services(
    stage_id: str,
    *,
    expected_submarine: bool,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    definition = load_default_stage(StageRef("campaign_main", stage_id))
    implementation_ids = {
        binding.implementation_id.value
        for extension in definition.runtime_profile.extensions
        for binding in extension.executors
    }
    runtime = DeclarativeCampaignMapRuntime(
        in_memory_config(f"submarine-wiring-{stage_id}", {}),
        object.__new__(Device),
        definition,
    )
    popup_calls: list[str] = []
    combat_calls: list[str] = []

    def confirm(name: str) -> bool:
        popup_calls.append(name)
        return True

    def combat(**kwargs: object) -> None:
        assert kwargs == {
            "balance_hp": False,
            "emotion_reduce": False,
            "expected_end": "no_searching",
        }
        combat_calls.append("combat")

    monkeypatch.setattr(runtime, "handle_popup_confirm", confirm)
    monkeypatch.setattr(runtime, "combat", combat)

    assert runtime.handle_submarine_support_popup() is expected_submarine
    assert popup_calls == (["SUBMARINE_SUPPORT"] if expected_submarine else [])
    lease = runtime.take_profile_lease()
    lease.start()
    assert combat_calls == []
    runtime.fresh_combat_service.start(runtime)
    assert combat_calls == (["combat"] if expected_submarine else [])
    lease.close(RuntimeSessionOutcome.COMPLETED)

    assert (_POPUP_ID in implementation_ids) is expected_submarine
    assert (_FRESH_COMBAT_ID in implementation_ids) is expected_submarine
