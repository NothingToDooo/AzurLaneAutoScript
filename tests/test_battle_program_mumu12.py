from dataclasses import dataclass, field
from typing import TYPE_CHECKING, cast

import pytest

from module.adapters.battle_program_fleet_mumu12 import Mumu12FleetActionDriver
from module.adapters.battle_program_mumu12_contracts import BattleProgramMumu12AdapterError
from module.adapters.battle_program_read_mumu12 import (
    Mumu12BattleProgramReadModel,
    RuntimeProgramState,
)
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
    BattleStep,
    BossStrategy,
    CellAccessibleCondition,
    ClearAnyEnemy,
    ClearBoss,
    ClearBossRoadblock,
    ClearChosenEnemy,
    ClearEnemy,
    ClearFilteredEnemy,
    ClearPriorityEnemy,
    ClearSelectedEnemy,
    ClearSiren,
    DefaultBattle,
    FlagCondition,
    GuardedBattleStep,
    TargetExpectation,
)
from module.content.cell import CellId
from module.content.mechanic_rules import (
    AirStrike,
    BreakSirenCaught,
    CandidateSortKey,
    ClearAllMystery,
    ClearChosenMystery,
    ClearMapItems,
    ClearMechanism,
    EncounterExpectation,
    EnsureFleet,
    EnsureFleetAt,
    FleetClearSelectedTarget,
    FleetClearTarget,
    FleetRole,
    MapItemKind,
    MechanicOperation,
    MechanicProcedure,
    MoveEnemy,
    MoveFleet,
    MoveFleetToBestCandidate,
    PickupAmmo,
    PickupMapItem,
    ProtectFleet,
    PushFleetForward,
    RescueFleet,
    RoadblockAction,
    RoadblockMode,
    RoadblockSelection,
    RoadGroup,
    RoadPath,
    StepFleetOn,
)
from module.content.models import StageRef
from module.content.runtime_profile import CampaignRuntimeProfile
from module.gameplay.battle_program import (
    MechanicApplied,
    MechanicFailed,
    MechanicNotApplied,
    MechanicSettled,
)
from module.map.map_grids import SelectedGrids
from module.map_detection.grid_info import GridInfo

if TYPE_CHECKING:
    from collections.abc import Iterator

    from module.adapters.battle_program_mumu12 import Mumu12BattleProgramPort
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


def _enemy_grid(cell: CellId, *, genre: str) -> GridInfo:
    grid = _grid(cell, enemy=True)
    grid.enemy_genre = genre
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


def test_initial_flags_queries_and_map_state_are_explicit() -> None:
    runtime = _Runtime(
        [
            _grid(A1, enemy=True),
            _grid(B1, siren=True),
            _grid(C1, boss=True),
            _grid(D1),
            _grid(E1),
            _grid(F1),
        ]
    )
    runtime.map_is_clear_mode = True
    runtime.config.fleet_2 = 0
    runtime.config.MAP_HAS_MOVABLE_ENEMY = True
    state = _ProgramState(support_fleet=True)
    port = _port(runtime, state, mob_move=True)
    cancellation = _cancel()

    assert port.initial_flags(cancellation) == frozenset(
        {
            program_model.ProgramFlag.CLEAR_MODE,
            program_model.ProgramFlag.MAP_HAS_MOB_MOVE,
            program_model.ProgramFlag.USE_SINGLE_FLEET,
            program_model.ProgramFlag.USE_SUPPORT_FLEET,
            program_model.ProgramFlag.MOVABLE_ENEMY,
        }
    )
    assert port.read_metric(program_model.ProgramMetric.BATTLE_COUNT, cancellation) == 0
    assert port.read_metric(program_model.ProgramMetric.FLEET_STEP, cancellation) == 2
    assert port.read_metric(program_model.ProgramMetric.MYSTERY_COUNT, cancellation) == 3
    assert port.read_metric(program_model.ProgramMetric.FLEET_BOSS_INDEX, cancellation) == 2
    assert port.read_metric(program_model.ProgramMetric.CONFIGURED_BOSS_FLEET, cancellation) == 2
    assert port.read_cell_property(A1, program_model.CellProperty.ENEMY_SCALE, cancellation) == 2
    assert port.read_cell_property(A1, program_model.CellProperty.ENEMY_GENRE, cancellation) == "Light"
    assert port.read_cell_property(D1, program_model.CellProperty.ACCESSIBLE, cancellation) is True
    assert port.has_map_presence(program_model.MapPresence.SIREN, cancellation)
    assert port.has_map_presence(program_model.MapPresence.BOSS, cancellation)
    assert port.is_boss_at(C1, cancellation)
    assert port.is_boss_accessible(FleetRole.FLEET_BOSS, cancellation)
    assert port.is_cell_accessible_for_fleet(D1, FleetRole.FLEET_1, cancellation)
    assert port.has_candidate_enemy((A1, D1), ("Main",), cancellation)

    port.mark_all_siren_candidates(cancellation)
    assert all(grid.may_siren for grid in runtime.map.layout)
    port.set_map_weights(((6, 5, 4, 3, 2, 1),), cancellation)
    assert [grid.weight for grid in runtime.map.layout] == [6, 5, 4, 3, 2, 1]


def test_stage_single_fleet_state_overrides_the_generic_fleet_count() -> None:
    runtime = _Runtime([_grid(A1)])
    runtime.config.fleet_2 = 0

    flags = _port(
        runtime,
        _ProgramState(single_fleet_override=False),
    ).initial_flags(_cancel())

    assert program_model.ProgramFlag.USE_SINGLE_FLEET not in flags


def test_program_read_model_projects_typed_runtime_facts_and_refreshes_each_query() -> None:
    target = _grid(D1, enemy=True, mystery=True, fortress=True)
    target.cost = 1
    target.cost_1 = 1
    target.cost_2 = 9999
    runtime = _Runtime([_grid(A1), _grid(B1, siren=True), _grid(C1, boss=True), target])
    runtime.map_is_clear_mode = True
    runtime.config.MAP_HAS_MOVABLE_NORMAL_ENEMY = True
    state = _ProgramState(support_fleet=True)
    reads = Mumu12BattleProgramReadModel(
        runtime,
        state,
        CampaignProgramCapabilityReader(CampaignProgramCapabilities(map_has_mob_move=True)),
    )

    status = reads.status(_cancel())
    battlefield = reads.battlefield(_cancel())

    assert status.flags == frozenset(
        {
            program_model.ProgramFlag.CLEAR_MODE,
            program_model.ProgramFlag.MAP_HAS_MOB_MOVE,
            program_model.ProgramFlag.MOVABLE_NORMAL_ENEMY,
            program_model.ProgramFlag.USE_SUPPORT_FLEET,
        }
    )
    assert status.metric(program_model.ProgramMetric.BATTLE_COUNT) == 0
    assert status.metric(program_model.ProgramMetric.FLEET_STEP) == 2
    assert status.metric(program_model.ProgramMetric.MYSTERY_COUNT) == 3
    assert status.fleet_location(FleetRole.FLEET_1) == A1
    assert status.fleet_location(FleetRole.FLEET_BOSS) == B1
    assert battlefield.has_presence(program_model.MapPresence.NON_BOSS_TARGET)
    assert battlefield.cell(D1).is_mystery
    assert battlefield.cell(D1).is_fortress
    assert battlefield.cell(D1).enemy_genre == "Light"
    assert battlefield.cell(D1).accessible_for(1)
    assert not battlefield.cell(D1).accessible_for(2)

    runtime.battle_count = 1
    target.is_mystery = False
    assert reads.read_metric(program_model.ProgramMetric.BATTLE_COUNT, _cancel()) == 1
    assert not reads.read_cell_property(D1, program_model.CellProperty.IS_MYSTERY, _cancel())


def test_battle_count_read_does_not_query_dynamic_program_state() -> None:
    runtime = _Runtime([_grid(A1)])
    runtime.battle_count = 7
    state = _ProgramState(single_fleet_override=True, support_fleet=True)
    reads = Mumu12BattleProgramReadModel(
        runtime,
        state,
        CampaignProgramCapabilityReader(CampaignProgramCapabilities(map_has_mob_move=True)),
    )
    cancellation = _Cancellation()

    assert reads.battle_count(cast("CancellationSource", cancellation)) == 7
    assert state.dynamic_queries == []
    assert cancellation.checks == 1


def test_read_status_keeps_profile_boss_override_distinct_from_effective_navigation() -> None:
    runtime = _Runtime([_grid(A1)])
    runtime.configured_boss_fleet = 2
    runtime.navigation.boss_index = 1

    status = Mumu12BattleProgramReadModel(
        runtime,
        _ProgramState(),
        CampaignProgramCapabilityReader(),
    ).status(_cancel())

    assert status.fleet_boss_index == 1
    assert status.configured_boss_fleet == 2


def test_alternate_fleet_accessibility_uses_precomputed_path_without_switching_runtime() -> None:
    target = _grid(D1)
    target.cost = 1
    target.cost_1 = 1
    target.cost_2 = 9999
    runtime = _Runtime([_grid(A1), _grid(B1), target])
    runtime.navigation.current_index = 1
    before_costs = (target.cost, target.cost_1, target.cost_2)

    assert not _port(runtime).is_cell_accessible_for_fleet(D1, FleetRole.FLEET_2, _cancel())
    assert runtime.navigation.current_index == 1
    assert runtime.events == []
    assert (target.cost, target.cost_1, target.cost_2) == before_costs


def test_fleet_driver_activates_by_index_without_side_effecting_getters_or_switch_to() -> None:
    runtime = _Runtime([_grid(A1), _grid(B1), _grid(C1, enemy=True)])
    driver = Mumu12FleetActionDriver(cast("Mumu12BattleProgramRuntime", runtime))

    assert not driver.activate(1, _cancel())
    assert driver.clear_target(2, C1, EncounterExpectation.ENEMY, _cancel())

    assert runtime.events == [
        ("navigation.activate", 2),
        ("clear_chosen_enemy", (C1.x, C1.y), "", 2),
    ]


def test_fleet_driver_rejects_a_failed_selection_postcondition() -> None:
    runtime = _Runtime()
    runtime.navigation_activate_changes_selection = False
    driver = Mumu12FleetActionDriver(cast("Mumu12BattleProgramRuntime", runtime))

    with pytest.raises(BattleProgramMumu12AdapterError, match="did not select"):
        driver.activate(2, _cancel())

    assert runtime.events == [("navigation.activate", 2)]


def test_fleet_driver_checks_cancellation_before_selection_io() -> None:
    runtime = _Runtime()
    driver = Mumu12FleetActionDriver(cast("Mumu12BattleProgramRuntime", runtime))
    cancellation = cast("CancellationSource", _Cancellation(requested=True))

    with pytest.raises(RequestedCancellation):
        driver.activate(2, cancellation)

    assert runtime.events == []


@pytest.mark.parametrize(
    ("method_name", "arguments"),
    [
        ("clear_target", (2, CellId(99, 99), EncounterExpectation.ENEMY)),
        ("move", (2, CellId(99, 99), EncounterExpectation.ANY)),
        ("pickup_ammo", (2, CellId(99, 99))),
        ("pickup_map_item", (2, CellId(99, 99), MapItemKind.FLARE)),
        ("clear_mystery", (2, CellId(99, 99))),
    ],
)
def test_fleet_driver_rejects_invalid_cells_before_activation(
    method_name: str,
    arguments: tuple[object, ...],
) -> None:
    runtime = _Runtime()
    driver = Mumu12FleetActionDriver(cast("Mumu12BattleProgramRuntime", runtime))

    with pytest.raises(BattleProgramMumu12AdapterError, match="outside the active map"):
        getattr(driver, method_name)(*arguments, _cancel())

    assert runtime.events == []


def test_fleet_move_measures_displacement_after_activation_refresh() -> None:
    runtime = _Runtime()
    runtime.navigation_activate_location = (C1.x, C1.y)
    runtime.navigation_goto_changes_location = False
    driver = Mumu12FleetActionDriver(cast("Mumu12BattleProgramRuntime", runtime))

    moved = driver.move(2, C1, EncounterExpectation.ANY, _cancel())

    assert not moved
    assert runtime.events == [("navigation.activate", 2)]


def test_map_item_is_not_marked_when_fleet_activation_fails() -> None:
    target = _grid(C1)
    runtime = _Runtime([_grid(A1), _grid(B1), target])
    runtime.navigation_activate_error = RuntimeError("selection failed")
    driver = Mumu12FleetActionDriver(cast("Mumu12BattleProgramRuntime", runtime))

    with pytest.raises(RuntimeError, match="selection failed"):
        driver.pickup_map_item(2, C1, MapItemKind.FLARE, _cancel())

    assert not target.is_flare
    assert runtime.events == [("navigation.activate", 2)]


def test_boss_accessibility_checks_every_boss_for_the_requested_fleet() -> None:
    blocked = _grid(B1, boss=True)
    blocked.cost_2 = 9999
    reachable = _grid(C1, boss=True)
    reachable.cost_2 = 1
    runtime = _Runtime([blocked, reachable])

    assert _port(runtime).is_boss_accessible(FleetRole.FLEET_2, _cancel())


@pytest.mark.parametrize(
    ("action", "grids", "expected", "expected_events"),
    [
        (
            ClearSiren(),
            [_grid(A1, siren=True)],
            program_model.ProgramBattleSettled(program_model.ProgramBattleTarget.SIREN),
            [("clear_chosen_enemy", (A1.x, A1.y), "siren", 1)],
        ),
        (
            ClearFilteredEnemy(0),
            [_grid(A1, enemy=True)],
            program_model.ProgramBattleSettled(program_model.ProgramBattleTarget.ENEMY),
            [("clear_chosen_enemy", (A1.x, A1.y), "", 1)],
        ),
        (
            ClearEnemy(scales=(2,)),
            [_grid(A1, enemy=True)],
            program_model.ProgramBattleSettled(program_model.ProgramBattleTarget.ENEMY),
            [("clear_chosen_enemy", (A1.x, A1.y), "", 1)],
        ),
        (
            ClearAnyEnemy(),
            [_grid(A1, enemy=True)],
            program_model.ProgramBattleSettled(program_model.ProgramBattleTarget.ENEMY),
            [("clear_chosen_enemy", (A1.x, A1.y), "", 1)],
        ),
        (
            ClearChosenEnemy(A1, TargetExpectation.ENEMY),
            [_grid(A1, enemy=True)],
            program_model.ProgramBattleSettled(program_model.ProgramBattleTarget.ENEMY),
            [("clear_chosen_enemy", (A1.x, A1.y), "", 1)],
        ),
        (
            ClearSelectedEnemy((A1, B1), expected=TargetExpectation.SIREN),
            [_grid(A1, enemy=True, siren=True), _grid(B1)],
            program_model.ProgramBattleSettled(program_model.ProgramBattleTarget.SIREN),
            [("clear_chosen_enemy", (A1.x, A1.y), "siren", 1)],
        ),
        (
            ClearPriorityEnemy(),
            [_enemy_grid(A1, genre="LightInvertedOrthant")],
            program_model.ProgramBattleSettled(program_model.ProgramBattleTarget.ENEMY),
            [("clear_chosen_enemy", (A1.x, A1.y), "", 1)],
        ),
        (
            DefaultBattle(),
            [_grid(A1, enemy=True)],
            program_model.ProgramBattleSettled(program_model.ProgramBattleTarget.ENEMY),
            [("clear_chosen_enemy", (A1.x, A1.y), "", 1)],
        ),
        (
            ClearBossRoadblock(BossStrategy.MAP_SEARCH),
            [_grid(A1, enemy=True), _grid(B1, boss=True)],
            program_model.ProgramBattleSettled(
                program_model.ProgramBattleTarget.ENEMY,
                advances_wave=False,
            ),
            [
                ("navigation.find_roadblocks", 2),
                ("clear_chosen_enemy", (A1.x, A1.y), "", 1),
            ],
        ),
        (
            ClearBoss(BossStrategy.BRUTE_FORCE),
            [_grid(A1, boss=True)],
            program_model.ProgramBattleSettled(program_model.ProgramBattleTarget.BOSS),
            [
                ("navigation.activate", 2),
                ("clear_chosen_enemy", (A1.x, A1.y), "boss", 2),
            ],
        ),
    ],
)
def test_every_battle_action_is_fact_closed(
    action: BattleStep,
    grids: list[GridInfo],
    expected: program_model.ProgramBattleSettled,
    expected_events: list[object],
) -> None:
    runtime = _Runtime(grids)
    result = _port(runtime).execute_battle(action, _cancel())

    assert result == expected
    assert runtime.battle_count == 1
    assert runtime.events == expected_events


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


def test_battle_primitive_success_without_a_count_advance_is_rejected_centrally() -> None:
    runtime = _Runtime([_grid(A1, enemy=True)])
    runtime.battle_delta = 0

    result = _port(runtime).execute_battle(ClearEnemy(), _cancel())

    assert result == program_model.ProgramFailed("battle primitive reported success without advancing battle_count")
    assert runtime.events == [("clear_chosen_enemy", (A1.x, A1.y), "", 1)]


@pytest.mark.parametrize(
    ("action", "grids"),
    [
        (ClearChosenEnemy(A1), [_grid(A1, accessible=False)]),
        (ClearSelectedEnemy((A1,)), [_grid(A1)]),
        (DefaultBattle(), [_grid(A1)]),
        (ClearBossRoadblock(BossStrategy.MAP_SEARCH), [_grid(A1)]),
        (ClearBoss(BossStrategy.BRUTE_FORCE), [_grid(A1, boss=True, accessible=False)]),
    ],
)
def test_battle_handlers_without_a_valid_target_have_no_side_effects(
    action: BattleStep,
    grids: list[GridInfo],
) -> None:
    runtime = _Runtime(grids)

    result = _port(runtime).execute_battle(action, _cancel())

    assert result == program_model.ProgramNoTarget()
    assert runtime.battle_count == 0
    assert runtime.events == []


@pytest.mark.parametrize(
    ("strategy", "expected_fleet"),
    [
        (BossStrategy.FLEET_BOSS, 2),
        (BossStrategy.BRUTE_FORCE, 2),
        (BossStrategy.FLEET_1, 1),
        (BossStrategy.MAP_SEARCH, 1),
    ],
)
def test_all_boss_strategies_issue_one_confirmed_boss_action(
    strategy: BossStrategy,
    expected_fleet: int,
) -> None:
    runtime = _Runtime([_grid(A1, boss=True)])

    result = _port(runtime).execute_battle(ClearBoss(strategy), _cancel())

    assert result == program_model.ProgramBattleSettled(program_model.ProgramBattleTarget.BOSS)
    assert runtime.battle_count == 1
    expected_events: list[object] = []
    if expected_fleet != 1:
        expected_events.append(("navigation.activate", expected_fleet))
    expected_events.append(("clear_chosen_enemy", (A1.x, A1.y), "boss", expected_fleet))
    assert runtime.events == expected_events


@pytest.mark.parametrize("strategy", [BossStrategy.MAP_SEARCH, BossStrategy.BRUTE_FORCE])
def test_boss_search_strategies_do_not_guess_or_clear_a_non_boss(strategy: BossStrategy) -> None:
    potential = _grid(A1, enemy=True)
    potential.may_boss = True
    runtime = _Runtime([potential])

    result = _port(runtime).execute_battle(ClearBoss(strategy), _cancel())

    assert result == program_model.ProgramNoTarget()
    assert runtime.battle_count == 0
    assert runtime.events == []


def test_brute_force_boss_does_not_clear_a_roadblock_for_an_inaccessible_boss() -> None:
    boss = _grid(B1, boss=True)
    boss.cost = 9999
    boss.cost_2 = 9999
    runtime = _Runtime([_grid(A1, enemy=True), boss])

    result = _port(runtime).execute_battle(ClearBoss(BossStrategy.BRUTE_FORCE), _cancel())

    assert result == program_model.ProgramNoTarget()
    assert runtime.battle_count == 0
    assert runtime.events == []


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


def test_confirmed_boss_action_rejects_more_than_one_battle_count_advance() -> None:
    runtime = _Runtime([_grid(A1, boss=True)])
    runtime.battle_delta = 2

    result = _port(runtime).execute_battle(ClearBoss(BossStrategy.BRUTE_FORCE), _cancel())

    assert result == program_model.ProgramFailed("one battle action changed battle_count by 2, expected zero or one")


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


@pytest.mark.parametrize(
    "mode",
    [
        RoadblockMode.CLEAR,
        RoadblockMode.CLEAR_POTENTIAL,
        RoadblockMode.CLEAR_FIRST,
        RoadblockMode.CLEAR_FOR_FASTER,
    ],
)
def test_all_roadblock_modes_are_explicit(mode: RoadblockMode) -> None:
    runtime = _Runtime([_grid(A1, enemy=True), _grid(B1)])
    path = (A1, B1) if mode is RoadblockMode.CLEAR_POTENTIAL else (A1,)
    action = RoadblockAction(
        0,
        mode,
        (RoadGroup((RoadPath(path),)),),
        RoadblockSelection.STRONGEST,
    )

    result = _port(runtime).execute_mechanic(action, _cancel())

    assert result == MechanicSettled(program_model.ProgramBattleTarget.ENEMY)
    assert runtime.events == [("clear_chosen_enemy", (A1.x, A1.y), "", 1)]


def test_every_fleet_mechanic_action_has_a_fixed_projection() -> None:
    road = RoadGroup((RoadPath((A1,)),))

    runtime = _Runtime([_grid(A1, siren=True)])
    assert _port(runtime).execute_mechanic(
        BreakSirenCaught(0),
        _cancel(),
    ) == MechanicSettled(program_model.ProgramBattleTarget.SIREN)
    assert runtime.events == ["break_siren_caught"]

    runtime = _Runtime()
    assert isinstance(_port(runtime).execute_mechanic(PushFleetForward(0), _cancel()), MechanicApplied)
    assert runtime.events == ["push_forward"]

    runtime = _Runtime()
    assert isinstance(_port(runtime).execute_mechanic(ProtectFleet(0), _cancel()), MechanicApplied)
    assert runtime.events == ["protect"]

    runtime = _Runtime()
    assert isinstance(_port(runtime).execute_mechanic(RescueFleet(0, A1), _cancel()), MechanicApplied)
    assert runtime.events == [("rescue", (A1.x, A1.y))]

    runtime = _Runtime()
    assert isinstance(
        _port(runtime).execute_mechanic(StepFleetOn(0, (C1,), (road,)), _cancel()),
        MechanicApplied,
    )
    assert runtime.events == ["step_on"]

    runtime = _Runtime()
    assert isinstance(
        _port(runtime).execute_mechanic(MoveFleet(0, C1, FleetRole.ACTIVE), _cancel()),
        MechanicApplied,
    )
    assert runtime.events == [("navigation.goto", (C1.x, C1.y), "", 1)]

    runtime = _Runtime()
    runtime.map.layout[B1.x, B1.y].weight = 5
    runtime.map.layout[B1.x, B1.y].cost = 2
    runtime.map.layout[B1.x, B1.y].cost_2 = 2
    runtime.map.layout[C1.x, C1.y].weight = 5
    runtime.map.layout[C1.x, C1.y].cost = 1
    runtime.map.layout[C1.x, C1.y].cost_2 = 1
    assert isinstance(
        _port(runtime).execute_mechanic(
            MoveFleetToBestCandidate(
                0,
                (B1, C1),
                FleetRole.FLEET_BOSS,
                (CandidateSortKey.WEIGHT, CandidateSortKey.COST),
            ),
            _cancel(),
        ),
        MechanicApplied,
    )
    assert runtime.events == [
        ("navigation.activate", 2),
        ("navigation.goto", (C1.x, C1.y), "", 2),
    ]

    runtime = _Runtime()
    assert isinstance(
        _port(runtime).execute_mechanic(EnsureFleet(0, FleetRole.NON_BOSS), _cancel()),
        MechanicNotApplied,
    )
    assert runtime.events == []

    runtime = _Runtime()
    assert isinstance(
        _port(runtime).execute_mechanic(EnsureFleetAt(0, A1, FleetRole.FLEET_1), _cancel()),
        MechanicApplied,
    )
    assert runtime.events == []

    runtime = _Runtime([_grid(A1, enemy=True)])
    assert _port(runtime).execute_mechanic(
        FleetClearTarget(0, A1, FleetRole.ACTIVE, EncounterExpectation.ENEMY),
        _cancel(),
    ) == MechanicSettled(program_model.ProgramBattleTarget.ENEMY)
    assert runtime.events == [("clear_chosen_enemy", (A1.x, A1.y), "", 1)]


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


def test_best_candidate_does_not_dispatch_an_unreachable_fleet_move() -> None:
    first = _grid(C1)
    first.cost_2 = 9999
    second = _grid(D1)
    second.cost_2 = 9999
    runtime = _Runtime([_grid(A1), _grid(B1), first, second])

    result = _port(runtime).execute_mechanic(
        MoveFleetToBestCandidate(0, (C1, D1), FleetRole.FLEET_2),
        _cancel(),
    )

    assert isinstance(result, MechanicNotApplied)
    assert runtime.navigation.current_index == 1
    assert runtime.events == []


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


def test_fleet_clear_target_does_not_switch_to_an_inaccessible_fleet() -> None:
    target = _grid(C1, enemy=True)
    target.cost_2 = 9999
    runtime = _Runtime([_grid(A1), _grid(B1), target])

    result = _port(runtime).execute_mechanic(
        FleetClearTarget(0, C1, FleetRole.FLEET_2, EncounterExpectation.ENEMY),
        _cancel(),
    )

    assert isinstance(result, MechanicNotApplied)
    assert runtime.navigation.current_index == 1
    assert runtime.events == []


def test_fleet_clear_selected_target_uses_first_matching_accessible_candidate() -> None:
    enemy = _grid(B1, enemy=True)
    unreachable_siren = _grid(C1, siren=True)
    unreachable_siren.cost_2 = 9999
    reachable_siren = _grid(D1, siren=True)
    reachable_siren.cost_2 = 1
    runtime = _Runtime([_grid(A1), enemy, unreachable_siren, reachable_siren])

    result = _port(runtime).execute_mechanic(
        FleetClearSelectedTarget(
            0,
            (B1, C1, D1),
            FleetRole.FLEET_2,
            EncounterExpectation.SIREN,
        ),
        _cancel(),
    )

    assert result == MechanicSettled(program_model.ProgramBattleTarget.SIREN)
    assert runtime.events == [
        ("navigation.activate", 2),
        ("clear_chosen_enemy", (D1.x, D1.y), "siren", 2),
    ]


def test_fleet_clear_selected_target_is_not_applied_without_a_matching_accessible_candidate() -> None:
    enemy = _grid(B1, enemy=True)
    unreachable_siren = _grid(C1, siren=True)
    unreachable_siren.cost_1 = 9999
    runtime = _Runtime([_grid(A1), enemy, unreachable_siren])

    result = _port(runtime).execute_mechanic(
        FleetClearSelectedTarget(
            0,
            (B1, C1),
            FleetRole.FLEET_1,
            EncounterExpectation.SIREN,
        ),
        _cancel(),
    )

    assert isinstance(result, MechanicNotApplied)
    assert runtime.events == []


def test_every_pickup_mechanic_action_has_a_fixed_projection() -> None:
    runtime = _Runtime([_grid(A1, ammo=True)])
    assert isinstance(_port(runtime).execute_mechanic(PickupAmmo(0), _cancel()), MechanicApplied)
    assert runtime.events == ["pickup_ammo"]
    assert runtime.ammo_target == (A1.x, A1.y)

    runtime = _Runtime()
    assert isinstance(
        _port(runtime).execute_mechanic(PickupMapItem(0, MapItemKind.FLARE, C1), _cancel()),
        MechanicApplied,
    )
    assert runtime.events == [("navigation.goto", (C1.x, C1.y), "", 1)]
    assert runtime.map.layout[C1.x, C1.y].is_flare


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


def test_pickup_ammo_does_not_activate_a_fleet_without_a_reachable_target() -> None:
    blocked = _grid(C1, ammo=True)
    blocked.cost_2 = 9999
    runtime = _Runtime([_grid(A1), _grid(B1), blocked])

    result = _port(runtime).execute_mechanic(PickupAmmo(0, FleetRole.FLEET_2), _cancel())

    assert isinstance(result, MechanicNotApplied)
    assert runtime.ammo_target is None
    assert runtime.events == []


def test_pickup_map_item_uses_requested_fleet_accessibility() -> None:
    target = _grid(C1)
    target.cost = 9999
    target.cost_1 = 9999
    target.cost_2 = 1
    runtime = _Runtime([_grid(A1), _grid(B1), target])

    result = _port(runtime).execute_mechanic(
        PickupMapItem(0, MapItemKind.FLARE, C1, FleetRole.FLEET_2),
        _cancel(),
    )

    assert isinstance(result, MechanicApplied)
    assert target.is_flare
    assert runtime.events == [
        ("navigation.activate", 2),
        ("navigation.goto", (C1.x, C1.y), "", 2),
    ]


def test_pickup_map_item_does_not_mark_or_switch_for_an_inaccessible_fleet() -> None:
    target = _grid(C1)
    target.cost_2 = 9999
    runtime = _Runtime([_grid(A1), _grid(B1), target])

    result = _port(runtime).execute_mechanic(
        PickupMapItem(0, MapItemKind.FLARE, C1, FleetRole.FLEET_2),
        _cancel(),
    )

    assert isinstance(result, MechanicNotApplied)
    assert not target.is_flare
    assert runtime.navigation.current_index == 1
    assert runtime.events == []


def test_every_map_interaction_mechanic_action_has_a_fixed_projection() -> None:
    runtime = _Runtime([_grid(A1, mystery=True)])
    assert isinstance(
        _port(runtime).execute_mechanic(ClearAllMystery(0, nearby=False), _cancel()),
        MechanicApplied,
    )
    assert runtime.events == [("clear_chosen_mystery", (A1.x, A1.y))]

    runtime = _Runtime([_grid(A1, mystery=True)])
    assert isinstance(
        _port(runtime).execute_mechanic(ClearChosenMystery(0, A1), _cancel()),
        MechanicApplied,
    )
    assert runtime.events == [("clear_chosen_mystery", (A1.x, A1.y))]

    runtime = _Runtime()
    runtime.map.layout[A1.x, A1.y].is_mechanism_trigger = True
    assert isinstance(
        _port(runtime).execute_mechanic(ClearMechanism(0, (A1,)), _cancel()),
        MechanicApplied,
    )
    event_name, selected = cast("tuple[str, SelectedGrids[GridInfo]]", runtime.events[0])
    assert event_name == "clear_mechanism"
    assert selected.location == [(A1.x, A1.y)]

    runtime = _Runtime()
    assert isinstance(
        _port(runtime).execute_mechanic(ClearMapItems(0, (C1, D1)), _cancel()),
        MechanicApplied,
    )
    assert runtime.events == [
        ("navigation.goto", (C1.x, C1.y), "", 1),
        ("navigation.goto", (D1.x, D1.y), "", 1),
    ]

    runtime = _Runtime()
    assert isinstance(_port(runtime).execute_mechanic(AirStrike(0, C1), _cancel()), MechanicApplied)
    assert runtime.events == [
        "strategy_open",
        "air_strike_enter",
        ("in_sight", (C1.x, C1.y)),
        ("strategy_close", False),
    ]


def test_clear_all_mystery_skips_target_inaccessible_to_current_fleet() -> None:
    target = _grid(C1, mystery=True)
    target.cost = 9999
    target.cost_1 = 9999
    target.cost_2 = 1
    runtime = _Runtime([_grid(A1), _grid(B1), target])

    result = _port(runtime).execute_mechanic(ClearAllMystery(0, nearby=False), _cancel())

    assert isinstance(result, MechanicNotApplied)
    assert target.is_mystery
    assert runtime.events == []


def test_clear_all_mystery_nearby_boundary_excludes_cost_twenty() -> None:
    target = _grid(C1, mystery=True)
    target.cost = 20
    target.cost_1 = 20
    runtime = _Runtime([_grid(A1), _grid(B1), target])

    result = _port(runtime).execute_mechanic(ClearAllMystery(0, nearby=True), _cancel())

    assert isinstance(result, MechanicNotApplied)
    assert target.is_mystery
    assert runtime.events == []


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


def test_clear_all_mystery_rejects_unchanged_projection_after_one_action() -> None:
    target = _grid(C1, mystery=True)
    runtime = _Runtime([_grid(A1), _grid(B1), target])
    runtime.clear_mystery_changes_projection = False

    with pytest.raises(BattleProgramMumu12AdapterError, match="did not remove target"):
        _port(runtime).execute_mechanic(ClearAllMystery(0, nearby=False), _cancel())

    assert target.is_mystery
    assert runtime.events == [("clear_chosen_mystery", (C1.x, C1.y))]


def test_standalone_mechanic_actions_have_fixed_projections() -> None:
    runtime = _Runtime([_grid(A1, enemy=True), _grid(B1)])
    assert isinstance(
        _port(runtime).execute_mechanic(MoveEnemy(0, A1, B1), _cancel()),
        MechanicApplied,
    )
    assert not runtime.map.layout[A1.x, A1.y].is_enemy
    assert runtime.map.layout[B1.x, B1.y].is_enemy
    assert runtime.events == [
        ("in_sight", (B1.x, B1.y)),
        "strategy_open",
        "mob_move_enter",
        "view_update",
        "navigation.rebuild_paths",
        ("strategy_close", False),
    ]

    runtime = _Runtime([_grid(A1, enemy=True)])
    result = _port(runtime).execute_mechanic(
        MechanicProcedure(0, (MechanicOperation.CLEAR_BOUNCING_ENEMY,)),
        _cancel(),
    )
    assert result == MechanicSettled(program_model.ProgramBattleTarget.ENEMY)
    assert runtime.events == ["clear_bouncing_enemy"]


def test_strategy_driver_does_not_mutate_map_without_the_mob_move_capability() -> None:
    source = _grid(A1, enemy=True)
    target = _grid(B1)
    runtime = _Runtime([source, target])
    runtime.mob_move_available = False
    driver = Mumu12StrategyActionDriver(cast("Mumu12BattleProgramRuntime", runtime))

    applied = driver.move_enemy(A1, B1, _cancel())

    assert not applied
    assert source.is_enemy
    assert not target.is_enemy
    assert runtime.events == [
        ("in_sight", (B1.x, B1.y)),
        "strategy_open",
        ("strategy_close", False),
    ]


def test_strategy_driver_checks_cancellation_before_device_io() -> None:
    runtime = _Runtime([_grid(C1)])
    driver = Mumu12StrategyActionDriver(cast("Mumu12BattleProgramRuntime", runtime))
    cancellation = cast("CancellationSource", _Cancellation(requested=True))

    with pytest.raises(RequestedCancellation):
        driver.air_strike(C1, cancellation)

    assert runtime.events == []


def test_air_strike_cancellation_in_target_mode_cancels_and_closes() -> None:
    runtime = _Runtime([_grid(C1)])
    driver = Mumu12StrategyActionDriver(cast("Mumu12BattleProgramRuntime", runtime))
    cancellation = cast("CancellationSource", _Cancellation(raise_on_check=3))

    with pytest.raises(RequestedCancellation):
        driver.air_strike(C1, cancellation)

    assert runtime.events == [
        "strategy_open",
        "air_strike_enter",
        "air_strike_cancel",
        ("strategy_close", False),
    ]


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


def test_strategy_open_failure_does_not_run_cleanup() -> None:
    runtime = _Runtime([_grid(C1)])
    runtime.strategy_open_error = RuntimeError("open failed")
    driver = Mumu12StrategyActionDriver(cast("Mumu12BattleProgramRuntime", runtime))

    with pytest.raises(RuntimeError, match="open failed"):
        driver.air_strike(C1, _cancel())

    assert runtime.events == ["strategy_open"]


def test_air_strike_selection_failure_cancels_target_mode_and_closes_strategy() -> None:
    runtime = _Runtime([_grid(C1)])
    runtime.air_target_error = RuntimeError("target recognition failed")
    driver = Mumu12StrategyActionDriver(cast("Mumu12BattleProgramRuntime", runtime))

    with pytest.raises(RuntimeError, match="target recognition failed"):
        driver.air_strike(C1, _cancel())

    assert runtime.events == [
        "strategy_open",
        "air_strike_enter",
        ("in_sight", (C1.x, C1.y)),
        "air_strike_cancel",
        ("strategy_close", False),
    ]


def test_unconfirmed_enemy_move_failure_does_not_mutate_map_and_runs_cleanup() -> None:
    source = _grid(A1, enemy=True)
    target = _grid(B1)
    runtime = _Runtime([source, target])
    runtime.mob_target_error = RuntimeError("origin recognition failed")
    driver = Mumu12StrategyActionDriver(cast("Mumu12BattleProgramRuntime", runtime))

    with pytest.raises(RuntimeError, match="origin recognition failed"):
        driver.move_enemy(A1, B1, _cancel())

    assert source.is_enemy
    assert not target.is_enemy
    assert runtime.events == [
        ("in_sight", (B1.x, B1.y)),
        "strategy_open",
        "mob_move_enter",
        "view_update",
        "mob_move_cancel",
        ("strategy_close", False),
    ]


@pytest.mark.parametrize("available", [False, True])
def test_air_strike_close_failure_is_not_reported_as_success_or_noop(*, available: bool) -> None:
    runtime = _Runtime([_grid(C1)])
    runtime.air_strike_available = available
    runtime.strategy_close_error = RuntimeError("close failed")
    driver = Mumu12StrategyActionDriver(cast("Mumu12BattleProgramRuntime", runtime))

    with pytest.raises(RuntimeError, match="close failed"):
        driver.air_strike(C1, _cancel())


def test_confirmed_enemy_move_updates_map_before_close_failure() -> None:
    source = _grid(A1, enemy=True)
    target = _grid(B1)
    runtime = _Runtime([source, target])
    runtime.strategy_close_error = RuntimeError("close failed")
    driver = Mumu12StrategyActionDriver(cast("Mumu12BattleProgramRuntime", runtime))

    with pytest.raises(RuntimeError, match="close failed"):
        driver.move_enemy(A1, B1, _cancel())

    assert not source.is_enemy
    assert target.is_enemy
    assert runtime.events[-2:] == ["navigation.rebuild_paths", ("strategy_close", False)]


def test_strategy_primary_cancel_and_close_failures_are_all_preserved() -> None:
    runtime = _Runtime([_grid(C1)])
    primary = RuntimeError("target failed")
    cancel = RuntimeError("cancel failed")
    close = RuntimeError("close failed")
    runtime.air_target_error = primary
    runtime.air_strike_cancel_error = cancel
    runtime.strategy_close_error = close
    driver = Mumu12StrategyActionDriver(cast("Mumu12BattleProgramRuntime", runtime))

    with pytest.raises(BaseExceptionGroup) as captured:
        driver.air_strike(C1, _cancel())

    outer = captured.value
    assert outer.exceptions[0] is primary
    cleanup = outer.exceptions[1]
    assert isinstance(cleanup, BaseExceptionGroup)
    assert cleanup.exceptions == (cancel, close)


@pytest.mark.parametrize(
    ("battle_delta", "expected"),
    [
        (1, MechanicSettled(program_model.ProgramBattleTarget.ENEMY)),
        (2, MechanicFailed("mechanic action changed battle_count by 2, expected zero or one")),
    ],
)
def test_mechanic_exception_after_settlement_closes_from_battle_count(
    battle_delta: int,
    expected: MechanicSettled | MechanicFailed,
) -> None:
    runtime = _Runtime([_grid(A1, enemy=True)])
    runtime.battle_delta = battle_delta
    runtime.raise_after_battle = True

    result = _port(runtime).execute_mechanic(
        FleetClearTarget(0, A1, FleetRole.ACTIVE, EncounterExpectation.ENEMY),
        _cancel(),
    )

    assert result == expected


@pytest.mark.parametrize(
    ("target", "grid_flags"),
    [
        (program_model.ProgramBattleTarget.SIREN, {"siren": True}),
        (program_model.ProgramBattleTarget.BOSS, {"boss": True}),
    ],
)
@pytest.mark.parametrize("best_candidate", [False, True])
def test_move_fleet_exception_freezes_any_target_before_the_grid_is_cleared(
    target: program_model.ProgramBattleTarget,
    grid_flags: dict[str, bool],
    *,
    best_candidate: bool,
) -> None:
    runtime = _Runtime([_grid(A1), _grid(B1, **grid_flags)])
    runtime.raise_after_battle = True
    action: MoveFleet | MoveFleetToBestCandidate
    if best_candidate:
        action = MoveFleetToBestCandidate(
            0,
            (B1,),
            FleetRole.ACTIVE,
            expected=EncounterExpectation.ANY,
        )
    else:
        action = MoveFleet(
            0,
            B1,
            FleetRole.ACTIVE,
            expected=EncounterExpectation.ANY,
        )

    result = _port(runtime).execute_mechanic(action, _cancel())

    assert result == MechanicSettled(target)


def test_mechanic_exception_without_settlement_propagates() -> None:
    runtime = _Runtime([_grid(A1, enemy=True)])
    runtime.battle_delta = 0
    runtime.raise_after_battle = True

    with pytest.raises(RuntimeError, match="campaign ended after settlement"):
        _port(runtime).execute_mechanic(
            FleetClearTarget(0, A1, FleetRole.ACTIVE, EncounterExpectation.ENEMY),
            _cancel(),
        )


def test_break_siren_caught_rejects_unconfirmed_success() -> None:
    runtime = _Runtime([_grid(A1, siren=True)])
    runtime.battle_delta = 0

    result = _port(runtime).execute_mechanic(BreakSirenCaught(0), _cancel())

    assert isinstance(result, MechanicFailed)
    assert "without advancing battle_count" in result.evidence


def test_ambiguous_runtime_primitives_fail_typed() -> None:
    runtime = _Runtime()
    port = _port(runtime)
    with pytest.raises(BattleProgramMumu12AdapterError, match="has no target/fleet operand"):
        port.execute_mechanic(
            MechanicProcedure(0, (MechanicOperation.CHECK_ACCESSIBILITY,)),
            _cancel(),
        )
    with pytest.raises(BattleProgramMumu12AdapterError, match="map weight matrix"):
        port.set_map_weights(((1,),), _cancel())
    with pytest.raises(BattleProgramMumu12AdapterError, match="outside the active map"):
        port.is_boss_at(CellId(9, 9), _cancel())


def test_cancellation_happens_before_any_runtime_io() -> None:
    runtime = _Runtime([_grid(A1, enemy=True)])
    cancellation = cast("CancellationSource", _Cancellation(requested=True))

    with pytest.raises(RequestedCancellation):
        _port(runtime).execute_battle(ClearChosenEnemy(A1), cancellation)

    assert runtime.events == []
