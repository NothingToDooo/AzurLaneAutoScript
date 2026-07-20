from module.adapters.campaign_runtime_mechanics import mechanic_runtime_executor_descriptors
from module.adapters.campaign_runtime_profile import (
    CampaignRuntimeExecutorRegistry,
    CampaignRuntimeProfileManager,
    RuntimeOperation,
    RuntimeSessionContext,
    RuntimeSessionEntryKind,
    RuntimeSessionOutcome,
)
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
from module.map.map_base import CampaignMap
from module.map_detection.utils_assets import ASSETS


class _Runtime:
    FUNCTION_NAME_BASE = "TEST_"
    map_is_clear_mode = True

    def __init__(self) -> None:
        self.config = _Config()
        self.manager: CampaignRuntimeProfileManager | None = None
        self.support_empty = False
        self.popup = False
        self.combat_calls = 0
        self.super_calls: list[tuple[RuntimeOperation, tuple[object, ...], dict[str, object]]] = []

    def runtime_super(
        self,
        operation: RuntimeOperation,
        /,
        *args: object,
        **kwargs: object,
    ) -> object:
        manager = self.manager
        if manager is None:
            message = "test runtime manager is not installed"
            raise AssertionError(message)
        return manager.invoke_super(operation, self, *args, **kwargs)

    def appear(self, button: object, *, offset: tuple[int, int]) -> bool:
        del button, offset
        return self.support_empty

    @staticmethod
    def strategy_has_mob_move() -> bool:
        return True

    def handle_popup_confirm(self, name: str) -> bool:
        assert name == "SUBMARINE_SUPPORT"
        return self.popup

    def combat(
        self,
        *,
        balance_hp: bool,
        emotion_reduce: bool,
        expected_end: str,
    ) -> object:
        assert not balance_hp
        assert not emotion_reduce
        assert expected_end == "no_searching"
        self.combat_calls += 1
        return None


class _Config:
    Fleet_FleetOrder = "fleet1_mob_fleet2_boss"


def _binding(
    implementation: str,
    kind: RuntimeExecutorKind,
    options: dict[str, object],
) -> RuntimeExecutorBinding:
    return RuntimeExecutorBinding(
        kind,
        RuntimeImplementationId(implementation),
        options,
    )


def _manager(*bindings: RuntimeExecutorBinding) -> CampaignRuntimeProfileManager:
    extensions = tuple(
        CampaignRuntimeExtension(
            CampaignRuntimeExtensionId(f"mechanic-test-{index}"),
            (binding,),
        )
        for index, binding in enumerate(bindings)
    )
    return CampaignRuntimeProfileManager(
        CampaignRuntimeProfile(
            CampaignRuntimeProfileId("mechanic-test"),
            extensions,
        ),
        CampaignRuntimeExecutorRegistry(mechanic_runtime_executor_descriptors()),
    )


def _support_binding() -> RuntimeExecutorBinding:
    return _binding(
        "map_mechanic/support_fleet",
        RuntimeExecutorKind.MAP_MECHANIC,
        {
            "operations": ["_map_swipe", "fleet_preparation"],
            "state": ["use_support_fleet"],
        },
    )


def _submarine_binding() -> RuntimeExecutorBinding:
    return _binding(
        "map_mechanic/submarine_fresh_entry",
        RuntimeExecutorKind.MAP_MECHANIC,
        {"operations": ["handle_submarine_support_popup", "map_init"]},
    )


def _bind(
    manager: CampaignRuntimeProfileManager,
    runtime: _Runtime,
) -> None:
    runtime.manager = manager
    manager.bind(runtime, CampaignMap("mechanic-test"))


def _begin(
    manager: CampaignRuntimeProfileManager,
    entry_kind: RuntimeSessionEntryKind,
) -> None:
    manager.begin_session(
        RuntimeSessionContext(
            CampaignRunVariant.LOOP,
            0,
            entry_kind,
        )
    )


def _start(
    manager: CampaignRuntimeProfileManager,
    runtime: _Runtime,
    entry_kind: RuntimeSessionEntryKind,
) -> None:
    _bind(manager, runtime)
    _begin(manager, entry_kind)


def test_support_fleet_state_is_shared_with_fresh_submarine_entry() -> None:
    manager = _manager(_support_binding(), _submarine_binding())
    runtime = _Runtime()
    _bind(manager, runtime)

    manager.mechanic.invoke(
        RuntimeOperation.FLEET_PREPARATION,
        runtime,
        lambda: True,
    )
    _begin(manager, RuntimeSessionEntryKind.FRESH)
    manager.mechanic.invoke(
        RuntimeOperation.MAP_INIT,
        runtime,
        lambda map_: map_,
        None,
    )

    assert manager.use_support_fleet(AbortToken())
    assert runtime.combat_calls == 1


def test_empty_support_fleet_suppresses_submarine_and_updates_state() -> None:
    manager = _manager(_support_binding(), _submarine_binding())
    runtime = _Runtime()
    runtime.support_empty = True
    _bind(manager, runtime)

    manager.mechanic.invoke(RuntimeOperation.FLEET_PREPARATION, runtime, lambda: True)
    assert not manager.use_support_fleet(AbortToken())

    _begin(manager, RuntimeSessionEntryKind.FRESH)
    manager.mechanic.invoke(RuntimeOperation.MAP_INIT, runtime, lambda map_: map_, None)

    assert not manager.use_support_fleet(AbortToken())
    assert runtime.combat_calls == 0


def test_support_fleet_retry_replaces_the_previous_ui_observation() -> None:
    manager = _manager(_support_binding())
    runtime = _Runtime()
    runtime.support_empty = True
    _bind(manager, runtime)

    manager.mechanic.invoke(RuntimeOperation.FLEET_PREPARATION, runtime, lambda: True)
    assert not manager.use_support_fleet(AbortToken())

    runtime.support_empty = False
    manager.mechanic.invoke(RuntimeOperation.FLEET_PREPARATION, runtime, lambda: True)
    assert manager.use_support_fleet(AbortToken())

    _begin(manager, RuntimeSessionEntryKind.FRESH)
    assert manager.use_support_fleet(AbortToken())


def test_resume_does_not_repeat_submarine_entry_battle() -> None:
    manager = _manager(_support_binding(), _submarine_binding())
    runtime = _Runtime()
    _start(manager, runtime, RuntimeSessionEntryKind.RESUME)

    manager.mechanic.invoke(RuntimeOperation.MAP_INIT, runtime, lambda map_: map_, None)

    assert runtime.combat_calls == 0


def test_runtime_ui_mask_restores_all_derived_caches() -> None:
    manager = _manager(
        _binding(
            "engine/ui_mask",
            RuntimeExecutorKind.ENGINE_EXTENSION,
            {
                "operations": ["map_data_init"],
                "asset": "event_20211125",
                "condition": "always",
            },
        )
    )
    runtime = _Runtime()
    _start(manager, runtime, RuntimeSessionEntryKind.FRESH)
    cache = ASSETS.__dict__
    original = {key: cache[key] for key in ("ui_mask", "ui_mask_stroke", "ui_mask_in_map") if key in cache}

    manager.engine.invoke(RuntimeOperation.MAP_DATA_INIT, runtime, lambda map_: map_, None)

    assert "ui_mask" in cache
    assert "ui_mask_stroke" not in cache
    assert "ui_mask_in_map" not in cache
    manager.end_session(RuntimeSessionOutcome.COMPLETED)
    assert {key: cache[key] for key in original} == original


def test_mob_move_strategy_executor_owns_session_state() -> None:
    manager = _manager(
        _binding(
            "map_mechanic/mob_move_strategy_state",
            RuntimeExecutorKind.MAP_MECHANIC,
            {
                "operations": ["strategy_set_execute"],
                "state": ["map_has_mob_move"],
            },
        )
    )
    runtime = _Runtime()
    _start(manager, runtime, RuntimeSessionEntryKind.FRESH)

    result = manager.mechanic.invoke(
        RuntimeOperation.STRATEGY_SET_EXECUTE,
        runtime,
        lambda: "configured",
    )

    assert result == "configured"
    assert manager.map_has_mob_move(AbortToken())


def test_session_state_policy_projects_stage_specific_fleet_order() -> None:
    manager = _manager(
        _support_binding(),
        _binding(
            "map_mechanic/session_state_policy",
            RuntimeExecutorKind.MAP_MECHANIC,
            {
                "operations": ["map_init"],
                "state": ["map_has_mob_move", "use_single_fleet"],
                "rules": [
                    {
                        "target": "map_has_mob_move",
                        "all": ["use_support_fleet", "clear_mode"],
                    },
                    {
                        "target": "use_single_fleet",
                        "fleet_order_contains": "standby",
                    },
                ],
            },
        ),
    )
    runtime = _Runtime()
    runtime.config.Fleet_FleetOrder = "fleet1_all_fleet2_standby"
    _start(manager, runtime, RuntimeSessionEntryKind.FRESH)

    assert manager.use_single_fleet_override(AbortToken()) is False
    manager.mechanic.invoke(RuntimeOperation.MAP_INIT, runtime, lambda map_: map_, None)

    assert manager.map_has_mob_move(AbortToken())
    assert manager.use_single_fleet_override(AbortToken()) is True
