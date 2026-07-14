from typing import TYPE_CHECKING

import numpy as np

from module.adapters.campaign_runtime_profile import (
    CampaignRuntimeExecutorRegistry,
    CampaignRuntimeProfileManager,
    RuntimeOperation,
)
from module.adapters.campaign_runtime_special_event_ui import (
    special_event_ui_runtime_executor_descriptors,
)
from module.adapters.campaign_runtime_special_navigation import (
    special_navigation_runtime_executor_descriptors,
)
from module.base.button import Button
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

if TYPE_CHECKING:
    import pytest


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
        *special_navigation_runtime_executor_descriptors(),
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
        self.story_entrance: Button | None = None

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

    @staticmethod
    def is_in_stage_page() -> bool:
        return False

    @staticmethod
    def _get_stage_name(image: object) -> object:
        del image
        return None

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
        {
            "operations": [
                "event_20230817_story",
                "get_story_button",
                "handle_chapter_additional",
                "is_stage_page_has_entrance",
            ]
        },
    )
    runtime = _EventRuntime(manager)
    runtime.story_visible = True

    result = manager.event_ui.invoke(
        RuntimeOperation.IS_STAGE_PAGE_HAS_ENTRANCE,
        runtime,
        lambda: False,
    )

    assert result is True


def test_event_20240815_exp_guard_and_story_entrance_detection() -> None:
    manager = _manager(
        "event_20240815_cn/campaign_base/campaign_base",
        RuntimeExecutorKind.EVENT_UI,
        {
            "operations": [
                "ensure_no_stage_entrance",
                "get_story_entrance",
                "handle_campaign_ui_additional",
                "handle_exp_info",
                "handle_get_chapter_additional",
                "handle_in_stage",
                "handle_story_entrance",
            ],
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

    entrance = manager.event_ui.invoke(RuntimeOperation.GET_STORY_ENTRANCE, runtime, lambda: None)
    blocked = manager.event_ui.invoke(RuntimeOperation.HANDLE_EXP_INFO, runtime, lambda: True)

    assert entrance is runtime.story_entrance
    assert blocked is False


class _Config:
    def __init__(self) -> None:
        self.overlays: list[dict[str, object]] = []

    def apply_runtime_overlay(self, **kwargs: object) -> None:
        self.overlays.append(kwargs)


class _NavigationRuntime:
    def __init__(self, manager: CampaignRuntimeProfileManager) -> None:
        self.manager = manager
        self.config = _Config()

    def runtime_super(
        self,
        operation: RuntimeOperation,
        /,
        *args: object,
        **kwargs: object,
    ) -> object:
        return self.manager.invoke_super(operation, self, *args, **kwargs)


def test_event_20240912_layers_selector_over_classic_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = _manager(
        "event_20240912_cn/campaign_base/campaign_base",
        RuntimeExecutorKind.NAVIGATION,
        {"operations": ["campaign_ensure_mode", "campaign_set_chapter_20241219"]},
    )
    runtime = _NavigationRuntime(manager)
    selected: list[str] = []

    def fake_set(self: ModeSwitch, state: str, main: object, **kwargs: object) -> bool:
        del self, main, kwargs
        selected.append(state)
        return True

    monkeypatch.setattr(ModeSwitch, "set", fake_set)
    delegated: list[str] = []

    def delegate_mode(mode: str) -> None:
        delegated.append(mode)

    manager.navigation.invoke(
        RuntimeOperation.CAMPAIGN_ENSURE_MODE,
        runtime,
        delegate_mode,
        "hard",
    )
    result = manager.navigation.invoke(
        RuntimeOperation.CAMPAIGN_SET_CHAPTER_20241219,
        runtime,
        lambda chapter, stage, mode: (chapter, stage, mode),
        "a",
        "1",
        "combat",
    )

    assert selected == ["combat"]
    assert delegated == ["hard"]
    assert result == ("a", "1", "combat")
    assert runtime.config.overlays == [
        {"MAP_CHAPTER_SWITCH_20241219": False, "MAP_HAS_MODE_SWITCH": False},
    ]
