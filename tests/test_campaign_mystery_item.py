from types import MappingProxyType, SimpleNamespace
from typing import TYPE_CHECKING, cast

import pytest

from module.adapters.campaign_mystery_item import (
    CampaignMysteryItemContributor,
    CampaignMysteryItemExecutor,
    MysteryItemHandler,
    MysteryItemNext,
    build_campaign_mystery_item_service,
)
from module.adapters.campaign_runtime_implementations import (
    load_default_campaign_runtime_executor_registry,
)
from module.adapters.campaign_runtime_mystery import mystery_runtime_executor_descriptors
from module.adapters.campaign_runtime_profile import (
    CampaignRuntimeExecutorRegistry,
    CampaignRuntimeProfileManager,
)
from module.combat.assets import GET_ITEMS_1, GET_ITEMS_1_RYZA
from module.content.manifest import load_default_event_manifests
from module.content.runtime_profile import (
    CampaignRuntimeExtension,
    CampaignRuntimeExtensionId,
    CampaignRuntimeProfile,
    CampaignRuntimeProfileId,
    RuntimeExecutorBinding,
    RuntimeExecutorKind,
    RuntimeImplementationId,
)
from module.content.runtime_profile_catalog import load_default_campaign_runtime_profile_registry
from module.handler.assets import MYSTERY_ITEM
from module.handler.mystery_item import (
    MysteryItemOutcome,
    MysteryItemRequest,
    MysteryItemRuntime,
    MysteryItemService,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

    from module.base.button import Button, MatchOffset
    from module.content.models import EventPack, StageSpec

_NON_COUNTING = "map_mechanic/non_counting_mystery_popup"
_RYZA = "map_mechanic/ryza_mystery_items"
_RYZA_EVENT_UI = "event_20221124_cn/campaign_base/campaign_base"


class _Device:
    def __init__(self) -> None:
        self.clicks: list[object] = []
        self.sleeps: list[float] = []
        self.screenshots = 0

    def click(self, button: object) -> None:
        self.clicks.append(button)

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)

    def screenshot(self) -> None:
        self.screenshots += 1


class _Runtime:
    def __init__(self, *visible: object) -> None:
        self.config = SimpleNamespace(MAP_MYSTERY_MAP_CLICK=False)
        self.device = _Device()
        self.visible = frozenset(visible)
        self.appear_calls: list[tuple[object, object]] = []
        self.strategy_close_calls = 0

    def appear(
        self,
        button: Button,
        offset: MatchOffset | None = 0,
        interval: float = 0,
        similarity: float = 0.85,
        threshold: int = 10,
    ) -> bool:
        del interval, similarity, threshold
        self.appear_calls.append((button, offset))
        return button in self.visible

    def strategy_close(self, *, skip_first_screenshot: bool = True) -> None:
        del skip_first_screenshot
        self.strategy_close_calls += 1


def _as_mystery_runtime(runtime: _Runtime) -> MysteryItemRuntime:
    return cast("MysteryItemRuntime", runtime)


def _binding(implementation: str, options: Mapping[str, object]) -> RuntimeExecutorBinding:
    return RuntimeExecutorBinding(
        RuntimeExecutorKind.MAP_MECHANIC,
        RuntimeImplementationId(implementation),
        options,
    )


def _manager(*bindings: RuntimeExecutorBinding) -> CampaignRuntimeProfileManager:
    extensions = tuple(
        CampaignRuntimeExtension(
            CampaignRuntimeExtensionId(f"mystery-test-{index}"),
            (binding,),
        )
        for index, binding in enumerate(bindings)
    )
    return CampaignRuntimeProfileManager(
        CampaignRuntimeProfile(CampaignRuntimeProfileId("mystery-test"), extensions),
        CampaignRuntimeExecutorRegistry(mystery_runtime_executor_descriptors()),
    )


def _service(manager: CampaignRuntimeProfileManager) -> MysteryItemService:
    return build_campaign_mystery_item_service(manager.executor_instances(RuntimeExecutorKind.MAP_MECHANIC))


def test_mystery_item_contributors_are_later_first_and_share_the_frozen_request() -> None:
    calls: list[tuple[str, MysteryItemRuntime, MysteryItemRequest]] = []

    def handler(label: str) -> MysteryItemHandler:
        def execute(
            runtime: MysteryItemRuntime,
            request: MysteryItemRequest,
            next_handler: MysteryItemNext,
        ) -> MysteryItemOutcome:
            calls.append((label, runtime, request))
            return next_handler(runtime, request)

        return execute

    service = build_campaign_mystery_item_service(
        (
            CampaignMysteryItemExecutor(CampaignMysteryItemContributor(handler("first"))),
            CampaignMysteryItemExecutor(CampaignMysteryItemContributor(handler("second"))),
        )
    )
    runtime = _Runtime()
    request = MysteryItemRequest()

    assert service.handle(_as_mystery_runtime(runtime), request) == MysteryItemOutcome(
        handled=False,
        counts_toward_mystery=False,
    )
    assert [(label, observed_runtime) for label, observed_runtime, _ in calls] == [
        ("second", runtime),
        ("first", runtime),
    ]
    assert all(observed_request is request for _, _, observed_request in calls)


def test_non_counting_contributor_preserves_handled_and_clears_only_counting() -> None:
    service = _service(_manager(_binding(_NON_COUNTING, {"count_as_mystery": False})))
    runtime = _Runtime(GET_ITEMS_1)

    outcome = service.handle(_as_mystery_runtime(runtime), MysteryItemRequest())

    assert outcome == MysteryItemOutcome(handled=True, counts_toward_mystery=False)
    assert runtime.device.clicks == [MYSTERY_ITEM]
    assert runtime.strategy_close_calls == 1


def test_non_counting_contributor_preserves_an_unhandled_standard_miss() -> None:
    service = _service(_manager(_binding(_NON_COUNTING, {"count_as_mystery": False})))

    outcome = service.handle(_as_mystery_runtime(_Runtime()), MysteryItemRequest())

    assert outcome == MysteryItemOutcome(handled=False, counts_toward_mystery=False)


def test_ryza_standard_success_short_circuits_the_special_popup() -> None:
    service = _service(_manager(_binding(_RYZA, {})))
    runtime = _Runtime(GET_ITEMS_1, GET_ITEMS_1_RYZA)

    outcome = service.handle(_as_mystery_runtime(runtime), MysteryItemRequest())

    assert outcome == MysteryItemOutcome(handled=True, counts_toward_mystery=True)
    assert runtime.appear_calls == [(GET_ITEMS_1, 5)]
    assert runtime.device.clicks == [MYSTERY_ITEM]
    assert runtime.strategy_close_calls == 1


def test_ryza_special_popup_runs_once_after_standard_miss() -> None:
    service = _service(_manager(_binding(_RYZA, {})))
    runtime = _Runtime(GET_ITEMS_1_RYZA)

    outcome = service.handle(_as_mystery_runtime(runtime), MysteryItemRequest())

    assert outcome == MysteryItemOutcome(handled=True, counts_toward_mystery=True)
    assert runtime.appear_calls == [
        (GET_ITEMS_1, 5),
        (GET_ITEMS_1_RYZA, (-20, -100, 20, 20)),
    ]
    assert runtime.device.clicks == [MYSTERY_ITEM]
    assert runtime.device.sleeps == [0.5]
    assert runtime.device.screenshots == 1
    assert runtime.strategy_close_calls == 0


def test_ryza_returns_unhandled_when_neither_popup_is_visible() -> None:
    service = _service(_manager(_binding(_RYZA, {})))
    runtime = _Runtime()

    outcome = service.handle(_as_mystery_runtime(runtime), MysteryItemRequest())

    assert outcome == MysteryItemOutcome(handled=False, counts_toward_mystery=False)
    assert runtime.device.clicks == []


@pytest.fixture(scope="module")
def packs_by_id() -> Mapping[str, EventPack]:
    return MappingProxyType({str(pack.pack_id): pack for pack in load_default_event_manifests()})


def _stage(packs_by_id: Mapping[str, EventPack], pack_id: str, stage_id: str) -> StageSpec:
    return next(stage for stage in packs_by_id[pack_id].stages if stage.ref.stage_id == stage_id)


def _production_service(
    packs_by_id: Mapping[str, EventPack],
    pack_id: str,
    stage_id: str,
) -> tuple[MysteryItemService, frozenset[tuple[RuntimeExecutorKind, str]]]:
    profiles = load_default_campaign_runtime_profile_registry()
    profile = profiles.resolve(_stage(packs_by_id, pack_id, stage_id).runtime_profile_id)
    manager = CampaignRuntimeProfileManager(
        profile,
        load_default_campaign_runtime_executor_registry(),
    )
    bindings = frozenset(
        (binding.kind, binding.implementation_id.value)
        for extension in profile.extensions
        for binding in extension.executors
    )
    return _service(manager), bindings


@pytest.mark.parametrize(
    ("pack_id", "stage_id"),
    [("campaign_main", "14-1"), ("campaign_hard", "14-4")],
)
def test_real_chapter_14_profiles_handle_items_without_counting(
    packs_by_id: Mapping[str, EventPack],
    pack_id: str,
    stage_id: str,
) -> None:
    service, bindings = _production_service(packs_by_id, pack_id, stage_id)
    runtime = _Runtime(GET_ITEMS_1)

    assert (RuntimeExecutorKind.MAP_MECHANIC, _NON_COUNTING) in bindings
    assert service.handle(_as_mystery_runtime(runtime), MysteryItemRequest()) == MysteryItemOutcome(
        handled=True,
        counts_toward_mystery=False,
    )


@pytest.mark.parametrize("stage_id", ["sp", "th1", "ts1"])
def test_real_ryza_profiles_bind_separate_typed_mystery_items(
    packs_by_id: Mapping[str, EventPack],
    stage_id: str,
) -> None:
    service, bindings = _production_service(packs_by_id, "event_20221124_cn", stage_id)
    runtime = _Runtime(GET_ITEMS_1_RYZA)

    assert (RuntimeExecutorKind.EVENT_UI, _RYZA_EVENT_UI) in bindings
    assert (RuntimeExecutorKind.MAP_MECHANIC, _RYZA) in bindings
    assert (RuntimeExecutorKind.EVENT_UI, _RYZA) not in bindings
    assert (RuntimeExecutorKind.MAP_MECHANIC, _RYZA_EVENT_UI) not in bindings
    assert service.handle(_as_mystery_runtime(runtime), MysteryItemRequest()) == MysteryItemOutcome(
        handled=True,
        counts_toward_mystery=True,
    )
