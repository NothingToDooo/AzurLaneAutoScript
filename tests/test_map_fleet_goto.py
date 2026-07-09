from module.exception import MapWalkError
from module.map.fleet import Fleet


class _Config:
    MAP_HAS_FLEET_STEP = False
    MAP_HAS_PORTAL = False
    MAP_HAS_MAZE = False
    MAP_HAS_AMBUSH = False


class _GridList:
    def __init__(self, items: list[object], *, non_enemy: object = True) -> None:
        self.items = items
        self.non_enemy = non_enemy

    def __iter__(self):
        return iter(self.items)

    def __len__(self) -> int:
        return len(self.items)

    def __getitem__(self, index: int) -> object:
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
        self.maze_nearby = _GridList(["bounce"])


class _Map:
    def __init__(self) -> None:
        self.path_results: dict[tuple[object, int, object], list[object]] = {}
        self.find_path_calls: list[tuple[object, int, object]] = []
        self.cells: dict[object, _Cell] = {}

    def find_path(self, location: object, *, step: int, turning_optimize: object) -> list[object]:
        call = (location, step, turning_optimize)
        self.find_path_calls.append(call)
        return self.path_results[call]

    def select(self, **kwargs: object) -> _GridList:
        if kwargs == {"is_fleet": True}:
            return _GridList(["fleet"])
        return _GridList([])

    def __getitem__(self, location: object) -> _Cell:
        if location not in self.cells:
            self.cells[location] = _Cell()
        return self.cells[location]


class _Fleet(Fleet):
    config: _Config
    map: _Map

    def __init__(self) -> None:
        self.config = _Config()
        self.map = _Map()
        self.calls: list[tuple[object, ...]] = []
        self.maze_nodes: set[object] = set()
        self.fail_once: set[object] = set()

    @property
    def fleet_step(self) -> int:
        return 3

    def _goto(self, location: object, expected: str = "") -> None:
        self.calls.append(("_goto", location, expected))
        if location in self.fail_once:
            self.fail_once.remove(location)
            message = "walk_out_of_step"
            raise MapWalkError(message)

    def maze_active_on(self, grid: object) -> bool:
        return grid in self.maze_nodes

    def predict(self) -> None:
        self.calls.append(("predict",))

    def ensure_edge_insight(self, *_args: object, **_kwargs: object) -> None:
        self.calls.append(("ensure_edge_insight",))


def test_goto_walks_directly_without_optimizations() -> None:
    fleet = _Fleet()

    fleet.goto((1, 2), expected="combat", step_optimize=False, turning_optimize=False)

    assert fleet.calls == [("_goto", (1, 2), "combat")]
    assert fleet.map.find_path_calls == []


def test_goto_uses_fleet_step_when_portal_forces_step_optimization() -> None:
    fleet = _Fleet()
    fleet.config.MAP_HAS_PORTAL = True
    fleet.map.path_results[((2, 3), 3, False)] = ["node"]

    fleet.goto((2, 3), expected="combat")

    assert fleet.map.find_path_calls == [((2, 3), 3, False)]
    assert fleet.calls == [("_goto", "node", "combat")]


def test_goto_passes_expected_only_to_final_path_node() -> None:
    fleet = _Fleet()
    fleet.config.MAP_HAS_AMBUSH = True
    fleet.map.path_results[((3, 4), 0, True)] = ["first", "final"]

    fleet.goto((3, 4), expected="combat")

    assert fleet.calls == [("_goto", "first", ""), ("_goto", "final", "combat")]


def test_goto_waits_on_active_maze_before_walking_node() -> None:
    fleet = _Fleet()
    maze = (1, 1)
    fleet.config.MAP_HAS_MAZE = True
    fleet.maze_nodes = {maze}
    fleet.map.path_results[((4, 5), 3, False)] = [maze]

    fleet.goto((4, 5))

    assert fleet.calls == [("_goto", "bounce", "")] * 10 + [("_goto", maze, "")]


def test_goto_retries_from_failed_node_after_walk_error() -> None:
    fleet = _Fleet()
    fleet.config.MAP_HAS_AMBUSH = True
    fleet.fail_once = {"final"}
    fleet.map.path_results[((5, 6), 0, True)] = ["final"]
    fleet.map.path_results[("final", 1, False)] = ["retry_a", "retry_b"]

    fleet.goto((5, 6), expected="combat")

    assert fleet.calls == [
        ("_goto", "final", "combat"),
        ("predict",),
        ("ensure_edge_insight",),
        ("_goto", "retry_a", "combat"),
        ("_goto", "retry_b", "combat"),
    ]
