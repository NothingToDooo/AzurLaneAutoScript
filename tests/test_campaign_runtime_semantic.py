from __future__ import annotations

from typing import TYPE_CHECKING, override

import pytest

from module.adapters.campaign_runtime_profile import (
    CampaignRuntimeExecutorRegistry,
    CampaignRuntimeProfileError,
    CampaignRuntimeProfileManager,
    RuntimeOperation,
)
from module.adapters.campaign_runtime_semantic import semantic_runtime_executor_descriptors
from module.config.config import AzurLaneConfig
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
    from typing import Unpack

    from module.config.config_generated import ConfigOverrides


class _Config(AzurLaneConfig):
    def __init__(self) -> None:
        self.overlays: list[dict[str, object]] = []

    @override
    def apply_runtime_overlay(self, **kwargs: Unpack[ConfigOverrides]) -> None:
        self.overlays.append(dict(kwargs))


class _Runtime:
    def __init__(self, manager: CampaignRuntimeProfileManager) -> None:
        self.manager = manager
        self.config = _Config()
        self.battle_count = 0
        self.event_animation_end = object()
        self.page_visible = False
        self.confirm_visible = False
        self.confirm_calls: list[tuple[object, tuple[int, int], float]] = []

    def runtime_super(
        self,
        operation: RuntimeOperation,
        /,
        *args: object,
        **kwargs: object,
    ) -> object:
        return self.manager.invoke_super(operation, self, *args, **kwargs)

    def ui_page_appear(self, page: object) -> bool:
        del page
        return self.page_visible

    def appear_then_click(
        self,
        button: object,
        *,
        offset: tuple[int, int],
        interval: float,
    ) -> bool:
        self.confirm_calls.append((button, offset, interval))
        return self.confirm_visible


def _manager(
    implementation: str,
    kind: RuntimeExecutorKind,
    options: dict[str, object],
) -> CampaignRuntimeProfileManager:
    binding = RuntimeExecutorBinding(
        kind,
        RuntimeImplementationId(implementation),
        options,
    )
    profile = CampaignRuntimeProfile(
        CampaignRuntimeProfileId("semantic-test"),
        (
            CampaignRuntimeExtension(
                CampaignRuntimeExtensionId("semantic-test"),
                (binding,),
            ),
        ),
    )
    return CampaignRuntimeProfileManager(
        profile,
        CampaignRuntimeExecutorRegistry(semantic_runtime_executor_descriptors()),
    )


def test_exp_info_page_guard_short_circuits_only_on_blocked_page() -> None:
    manager = _manager(
        "event_ui/exp_info_page_guard",
        RuntimeExecutorKind.EVENT_UI,
        {"operations": ["handle_exp_info"], "blocked_page": "event"},
    )
    runtime = _Runtime(manager)
    fallbacks: list[str] = []
    runtime.page_visible = True

    blocked = manager.event_ui.invoke(
        RuntimeOperation.HANDLE_EXP_INFO,
        runtime,
        lambda: fallbacks.append("fallback") or True,
    )
    runtime.page_visible = False
    delegated = manager.event_ui.invoke(
        RuntimeOperation.HANDLE_EXP_INFO,
        runtime,
        lambda: fallbacks.append("fallback") or True,
    )

    assert blocked is False
    assert delegated is True
    assert fallbacks == ["fallback"]


def test_exp_info_click_guard_uses_closed_asset_mapping() -> None:
    manager = _manager(
        "event_ui/exp_info_click_guard",
        RuntimeExecutorKind.EVENT_UI,
        {
            "operations": ["handle_exp_info"],
            "asset": "ALCHEMIST_MATERIAL_CONFIRM",
            "offset": [20, 20],
            "interval": 1,
        },
    )
    runtime = _Runtime(manager)
    runtime.confirm_visible = True

    result = manager.event_ui.invoke(
        RuntimeOperation.HANDLE_EXP_INFO,
        runtime,
        lambda: True,
    )

    assert result is False
    assert len(runtime.confirm_calls) == 1
    assert runtime.confirm_calls[0][1:] == ((20, 20), 1.0)


@pytest.mark.parametrize(
    ("condition", "handled", "expected_count"),
    [("handled", False, 0), ("handled", True, 1), ("always", False, 1)],
)
def test_clear_mode_overlay_is_session_ephemeral(
    condition: str,
    *,
    handled: bool,
    expected_count: int,
) -> None:
    manager = _manager(
        "engine/clear_mode_config_overlay",
        RuntimeExecutorKind.ENGINE_EXTENSION,
        {
            "operations": ["handle_clear_mode_config_cover"],
            "condition": condition,
            "overrides": {"MAP_HAS_SIREN": True, "MAP_SIREN_TEMPLATE": ["SS"]},
        },
    )
    runtime = _Runtime(manager)

    result = manager.engine.invoke(
        RuntimeOperation.HANDLE_CLEAR_MODE_CONFIG_COVER,
        runtime,
        lambda: handled,
    )

    assert result is handled
    assert len(runtime.config.overlays) == expected_count
    if runtime.config.overlays:
        assert runtime.config.overlays[0] == {
            "MAP_HAS_SIREN": True,
            "MAP_SIREN_TEMPLATE": ("SS",),
        }


def test_event_animation_expected_end_delegates_outside_configured_battle() -> None:
    manager = _manager(
        "engine/event_animation_expected_end",
        RuntimeExecutorKind.ENGINE_EXTENSION,
        {"operations": ["_expected_end"], "event_animation_end_battle": 3},
    )
    runtime = _Runtime(manager)

    runtime.battle_count = 3
    special = manager.engine.invoke(
        RuntimeOperation.EXPECTED_END,
        runtime,
        lambda expected: expected,
        "no_searching",
    )
    runtime.battle_count = 2
    delegated = manager.engine.invoke(
        RuntimeOperation.EXPECTED_END,
        runtime,
        lambda expected: expected,
        "no_searching",
    )

    assert special is runtime.event_animation_end
    assert delegated == "no_searching"


def test_runtime_config_overlay_runs_after_map_data_initialization() -> None:
    manager = _manager(
        "engine/runtime_config_overlay",
        RuntimeExecutorKind.ENGINE_EXTENSION,
        {
            "operations": ["map_data_init"],
            "phase": "map_init",
            "overrides": {"EnemyPriority_EnemyScaleBalanceWeight": "default_mode"},
        },
    )
    runtime = _Runtime(manager)

    result = manager.engine.invoke(
        RuntimeOperation.MAP_DATA_INIT,
        runtime,
        lambda map_: ("initialized", map_),
        "map",
    )

    assert result == ("initialized", "map")
    assert runtime.config.overlays == [
        {"EnemyPriority_EnemyScaleBalanceWeight": "default_mode"},
    ]


def test_semantic_executor_rejects_unknown_option_value_before_binding() -> None:
    with pytest.raises(CampaignRuntimeProfileError, match="unsupported EXP-info blocked page"):
        _manager(
            "event_ui/exp_info_page_guard",
            RuntimeExecutorKind.EVENT_UI,
            {"operations": ["handle_exp_info"], "blocked_page": "unknown"},
        )
