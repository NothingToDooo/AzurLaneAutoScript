from dataclasses import dataclass
from types import SimpleNamespace
from typing import TYPE_CHECKING, cast

import pytest
from config_factory import in_memory_config

import module.adapters.campaign_runtime_mechanics as mechanics_module
from module.adapters.campaign_map_session_mumu12 import Mumu12CampaignMapSessionOwner
from module.adapters.campaign_mumu12 import DeclarativeCampaignMapRuntime
from module.adapters.campaign_runtime_implementations import (
    default_campaign_runtime_executor_descriptors,
    load_default_campaign_runtime_executor_registry,
)
from module.adapters.campaign_runtime_profile import (
    CampaignRuntimeProfileError,
    CampaignRuntimeProfileManager,
    RuntimeOperation,
    RuntimeSessionContext,
    RuntimeSessionEntryKind,
    RuntimeSessionOutcome,
)
from module.adapters.campaign_runtime_session import RuntimeProfileLease
from module.adapters.campaign_submarine import (
    STANDARD_CAMPAIGN_SUBMARINE_SERVICES,
    CampaignSubmarineFreshCombatContributor,
    CampaignSubmarineFreshCombatService,
    CampaignSubmarineSupportPopupContributor,
    SubmarineFreshCombatRuntime,
    build_campaign_submarine_services,
)
from module.application import AbortRequested
from module.content.campaign_session import (
    CampaignRunVariant,
    CampaignSessionState,
    CampaignSessionStatus,
    RemainingSpawns,
)
from module.content.mechanic_rules import MapMutationRules
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
from module.content.runtime_profile_catalog import (
    load_default_campaign_runtime_profile_registry as load_default_profile_registry,
)
from module.content.stage_loader import load_default_stage
from module.device.device import Device
from module.map.map_base import CampaignMap
from module.map.support_fleet import SupportFleetAttemptState, SupportFleetStateSource, SupportFleetStatus

if TYPE_CHECKING:
    from collections.abc import Callable

    from module.combat.combat import CombatEnd
    from module.content.stage_definition import CampaignStageDefinition


_SUPPORT_ID = "map_mechanic/support_fleet"
_POPUP_ID = "map_mechanic/submarine_support_popup"
_FRESH_COMBAT_ID = "map_mechanic/submarine_fresh_combat"
_OLD_ID = "map_mechanic/submarine_fresh_entry"


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
    manager.begin_session(
        RuntimeSessionContext(
            CampaignRunVariant.NORMAL,
            0,
            RuntimeSessionEntryKind.FRESH,
        )
    )


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

    def begin_session(self, context: RuntimeSessionContext) -> None:
        self.events.append(("lease.start", context.entry_kind))

    def end_session(self, outcome: RuntimeSessionOutcome) -> None:
        self.events.append(("lease.close", outcome))

    def reset(self) -> None:
        self.events.append("reset")


class _SessionRuntime:
    FUNCTION_NAME_BASE = "SESSION_TEST_"

    def __init__(self, events: list[object]) -> None:
        self.definition = cast(
            "CampaignStageDefinition",
            SimpleNamespace(mechanics=SimpleNamespace(map_mutations=MapMutationRules())),
        )
        self.MAP = CampaignMap("submarine-session")
        self.map = self.MAP
        self.session_variant = CampaignRunVariant.NORMAL
        self.map_is_clear_mode = False
        self.battle_count = 0
        self.events = events

    def map_init(self, map_: CampaignMap | None) -> None:
        assert map_ is self.MAP
        self.events.append("map_init")

    @staticmethod
    def combat(
        *,
        balance_hp: bool,
        emotion_reduce: bool,
        expected_end: CombatEnd | None,
    ) -> object:
        del balance_hp, emotion_reduce, expected_end
        message = "session owner test injects its fresh combat handler"
        raise AssertionError(message)


def _session_state(battle_index: int = 0) -> CampaignSessionState:
    return CampaignSessionState(
        CampaignRunVariant.NORMAL,
        CampaignSessionStatus.ACTIVE,
        battle_index,
        RemainingSpawns(),
    )


def _owner(
    events: list[object],
    handler: Callable[[SubmarineFreshCombatRuntime], None],
) -> tuple[Mumu12CampaignMapSessionOwner, _SessionRuntime]:
    runtime = _SessionRuntime(events)
    service = CampaignSubmarineFreshCombatService(handler)
    owner = Mumu12CampaignMapSessionOwner(
        runtime,
        RuntimeProfileLease(_SessionManager(events)),
        service,
    )
    return owner, runtime


def test_session_owner_runs_fresh_hook_after_lease_start_and_before_map_init() -> None:
    events: list[object] = []
    owner, _runtime = _owner(events, lambda _runtime: events.append("fresh_combat"))

    owner.initialize(_session_state(), RuntimeSessionEntryKind.FRESH)

    assert events == [
        ("lease.start", RuntimeSessionEntryKind.FRESH),
        "fresh_combat",
        "map_init",
    ]


def test_session_owner_skips_fresh_hook_for_a_resume_entry() -> None:
    cold_events: list[object] = []
    cold_owner, _runtime = _owner(cold_events, lambda _runtime: cold_events.append("fresh_combat"))

    cold_owner.initialize(_session_state(2), RuntimeSessionEntryKind.RESUME)
    assert cold_events == [
        ("lease.start", RuntimeSessionEntryKind.RESUME),
        "map_init",
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

    owner, _runtime = _owner(events, fail)

    with pytest.raises(type(error)) as raised:
        owner.initialize(_session_state(), RuntimeSessionEntryKind.FRESH)

    assert raised.value is error
    assert events == [
        ("lease.start", RuntimeSessionEntryKind.FRESH),
        ("lease.close", outcome),
        "reset",
    ]
    assert not owner.active


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
    runtime._runtime_profile_lease.start(  # ruff:ignore[private-member-access] - direct hard-style lease boundary must not execute owner hooks.
        RuntimeSessionContext(
            CampaignRunVariant.NORMAL,
            0,
            RuntimeSessionEntryKind.FRESH,
        )
    )
    assert combat_calls == []
    runtime._submarine_services.fresh_combat.start(runtime)  # ruff:ignore[private-member-access] - 验证生产 profile 编译出的 typed hook。
    assert combat_calls == (["combat"] if expected_submarine else [])
    runtime._runtime_profile_lease.close(RuntimeSessionOutcome.COMPLETED)  # ruff:ignore[private-member-access] - 完整关闭纯内存 session。

    assert (_POPUP_ID in implementation_ids) is expected_submarine
    assert (_FRESH_COMBAT_ID in implementation_ids) is expected_submarine
    assert _OLD_ID not in implementation_ids


def test_old_submarine_runtime_surfaces_are_removed() -> None:
    implementation_ids = {
        descriptor.implementation_id.value for descriptor in default_campaign_runtime_executor_descriptors()
    }

    assert "HANDLE_SUBMARINE_SUPPORT_POPUP" not in RuntimeOperation.__members__
    assert _OLD_ID not in implementation_ids
    assert _POPUP_ID in implementation_ids
    assert _FRESH_COMBAT_ID in implementation_ids
    assert not hasattr(mechanics_module, "SubmarineFreshEntryExecutor")
    mechanic_host = vars(mechanics_module)["_MechanicRuntimeHost"]
    for removed in ("FUNCTION_NAME_BASE", "handle_popup_confirm", "combat"):
        assert not hasattr(mechanic_host, removed)

    extension_ids = {extension_id.value for extension_id in load_default_profile_registry().extensions}
    assert "campaign_main/campaign_16_base_submarine/campaign_base" not in extension_ids
