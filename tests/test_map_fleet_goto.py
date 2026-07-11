from typing import TYPE_CHECKING, override

from module.exception import MapWalkError
from module.map.fleet import Fleet

if TYPE_CHECKING:
    from collections.abc import Iterator

    from module.map.type_alias import GridLocation
    from module.map_detection.grid_info import GridInfo

type _Node = GridLocation


class _Config:
    MAP_HAS_FLEET_STEP = False
    MAP_HAS_PORTAL = False
    MAP_HAS_MAZE = False
    MAP_HAS_AMBUSH = False


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


class _Map:
    def __init__(self) -> None:
        self.path_results: dict[tuple[GridLocation, int, bool], list[GridLocation]] = {}
        self.find_path_calls: list[tuple[GridLocation, int, bool]] = []
        self.cells: dict[GridLocation, _Cell] = {}

    def find_path(self, location: GridLocation, *, step: int, turning_optimize: bool) -> list[GridLocation]:
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


class _Fleet(Fleet):
    config: _Config
    map: _Map

    def __init__(self) -> None:
        self.config = _Config()
        self.map = _Map()
        self.calls: list[tuple[str, GridInfo | str | GridLocation, str] | tuple[str]] = []
        self.maze_nodes: set[GridLocation] = set()
        self.fail_once: set[GridInfo | str | GridLocation] = set()

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
    def maze_active_on(self, grid: GridInfo | str | GridLocation) -> bool:
        return grid in self.maze_nodes

    @override
    def predict(self) -> None:
        self.calls.append(("predict",))

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
    fleet.maze_nodes = {maze}
    fleet.map.path_results[((4, 5), 3, False)] = [maze]

    fleet.goto((4, 5))

    assert fleet.calls == [("_goto", (0, 1), "")] * 10 + [("_goto", maze, "")]


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
