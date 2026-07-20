from typing import cast, override

import numpy as np
import pytest

from module.adapters.campaign_event_ui import build_campaign_event_ui_services
from module.adapters.campaign_runtime_navigation import (
    CampaignNavigationPlanExecutor,
    Event20240912NavigationPlan,
    navigation_runtime_executor_descriptors,
)
from module.adapters.campaign_runtime_profile import (
    CampaignRuntimeExecutorRegistry,
    CampaignRuntimeProfileManager,
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
    def __init__(self) -> None:
        self.device = _Device()
        self.story_visible = False
        self.page_visible = False
        self.stage_page_visible = False
        self.story_entrance: Button | None = None
        self.stage_ocr_results: list[bool] = []
        self.stage_ocr_images: list[object] = []
        self.exp_info_calls = 0
        self.transition_calls: list[str] = []

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

    def handle_exp_info(self) -> bool:
        self.exp_info_calls += 1
        return True

    def handle_in_stage(self) -> bool:
        self.transition_calls.append("handle-stage-return")
        return False

    def is_stage_page_has_entrance(self) -> bool:
        self.transition_calls.append("stage-page-ready")
        return False

    def is_event_animation(self) -> bool:
        self.transition_calls.append("event-animation")
        return False


def test_event_20230817_story_button_replaces_stage_entrance() -> None:
    manager = _manager(
        "event_20230817_cn/campaign_base/campaign_base",
        RuntimeExecutorKind.EVENT_UI,
        {},
    )
    runtime = _EventRuntime()
    runtime.story_visible = True

    services = build_campaign_event_ui_services(manager.executor_instances(RuntimeExecutorKind.EVENT_UI))
    result = services.map_transition.stage_page_ready(runtime)

    assert result is True

    runtime.story_visible = False
    assert not services.map_transition.stage_page_ready(runtime)
    assert runtime.transition_calls == ["stage-page-ready"]


def test_event_20230817_stage_recovery_handles_story_and_continues_on_miss(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = _manager(
        "event_20230817_cn/campaign_base/campaign_base",
        RuntimeExecutorKind.EVENT_UI,
        {},
    )
    instance = manager.executor_instance(RuntimeExecutorKind.EVENT_UI)
    assert isinstance(instance, Event20230817UiExecutor)
    services = build_campaign_event_ui_services((instance,))
    runtime = _EventRuntime()
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
            "exp_info_blocked_page": "event",
            "state": ["entrance_timer"],
        },
    )
    runtime = _EventRuntime()
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
    blocked = services.combat_result.handle_experience_result(cast("CampaignEngine", runtime))

    assert blocked is False


def test_event_20240815_recovery_continues_to_standard_on_miss(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = _manager(
        "event_20240815_cn/campaign_base/campaign_base",
        RuntimeExecutorKind.EVENT_UI,
        {
            "exp_info_blocked_page": "event",
            "state": ["entrance_timer"],
        },
    )
    runtime = _EventRuntime()

    def campaign_fallback(_runtime: CampaignEngine) -> bool:
        return True

    def stage_page_fallback(_runtime: CampaignEngine) -> bool:
        return True

    monkeypatch.setattr(CampaignEngine, "handle_campaign_ui_additional", campaign_fallback)
    monkeypatch.setattr(CampaignEngine, "handle_get_chapter_additional", stage_page_fallback)
    services = build_campaign_event_ui_services(manager.executor_instances(RuntimeExecutorKind.EVENT_UI))

    assert services.stage_recovery.recover_campaign_selection(cast("CampaignEngine", runtime))
    assert services.stage_recovery.recover_stage_page(cast("CampaignEngine", runtime))
    assert services.combat_result.handle_experience_result(cast("CampaignEngine", runtime))
    assert runtime.exp_info_calls == 1


def test_event_20240815_story_entrance_falls_back_after_stage_ocr_failure() -> None:
    manager = _manager(
        "event_20240815_cn/campaign_base/campaign_base",
        RuntimeExecutorKind.EVENT_UI,
        {
            "exp_info_blocked_page": "event",
            "state": ["entrance_timer"],
        },
    )
    runtime = _EventRuntime()
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
    assert services.combat_result.handle_experience_result(cast("CampaignEngine", runtime))
    assert runtime.exp_info_calls == 1

    result = services.stage_recovery.recover_campaign_selection(cast("CampaignEngine", runtime))

    assert result is True
    assert runtime.device.clicks == [runtime.story_entrance]
    assert runtime.stage_ocr_images == [runtime.device.image, runtime.device.image]

    # Typed recovery 与 transition 共享同一 executor/timer；刚 reset 的 timer 会抑制重复点击。
    assert services.map_transition.handle_stage_return(runtime) is False
    assert runtime.device.clicks == [runtime.story_entrance]

    # Executor reset 会 clear 同一个 timer，下一次 in-stage 检查可立即处理入口。
    instance.reset()
    assert services.map_transition.handle_stage_return(runtime) is False
    assert runtime.device.clicks == [runtime.story_entrance, runtime.story_entrance]

    runtime.story_entrance = None
    runtime.transition_calls.clear()
    assert services.map_transition.handle_stage_return(runtime) is False
    assert runtime.transition_calls == ["handle-stage-return"]


def test_event_ui_profile_options_have_no_string_dispatched_operations() -> None:
    registry = load_default_campaign_runtime_profile_registry()
    event_20230817 = registry.extensions[CampaignRuntimeExtensionId("event_20230817_cn/campaign_base/campaign_base")]
    event_20240815 = registry.extensions[CampaignRuntimeExtensionId("event_20240815_cn/campaign_base/campaign_base")]
    binding_20230817 = next(
        binding for binding in event_20230817.executors if binding.kind is RuntimeExecutorKind.EVENT_UI
    )
    binding_20240815 = next(
        binding for binding in event_20240815.executors if binding.kind is RuntimeExecutorKind.EVENT_UI
    )
    assert binding_20230817.options == {}
    assert binding_20240815.options == {
        "exp_info_blocked_page": "event",
        "state": ("entrance_timer",),
    }

    for extension in registry.extensions.values():
        for binding in extension.executors:
            if binding.kind is RuntimeExecutorKind.EVENT_UI:
                assert "operations" not in binding.options


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
