from dataclasses import dataclass
from types import SimpleNamespace
from typing import TYPE_CHECKING

import pytest

from module.adapters import campaign_runtime_hard as hard_runtime
from module.adapters.campaign_runtime_implementations import load_default_campaign_runtime_executor_registry
from module.adapters.campaign_runtime_profile import (
    CampaignRuntimeExecutorRegistry,
    CampaignRuntimeProfileError,
    CampaignRuntimeProfileManager,
    RuntimeOperation,
)
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
from module.content.runtime_profile_catalog import load_default_campaign_runtime_profile_registry
from module.exception import CampaignEnd
from module.map.assets import FLEET_PREPARATION, MAP_PREPARATION
from module.map.map_base import CampaignMap
from module.map.map_grids import SelectedGrids
from module.ui.assets import CAMPAIGN_CHECK

if TYPE_CHECKING:
    from collections.abc import Mapping


@dataclass(frozen=True, slots=True)
class _Grid:
    name: str
    weight: int
    cost: int


class _Map:
    def __init__(
        self,
        *,
        bosses: tuple[_Grid, ...] = (),
        possible_bosses: tuple[_Grid, ...] = (),
    ) -> None:
        self.bosses = bosses
        self.possible_bosses = possible_bosses
        self.select_calls: list[dict[str, object]] = []

    def select(self, **kwargs: object) -> SelectedGrids[_Grid]:
        self.select_calls.append(kwargs)
        if kwargs == {"is_boss": True}:
            return SelectedGrids(self.bosses)
        if kwargs in (
            {"may_boss": True},
            {"may_boss": True, "is_enemy": True},
        ):
            return SelectedGrids(self.possible_bosses)
        return SelectedGrids(())


@dataclass(slots=True)
class _Config:
    FLEET_HARD_EQUIPMENT: object | None
    MAP_HAS_AMBUSH: bool = True

    def apply_runtime_overlay(self, **kwargs: object) -> None:
        for name, value in kwargs.items():
            setattr(self, name, value)


class _Device:
    def __init__(self, runtime: _Runtime) -> None:
        self.runtime = runtime
        self.clicks: list[object] = []

    def screenshot(self) -> None:
        self.runtime.screenshot_count += 1

    def click(self, button: object) -> None:
        self.clicks.append(button)


class _Runtime:
    def __init__(self, map_: _Map | None = None) -> None:
        self.config = _Config(object())
        self.map = _Map() if map_ is None else map_
        self.ENTRANCE = object()
        self.equipment_has_take_on = True
        self.screenshot_count = 0
        self.device = _Device(self)
        self.goto_calls: list[tuple[object, str, bool | None, bool | None]] = []
        self.appear_calls: list[tuple[object, tuple[int, int]]] = []
        self.potential_boss_calls = 0
        self.equipment_take_off_calls = 0
        self.ui_back_calls: list[tuple[object, object]] = []
        self.retirement_calls = 0

    def goto(
        self,
        location: object,
        expected: str = "",
        *,
        step_optimize: bool | None = None,
        turning_optimize: bool | None = None,
    ) -> None:
        self.goto_calls.append((location, expected, step_optimize, turning_optimize))

    def appear(self, button: object, *, offset: tuple[int, int]) -> bool:
        self.appear_calls.append((button, offset))
        if button is MAP_PREPARATION:
            return self.screenshot_count == 2
        if button is FLEET_PREPARATION:
            return self.screenshot_count == 3
        return False

    def clear_potential_boss(self) -> bool:
        self.potential_boss_calls += 1
        return True

    def equipment_take_off(self) -> bool:
        self.equipment_take_off_calls += 1
        return True

    def handle_retirement(self) -> bool:
        self.retirement_calls += 1
        return False

    def is_in_stage(self) -> bool:
        return self.screenshot_count == 1

    def ui_back(self, *, check_button: object, appear_button: object) -> None:
        self.ui_back_calls.append((check_button, appear_button))


def _options(**overrides: object) -> dict[str, object]:
    options: dict[str, object] = {
        "operations": [
            "_expected_end",
            "clear_boss",
            "equipment_take_off_when_finished",
        ],
        "expected_end": "in_stage",
    }
    options.update(overrides)
    return options


def _manager(options: Mapping[str, object] | None = None) -> CampaignRuntimeProfileManager:
    binding = RuntimeExecutorBinding(
        RuntimeExecutorKind.HARD_MODE,
        RuntimeImplementationId("hard_mode/campaign_clear_mode"),
        _options() if options is None else options,
    )
    profile = CampaignRuntimeProfile(
        CampaignRuntimeProfileId("hard-runtime-test"),
        (
            CampaignRuntimeExtension(
                CampaignRuntimeExtensionId("hard-runtime-test"),
                (binding,),
            ),
        ),
    )
    return CampaignRuntimeProfileManager(
        profile,
        CampaignRuntimeExecutorRegistry(hard_runtime.hard_runtime_executor_descriptors()),
    )


def test_expected_end_is_fixed_to_in_stage() -> None:
    manager = _manager()

    result = manager.hard.invoke(
        RuntimeOperation.EXPECTED_END,
        _Runtime(),
        lambda expected: expected,
        "no_searching",
    )

    assert result == "in_stage"


def test_runtime_created_applies_hard_mode_config_overlay() -> None:
    manager = _manager()
    runtime = _Runtime()

    manager.bind(runtime, CampaignMap("hard-runtime-config"))

    assert runtime.config.MAP_HAS_AMBUSH is False
    manager.reset()


def test_production_hard_profile_bind_uses_only_allowed_config_overlays() -> None:
    profile_registry = load_default_campaign_runtime_profile_registry()
    hard_extension_id = CampaignRuntimeExtensionId("campaign_hard/campaign_hard/campaign")
    hard_profiles = tuple(
        profile
        for profile in profile_registry.profiles.values()
        if hard_extension_id in {extension.extension_id for extension in profile.extensions}
    )
    assert len(hard_profiles) == 1
    manager = CampaignRuntimeProfileManager(
        hard_profiles[0],
        load_default_campaign_runtime_executor_registry(),
    )
    config = AzurLaneConfig.from_snapshot("hard-runtime-production-config", {})

    manager.bind(SimpleNamespace(config=config), CampaignMap("hard-runtime-production-config"))

    assert config.MAP_HAS_AMBUSH is False
    manager.reset()


def test_clear_boss_combines_candidates_and_chooses_lowest_weight_then_cost() -> None:
    boss = _Grid("boss", weight=10, cost=1)
    possible = _Grid("possible", weight=2, cost=3)
    runtime = _Runtime(_Map(bosses=(boss,), possible_bosses=(possible,)))

    with pytest.raises(CampaignEnd, match=r"BOSS Clear\."):
        _manager().hard.invoke(
            RuntimeOperation.CLEAR_BOSS,
            runtime,
            lambda: False,
        )

    assert runtime.goto_calls == [(possible, "boss", False, False)]
    assert runtime.potential_boss_calls == 0


def test_clear_boss_falls_back_to_all_spawn_points() -> None:
    runtime = _Runtime()

    result = _manager().hard.invoke(
        RuntimeOperation.CLEAR_BOSS,
        runtime,
        lambda: True,
    )

    assert result is False
    assert runtime.goto_calls == []
    assert runtime.potential_boss_calls == 1


def test_equipment_cleanup_skips_when_not_configured() -> None:
    runtime = _Runtime()
    runtime.config.FLEET_HARD_EQUIPMENT = None

    result = _manager().hard.invoke(
        RuntimeOperation.EQUIPMENT_TAKE_OFF_WHEN_FINISHED,
        runtime,
        lambda: True,
    )

    assert result is False
    assert runtime.screenshot_count == 0


def test_equipment_cleanup_skips_when_not_mounted() -> None:
    runtime = _Runtime()
    runtime.equipment_has_take_on = False

    result = _manager().hard.invoke(
        RuntimeOperation.EQUIPMENT_TAKE_OFF_WHEN_FINISHED,
        runtime,
        lambda: True,
    )

    assert result is False
    assert runtime.screenshot_count == 0


def test_equipment_cleanup_reaches_fleet_preparation_through_closed_assets() -> None:
    runtime = _Runtime()

    result = _manager().hard.invoke(
        RuntimeOperation.EQUIPMENT_TAKE_OFF_WHEN_FINISHED,
        runtime,
        lambda: False,
    )

    assert result is True
    assert runtime.screenshot_count == 3
    assert runtime.device.clicks == [runtime.ENTRANCE, MAP_PREPARATION]
    assert runtime.appear_calls == [
        (MAP_PREPARATION, (20, 20)),
        (FLEET_PREPARATION, (20, 50)),
    ]
    assert runtime.equipment_take_off_calls == 1
    assert runtime.ui_back_calls == [(CAMPAIGN_CHECK, FLEET_PREPARATION)]


@pytest.mark.parametrize(
    "options",
    [
        _options(operations=["clear_boss"]),
        _options(expected_end="no_searching"),
        _options(unexpected=True),
    ],
)
def test_invalid_hard_contract_is_rejected_at_manager_construction(
    options: Mapping[str, object],
) -> None:
    with pytest.raises(CampaignRuntimeProfileError):
        _manager(options)
