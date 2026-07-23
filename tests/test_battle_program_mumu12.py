from dataclasses import dataclass, field
from typing import TYPE_CHECKING, cast

import pytest

from module.adapters.battle_program_fleet_mumu12 import Mumu12FleetActionDriver
from module.adapters.battle_program_strategy_mumu12 import Mumu12StrategyActionDriver
from module.adapters.campaign_program_capabilities import (
    CampaignProgramCapabilities,
    CampaignProgramCapabilityReader,
)
from module.adapters.campaign_program_mumu12 import (
    Mumu12BattleProgramRuntime,
    build_mumu12_battle_program_port,
)
from module.content import battle_program as program_model
from module.content.battle_policy import (
    AllConditions,
    BattleFlag,
    BossStrategy,
    CellAccessibleCondition,
    ClearBoss,
    ClearBossRoadblock,
    ClearChosenEnemy,
    ClearSiren,
    DefaultBattle,
    FlagCondition,
    GuardedBattleStep,
)
from module.content.cell import CellId
from module.content.mechanic_rules import (
    CandidateSortKey,
    ClearAllMystery,
    EncounterExpectation,
    FleetClearTarget,
    FleetRole,
    MoveFleetToBestCandidate,
    PickupAmmo,
)
from module.content.models import StageRef
from module.content.runtime_profile import CampaignRuntimeProfile
from module.gameplay.battle_program import (
    MechanicApplied,
    MechanicSettled,
)
from module.map.map_grids import SelectedGrids
from module.map_detection.grid_info import GridInfo

if TYPE_CHECKING:
    from collections.abc import Iterator

    from module.adapters.battle_program_mumu12 import Mumu12BattleProgramPort
    from module.adapters.battle_program_read_mumu12 import RuntimeProgramState
    from module.application import CancellationSource


A1 = CellId(0, 0)
B1 = CellId(1, 0)
C1 = CellId(2, 0)
D1 = CellId(3, 0)
E1 = CellId(4, 0)
F1 = CellId(5, 0)


class RequestedCancellation(RuntimeError):  # ruff:ignore[error-suffix-on-exception-name] - 测试取消传播的控制流信号。
    pass


@dataclass(slots=True)
class _Cancellation:
    requested: bool = False
    raise_on_check: int | None = None
    checks: int = 0

    def raise_if_requested(self) -> None:
        self.checks += 1
        if self.requested or self.checks == self.raise_on_check:
            raise RequestedCancellation


@dataclass(slots=True)
class _ProgramState:
    single_fleet_override: bool | None = None
    support_fleet: bool = False
    dynamic_queries: list[str] = field(default_factory=list)

    def use_support_fleet(self, cancellation: CancellationSource) -> bool:
        cancellation.raise_if_requested()
        self.dynamic_queries.append("use_support_fleet")
        return self.support_fleet

    def use_single_fleet_override(self, cancellation: CancellationSource) -> bool | None:
        cancellation.raise_if_requested()
        self.dynamic_queries.append("use_single_fleet_override")
        return self.single_fleet_override


class _MapLayout:
    def __init__(self, grids: list[GridInfo]) -> None:
        self._grids = grids
        self._by_location = {grid.location: grid for grid in grids}

    def __iter__(self) -> Iterator[GridInfo]:
        return iter(self._grids)

    def __getitem__(self, location: tuple[int, int]) -> GridInfo:
        return self._by_location[location]

    def select(self, **criteria: object) -> SelectedGrids[GridInfo]:
        return SelectedGrids(
            [
                grid
                for grid in self._grids
                if all(getattr(grid, name) == expected for name, expected in criteria.items())
            ]
        )


class _Map:
    def __init__(self, grids: list[GridInfo]) -> None:
        self.layout = _MapLayout(grids)

    def __iter__(self) -> Iterator[GridInfo]:
        return iter(self.layout)

    def __getitem__(self, location: tuple[int, int]) -> GridInfo:
        return self.layout[location]

    def show(self) -> None:
        pass


@dataclass(slots=True)
class _Shape:
    columns: int = 6
    rows: int = 1


@dataclass(slots=True)
class _MapDefinition:
    shape: _Shape = field(default_factory=_Shape)


@dataclass(slots=True)
class _Definition:
    ref: StageRef = field(default_factory=lambda: StageRef("test", "a2"))
    enemy_filter: str = "1L > 2L"
    map: _MapDefinition = field(default_factory=_MapDefinition)
    runtime_profile: CampaignRuntimeProfile = field(default_factory=CampaignRuntimeProfile.core)


@dataclass(slots=True)
class _Config:
    EnemyPriority_EnemyScaleBalanceWeight: str = "default_mode"
    MAP_CLEAR_ALL_THIS_TIME: bool = False
    MAP_HAS_MOVABLE_NORMAL_ENEMY: bool = False
    MAP_HAS_MOVABLE_ENEMY: bool = False
    POOR_MAP_DATA: bool = False
    fleet_2: int = 2


@dataclass(slots=True)
class _Device:
    events: list[str]
    image: object = field(default_factory=object)

    def screenshot(self) -> None:
        self.events.append("screenshot")

    def click(self, _target: object) -> None:
        self.events.append("click")


@dataclass(slots=True)
class _View:
    events: list[str]

    def update(self, *, image: object) -> None:
        del image
        self.events.append("view_update")


@dataclass(slots=True)
class _VisualGrid:
    air_error: BaseException | None = None
    mob_error: BaseException | None = None

    def predict_air_strike_icon(self) -> bool:
        if self.air_error is not None:
            raise self.air_error
        return True

    def predict_mob_move_icon(self) -> bool:
        if self.mob_error is not None:
            raise self.mob_error
        return True


@dataclass(frozen=True, slots=True)
class _NavigationSnapshot:
    fleet_1: tuple[int, int] | tuple[()]
    fleet_2: tuple[int, int] | tuple[()]
    current_index: int


class _Runtime:  # ruff:ignore[too-many-public-methods] - 完整实现 BattleRuntime 测试协议。
    def __init__(self, grids: list[GridInfo] | None = None) -> None:
        self.events: list[object] = []
        self.map = _Map(grids or [_grid(A1), _grid(B1), _grid(C1), _grid(D1), _grid(E1), _grid(F1)])
        self.definition = _Definition()
        self.config = _Config()
        self.map_is_clear_mode = False
        self.battle_count = 0
        self.mystery_count = 3
        self.configured_boss_fleet = 2
        self.battle_delta = 1
        self.raise_after_battle = False
        self.ammo_available = True
        self.ammo_target: tuple[int, int] | None = None
        self.mechanic_applied = True
        self.air_strike_available = True
        self.mob_move_available = True
        self.strategy_open_error: BaseException | None = None
        self.strategy_close_error: BaseException | None = None
        self.air_strike_enter_error: BaseException | None = None
        self.mob_move_enter_error: BaseException | None = None
        self.air_strike_cancel_error: BaseException | None = None
        self.mob_move_cancel_error: BaseException | None = None
        self.air_target_error: BaseException | None = None
        self.mob_target_error: BaseException | None = None
        self.navigation_activate_error: BaseException | None = None
        self.navigation_activate_changes_selection = True
        self.navigation_activate_location: tuple[int, int] | None = None
        self.navigation_goto_changes_location = True
        self.clear_mystery_changes_projection = True
        self.camera = (0, 0)
        self.device = _Device(cast("list[str]", self.events))
        self.view = _View(cast("list[str]", self.events))
        self.navigation = _Navigation(self)

    def _hostile(self) -> GridInfo | None:
        return next((grid for grid in self.map.layout if grid.is_enemy or grid.is_siren or grid.is_boss), None)

    def _settle(self, grid: GridInfo | None = None) -> bool:
        if grid is None:
            grid = self._hostile()
        if grid is None:
            return False
        self.battle_count += self.battle_delta
        grid.is_enemy = grid.is_siren = grid.is_boss = False
        if self.raise_after_battle:
            message = "campaign ended after settlement"
            raise RuntimeError(message)
        return True

    def clear_chosen_enemy(self, grid: GridInfo, expected: str = "") -> bool:
        index = self.navigation.current_index
        self.events.append(("clear_chosen_enemy", grid.location, expected, index))
        if index == 1:
            self.navigation.fleet_1 = cast("tuple[int, int]", grid.location)
        else:
            self.navigation.fleet_2 = cast("tuple[int, int]", grid.location)
        return self._settle(grid)

    def clear_enemy(self, **criteria: object) -> bool:
        self.events.append(("clear_enemy", criteria))
        return self._settle(next((grid for grid in self.map.layout if grid.is_enemy and not grid.is_boss), None))

    def clear_any_enemy(self, **criteria: object) -> bool:
        self.events.append(("clear_any_enemy", criteria))
        return self._settle()

    def clear_siren(self, **criteria: object) -> bool:
        self.events.append(("clear_siren", criteria))
        return self._settle(next((grid for grid in self.map.layout if grid.is_siren), None))

    def clear_filter_enemy(self, enemy_filter: str, preserve: int = 0) -> bool:
        self.events.append(("clear_filter_enemy", enemy_filter, preserve))
        enemies = [grid for grid in self.map.layout if grid.is_enemy and not grid.is_boss]
        return self._settle(enemies[preserve] if len(enemies) > preserve else None)

    def clear_roadblocks(self, _roads: object, **selection: object) -> bool:
        self.events.append(("clear_roadblocks", selection))
        return self._settle()

    def clear_potential_roadblocks(self, _roads: object, **selection: object) -> bool:
        self.events.append(("clear_potential_roadblocks", selection))
        return self._settle()

    def clear_first_roadblocks(self, _roads: object, **selection: object) -> bool:
        self.events.append(("clear_first_roadblocks", selection))
        return self._settle()

    def clear_grids_for_faster(self, _grids: object, **selection: object) -> bool:
        self.events.append(("clear_grids_for_faster", selection))
        return self._settle()

    def fleet_2_push_forward(self) -> bool:
        self.events.append("push_forward")
        return self.mechanic_applied

    def fleet_2_break_siren_caught(self) -> bool:
        self.events.append("break_siren_caught")
        if not self.mechanic_applied:
            return False
        self._settle(next((grid for grid in self.map.layout if grid.is_siren), None))
        return True

    def fleet_2_protect(self) -> bool:
        self.events.append("protect")
        return self.mechanic_applied

    def fleet_2_rescue(self, grid: GridInfo) -> bool:
        self.events.append(("rescue", grid.location))
        return self.mechanic_applied

    def fleet_2_step_on(self, _grids: object, _roads: object) -> bool:
        self.events.append("step_on")
        return self.mechanic_applied

    def pick_up_ammo(self, _grid: GridInfo | None = None) -> bool:
        self.events.append("pickup_ammo")
        self.ammo_target = None if _grid is None else cast("tuple[int, int]", _grid.location)
        return self.ammo_available

    def ensure_no_info_bar(self) -> bool:
        self.events.append("ensure_no_info_bar")
        return True

    def clear_all_mystery(self, **_criteria: object) -> bool:
        self.events.append("clear_all_mystery")
        for grid in self.map.layout:
            grid.is_mystery = False
        return False

    def clear_chosen_mystery(self, grid: GridInfo) -> None:
        self.events.append(("clear_chosen_mystery", grid.location))
        if self.clear_mystery_changes_projection:
            grid.is_mystery = False

    def clear_mechanism(self, grids: object = None) -> bool:
        self.events.append(("clear_mechanism", grids))
        for grid in self.map.layout:
            grid.is_mechanism_trigger = False
        return self.mechanic_applied

    def clear_bouncing_enemy(self) -> bool:
        self.events.append("clear_bouncing_enemy")
        return self._settle()

    def full_scan(self) -> None:
        self.events.append("full_scan")

    def strategy_open(self) -> None:
        self.events.append("strategy_open")
        if self.strategy_open_error is not None:
            raise self.strategy_open_error

    def strategy_close(self, *, skip_first_screenshot: bool = True) -> None:
        self.events.append(("strategy_close", skip_first_screenshot))
        if self.strategy_close_error is not None:
            raise self.strategy_close_error

    def strategy_has_air_strike(self) -> bool:
        return self.air_strike_available

    def strategy_air_strike_enter(self) -> None:
        self.events.append("air_strike_enter")
        if self.air_strike_enter_error is not None:
            raise self.air_strike_enter_error

    def strategy_air_strike_cancel(self) -> None:
        self.events.append("air_strike_cancel")
        if self.air_strike_cancel_error is not None:
            raise self.air_strike_cancel_error

    @staticmethod
    def is_in_strategy_air_strike() -> bool:
        return True

    def strategy_has_mob_move(self) -> bool:
        return self.mob_move_available

    def strategy_mob_move_enter(self) -> None:
        self.events.append("mob_move_enter")
        if self.mob_move_enter_error is not None:
            raise self.mob_move_enter_error

    def strategy_mob_move_cancel(self) -> None:
        self.events.append("mob_move_cancel")
        if self.mob_move_cancel_error is not None:
            raise self.mob_move_cancel_error

    @staticmethod
    def is_in_strategy_mob_move() -> bool:
        return True

    def in_sight(self, grid: GridInfo) -> None:
        self.events.append(("in_sight", grid.location))

    def convert_global_to_local(self, _grid: GridInfo) -> _VisualGrid:
        return _VisualGrid(self.air_target_error, self.mob_target_error)

    @staticmethod
    def appear(_button: object, **_criteria: object) -> bool:
        return True

    @staticmethod
    def handle_popup_confirm(_name: str) -> bool:
        return False


class _Navigation:
    fleet_step = 2
    boss_index = 2

    def __init__(self, runtime: _Runtime) -> None:
        self._runtime = runtime
        self.fleet_1: tuple[int, int] | tuple[()] = (0, 0)
        self.fleet_2: tuple[int, int] | tuple[()] = (1, 0)
        self.current_index = 1

    @property
    def snapshot(self) -> _NavigationSnapshot:
        return _NavigationSnapshot(self.fleet_1, self.fleet_2, self.current_index)

    def activate(self, index: int) -> bool:
        changed = index != self.current_index
        self._runtime.events.append(("navigation.activate", index))
        if self._runtime.navigation_activate_error is not None:
            raise self._runtime.navigation_activate_error
        if self._runtime.navigation_activate_changes_selection:
            self.current_index = index
        if self._runtime.navigation_activate_location is not None:
            if index == 1:
                self.fleet_1 = self._runtime.navigation_activate_location
            else:
                self.fleet_2 = self._runtime.navigation_activate_location
        return changed

    def goto(self, grid: GridInfo, expected: str = "") -> None:
        self._runtime.events.append(("navigation.goto", grid.location, expected, self.current_index))
        if self._runtime.navigation_goto_changes_location:
            if self.current_index == 1:
                self.fleet_1 = cast("tuple[int, int]", grid.location)
            else:
                self.fleet_2 = cast("tuple[int, int]", grid.location)
        if grid.is_enemy or grid.is_siren or grid.is_boss:
            self._runtime._settle(grid)  # ruff:ignore[private-member-access] - fake navigation closes the runtime battle.

    def rebuild_paths(self) -> None:
        self._runtime.events.append("navigation.rebuild_paths")

    def find_roadblocks(self, _grid: GridInfo, fleet: int | None = None) -> SelectedGrids[GridInfo]:
        self._runtime.events.append(("navigation.find_roadblocks", fleet))
        return SelectedGrids([grid for grid in self._runtime.map.layout if grid.is_enemy and not grid.is_boss])


def _grid(  # ruff:ignore[too-many-arguments] - 测试网格显式暴露互斥识别事实。
    cell: CellId,
    *,
    enemy: bool = False,
    siren: bool = False,
    boss: bool = False,
    mystery: bool = False,
    fortress: bool = False,
    land: bool = False,
    ammo: bool = False,
    accessible: bool = True,
) -> GridInfo:
    grid = GridInfo()
    grid.location = (cell.x, cell.y)
    grid.cost = cell.x + 1 if accessible else 9999
    grid.cost_1 = grid.cost
    grid.cost_2 = grid.cost
    grid.weight = cell.x + 1
    grid.is_enemy = enemy
    grid.is_siren = siren
    grid.is_boss = boss
    grid.is_mystery = mystery
    grid.is_fortress = fortress
    grid.is_land = land
    grid.may_ammo = ammo
    grid.enemy_scale = 2 if enemy else 0
    grid.enemy_genre = "Light" if enemy else ""
    return grid


def _port(
    runtime: _Runtime,
    state: RuntimeProgramState | None = None,
    *,
    mob_move: bool = False,
) -> Mumu12BattleProgramPort:
    if state is None:
        state = _ProgramState()
    action_runtime = cast("Mumu12BattleProgramRuntime", runtime)
    return build_mumu12_battle_program_port(
        action_runtime,
        state,
        CampaignProgramCapabilityReader(CampaignProgramCapabilities(map_has_mob_move=mob_move)),
    )


def _cancel() -> CancellationSource:
    return cast("CancellationSource", _Cancellation())


def test_fleet_move_measures_displacement_after_activation_refresh() -> None:
    runtime = _Runtime()
    runtime.navigation_activate_location = (C1.x, C1.y)
    runtime.navigation_goto_changes_location = False
    driver = Mumu12FleetActionDriver(cast("Mumu12BattleProgramRuntime", runtime))

    moved = driver.move(2, C1, EncounterExpectation.ANY, _cancel())

    assert not moved
    assert runtime.events == [("navigation.activate", 2)]


def test_boss_accessibility_checks_every_boss_for_the_requested_fleet() -> None:
    blocked = _grid(B1, boss=True)
    blocked.cost_2 = 9999
    reachable = _grid(C1, boss=True)
    reachable.cost_2 = 1
    runtime = _Runtime([blocked, reachable])

    assert _port(runtime).is_boss_accessible(FleetRole.FLEET_2, _cancel())


def test_hidden_siren_candidates_are_marked_before_the_clear_primitive() -> None:
    runtime = _Runtime([_grid(A1, siren=True), _grid(B1)])

    result = _port(runtime).execute_battle(
        ClearSiren(include_hidden_candidates=True),
        _cancel(),
    )

    assert result == program_model.ProgramBattleSettled(program_model.ProgramBattleTarget.SIREN)
    assert all(grid.may_siren for grid in runtime.map.layout)
    assert runtime.events == [("clear_chosen_enemy", (A1.x, A1.y), "siren", 1)]


def test_default_battle_keeps_the_selected_target_kind_after_the_primitive_mutates_the_grid() -> None:
    runtime = _Runtime([_grid(A1, siren=True)])

    result = _port(runtime).execute_battle(DefaultBattle(), _cancel())

    assert result == program_model.ProgramBattleSettled(program_model.ProgramBattleTarget.SIREN)
    assert runtime.events == [("clear_chosen_enemy", (A1.x, A1.y), "siren", 1)]


def test_boss_selection_uses_the_executor_fleet_path_cost() -> None:
    boss = _grid(B1, boss=True)
    boss.cost = 9999
    boss.cost_1 = 9999
    boss.cost_2 = 1
    runtime = _Runtime([boss])

    result = _port(runtime).execute_battle(ClearBoss(BossStrategy.FLEET_BOSS), _cancel())

    assert result == program_model.ProgramBattleSettled(program_model.ProgramBattleTarget.BOSS)
    assert runtime.events == [
        ("navigation.activate", 2),
        ("clear_chosen_enemy", (B1.x, B1.y), "boss", 2),
    ]


def test_boss_roadblock_selection_uses_the_clearing_fleet_path_cost() -> None:
    fleet_2_choice = _grid(B1, enemy=True)
    fleet_2_choice.weight = 1
    fleet_2_choice.cost = 1
    fleet_2_choice.cost_1 = 10
    fleet_2_choice.cost_2 = 1
    fleet_1_choice = _grid(C1, enemy=True)
    fleet_1_choice.weight = 1
    fleet_1_choice.cost = 10
    fleet_1_choice.cost_1 = 1
    fleet_1_choice.cost_2 = 10
    runtime = _Runtime([fleet_2_choice, fleet_1_choice, _grid(D1, boss=True)])
    runtime.navigation.current_index = 2

    result = _port(runtime).execute_battle(ClearBossRoadblock(BossStrategy.MAP_SEARCH), _cancel())

    assert result == program_model.ProgramBattleSettled(
        program_model.ProgramBattleTarget.ENEMY,
        advances_wave=False,
    )
    assert runtime.events == [
        ("navigation.find_roadblocks", 2),
        ("navigation.activate", 1),
        ("clear_chosen_enemy", (C1.x, C1.y), "", 1),
    ]


def test_guarded_battle_and_exception_after_settlement_preserve_facts() -> None:
    runtime = _Runtime([_grid(A1, enemy=True)])
    runtime.raise_after_battle = True
    guarded = GuardedBattleStep(
        AllConditions(
            (
                FlagCondition(BattleFlag.CLEAR_MODE, value=False),
                CellAccessibleCondition(A1),
            )
        ),
        ClearChosenEnemy(A1),
    )

    result = _port(runtime).execute_battle(guarded, _cancel())

    assert result == program_model.ProgramBattleSettled(program_model.ProgramBattleTarget.ENEMY)


def test_best_candidate_uses_the_requested_fleet_path_cost() -> None:
    fleet_1_choice = _grid(B1)
    fleet_1_choice.weight = 1
    fleet_1_choice.cost = 1
    fleet_1_choice.cost_1 = 1
    fleet_1_choice.cost_2 = 10
    fleet_2_choice = _grid(C1)
    fleet_2_choice.weight = 1
    fleet_2_choice.cost = 10
    fleet_2_choice.cost_1 = 10
    fleet_2_choice.cost_2 = 1
    runtime = _Runtime([fleet_1_choice, fleet_2_choice])

    result = _port(runtime).execute_mechanic(
        MoveFleetToBestCandidate(
            0,
            (B1, C1),
            FleetRole.FLEET_2,
            (CandidateSortKey.WEIGHT, CandidateSortKey.COST),
        ),
        _cancel(),
    )

    assert isinstance(result, MechanicApplied)
    assert runtime.events == [
        ("navigation.activate", 2),
        ("navigation.goto", (C1.x, C1.y), "", 2),
    ]


def test_fleet_clear_target_uses_requested_fleet_accessibility_before_switching() -> None:
    target = _grid(C1, enemy=True)
    target.cost = 9999
    target.cost_1 = 9999
    target.cost_2 = 1
    runtime = _Runtime([_grid(A1), _grid(B1), target])

    result = _port(runtime).execute_mechanic(
        FleetClearTarget(0, C1, FleetRole.FLEET_2, EncounterExpectation.ENEMY),
        _cancel(),
    )

    assert result == MechanicSettled(program_model.ProgramBattleTarget.ENEMY)
    assert runtime.events == [
        ("navigation.activate", 2),
        ("clear_chosen_enemy", (C1.x, C1.y), "", 2),
    ]


def test_pickup_ammo_selects_a_reachable_target_before_activating_requested_fleet() -> None:
    blocked = _grid(B1, ammo=True)
    blocked.cost_2 = 9999
    reachable = _grid(C1, ammo=True)
    reachable.cost_2 = 1
    runtime = _Runtime([_grid(A1), blocked, reachable])

    result = _port(runtime).execute_mechanic(PickupAmmo(0, FleetRole.FLEET_2), _cancel())

    assert isinstance(result, MechanicApplied)
    assert runtime.ammo_target == (C1.x, C1.y)
    assert runtime.events == [("navigation.activate", 2), "pickup_ammo"]


def test_clear_all_mystery_uses_active_fleet_cost() -> None:
    target = _grid(C1, mystery=True)
    target.cost = 9999
    target.cost_1 = 9999
    target.cost_2 = 1
    runtime = _Runtime([_grid(A1), _grid(B1), target])
    runtime.navigation.current_index = 2

    result = _port(runtime).execute_mechanic(ClearAllMystery(0, nearby=True), _cancel())

    assert isinstance(result, MechanicApplied)
    assert not target.is_mystery
    assert runtime.events == [("clear_chosen_mystery", (C1.x, C1.y))]


def test_enemy_move_cancellation_after_confirmation_keeps_committed_state() -> None:
    source = _grid(A1, enemy=True)
    target = _grid(B1)
    runtime = _Runtime([source, target])
    driver = Mumu12StrategyActionDriver(cast("Mumu12BattleProgramRuntime", runtime))
    cancellation = cast("CancellationSource", _Cancellation(raise_on_check=6))

    with pytest.raises(RequestedCancellation):
        driver.move_enemy(A1, B1, cancellation)

    assert not source.is_enemy
    assert target.is_enemy
    assert runtime.events == [
        ("in_sight", (B1.x, B1.y)),
        "strategy_open",
        "mob_move_enter",
        "view_update",
        "navigation.rebuild_paths",
        ("strategy_close", False),
    ]


def test_cancellation_happens_before_any_runtime_io() -> None:
    runtime = _Runtime([_grid(A1, enemy=True)])
    cancellation = cast("CancellationSource", _Cancellation(requested=True))

    with pytest.raises(RequestedCancellation):
        _port(runtime).execute_battle(ClearChosenEnemy(A1), cancellation)

    assert runtime.events == []
