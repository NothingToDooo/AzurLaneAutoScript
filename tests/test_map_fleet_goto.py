from types import SimpleNamespace
from typing import TYPE_CHECKING, cast, override

import pytest

from module.exception import MapEnemyMoved, MapWalkError
from module.map.fleet import Fleet
from module.map.fleet_turn import FleetTurnEvent
from module.map.map_observer import STANDARD_CAMPAIGN_MAP_OBSERVER, CampaignMapObserver
from module.map.map_scanner import MapScanRequest, MovableEnemySnapshot, MovableScanRequest

if TYPE_CHECKING:
    from collections.abc import Iterator
    from typing import Any

    from module.map.fleet_turn import FleetTurnController
    from module.map.type_alias import GridLocation
    from module.map_detection.grid_info import GridInfo

type _Node = GridLocation


class _Config:
    MAP_HAS_FLEET_STEP = False
    MAP_HAS_PORTAL = False
    MAP_HAS_MAZE = False
    MAP_HAS_AMBUSH = False
    MAP_HAS_DECOY_ENEMY = False
    MAP_HAS_MOVABLE_ENEMY = True
    MAP_HAS_MOVABLE_NORMAL_ENEMY = False
    MAP_ENEMY_TEMPLATE: tuple[str, ...] = ()
    MAP_HAS_WALL = False
    MOVABLE_ENEMY_FLEET_STEP = 2


class _GridList:
    def __init__(self, items: list[_Node], *, non_enemy: bool = True) -> None:
        self.items = items
        self.non_enemy = non_enemy

    def __iter__(self) -> Iterator[_Node]:
        return iter(self.items)

    def __len__(self) -> int:
        return len(self.items)

    def __getitem__(self, index: int) -> _Node:
        return self.items[index]

    def delete(self, _other: object) -> _GridList:
        return self

    def select(self, **kwargs: object) -> _GridList:
        if kwargs == {"is_enemy": False} and self.non_enemy:
            return self
        return _GridList([])

    def sort(self, _key: str, *_args: object, **_kwargs: object) -> _GridList:
        return self


class _Cell:
    def __init__(self) -> None:
        self.maze_nearby = _GridList([(0, 1)])
        self.is_fleet = False

    def wipe_out(self) -> None:
        pass


class _Map:
    def __init__(self) -> None:
        self.layout = self
        self.path_results: dict[tuple[GridLocation, int, bool], list[GridLocation]] = {}
        self.find_path_calls: list[tuple[GridLocation, int, bool]] = []
        self.cells: dict[GridLocation, _Cell] = {}
        self.pathfinder = self

    def route(self, location: GridLocation, *, step: int, turning_optimize: bool) -> list[GridLocation]:
        call = (location, step, turning_optimize)
        self.find_path_calls.append(call)
        return self.path_results[call]

    @staticmethod
    def select(**kwargs: object) -> _GridList:
        if kwargs == {"is_fleet": True}:
            return _GridList([(99, 99)])
        return _GridList([])

    def __getitem__(self, location: GridLocation) -> _Cell:
        if location not in self.cells:
            self.cells[location] = _Cell()
        return self.cells[location]


class _TurnController:
    movement_wait = 0.0

    def __init__(self, trace: list[object]) -> None:
        self.trace = trace
        self.maze_nodes: set[GridLocation] = set()
        self.event = FleetTurnEvent.STABLE

    def battle_resolved(self, battle_count: int) -> None:
        self.trace.append(("battle_resolved", battle_count))

    def fleet_arrived(self) -> FleetTurnEvent:
        self.trace.append(("fleet_arrived",))
        return self.event

    def maze_active_on(self, location: GridLocation) -> bool:
        return location in self.maze_nodes


class _RecordingScanner:
    @staticmethod
    def full_scan(runtime: object, request: MapScanRequest) -> None:
        del runtime, request

    @staticmethod
    def full_scan_movable(runtime: object, request: MovableScanRequest) -> None:
        cast("_Fleet", runtime).calls.append(("full_scan_movable", request.enemy_cleared))


class _Fleet(Fleet):
    config: _Config
    map: _Map

    def __init__(self) -> None:
        self.config = _Config()
        self.map = _Map()
        self.calls: list[object] = []
        self.turns = _TurnController(self.calls)
        self._turn_controller = cast("FleetTurnController", self.turns)
        self._map_observer = CampaignMapObserver(
            combat=STANDARD_CAMPAIGN_MAP_OBSERVER.combat,
            scanner=cast("Any", _RecordingScanner()),
            enemy_searching=STANDARD_CAMPAIGN_MAP_OBSERVER.enemy_searching,
            viewport=STANDARD_CAMPAIGN_MAP_OBSERVER.viewport,
            fleet_locator=STANDARD_CAMPAIGN_MAP_OBSERVER.fleet_locator,
            preparation=STANDARD_CAMPAIGN_MAP_OBSERVER.preparation,
        )
        self.fail_once: set[GridInfo | str | GridLocation] = set()
        self.predict_error: BaseException | None = None
        self.fleet_current_index = 1
        self.fleet_1_location = (0, 0)
        self.battle_count = 1

    @property
    def fleet_step(self) -> int:
        return 3

    @override
    def _goto(self, location: GridInfo | str | GridLocation, expected: str = "") -> None:
        self.calls.append(("_goto", location, expected))
        if location in self.fail_once:
            self.fail_once.remove(location)
            message = "walk_out_of_step"
            raise MapWalkError(message)

    @override
    def predict(self) -> None:
        self.calls.append(("predict",))
        if self.predict_error is not None:
            raise self.predict_error

    @override
    def find_path_initial(self) -> None:
        self.calls.append(("find_path_initial",))

    @override
    def ensure_edge_insight(
        self,
        *,
        reverse: bool = False,
        preset: GridLocation | None = None,
        swipe_limit: GridLocation = (3, 2),
        skip_first_update: bool = True,
    ) -> list[GridLocation]:
        del reverse, preset, swipe_limit, skip_first_update
        self.calls.append(("ensure_edge_insight",))
        return []


def test_goto_walks_directly_without_optimizations() -> None:
    fleet = _Fleet()

    fleet.goto((1, 2), expected="combat", step_optimize=False, turning_optimize=False)

    assert fleet.calls == [("_goto", (1, 2), "combat")]
    assert fleet.map.find_path_calls == []


def test_goto_uses_fleet_step_when_portal_forces_step_optimization() -> None:
    fleet = _Fleet()
    fleet.config.MAP_HAS_PORTAL = True
    node = (2, 2)
    fleet.map.path_results[((2, 3), 3, False)] = [node]

    fleet.goto((2, 3), expected="combat")

    assert fleet.map.find_path_calls == [((2, 3), 3, False)]
    assert fleet.calls == [("_goto", node, "combat")]


def test_goto_passes_expected_only_to_final_path_node() -> None:
    fleet = _Fleet()
    fleet.config.MAP_HAS_AMBUSH = True
    first = (3, 3)
    final = (3, 4)
    fleet.map.path_results[((3, 4), 0, True)] = [first, final]

    fleet.goto((3, 4), expected="combat")

    assert fleet.calls == [("_goto", first, ""), ("_goto", final, "combat")]


def test_goto_waits_on_active_maze_before_walking_node() -> None:
    fleet = _Fleet()
    maze = (1, 1)
    fleet.config.MAP_HAS_MAZE = True
    fleet.turns.maze_nodes = {maze}
    fleet.map.path_results[((4, 5), 3, False)] = [maze]

    fleet.goto((4, 5))

    assert fleet.calls == [("_goto", (0, 1), "")] * 10 + [("_goto", maze, "")]


def test_goto_finish_keeps_battle_prediction_before_turn_advance() -> None:
    fleet = _Fleet()
    prediction_error = RuntimeError("prediction failed")
    fleet.predict_error = prediction_error
    state = cast(
        "Any",
        SimpleNamespace(
            location=(1, 0),
            result="combat",
            result_mystery="",
            expected="combat",
            movable_snapshot=MovableEnemySnapshot(),
        ),
    )

    with pytest.raises(RuntimeError) as raised:
        fleet._goto_finish(state)  # ruff:ignore[private-member-access] - 验证轮次提交与预测的真实顺序。

    assert raised.value is prediction_error
    assert fleet.calls == [("battle_resolved", 1), ("predict",)]


def test_goto_finish_handles_enemy_turn_after_battle_prediction() -> None:
    fleet = _Fleet()
    fleet.turns.event = FleetTurnEvent.ENEMY_MOVED
    state = cast(
        "Any",
        SimpleNamespace(
            location=(1, 0),
            result="combat",
            result_mystery="",
            expected="combat",
            movable_snapshot=MovableEnemySnapshot(),
        ),
    )

    with pytest.raises(MapEnemyMoved):
        fleet._goto_finish(state)  # ruff:ignore[private-member-access] - 验证轮次事件驱动真实扫描顺序。

    assert fleet.calls == [
        ("battle_resolved", 1),
        ("predict",),
        ("fleet_arrived",),
        ("full_scan_movable", True),
        ("find_path_initial",),
    ]


def test_goto_retries_from_failed_node_after_walk_error() -> None:
    fleet = _Fleet()
    fleet.config.MAP_HAS_AMBUSH = True
    final = (5, 6)
    retry_a = (5, 5)
    retry_b = (4, 5)
    fleet.fail_once = {final}
    fleet.map.path_results[((5, 6), 0, True)] = [final]
    fleet.map.path_results[(final, 1, False)] = [retry_a, retry_b]

    fleet.goto((5, 6), expected="combat")

    assert fleet.calls == [
        ("_goto", final, "combat"),
        ("predict",),
        ("ensure_edge_insight",),
        ("_goto", retry_a, "combat"),
        ("_goto", retry_b, "combat"),
    ]
