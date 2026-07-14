from dataclasses import dataclass, field
from typing import TYPE_CHECKING, cast

import pytest

from module.adapters.battle_program_mumu12 import (
    BattleProgramMumu12AdapterError,
    Mumu12BattleProgramPort,
    RuntimeProgramState,
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
    FixedTargetSequence,
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
    PresetRouteBattle,
    PresetRouteStep,
    PresetRouteVariant,
    ProtectFleet,
    PushFleetForward,
    RescueFleet,
    RoadblockAction,
    RoadblockMode,
    RoadblockSelection,
    RoadGroup,
    RoadPath,
    StepFleetOn,
    SwitchFleet,
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

    from module.adapters.campaign_live import CampaignMapRuntime
    from module.interaction.ports import CancellationSignal


A1 = CellId(0, 0)
B1 = CellId(1, 0)
C1 = CellId(2, 0)
D1 = CellId(3, 0)
E1 = CellId(4, 0)
F1 = CellId(5, 0)


class RequestedCancellation(RuntimeError):
    pass


@dataclass(slots=True)
class _Cancellation:
    requested: bool = False
    checks: int = 0

    def raise_if_requested(self) -> None:
        self.checks += 1
        if self.requested:
            raise RequestedCancellation


@dataclass(slots=True)
class _ProgramState:
    mob_move: bool = False
    single_fleet_override: bool | None = None
    support_fleet: bool = False

    def map_has_mob_move(self, cancellation: CancellationSignal) -> bool:
        cancellation.raise_if_requested()
        return self.mob_move

    def use_support_fleet(self, cancellation: CancellationSignal) -> bool:
        cancellation.raise_if_requested()
        return self.support_fleet

    def use_single_fleet_override(self, cancellation: CancellationSignal) -> bool | None:
        cancellation.raise_if_requested()
        return self.single_fleet_override


class _Map:
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
    MAP_CLEAR_ALL_THIS_TIME: bool = False
    MAP_HAS_MOVABLE_NORMAL_ENEMY: bool = False
    MAP_HAS_MOVABLE_ENEMY: bool = False
    POOR_MAP_DATA: bool = False
    fleet_2: int = 2
    fleet_boss: int = 2


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


class _VisualGrid:
    @staticmethod
    def predict_air_strike_icon() -> bool:
        return True

    @staticmethod
    def predict_mob_move_icon() -> bool:
        return True


class _Runtime:
    def __init__(self, grids: list[GridInfo] | None = None) -> None:
        self.events: list[object] = []
        self.map = _Map(grids or [_grid(A1), _grid(B1), _grid(C1), _grid(D1), _grid(E1), _grid(F1)])
        self.definition = _Definition()
        self.config = _Config()
        self.map_is_clear_mode = False
        self.battle_count = 0
        self.mystery_count = 3
        self.fleet_step = 2
        self.fleet_boss_index = 2
        self.fleet_current_index = 1
        self.fleet_1_location: tuple[int, int] = (0, 0)
        self.fleet_2_location: tuple[int, int] = (1, 0)
        self.battle_delta = 1
        self.raise_after_battle = False
        self.ammo_available = True
        self.mechanic_applied = True
        self.camera = (0, 0)
        self.device = _Device(cast("list[str]", self.events))
        self.view = _View(cast("list[str]", self.events))

    @property
    def fleet_current(self) -> tuple[int, int]:
        return self.fleet_1_location if self.fleet_current_index == 1 else self.fleet_2_location

    @property
    def fleet_1(self) -> _Runtime:
        self.fleet_current_index = 1
        return self

    @property
    def fleet_2(self) -> _Runtime:
        self.fleet_current_index = 2
        return self

    @property
    def fleet_boss(self) -> _Runtime:
        self.fleet_current_index = self.fleet_boss_index
        return self

    def _hostile(self) -> GridInfo | None:
        return next((grid for grid in self.map if grid.is_enemy or grid.is_siren or grid.is_boss), None)

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
        self.events.append(("clear_chosen_enemy", grid.location, expected, self.fleet_current_index))
        if self.fleet_current_index == 1:
            self.fleet_1_location = cast("tuple[int, int]", grid.location)
        else:
            self.fleet_2_location = cast("tuple[int, int]", grid.location)
        return self._settle(grid)

    def clear_enemy(self, **criteria: object) -> bool:
        self.events.append(("clear_enemy", criteria))
        return self._settle(next((grid for grid in self.map if grid.is_enemy and not grid.is_boss), None))

    def clear_any_enemy(self, **criteria: object) -> bool:
        self.events.append(("clear_any_enemy", criteria))
        return self._settle()

    def clear_siren(self, **criteria: object) -> bool:
        self.events.append(("clear_siren", criteria))
        return self._settle(next((grid for grid in self.map if grid.is_siren), None))

    def clear_filter_enemy(self, enemy_filter: str, preserve: int = 0) -> bool:
        self.events.append(("clear_filter_enemy", enemy_filter, preserve))
        enemies = [grid for grid in self.map if grid.is_enemy and not grid.is_boss]
        return self._settle(enemies[preserve] if len(enemies) > preserve else None)

    def brute_find_roadblocks(self, _grid: GridInfo, fleet: int | None = None) -> SelectedGrids[GridInfo]:
        self.events.append(("brute_find_roadblocks", fleet))
        return SelectedGrids([grid for grid in self.map if grid.is_enemy and not grid.is_boss])

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

    def fleet_at(self, grid: GridInfo, fleet: int | None = None) -> bool:
        index = self.fleet_current_index if fleet is None else fleet
        location = self.fleet_1_location if index == 1 else self.fleet_2_location
        return grid.location == location

    def check_accessibility(self, grid: GridInfo, fleet: int | str | None = None) -> bool:
        self.events.append(("check_accessibility", grid.location, fleet))
        return grid.is_accessible

    def fleet_ensure(self, index: int) -> bool:
        changed = index != self.fleet_current_index
        self.fleet_current_index = index
        self.events.append(("fleet_ensure", index))
        return changed

    def switch_to(self) -> None:
        self.events.append(("switch_to", self.fleet_current_index))

    def goto(self, grid: GridInfo, expected: str = "") -> None:
        self.events.append(("goto", grid.location, expected, self.fleet_current_index))
        if self.fleet_current_index == 1:
            self.fleet_1_location = cast("tuple[int, int]", grid.location)
        else:
            self.fleet_2_location = cast("tuple[int, int]", grid.location)
        if grid.is_enemy or grid.is_siren or grid.is_boss:
            self._settle(grid)

    def fleet_2_push_forward(self) -> bool:
        self.events.append("push_forward")
        return self.mechanic_applied

    def fleet_2_break_siren_caught(self) -> bool:
        self.events.append("break_siren_caught")
        if not self.mechanic_applied:
            return False
        self._settle(next((grid for grid in self.map if grid.is_siren), None))
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

    def pick_up_ammo(self) -> bool:
        self.events.append("pickup_ammo")
        return self.ammo_available

    def ensure_no_info_bar(self) -> bool:
        self.events.append("ensure_no_info_bar")
        return True

    def clear_all_mystery(self, **_criteria: object) -> bool:
        self.events.append("clear_all_mystery")
        for grid in self.map:
            grid.is_mystery = False
        return False

    def clear_chosen_mystery(self, grid: GridInfo) -> None:
        self.events.append(("clear_chosen_mystery", grid.location))
        grid.is_mystery = False

    def clear_mechanism(self, grids: object = None) -> bool:
        self.events.append(("clear_mechanism", grids))
        for grid in self.map:
            grid.is_mechanism_trigger = False
        return self.mechanic_applied

    def clear_bouncing_enemy(self) -> bool:
        self.events.append("clear_bouncing_enemy")
        return self._settle()

    def full_scan(self) -> None:
        self.events.append("full_scan")

    def find_path_initial(self) -> None:
        self.events.append("find_path_initial")

    def strategy_open(self) -> None:
        self.events.append("strategy_open")

    def strategy_close(self, *, skip_first_screenshot: bool = True) -> None:
        self.events.append(("strategy_close", skip_first_screenshot))

    @staticmethod
    def strategy_has_air_strike() -> bool:
        return True

    def strategy_air_strike_enter(self) -> None:
        self.events.append("air_strike_enter")

    @staticmethod
    def is_in_strategy_air_strike() -> bool:
        return True

    @staticmethod
    def strategy_has_mob_move() -> bool:
        return True

    def strategy_mob_move_enter(self) -> None:
        self.events.append("mob_move_enter")

    @staticmethod
    def is_in_strategy_mob_move() -> bool:
        return True

    def in_sight(self, grid: GridInfo) -> None:
        self.events.append(("in_sight", grid.location))

    @staticmethod
    def convert_global_to_local(_grid: GridInfo) -> _VisualGrid:
        return _VisualGrid()

    @staticmethod
    def appear(_button: object, **_criteria: object) -> bool:
        return True

    @staticmethod
    def handle_popup_confirm(_name: str) -> bool:
        return False


def _grid(  # noqa: PLR0913 - 测试网格显式暴露互斥识别事实。
    cell: CellId,
    *,
    enemy: bool = False,
    siren: bool = False,
    boss: bool = False,
    mystery: bool = False,
    land: bool = False,
) -> GridInfo:
    grid = GridInfo()
    grid.location = (cell.x, cell.y)
    grid.cost = cell.x + 1
    grid.cost_1 = grid.cost
    grid.cost_2 = grid.cost
    grid.weight = cell.x + 1
    grid.is_enemy = enemy
    grid.is_siren = siren
    grid.is_boss = boss
    grid.is_mystery = mystery
    grid.is_land = land
    grid.enemy_scale = 2 if enemy else 0
    grid.enemy_genre = "Light" if enemy else ""
    return grid


def _port(
    runtime: _Runtime,
    state: RuntimeProgramState | None = None,
) -> Mumu12BattleProgramPort:
    if state is None:
        state = _ProgramState()
    return Mumu12BattleProgramPort(cast("CampaignMapRuntime", runtime), state)


def _cancel() -> CancellationSignal:
    return cast("CancellationSignal", _Cancellation())


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
    state = _ProgramState(mob_move=True, support_fleet=True)
    port = _port(runtime, state)
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
    assert all(grid.may_siren for grid in runtime.map)
    port.set_map_weights(((6, 5, 4, 3, 2, 1),), cancellation)
    assert [grid.weight for grid in runtime.map] == [6, 5, 4, 3, 2, 1]


def test_stage_single_fleet_state_overrides_the_generic_fleet_count() -> None:
    runtime = _Runtime([_grid(A1)])
    runtime.config.fleet_2 = 0

    flags = _port(
        runtime,
        _ProgramState(single_fleet_override=False),
    ).initial_flags(_cancel())

    assert program_model.ProgramFlag.USE_SINGLE_FLEET not in flags


@pytest.mark.parametrize(
    ("action", "grids", "expected"),
    [
        (
            ClearSiren(),
            [_grid(A1, siren=True)],
            program_model.ProgramBattleSettled(program_model.ProgramBattleTarget.SIREN),
        ),
        (
            ClearFilteredEnemy(0),
            [_grid(A1, enemy=True)],
            program_model.ProgramBattleSettled(program_model.ProgramBattleTarget.ENEMY),
        ),
        (
            ClearEnemy(scales=(2,)),
            [_grid(A1, enemy=True)],
            program_model.ProgramBattleSettled(program_model.ProgramBattleTarget.ENEMY),
        ),
        (
            ClearAnyEnemy(),
            [_grid(A1, enemy=True)],
            program_model.ProgramBattleSettled(program_model.ProgramBattleTarget.ENEMY),
        ),
        (
            ClearChosenEnemy(A1, TargetExpectation.ENEMY),
            [_grid(A1, enemy=True)],
            program_model.ProgramBattleSettled(program_model.ProgramBattleTarget.ENEMY),
        ),
        (
            ClearSelectedEnemy((A1, B1), expected=TargetExpectation.SIREN),
            [_grid(A1, enemy=True, siren=True), _grid(B1)],
            program_model.ProgramBattleSettled(program_model.ProgramBattleTarget.SIREN),
        ),
        (
            ClearPriorityEnemy(),
            [_grid(A1, enemy=True)],
            program_model.ProgramBattleSettled(program_model.ProgramBattleTarget.ENEMY),
        ),
        (
            DefaultBattle(),
            [_grid(A1, enemy=True)],
            program_model.ProgramBattleSettled(program_model.ProgramBattleTarget.ENEMY),
        ),
        (
            ClearBossRoadblock(BossStrategy.MAP_SEARCH),
            [_grid(A1, enemy=True), _grid(B1, boss=True)],
            program_model.ProgramBattleSettled(
                program_model.ProgramBattleTarget.ENEMY,
                advances_wave=False,
            ),
        ),
        (
            ClearBoss(BossStrategy.BRUTE_FORCE),
            [_grid(A1, boss=True)],
            program_model.ProgramBattleSettled(program_model.ProgramBattleTarget.BOSS),
        ),
    ],
)
def test_every_battle_action_is_fact_closed(
    action: BattleStep,
    grids: list[GridInfo],
    expected: program_model.ProgramBattleSettled,
) -> None:
    runtime = _Runtime(grids)
    result = _port(runtime).execute_battle(action, _cancel())

    assert result == expected


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
    assert runtime.events == [("clear_chosen_enemy", (A1.x, A1.y), "boss", expected_fleet)]


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
    runtime = _Runtime([_grid(A1, enemy=True), boss])

    result = _port(runtime).execute_battle(ClearBoss(BossStrategy.BRUTE_FORCE), _cancel())

    assert result == program_model.ProgramNoTarget()
    assert runtime.battle_count == 0
    assert runtime.events == []


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
    tuple(RoadblockMode),
)
def test_all_roadblock_modes_are_explicit(mode: RoadblockMode) -> None:
    runtime = _Runtime([_grid(A1, enemy=True), _grid(B1)])
    action = RoadblockAction(
        0,
        mode,
        (RoadGroup((RoadPath((A1,)),)),),
        RoadblockSelection.STRONGEST,
    )

    result = _port(runtime).execute_mechanic(action, _cancel())

    assert result == MechanicSettled(program_model.ProgramBattleTarget.ENEMY)


def test_every_mechanic_action_has_a_fixed_projection() -> None:
    road = RoadGroup((RoadPath((A1,)),))

    runtime = _Runtime([_grid(A1, siren=True)])
    assert _port(runtime).execute_mechanic(
        BreakSirenCaught(0),
        _cancel(),
    ) == MechanicSettled(program_model.ProgramBattleTarget.SIREN)

    runtime = _Runtime()
    assert isinstance(_port(runtime).execute_mechanic(PushFleetForward(0), _cancel()), MechanicApplied)
    assert isinstance(_port(runtime).execute_mechanic(ProtectFleet(0), _cancel()), MechanicApplied)
    assert isinstance(_port(runtime).execute_mechanic(RescueFleet(0, A1), _cancel()), MechanicApplied)
    assert isinstance(
        _port(runtime).execute_mechanic(StepFleetOn(0, (C1,), (road,)), _cancel()),
        MechanicApplied,
    )

    runtime = _Runtime()
    assert isinstance(
        _port(runtime).execute_mechanic(MoveFleet(0, C1, FleetRole.ACTIVE), _cancel()),
        MechanicApplied,
    )
    runtime = _Runtime()
    runtime.map[B1.x, B1.y].weight = 5
    runtime.map[B1.x, B1.y].cost = 2
    runtime.map[C1.x, C1.y].weight = 5
    runtime.map[C1.x, C1.y].cost = 1
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
    assert ("goto", (C1.x, C1.y), "", 2) in runtime.events
    runtime = _Runtime()
    assert isinstance(
        _port(runtime).execute_mechanic(SwitchFleet(0, FleetRole.FLEET_2), _cancel()),
        MechanicApplied,
    )
    runtime = _Runtime()
    assert isinstance(
        _port(runtime).execute_mechanic(EnsureFleet(0, FleetRole.NON_BOSS), _cancel()),
        MechanicNotApplied,
    )
    runtime = _Runtime()
    assert isinstance(
        _port(runtime).execute_mechanic(EnsureFleetAt(0, A1, FleetRole.FLEET_1), _cancel()),
        MechanicApplied,
    )

    runtime = _Runtime([_grid(A1, enemy=True)])
    assert _port(runtime).execute_mechanic(
        FleetClearTarget(0, A1, FleetRole.ACTIVE, EncounterExpectation.ENEMY),
        _cancel(),
    ) == MechanicSettled(program_model.ProgramBattleTarget.ENEMY)
    runtime = _Runtime()
    assert isinstance(_port(runtime).execute_mechanic(PickupAmmo(0), _cancel()), MechanicApplied)
    runtime = _Runtime()
    assert isinstance(
        _port(runtime).execute_mechanic(PickupMapItem(0, MapItemKind.FLARE, C1), _cancel()),
        MechanicApplied,
    )

    runtime = _Runtime([_grid(A1, mystery=True)])
    assert isinstance(
        _port(runtime).execute_mechanic(ClearAllMystery(0, nearby=False), _cancel()),
        MechanicApplied,
    )
    runtime = _Runtime([_grid(A1, mystery=True)])
    assert isinstance(
        _port(runtime).execute_mechanic(ClearChosenMystery(0, A1), _cancel()),
        MechanicApplied,
    )
    runtime = _Runtime()
    runtime.map[A1.x, A1.y].is_mechanism_trigger = True
    assert isinstance(
        _port(runtime).execute_mechanic(ClearMechanism(0, (A1,)), _cancel()),
        MechanicApplied,
    )
    runtime = _Runtime()
    assert isinstance(
        _port(runtime).execute_mechanic(ClearMapItems(0, (C1, D1)), _cancel()),
        MechanicApplied,
    )
    runtime = _Runtime()
    assert isinstance(_port(runtime).execute_mechanic(AirStrike(0, C1), _cancel()), MechanicApplied)

    runtime = _Runtime([_grid(A1, enemy=True), _grid(B1)])
    assert isinstance(
        _port(runtime).execute_mechanic(MoveEnemy(0, A1, B1), _cancel()),
        MechanicApplied,
    )
    assert not runtime.map[A1.x, A1.y].is_enemy
    assert runtime.map[B1.x, B1.y].is_enemy

    runtime = _Runtime([_grid(A1, enemy=True)])
    result = _port(runtime).execute_mechanic(
        MechanicProcedure(0, (MechanicOperation.CLEAR_BOUNCING_ENEMY,)),
        _cancel(),
    )
    assert result == MechanicSettled(program_model.ProgramBattleTarget.ENEMY)


def test_break_siren_caught_rejects_unconfirmed_success() -> None:
    runtime = _Runtime([_grid(A1, siren=True)])
    runtime.battle_delta = 0

    result = _port(runtime).execute_mechanic(BreakSirenCaught(0), _cancel())

    assert isinstance(result, MechanicFailed)
    assert "without advancing battle_count" in result.evidence


def test_preset_route_and_fixed_target_are_fact_closed() -> None:
    runtime = _Runtime(
        [
            _grid(A1),
            _grid(B1),
            _grid(C1),
            _grid(D1),
            _grid(E1),
            _grid(F1, enemy=True),
        ]
    )
    runtime.fleet_1_location = (4, 0)
    route = PresetRouteVariant(
        4,
        (
            PresetRouteBattle(
                0,
                (PresetRouteStep(FleetRole.FLEET_1, 1, 0, clear_enemy=True),),
            ),
        ),
    )
    route_result = _port(runtime).execute_preset_route(
        program_model.ExecutePresetRoute(0, (route,), ()),
        _cancel(),
    )
    assert route_result == MechanicSettled(program_model.ProgramBattleTarget.ENEMY)

    runtime = _Runtime([_grid(A1), _grid(B1, siren=True)])
    fixed_result = _port(runtime).execute_fixed_target(
        program_model.ExecuteFixedTarget(
            0,
            (FixedTargetSequence((0,), (B1,), FleetRole.FLEET_1),),
        ),
        _cancel(),
    )
    assert fixed_result == MechanicSettled(program_model.ProgramBattleTarget.SIREN)


def test_missing_or_ambiguous_runtime_primitives_fail_typed() -> None:
    runtime = _Runtime()
    port = _port(runtime)
    with pytest.raises(BattleProgramMumu12AdapterError, match="only has a fleet_2 primitive"):
        port.execute_mechanic(PushFleetForward(0, FleetRole.FLEET_1), _cancel())
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
    cancellation = cast("CancellationSignal", _Cancellation(requested=True))

    with pytest.raises(RequestedCancellation):
        _port(runtime).execute_battle(ClearChosenEnemy(A1), cancellation)

    assert runtime.events == []
