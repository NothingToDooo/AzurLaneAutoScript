from dataclasses import dataclass
from types import SimpleNamespace
from typing import TYPE_CHECKING

import pytest
from config_factory import in_memory_config

from module.adapters import campaign_runtime_hard as hard_runtime
from module.adapters.campaign_runtime_implementations import load_default_campaign_runtime_executor_registry
from module.adapters.campaign_runtime_profile import (
    CampaignRuntimeExecutorRegistry,
    CampaignRuntimeProfileError,
    CampaignRuntimeProfileManager,
    RuntimeExecutorInstance,
)
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
from module.map.map_base import CampaignMap
from module.map.map_grids import SelectedGrids

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
    MAP_HAS_AMBUSH: bool = True

    def apply_runtime_overlay(self, **kwargs: object) -> None:
        for name, value in kwargs.items():
            setattr(self, name, value)


class _Runtime:
    def __init__(self, map_: _Map | None = None) -> None:
        self.config = _Config()
        self.map = _Map() if map_ is None else map_
        self.goto_calls: list[tuple[object, str, bool | None, bool | None]] = []
        self.potential_boss_calls = 0

    def goto(
        self,
        location: object,
        expected: str = "",
        *,
        step_optimize: bool | None = None,
        turning_optimize: bool | None = None,
    ) -> None:
        self.goto_calls.append((location, expected, step_optimize, turning_optimize))

    def clear_potential_boss(self) -> bool:
        self.potential_boss_calls += 1
        return True


def _options(**overrides: object) -> dict[str, object]:
    return dict(overrides)


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


def _executor(manager: CampaignRuntimeProfileManager) -> hard_runtime.CampaignClearModeExecutor:
    instance = manager.executor_instance(RuntimeExecutorKind.HARD_MODE)
    assert isinstance(instance, hard_runtime.CampaignClearModeExecutor)
    return instance


def test_expected_end_is_fixed_to_in_stage() -> None:
    assert _executor(_manager()).expected_end("no_searching") == "in_stage"


def test_apply_runtime_config_applies_hard_mode_overlay() -> None:
    manager = _manager()
    runtime = _Runtime()

    manager.bind(runtime, CampaignMap("hard-runtime-config"))
    _executor(manager).apply_runtime_config(runtime)

    assert runtime.config.MAP_HAS_AMBUSH is False
    manager.reset()


def test_production_hard_profile_builds_typed_behavior() -> None:
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
    config = in_memory_config("hard-runtime-production-config", {})

    runtime = SimpleNamespace(config=config)
    manager.bind(runtime, CampaignMap("hard-runtime-production-config"))
    behavior = hard_runtime.build_campaign_clear_mode_behavior(
        manager.executor_instances(RuntimeExecutorKind.HARD_MODE)
    )
    assert behavior is not None
    behavior.apply_runtime_config(runtime)

    assert config.MAP_HAS_AMBUSH is False
    manager.reset()


def test_clear_boss_combines_candidates_and_chooses_lowest_weight_then_cost() -> None:
    boss = _Grid("boss", weight=10, cost=1)
    possible = _Grid("possible", weight=2, cost=3)
    runtime = _Runtime(_Map(bosses=(boss,), possible_bosses=(possible,)))

    with pytest.raises(CampaignEnd, match=r"BOSS Clear\."):
        _executor(_manager()).clear_boss(runtime)

    assert runtime.goto_calls == [(possible, "boss", False, False)]
    assert runtime.potential_boss_calls == 0


def test_clear_boss_falls_back_to_all_spawn_points() -> None:
    runtime = _Runtime()

    result = _executor(_manager()).clear_boss(runtime)

    assert result is False
    assert runtime.goto_calls == []
    assert runtime.potential_boss_calls == 1


def test_hard_behavior_builder_returns_none_without_a_hard_executor() -> None:
    assert hard_runtime.build_campaign_clear_mode_behavior(()) is None


def test_hard_behavior_builder_returns_the_single_typed_executor() -> None:
    behavior = _executor(_manager())

    assert hard_runtime.build_campaign_clear_mode_behavior((behavior,)) is behavior


def test_hard_behavior_builder_rejects_an_untyped_executor() -> None:
    instance = RuntimeExecutorInstance({RuntimeExecutorKind.HARD_MODE})

    with pytest.raises(CampaignRuntimeProfileError, match="must provide CampaignClearModeExecutor"):
        hard_runtime.build_campaign_clear_mode_behavior((instance,))


def test_hard_behavior_builder_rejects_multiple_executors() -> None:
    behavior = _executor(_manager())

    with pytest.raises(CampaignRuntimeProfileError, match="at most one"):
        hard_runtime.build_campaign_clear_mode_behavior((behavior, behavior))


@pytest.mark.parametrize(
    "options",
    [
        _options(operations=["clear_boss"]),
        _options(expected_end="in_stage"),
        _options(unexpected=True),
    ],
)
def test_hard_profile_rejects_unknown_options(
    options: Mapping[str, object],
) -> None:
    with pytest.raises(CampaignRuntimeProfileError, match="unknown option"):
        _manager(options)
