from collections.abc import Callable, Mapping
from types import SimpleNamespace
from typing import cast

import pytest

from module.adapters.campaign_event_ui import CampaignEventUiServices
from module.adapters.campaign_runtime_navigation import (
    BallChapterNavigationPlan,
    CampaignBallOperation,
    CampaignNavigationPlan,
    CampaignNavigationPlanExecutor,
    CampaignRouteDestination,
    CampaignRouteMode,
    CampaignRouteTarget,
    ChapterRouteNavigationPlan,
    navigation_runtime_executor_descriptors,
)
from module.adapters.campaign_runtime_profile import (
    CampaignRuntimeExecutorRegistry,
    CampaignRuntimeProfileError,
    CampaignRuntimeProfileManager,
)
from module.adapters.campaign_stage_navigator import ProfileCampaignStageNavigator
from module.base.button import Button
from module.campaign.campaign_engine import CampaignEngine
from module.campaign.campaign_ocr import CampaignStagePage
from module.campaign.event_destination import STANDARD_EVENT_DESTINATION
from module.content.runtime_profile import (
    CampaignRuntimeExtension,
    CampaignRuntimeExtensionId,
    CampaignRuntimeProfile,
    CampaignRuntimeProfileId,
    RuntimeExecutorBinding,
    RuntimeExecutorKind,
    RuntimeImplementationId,
    RuntimeTuningValue,
)
from module.content.runtime_profile_catalog import load_default_campaign_runtime_profile_registry
from module.exception import CampaignNameError

_ROUTE_PLAN = "navigation/chapter_route_plan"
_BALL_ROUTE = "navigation/ball_chapter_route"


def _content_binding(extension_id: str, implementation: str) -> RuntimeExecutorBinding:
    catalog = load_default_campaign_runtime_profile_registry()
    extension = catalog.extensions[CampaignRuntimeExtensionId(extension_id)]
    matches = tuple(
        binding
        for binding in extension.executors
        if binding.kind is RuntimeExecutorKind.NAVIGATION
        and binding.implementation_id == RuntimeImplementationId(implementation)
    )
    assert len(matches) == 1
    return matches[0]


def _manager(binding: RuntimeExecutorBinding) -> CampaignRuntimeProfileManager:
    profile = CampaignRuntimeProfile(
        CampaignRuntimeProfileId("navigation-test"),
        (
            CampaignRuntimeExtension(
                CampaignRuntimeExtensionId("navigation-test"),
                (binding,),
            ),
        ),
    )
    return CampaignRuntimeProfileManager(
        profile,
        CampaignRuntimeExecutorRegistry(navigation_runtime_executor_descriptors()),
    )


def _plan_for(
    extension_id: str,
    implementation: str = _ROUTE_PLAN,
) -> CampaignNavigationPlan:
    manager = _manager(_content_binding(extension_id, implementation))
    instance = manager.executor_instance(RuntimeExecutorKind.NAVIGATION)
    assert isinstance(instance, CampaignNavigationPlanExecutor)
    return instance.plan


def _thaw(value: RuntimeTuningValue) -> object:
    if isinstance(value, Mapping):
        values = cast("Mapping[str, RuntimeTuningValue]", value)
        return {key: _thaw(item) for key, item in values.items()}
    if isinstance(value, tuple):
        return [_thaw(item) for item in value]
    return value


def _mutated_binding(
    extension_id: str,
    implementation: str,
    mutate: Callable[[dict[str, object]], None],
) -> RuntimeExecutorBinding:
    original = _content_binding(extension_id, implementation)
    options = cast("dict[str, object]", _thaw(original.options))
    mutate(options)
    return RuntimeExecutorBinding(
        RuntimeExecutorKind.NAVIGATION,
        RuntimeImplementationId(implementation),
        options,
    )


def _separate(plan: ChapterRouteNavigationPlan, name: str) -> tuple[str, str]:
    for rule in plan.name_rules:
        separated = rule.separate(name)
        if separated is not None:
            return separated
    return CampaignEngine.campaign_separate_name(name)


class _Runtime:
    def __init__(self) -> None:
        self.info_bar_count = 0
        self.config = SimpleNamespace(MAP_HAS_MODE_SWITCH=False)
        self.device = SimpleNamespace(image=object(), screenshot=lambda: None)

    def handle_info_bar(self) -> bool:
        self.info_bar_count += 1
        return False


class _NavigationHarness(ProfileCampaignStageNavigator):
    def __init__(self, plan: CampaignNavigationPlan) -> None:
        self._plan = plan
        self._runtime = cast("CampaignEngine", _Runtime())
        self.calls: list[tuple[object, ...]] = []

    def _open_campaign(self) -> bool:
        self.calls.append(("destination", "campaign"))
        return True

    def _open_event(self) -> bool:
        self.calls.append(("destination", "event"))
        return True

    def _open_sp(self) -> bool:
        self.calls.append(("destination", "sp"))
        return True

    def _ensure_mode(self, mode: str) -> None:
        self.calls.append(("mode", mode))

    def _ensure_chapter(self, chapter: str | int, *, skip_first_screenshot: bool = True) -> None:
        del skip_first_screenshot
        self.calls.append(("chapter", chapter))

    def _set_ball(self, plan: BallChapterNavigationPlan, status: str) -> None:
        self.calls.append(("ball", plan.ball.area, status))

    def apply_route(self, plan: ChapterRouteNavigationPlan, name: str, mode: str) -> bool:
        chapter, stage = _separate(plan, name)
        return self._apply_first_route(plan.routes, chapter, stage, mode)

    def select_ball(self, plan: BallChapterNavigationPlan, name: str, mode: str) -> bool:
        chapter, stage = CampaignEngine.campaign_separate_name(name)
        return self._select_ball_chapter(plan, chapter, stage, mode)

    def resolve(self, page: CampaignStagePage, name: str, *, has_mode_switch: bool) -> Button:
        runtime = cast("_Runtime", self._runtime)
        runtime.config.MAP_HAS_MODE_SWITCH = has_mode_switch
        self._page = page
        return self._resolve_entrance(name)

    def ball_status(self, plan: BallChapterNavigationPlan, chapter: str, stage: str) -> str:
        return self._ball_status(plan, chapter, stage)


class _RecordingStageRecovery:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def recover_campaign_selection(self, runtime: CampaignEngine) -> bool:
        del runtime
        self.calls.append("campaign")
        return False

    def recover_chapter_selection(self, runtime: CampaignEngine) -> bool:
        del runtime
        self.calls.append("chapter")
        return False

    def recover_stage_page(self, runtime: CampaignEngine) -> bool:
        del runtime
        self.calls.append("get-chapter")
        return False


class _DirectRecoveryNavigator(ProfileCampaignStageNavigator):
    def handle_campaign_recovery(self) -> bool:
        return self._recover_campaign_selection()

    def ensure_chapter(self, chapter: str | int) -> None:
        self._ensure_chapter(chapter)

    def current_page(self) -> CampaignStagePage:
        return self._current_page()


def test_stage_navigator_calls_typed_recovery_services_directly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recovery = _RecordingStageRecovery()
    services = CampaignEventUiServices(
        destination=STANDARD_EVENT_DESTINATION,
        stage_recovery=recovery,
    )
    runtime = cast("CampaignEngine", _Runtime())
    navigator = _DirectRecoveryNavigator(runtime, services, None, None)

    assert not navigator.handle_campaign_recovery()

    def current_page(
        _navigator: ProfileCampaignStageNavigator,
        *,
        skip_first_screenshot: bool = True,
    ) -> CampaignStagePage:
        del skip_first_screenshot
        return CampaignStagePage("1", {})

    with monkeypatch.context() as patch:
        patch.setattr(ProfileCampaignStageNavigator, "_current_page", current_page)
        navigator.ensure_chapter(1)

    reads = 0

    def read_stage_page(
        _runtime: CampaignEngine,
        image: object,
        *,
        normalize_result: Callable[[str], str],
        separate_name: Callable[[str], tuple[str, str]],
        match_similarity: float | None = None,
    ) -> CampaignStagePage:
        nonlocal reads
        del image, normalize_result, separate_name, match_similarity
        reads += 1
        if reads == 1:
            raise CampaignNameError
        return CampaignStagePage("1", {})

    monkeypatch.setattr(CampaignEngine, "read_stage_page", read_stage_page)
    assert navigator.current_page().chapter == "1"
    assert recovery.calls == ["campaign", "chapter", "get-chapter"]


def test_route_plan_validates_nested_options_during_manager_construction() -> None:
    def invalidate(options: dict[str, object]) -> None:
        routes = cast("list[dict[str, object]]", options["routes"])
        routes[0]["destination"] = "moon"

    with pytest.raises(CampaignRuntimeProfileError):
        _manager(
            _mutated_binding(
                "event_20201029_cn/campaign_base/campaign_base",
                _ROUTE_PLAN,
                invalidate,
            )
        )


def test_ball_route_rejects_assets_outside_the_closed_mapping() -> None:
    def invalidate(options: dict[str, object]) -> None:
        ball = cast("dict[str, object]", options["ball"])
        ball["asset"] = "BALL"

    with pytest.raises(CampaignRuntimeProfileError):
        _manager(
            _mutated_binding(
                "event_20200917_cn/campaign_base/campaign_base",
                _BALL_ROUTE,
                invalidate,
            )
        )


def test_navigation_bindings_compile_without_operation_or_fallback_contracts() -> None:
    registry = load_default_campaign_runtime_profile_registry()
    bindings = tuple(
        binding
        for extension in registry.extensions.values()
        for binding in extension.executors
        if binding.kind is RuntimeExecutorKind.NAVIGATION
    )
    assert len(bindings) == 29
    assert all("operations" not in binding.options for binding in bindings)
    assert all("fallback" not in binding.options for binding in bindings)
    for binding in bindings:
        instance = _manager(binding).executor_instance(RuntimeExecutorKind.NAVIGATION)
        assert isinstance(instance, CampaignNavigationPlanExecutor)


def test_20201029_chapter_index_and_routes_compile_to_one_final_plan() -> None:
    plan = _plan_for("event_20201029_cn/campaign_base/campaign_base")
    assert isinstance(plan, ChapterRouteNavigationPlan)
    assert plan.route_target is CampaignRouteTarget.ALL
    assert plan.chapter_indices["ex_sp"] == 2
    assert plan.routes[0].destination is CampaignRouteDestination.CAMPAIGN
    assert plan.routes[0].mode is CampaignRouteMode.REQUESTED
    assert plan.routes[0].reselect_after_hard is True

    harness = _NavigationHarness(plan)
    assert harness.apply_route(plan, "12-4", "hard") is True
    assert harness.calls == [
        ("destination", "campaign"),
        ("mode", "normal"),
        ("chapter", "12"),
        ("mode", "hard"),
        ("chapter", "12"),
    ]


def test_20210722_name_entrance_and_similarity_rules_are_typed() -> None:
    plan = _plan_for("event_20210722_cn/campaign_base/campaign_base")
    assert isinstance(plan, ChapterRouteNavigationPlan)
    assert _separate(plan, "sp") == ("ex_sp", "1")
    assert _separate(plan, "vsp") == ("ex_sp", "1")
    assert _separate(plan, "extra-stage") == ("ex_ex", "1")
    assert _separate(plan, "d-3") == ("d", "3")
    assert _separate(plan, "sp4") == ("sp", "4")
    assert _separate(plan, "t6") == ("t", "6")
    assert plan.entrance_aliases["sp"] == "vsp"
    assert plan.stage_match_similarity == pytest.approx(0.8)


def test_mode_name_lookup_keeps_the_requested_entrance_name() -> None:
    plan = _plan_for("event_20210722_cn/campaign_base/campaign_base")
    assert isinstance(plan, ChapterRouteNavigationPlan)
    harness = _NavigationHarness(plan)
    button = Button(area=(), color=(), button=(), name="original")

    entrance = harness.resolve(
        CampaignStagePage("t", {"ht1": button}),
        "t1",
        has_mode_switch=True,
    )

    assert entrance is button
    assert entrance.name == "t1"


def test_select_discards_the_previous_page_before_each_navigation_attempt() -> None:
    plan = _plan_for("event_20210722_cn/campaign_base/campaign_base")
    assert isinstance(plan, ChapterRouteNavigationPlan)
    stale = Button(area=(), color=(), button=(), name="stale")
    fresh = Button(area=(), color=(), button=(), name="fresh")

    class _FreshPageHarness(_NavigationHarness):
        def __init__(self) -> None:
            super().__init__(plan)
            self._page = CampaignStagePage("t", {"t1": stale})
            self.pages_before_select: list[CampaignStagePage | None] = []

        def _select_chapter(self, name: str, mode: str) -> None:
            del name, mode
            self.pages_before_select.append(self._page)
            self._page = CampaignStagePage("t", {"t1": fresh})

    harness = _FreshPageHarness()

    assert harness.select("t1") is fresh
    assert harness.pages_before_select == [None]


def test_ocr_aliases_are_part_of_the_final_plan() -> None:
    plan = _plan_for("event_20240425_cn/campaign_base/campaign_base")
    assert isinstance(plan, ChapterRouteNavigationPlan)
    assert plan.ocr_aliases == {
        "iisp": "sp",
        "ijsp": "sp",
        "jjsp": "sp",
        "usp": "sp",
    }


@pytest.mark.parametrize(
    ("extension_id", "target", "destination"),
    [
        ("event_20220818_cn/campaign_base/campaign_base", CampaignRouteTarget.SP, "event"),
        ("war_archives_20220818_cn/campaign_base/campaign_base", CampaignRouteTarget.SP, "sp"),
    ],
)
def test_20220818_route_target_preserves_event_and_archive_destinations(
    extension_id: str,
    target: CampaignRouteTarget,
    destination: str,
) -> None:
    plan = _plan_for(extension_id)
    assert isinstance(plan, ChapterRouteNavigationPlan)
    assert plan.route_target is target
    assert _separate(plan, "esp") == ("sp_sp", "2")
    assert plan.entrance_aliases["sp"] == "esp"
    assert plan.routes[0].destination.value == destination


@pytest.mark.parametrize(("stage", "aside"), [("2", "part1"), ("5", "part2")])
def test_20241024_route_selects_combat_mode_and_stage_aside(stage: str, aside: str) -> None:
    plan = _plan_for("event_20241024_cn/campaign_base/campaign_base")
    assert isinstance(plan, ChapterRouteNavigationPlan)
    route = plan.routes[0]
    assert plan.route_target is CampaignRouteTarget.SWITCH_20241219
    assert route.mode is CampaignRouteMode.COMBAT
    assert any(stage in stages and candidate == aside for stages, candidate in route.aside_by_stage)


@pytest.mark.parametrize(
    ("extension_id", "chapter", "stage", "expected"),
    [
        ("event_20200917_cn/campaign_base/campaign_base", "t", "1", "blue"),
        ("event_20200917_cn/campaign_base/campaign_base", "t", "5", "red"),
        ("event_20230525_cn/campaign_base/campaign_base", "t", "3", "blue"),
        ("event_20230525_cn/campaign_base/campaign_base", "ts", "2", "red"),
    ],
)
def test_ball_blue_rules_are_compiled(
    extension_id: str,
    chapter: str,
    stage: str,
    expected: str,
) -> None:
    plan = _plan_for(extension_id, _BALL_ROUTE)
    assert isinstance(plan, BallChapterNavigationPlan)
    assert _NavigationHarness(plan).ball_status(plan, chapter, stage) == expected


@pytest.mark.parametrize(
    ("extension_id", "expected_area", "expected_calls"),
    [
        (
            "event_20200917_cn/campaign_base/campaign_base",
            (571, 283, 696, 387),
            [
                ("destination", "event"),
                ("ball", (571, 283, 696, 387), "blue"),
                ("mode", "normal"),
                ("chapter", 1),
            ],
        ),
        (
            "event_20230525_cn/campaign_base/campaign_base",
            (589, 279, 685, 374),
            [
                ("destination", "event"),
                ("mode", "normal"),
                ("ball", (589, 279, 685, 374), "blue"),
                ("chapter", 1),
            ],
        ),
    ],
)
def test_ball_operation_order_and_closed_asset_mapping(
    extension_id: str,
    expected_area: tuple[int, int, int, int],
    expected_calls: list[tuple[object, ...]],
) -> None:
    plan = _plan_for(extension_id, _BALL_ROUTE)
    assert isinstance(plan, BallChapterNavigationPlan)
    assert set(plan.operation_order) == set(CampaignBallOperation)
    assert plan.ball.area == expected_area
    harness = _NavigationHarness(plan)
    assert harness.select_ball(plan, "t1", "normal") is True
    assert harness.calls == expected_calls


def test_ball_main_hard_route_preserves_its_single_chapter_selection() -> None:
    plan = _plan_for("event_20200917_cn/campaign_base/campaign_base", _BALL_ROUTE)
    assert isinstance(plan, BallChapterNavigationPlan)
    harness = _NavigationHarness(plan)

    assert harness.select_ball(plan, "12-4", "hard") is True
    assert harness.calls == [
        ("destination", "campaign"),
        ("mode", "normal"),
        ("chapter", "12"),
        ("mode", "hard"),
    ]
