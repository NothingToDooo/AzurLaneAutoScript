from typing import TYPE_CHECKING, cast, override

import module.adapters.campaign_profile_services as profile_services
from module.adapters.campaign_runtime_profile import CampaignRuntimeProfileManager, RuntimeExecutorInstance
from module.content.runtime_profile import RuntimeExecutorKind

if TYPE_CHECKING:
    from collections.abc import Callable

    import pytest


class _RecordingManager(CampaignRuntimeProfileManager):
    __slots__ = ("calls",)

    def __init__(self) -> None:
        self.calls: list[RuntimeExecutorKind | str] = []

    @override
    def executor_instances(self, kind: RuntimeExecutorKind) -> tuple[RuntimeExecutorInstance, ...]:
        self.calls.append(kind)
        return cast("tuple[RuntimeExecutorInstance, ...]", (f"{kind.value}-instance",))

    @override
    def executor_instances_in_profile_order(self) -> tuple[RuntimeExecutorInstance, ...]:
        self.calls.append("profile-order")
        return cast("tuple[RuntimeExecutorInstance, ...]", ("first", "second"))

    @property
    @override
    def map_clear_percentage_multiplier(self) -> float:
        return 1.75


def test_compile_campaign_profile_services_covers_every_runtime_consumer_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = _RecordingManager()
    calls: list[tuple[str, tuple[object, ...], dict[str, object]]] = []
    results: dict[str, object] = {}

    def record(name: str) -> Callable[..., object]:
        result = object()
        results[name] = result

        def build(*args: object, **kwargs: object) -> object:
            calls.append((name, args, kwargs))
            return result

        return build

    builder_fields = {
        "build_campaign_clear_mode_behavior": "hard_behavior",
        "build_campaign_event_ui_services": "event_ui",
        "build_campaign_map_observer": "map_observer",
        "build_campaign_fleet_preparation_service": "fleet_preparation",
        "build_campaign_submarine_services": "submarine",
        "build_campaign_strategy_set_service": "strategy_set",
        "build_campaign_program_capability_reader": "program_capabilities",
        "build_campaign_map_swipe_service": "map_swipe",
        "build_campaign_mystery_item_service": "mystery_item",
        "build_campaign_map_initialization_service": "map_initialization",
        "build_campaign_clear_mode_config_service": "clear_mode_config",
    }
    for builder_name in builder_fields:
        monkeypatch.setattr(profile_services, builder_name, record(builder_name))

    services = profile_services.compile_campaign_profile_services(manager)

    assert manager.calls == [
        RuntimeExecutorKind.HARD_MODE,
        RuntimeExecutorKind.EVENT_UI,
        RuntimeExecutorKind.MAP_OBSERVATION,
        RuntimeExecutorKind.MAP_MECHANIC,
        "profile-order",
    ]
    expected_instances = {
        "build_campaign_clear_mode_behavior": ("hard_mode-instance",),
        "build_campaign_event_ui_services": ("event_ui-instance",),
        "build_campaign_map_observer": ("map_observation-instance",),
        "build_campaign_fleet_preparation_service": ("map_mechanic-instance",),
        "build_campaign_submarine_services": ("map_mechanic-instance",),
        "build_campaign_strategy_set_service": ("map_mechanic-instance",),
        "build_campaign_program_capability_reader": ("map_mechanic-instance",),
        "build_campaign_map_swipe_service": ("map_mechanic-instance",),
        "build_campaign_mystery_item_service": ("map_mechanic-instance",),
        "build_campaign_map_initialization_service": ("first", "second"),
        "build_campaign_clear_mode_config_service": ("first", "second"),
    }
    assert [name for name, _args, _kwargs in calls] == list(builder_fields)
    for name, args, kwargs in calls:
        assert args == (expected_instances[name],)
        expected_kwargs = {"map_clear_percentage_multiplier": 1.75} if name == "build_campaign_map_observer" else {}
        assert kwargs == expected_kwargs
    for builder_name, field_name in builder_fields.items():
        assert getattr(services, field_name) is results[builder_name]
