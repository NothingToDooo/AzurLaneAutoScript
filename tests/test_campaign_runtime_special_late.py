from typing import cast, override

import numpy as np
import pytest

from module.adapters.campaign_event_ui import build_campaign_event_ui_services
from module.adapters.campaign_mumu12 import DeclarativeCampaignMapRuntime
from module.adapters.campaign_runtime_navigation import (
    CampaignNavigationPlanExecutor,
    Event20240912NavigationPlan,
    navigation_runtime_executor_descriptors,
)
from module.adapters.campaign_runtime_profile import (
    CampaignRuntimeExecutorRegistry,
    CampaignRuntimeProfileManager,
    RuntimeOperation,
)
from module.adapters.campaign_runtime_special_event_ui import (
    Event20230817UiExecutor,
    Event20240815UiExecutor,
    special_event_ui_runtime_executor_descriptors,
)
from module.adapters.campaign_stage_navigator import ProfileCampaignStageNavigator
from module.base.button import Button
from module.campaign.campaign_engine import CampaignEngine
from module.campaign.campaign_ui import ModeSwitch
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
from module.exception import CampaignNameError


def _manager(
    implementation: str,
    kind: RuntimeExecutorKind,
    options: dict[str, object],
) -> CampaignRuntimeProfileManager:
    binding = RuntimeExecutorBinding(kind, RuntimeImplementationId(implementation), options)
    profile = CampaignRuntimeProfile(
        CampaignRuntimeProfileId("special-late-test"),
        (
            CampaignRuntimeExtension(
                CampaignRuntimeExtensionId("special-late-test"),
                (binding,),
            ),
        ),
    )
    descriptors = (
        *special_event_ui_runtime_executor_descriptors(),
        *navigation_runtime_executor_descriptors(),
    )
    return CampaignRuntimeProfileManager(profile, CampaignRuntimeExecutorRegistry(descriptors))


class _Device:
    def __init__(self) -> None:
        self.image = np.zeros((720, 1280, 3), dtype=np.uint8)
        self.clicks: list[object] = []

    def screenshot(self) -> object:
        return self.image

    def click(self, button: object) -> object:
        self.clicks.append(button)
        return None


class _EventRuntime:
    def __init__(self, manager: CampaignRuntimeProfileManager) -> None:
        self.manager = manager
        self.device = _Device()
        self.story_visible = False
        self.page_visible = False
        self.stage_page_visible = False
        self.story_entrance: Button | None = None
        self.stage_ocr_results: list[bool] = []
        self.stage_ocr_images: list[object] = []

    def runtime_super(
        self,
        operation: RuntimeOperation,
        /,
        *args: object,
        **kwargs: object,
    ) -> object:
        return self.manager.invoke_super(operation, self, *args, **kwargs)

    def appear(self, button: object, *, offset: tuple[int, int]) -> bool:
        del button, offset
        return self.story_visible

    def ui_page_appear(self, page: object) -> bool:
        del page
        return self.page_visible

    @staticmethod
    def handle_story_skip() -> bool:
        return False

    @staticmethod
    def handle_get_items() -> bool:
        return False

    def image_color_button(self, **kwargs: object) -> Button | None:
        del kwargs
        return self.story_entrance

    def is_in_stage_page(self) -> bool:
        return self.stage_page_visible

    def try_update_stage_entrances(self, image: object) -> bool:
        self.stage_ocr_images.append(image)
        return self.stage_ocr_results.pop(0)

    @staticmethod
    def interval_clear(button: object) -> object:
        del button
        return None

    @staticmethod
    def appear_then_click(button: object, **kwargs: object) -> bool:
        del button, kwargs
        return False


def test_event_20230817_story_button_replaces_stage_entrance() -> None:
    manager = _manager(
        "event_20230817_cn/campaign_base/campaign_base",
        RuntimeExecutorKind.EVENT_UI,
        {"operations": ["is_stage_page_has_entrance"]},
    )
    runtime = _EventRuntime(manager)
    runtime.story_visible = True

    result = manager.event_ui.invoke(
        RuntimeOperation.IS_STAGE_PAGE_HAS_ENTRANCE,
        runtime,
        lambda: False,
    )

    assert result is True


def test_event_20230817_stage_recovery_handles_story_and_continues_on_miss(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = _manager(
        "event_20230817_cn/campaign_base/campaign_base",
        RuntimeExecutorKind.EVENT_UI,
        {"operations": ["is_stage_page_has_entrance"]},
    )
    instance = manager.executor_instance(RuntimeExecutorKind.EVENT_UI)
    assert isinstance(instance, Event20230817UiExecutor)
    services = build_campaign_event_ui_services((instance,))
    runtime = _EventRuntime(manager)
    stories: list[object] = []

    def record_story(
        executor: Event20230817UiExecutor,
        selected_runtime: object,
        *,
        skip_first_screenshot: bool = True,
    ) -> None:
        del executor, skip_first_screenshot
        stories.append(selected_runtime)

    monkeypatch.setattr(Event20230817UiExecutor, "_run_story", record_story)
    runtime.story_visible = True
    assert services.stage_recovery.recover_chapter_selection(cast("CampaignEngine", runtime))
    assert stories == [runtime]

    runtime.story_visible = False

    def chapter_fallback() -> bool:
        return True

    monkeypatch.setattr(CampaignEngine, "handle_chapter_additional", staticmethod(chapter_fallback))
    assert services.stage_recovery.recover_chapter_selection(cast("CampaignEngine", runtime))


def test_event_20240815_exp_guard_and_story_entrance_detection() -> None:
    manager = _manager(
        "event_20240815_cn/campaign_base/campaign_base",
        RuntimeExecutorKind.EVENT_UI,
        {
            "operations": ["handle_exp_info", "handle_in_stage"],
            "exp_info_blocked_page": "event",
            "state": ["entrance_timer"],
        },
    )
    runtime = _EventRuntime(manager)
    runtime.story_entrance = Button(
        area=(100, 300, 140, 340),
        color=(0, 0, 0),
        button=(100, 300, 140, 340),
        name="STORY",
    )
    runtime.page_visible = True
    services = build_campaign_event_ui_services(manager.executor_instances(RuntimeExecutorKind.EVENT_UI))

    with pytest.raises(CampaignNameError):
        services.stage_recovery.recover_stage_page(cast("CampaignEngine", runtime))
    blocked = manager.event_ui.invoke(RuntimeOperation.HANDLE_EXP_INFO, runtime, lambda: True)

    assert blocked is False


def test_event_20240815_recovery_continues_to_standard_on_miss(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = _manager(
        "event_20240815_cn/campaign_base/campaign_base",
        RuntimeExecutorKind.EVENT_UI,
        {
            "operations": ["handle_exp_info", "handle_in_stage"],
            "exp_info_blocked_page": "event",
            "state": ["entrance_timer"],
        },
    )
    runtime = _EventRuntime(manager)

    def campaign_fallback(_runtime: CampaignEngine) -> bool:
        return True

    def stage_page_fallback(_runtime: CampaignEngine) -> bool:
        return True

    monkeypatch.setattr(CampaignEngine, "handle_campaign_ui_additional", campaign_fallback)
    monkeypatch.setattr(CampaignEngine, "handle_get_chapter_additional", stage_page_fallback)
    services = build_campaign_event_ui_services(manager.executor_instances(RuntimeExecutorKind.EVENT_UI))

    assert services.stage_recovery.recover_campaign_selection(cast("CampaignEngine", runtime))
    assert services.stage_recovery.recover_stage_page(cast("CampaignEngine", runtime))


def test_event_20240815_story_entrance_falls_back_after_stage_ocr_failure() -> None:
    manager = _manager(
        "event_20240815_cn/campaign_base/campaign_base",
        RuntimeExecutorKind.EVENT_UI,
        {
            "operations": ["handle_exp_info", "handle_in_stage"],
            "exp_info_blocked_page": "event",
            "state": ["entrance_timer"],
        },
    )
    runtime = _EventRuntime(manager)
    runtime.stage_page_visible = True
    runtime.stage_ocr_results = [False, True]
    runtime.story_entrance = Button(
        area=(100, 300, 140, 340),
        color=(0, 0, 0),
        button=(100, 300, 140, 340),
        name="STORY",
    )
    instance = manager.executor_instance(RuntimeExecutorKind.EVENT_UI)
    assert isinstance(instance, Event20240815UiExecutor)
    services = build_campaign_event_ui_services((instance,))

    result = services.stage_recovery.recover_campaign_selection(cast("CampaignEngine", runtime))

    assert result is True
    assert runtime.device.clicks == [runtime.story_entrance]
    assert runtime.stage_ocr_images == [runtime.device.image, runtime.device.image]

    # Typed recovery 与保留的 operation facet 共享同一 executor/timer；刚 reset 的 timer 会抑制重复点击。
    assert manager.event_ui.invoke(RuntimeOperation.HANDLE_IN_STAGE, runtime, lambda: False) is False
    assert runtime.device.clicks == [runtime.story_entrance]

    # Executor reset 会 clear 同一个 timer，下一次 in-stage 检查可立即处理入口。
    instance.reset()
    assert manager.event_ui.invoke(RuntimeOperation.HANDLE_IN_STAGE, runtime, lambda: False) is False
    assert runtime.device.clicks == [runtime.story_entrance, runtime.story_entrance]


def test_stage_recovery_operations_leave_only_later_phase_facades() -> None:
    removed = {
        "ENSURE_NO_STAGE_ENTRANCE": "ensure_no_stage_entrance",
        "EVENT_20230817_STORY": "event_20230817_story",
        "GET_STORY_BUTTON": "get_story_button",
        "GET_STORY_ENTRANCE": "get_story_entrance",
        "HANDLE_CAMPAIGN_UI_ADDITIONAL": "handle_campaign_ui_additional",
        "HANDLE_CHAPTER_ADDITIONAL": "handle_chapter_additional",
        "HANDLE_GET_CHAPTER_ADDITIONAL": "handle_get_chapter_additional",
        "HANDLE_STORY_ENTRANCE": "handle_story_entrance",
    }
    kept = {
        "EVENT_ANIMATION_END": "event_animation_end",
        "HANDLE_EXP_INFO": "handle_exp_info",
        "HANDLE_IN_STAGE": "handle_in_stage",
        "IS_EVENT_ANIMATION": "is_event_animation",
        "IS_STAGE_PAGE_HAS_ENTRANCE": "is_stage_page_has_entrance",
    }

    assert all(not hasattr(RuntimeOperation, enum_name) for enum_name in removed)
    assert all(method_name not in vars(DeclarativeCampaignMapRuntime) for method_name in removed.values())
    assert all(hasattr(RuntimeOperation, enum_name) for enum_name in kept)
    assert all(method_name in vars(DeclarativeCampaignMapRuntime) for method_name in kept.values())


def test_stage_recovery_profile_options_keep_only_operation_facets() -> None:
    registry = load_default_campaign_runtime_profile_registry()

    def operations(extension_id: str) -> object:
        extension = registry.extensions[CampaignRuntimeExtensionId(extension_id)]
        binding = next(binding for binding in extension.executors if binding.kind is RuntimeExecutorKind.EVENT_UI)
        return binding.options["operations"]

    assert operations("event_20230817_cn/campaign_base/campaign_base") == ("is_stage_page_has_entrance",)
    assert operations("event_20240815_cn/campaign_base/campaign_base") == (
        "handle_exp_info",
        "handle_in_stage",
    )


class _Config:
    def __init__(self) -> None:
        self.overlays: list[dict[str, object]] = []

    def apply_runtime_overlay(self, **kwargs: object) -> None:
        self.overlays.append(kwargs)


class _NavigationRuntime:
    def __init__(self) -> None:
        self.config = _Config()


class _Event20240912Harness(ProfileCampaignStageNavigator):
    def __init__(
        self,
        runtime: _NavigationRuntime,
        manager: CampaignRuntimeProfileManager,
        plan: Event20240912NavigationPlan,
    ) -> None:
        event_ui = build_campaign_event_ui_services(manager.executor_instances(RuntimeExecutorKind.EVENT_UI))
        super().__init__(cast("CampaignEngine", runtime), event_ui, plan, None)
        self.base_calls: list[tuple[str, str, str]] = []

    def ensure_mode(self, mode: str) -> None:
        self._ensure_mode(mode)

    def select_event(self, chapter: str, stage: str, mode: str) -> bool:
        return self._select_event_20240912(chapter, stage, mode)

    @override
    def _select_main_chapter(self, chapter: str, mode: str) -> bool:
        del chapter, mode
        return False

    def _select_base_20241219(self, chapter: str, stage: str, mode: str) -> bool:
        self.base_calls.append((chapter, stage, mode))
        return True


def test_event_20240912_layers_selector_over_classic_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = _manager(
        "event_20240912_cn/campaign_base/campaign_base",
        RuntimeExecutorKind.NAVIGATION,
        {"mode_switch": "event_20240912"},
    )
    instance = manager.executor_instance(RuntimeExecutorKind.NAVIGATION)
    assert isinstance(instance, CampaignNavigationPlanExecutor)
    assert isinstance(instance.plan, Event20240912NavigationPlan)
    runtime = _NavigationRuntime()
    navigator = _Event20240912Harness(runtime, manager, instance.plan)
    selected: list[str] = []

    def fake_set(self: ModeSwitch, state: str, main: object, **kwargs: object) -> bool:
        del self, main, kwargs
        selected.append(state)
        return True

    monkeypatch.setattr(ModeSwitch, "set", fake_set)
    delegated: list[str] = []

    def delegate_mode(runtime: object, mode: str) -> None:
        del runtime
        delegated.append(mode)

    monkeypatch.setattr(CampaignEngine, "campaign_ensure_mode", delegate_mode)
    navigator.ensure_mode("hard")
    navigator.ensure_mode("story")
    result = navigator.select_event("a", "1", "combat")

    assert selected == ["combat", "story"]
    assert delegated == ["hard"]
    assert result is True
    assert navigator.base_calls == [("a", "1", "combat")]
    assert runtime.config.overlays == [
        {"MAP_CHAPTER_SWITCH_20241219": False, "MAP_HAS_MODE_SWITCH": False},
    ]
