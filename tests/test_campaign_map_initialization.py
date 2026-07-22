from dataclasses import dataclass
from types import SimpleNamespace
from typing import TYPE_CHECKING, cast

import pytest
from config_factory import in_memory_config

from module.adapters.campaign_map_initialization import (
    CampaignMapInitializationContributor,
    CampaignMapInitializationRuntime,
    CampaignMapInitializationService,
    build_campaign_map_initialization_service,
)
from module.adapters.campaign_mumu12 import Mumu12CampaignAttempt
from module.adapters.campaign_program_capabilities import CampaignProgramCapabilityReader
from module.adapters.campaign_runtime_implementations import load_default_campaign_runtime_executor_registry
from module.adapters.campaign_runtime_profile import (
    CampaignRuntimeExecutorRegistry,
    CampaignRuntimeProfileManager,
    RuntimeExecutorBuildContext,
    RuntimeExecutorFactoryDescriptor,
    RuntimeExecutorInstance,
    RuntimeExecutorOptionsSchema,
)
from module.adapters.campaign_runtime_session import RuntimeProfileLease, RuntimeProfileLeaseState
from module.adapters.campaign_submarine import STANDARD_CAMPAIGN_SUBMARINE_SERVICES
from module.application import AbortToken
from module.content.campaign_session import CampaignRunVariant
from module.content.runtime_profile import (
    CampaignRuntimeExtension,
    CampaignRuntimeExtensionId,
    CampaignRuntimeProfile,
    CampaignRuntimeProfileId,
    RuntimeExecutorBinding,
    RuntimeExecutorKind,
    RuntimeImplementationId,
)
from module.device.device import Device
from module.gameplay.campaign import CampaignJobKind
from module.map.map_base import CampaignMap
from module.map_detection.utils_assets import ASSETS

if TYPE_CHECKING:
    from collections.abc import Callable

    from module.adapters.campaign_mumu12 import DeclarativeCampaignMapRuntime
    from module.combat.combat import CombatEnd
    from module.content.campaign_session import CampaignSession
    from module.gameplay.campaign import CampaignJobSpec


@dataclass(frozen=True, slots=True)
class _ContributorSource:
    map_initialization_contributor: CampaignMapInitializationContributor


class _InitializationExecutor(RuntimeExecutorInstance):
    __slots__ = ("_map_initialization_contributor",)

    def __init__(
        self,
        kind: RuntimeExecutorKind,
        contributor: CampaignMapInitializationContributor,
    ) -> None:
        self._map_initialization_contributor = contributor
        super().__init__({kind})

    @property
    def map_initialization_contributor(self) -> CampaignMapInitializationContributor:
        return self._map_initialization_contributor


def _trace_hook(label: str, trace: list[str]) -> Callable[[CampaignMapInitializationRuntime], None]:
    def run(runtime: CampaignMapInitializationRuntime) -> None:
        del runtime
        trace.append(label)

    return run


def test_initialization_contributors_preserve_profile_order_per_explicit_phase() -> None:
    trace: list[str] = []
    service = build_campaign_map_initialization_service(
        (
            _ContributorSource(
                CampaignMapInitializationContributor(
                    pre_control=_trace_hook("first:pre", trace),
                    post_control=_trace_hook("first:post", trace),
                )
            ),
            _ContributorSource(
                CampaignMapInitializationContributor(
                    pre_control=_trace_hook("second:pre", trace),
                    post_control=_trace_hook("second:post", trace),
                )
            ),
        )
    )
    runtime = cast("CampaignMapInitializationRuntime", object())

    service.pre_control(runtime)
    service.post_control(runtime)

    assert trace == ["first:pre", "second:pre", "first:post", "second:post"]


def test_manager_accessor_preserves_cross_kind_profile_order_for_initialization() -> None:
    trace: list[str] = []
    specifications = (
        ("first", RuntimeExecutorKind.MAP_MECHANIC),
        ("second", RuntimeExecutorKind.ENGINE_EXTENSION),
        ("third", RuntimeExecutorKind.MAP_MECHANIC),
    )
    descriptors: list[RuntimeExecutorFactoryDescriptor] = []
    extensions: list[CampaignRuntimeExtension] = []
    for label, kind in specifications:
        implementation_id = RuntimeImplementationId(f"initialization/{label}")
        contributor = CampaignMapInitializationContributor(
            pre_control=_trace_hook(f"{label}:pre", trace),
            post_control=_trace_hook(f"{label}:post", trace),
        )

        def build(
            context: RuntimeExecutorBuildContext,
            *,
            expected_kind: RuntimeExecutorKind = kind,
            selected: CampaignMapInitializationContributor = contributor,
        ) -> RuntimeExecutorInstance:
            _ = context.options(expected_kind)
            return _InitializationExecutor(expected_kind, selected)

        descriptors.append(
            RuntimeExecutorFactoryDescriptor(
                implementation_id,
                {kind: RuntimeExecutorOptionsSchema()},
                build,
            )
        )
        extensions.append(
            CampaignRuntimeExtension(
                CampaignRuntimeExtensionId(f"initialization/{label}"),
                (RuntimeExecutorBinding(kind, implementation_id, {}),),
            )
        )
    manager = CampaignRuntimeProfileManager(
        CampaignRuntimeProfile(CampaignRuntimeProfileId("initialization/order"), tuple(extensions)),
        CampaignRuntimeExecutorRegistry(descriptors),
    )
    service = build_campaign_map_initialization_service(manager.executor_instances_in_profile_order())
    runtime = cast("CampaignMapInitializationRuntime", object())

    service.pre_control(runtime)
    service.post_control(runtime)

    assert trace == [
        "first:pre",
        "second:pre",
        "third:pre",
        "first:post",
        "second:post",
        "third:post",
    ]


class _Runtime:
    FUNCTION_NAME_BASE = "INITIALIZATION_TEST_"
    _map_initialization_service: CampaignMapInitializationService
    _program_capabilities: CampaignProgramCapabilityReader
    _runtime_profile: CampaignRuntimeProfileManager
    _runtime_profile_lease: RuntimeProfileLease
    _submarine_services: SimpleNamespace
    device: Device

    def __init__(self, failure_phase: str, trace: list[str]) -> None:
        self.MAP = CampaignMap("initialization-test")
        self.config = in_memory_config(f"initialization-{failure_phase}", {})
        self.map_is_clear_mode = False
        self.session_variant = CampaignRunVariant.NORMAL
        self.failure_phase = failure_phase
        self.trace = trace

    def map_data_init(self, map_: CampaignMap | None) -> None:
        assert map_ is self.MAP
        self.trace.append("data")
        if self.failure_phase == "data":
            message = "data failed"
            raise RuntimeError(message)

    def map_control_init(self) -> None:
        self.assert_mask_installed()
        self.trace.append("control")
        if self.failure_phase == "control":
            message = "control failed"
            raise RuntimeError(message)

    @staticmethod
    def combat(
        *,
        balance_hp: bool,
        emotion_reduce: bool,
        expected_end: CombatEnd | None,
    ) -> object:
        del balance_hp, emotion_reduce, expected_end
        return None

    @staticmethod
    def assert_mask_installed() -> None:
        cache = ASSETS.__dict__
        assert "ui_mask" in cache
        assert "ui_mask_stroke" not in cache
        assert "ui_mask_in_map" not in cache


def _ui_mask_manager() -> CampaignRuntimeProfileManager:
    binding = RuntimeExecutorBinding(
        RuntimeExecutorKind.ENGINE_EXTENSION,
        RuntimeImplementationId("engine/ui_mask"),
        {"asset": "event_20211125", "condition": "always"},
    )
    profile = CampaignRuntimeProfile(
        CampaignRuntimeProfileId("initialization-test"),
        (
            CampaignRuntimeExtension(
                CampaignRuntimeExtensionId("initialization-test/ui-mask"),
                (binding,),
            ),
        ),
    )
    return CampaignRuntimeProfileManager(profile, load_default_campaign_runtime_executor_registry())


def _failure_source(phase: str, trace: list[str]) -> _ContributorSource | None:
    if phase not in {"pre", "post"}:
        return None

    def fail(runtime: CampaignMapInitializationRuntime) -> None:
        cast("_Runtime", runtime).assert_mask_installed()
        trace.append(f"{phase}:fail")
        message = f"{phase} failed"
        raise RuntimeError(message)

    if phase == "pre":
        return _ContributorSource(CampaignMapInitializationContributor(pre_control=fail))
    return _ContributorSource(CampaignMapInitializationContributor(post_control=fail))


def _attempt(
    runtime: _Runtime,
    manager: CampaignRuntimeProfileManager,
    lease: RuntimeProfileLease,
    initialization: CampaignMapInitializationService,
) -> Mumu12CampaignAttempt:
    runtime._runtime_profile_lease = lease  # ruff:ignore[private-member-access] - fake runtime 注入真实 lease。
    runtime._submarine_services = SimpleNamespace(  # ruff:ignore[private-member-access] - fake runtime 只提供 attempt 需要的已编译 service。
        fresh_combat=STANDARD_CAMPAIGN_SUBMARINE_SERVICES.fresh_combat
    )
    runtime._map_initialization_service = initialization  # ruff:ignore[private-member-access] - fake runtime 注入被测 service。
    runtime._runtime_profile = manager  # ruff:ignore[private-member-access] - program state 不参与本测试。
    runtime._program_capabilities = CampaignProgramCapabilityReader()  # ruff:ignore[private-member-access] - program 能力不参与本测试。
    device = object.__new__(Device)
    return Mumu12CampaignAttempt(
        cast("DeclarativeCampaignMapRuntime", runtime),
        cast("CampaignJobSpec", SimpleNamespace(kind=CampaignJobKind.STANDARD)),
        cast("CampaignSession", SimpleNamespace()),
        device,
        AbortToken(),
    )


@pytest.mark.parametrize(
    ("failure_phase", "expected_trace"),
    [
        ("data", ["data"]),
        ("pre", ["data", "pre:fail"]),
        ("control", ["data", "control"]),
        ("post", ["data", "control", "post:fail"]),
    ],
)
def test_initialization_failure_closes_lease_and_restores_all_ui_mask_caches(
    failure_phase: str,
    expected_trace: list[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sentinels = {key: object() for key in ("ui_mask", "ui_mask_stroke", "ui_mask_in_map")}
    for key, value in sentinels.items():
        monkeypatch.setitem(ASSETS.__dict__, key, value)
    trace: list[str] = []
    runtime = _Runtime(failure_phase, trace)
    manager = _ui_mask_manager()
    manager.bind(runtime, runtime.MAP)
    sources: list[object] = list(manager.executor_instances_in_profile_order())
    failure_source = _failure_source(failure_phase, trace)
    if failure_source is not None:
        sources.append(failure_source)
    initialization = build_campaign_map_initialization_service(sources)
    lease = RuntimeProfileLease(manager)
    attempt = _attempt(runtime, manager, lease, initialization)
    with pytest.raises(RuntimeError, match=rf"{failure_phase} failed"):
        attempt.initialize(CampaignRunVariant.NORMAL)

    assert trace == expected_trace
    assert lease.state is RuntimeProfileLeaseState.CLOSED
    assert {key: ASSETS.__dict__[key] for key in sentinels} == sentinels
