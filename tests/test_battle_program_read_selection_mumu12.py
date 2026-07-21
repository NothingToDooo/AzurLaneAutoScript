from dataclasses import dataclass, field
from typing import TYPE_CHECKING, cast

from module.adapters.battle_program_read_mumu12 import (
    Mumu12BattleProgramReadModel,
    Mumu12ProgramReadSource,
    RuntimeProgramState,
)
from module.adapters.campaign_program_capabilities import CampaignProgramCapabilityReader
from module.gameplay.campaign import EnemyPriorityMode

if TYPE_CHECKING:
    from module.application import CancellationSource


class _Cancellation:
    @staticmethod
    def raise_if_requested() -> None:
        pass


class _ProgramState:
    @staticmethod
    def use_single_fleet_override(_cancellation: _Cancellation) -> bool | None:
        return None

    @staticmethod
    def use_support_fleet(_cancellation: _Cancellation) -> bool:
        return False


@dataclass(slots=True)
class _Grid:
    location: tuple[int, int] = (0, 0)
    weight: float = 1
    cost_1: float = 2
    cost_2: float = 3
    is_enemy: bool = True
    is_siren: bool = False
    is_boss: bool = False
    is_fortress: bool = False
    is_mystery: bool = False
    may_ammo: bool = False
    enemy_scale: int = 1
    enemy_genre: str = "LightInvertedOrthant"


@dataclass(slots=True)
class _Config:
    EnemyPriority_EnemyScaleBalanceWeight: str = "S3_enemy_first"
    MAP_CLEAR_ALL_THIS_TIME: bool = True
    MAP_HAS_MOVABLE_NORMAL_ENEMY: bool = True


@dataclass(slots=True)
class _Definition:
    enemy_filter: str = "1L > 1M"


@dataclass(frozen=True, slots=True)
class _NavigationSnapshot:
    fleet_1: tuple[int, int] | tuple[()] = (0, 0)
    fleet_2: tuple[int, int] | tuple[()] = (1, 0)
    current_index: int = 2


@dataclass(slots=True)
class _Navigation:
    snapshot: _NavigationSnapshot = field(default_factory=_NavigationSnapshot)
    fleet_step: int = 0
    boss_index: int = 1


@dataclass(slots=True)
class _Source:
    map: tuple[_Grid, ...]
    config: _Config
    definition: _Definition
    navigation: _Navigation = field(default_factory=_Navigation)


def _read_model(grid: _Grid) -> Mumu12BattleProgramReadModel:
    source = _Source((grid,), _Config(), _Definition())
    return Mumu12BattleProgramReadModel(
        cast("Mumu12ProgramReadSource", source),
        cast("RuntimeProgramState", _ProgramState()),
        CampaignProgramCapabilityReader(),
    )


def test_selection_context_normalizes_runtime_policy_and_filter() -> None:
    read_model = _read_model(_Grid())

    context = read_model.selection_context(cast("CancellationSource", _Cancellation()))

    assert context.executor_fleet == 2
    assert context.enemy_priority is EnemyPriorityMode.LARGE_ENEMY_FIRST
    assert context.clear_all
    assert context.movable_normal_enemy
    assert [(entry.scale, entry.genre_code) for entry in context.default_enemy_filter] == [(1, "L"), (1, "M")]
