from contextlib import AbstractContextManager
from typing import TypeVar

from module.os.map import OSMap

_T = TypeVar("_T")

_EVENT_FLAGS = (
    "is_exploration_reward",
    "is_akashi",
    "is_scanning_device",
    "is_logging_tower",
    "is_fleet_mechanism",
)


class _TemporaryConfig(AbstractContextManager[None]):
    def __init__(self, owner: _Config, kwargs: dict[str, object]) -> None:
        self.owner = owner
        self.kwargs = kwargs

    def __enter__(self) -> None:
        self.owner.temporary_entries.append(self.kwargs)

    def __exit__(self, *_exc_info: object) -> None:
        return None


class _Config:
    def __init__(self) -> None:
        self.temporary_entries: list[dict[str, object]] = []

    def temporary(self, **kwargs: object) -> _TemporaryConfig:
        return _TemporaryConfig(self, kwargs)


class _Grid:
    def __init__(self, event: str) -> None:
        self.event = event
        for flag in _EVENT_FLAGS:
            setattr(self, flag, False)
        setattr(self, event, True)

    def __repr__(self) -> str:
        return f"_Grid({self.event})"


class _FleetLocation:
    def __init__(self, distance: int) -> None:
        self.distance = distance

    def distance_to(self, _grid: _Grid) -> int:
        return self.distance

    def __repr__(self) -> str:
        return f"_FleetLocation({self.distance})"


class _Device:
    def __init__(self) -> None:
        self.clicks: list[object] = []

    def click(self, target: object) -> None:
        self.clicks.append(target)


class _View:
    def __init__(self, owner: _MapRescan) -> None:
        self.owner = owner

    def select(self, **kwargs: object) -> list[_Grid]:
        self.owner.calls.append(("select", kwargs))
        for flag, enabled in kwargs.items():
            if enabled:
                return self.owner.grids.get(flag, [])
        return []


class _MapRescan(OSMap):
    config: _Config
    device: _Device
    view: _View

    def __init__(self) -> None:
        self.config = _Config()
        self.device = _Device()
        self.view = _View(self)
        self.calls: list[tuple[object, ...]] = []
        self.grids: dict[str, list[_Grid]] = {}
        self.wait_results: list[str] = []
        self.fleet_distance = 0
        self.in_cl1_leveling = False
        self.in_task_explore = False
        self._solved_map_event: set[str] = set()
        self._solved_fleet_mechanism = False

    @staticmethod
    def _next_result(results: list[_T], *, default: _T) -> _T:
        if results:
            return results.pop(0)
        return default

    def add_grid(self, event: str) -> _Grid:
        grid = _Grid(event)
        self.grids[event] = [grid]
        return grid

    @property
    def is_in_task_cl1_leveling(self) -> bool:
        return self.in_cl1_leveling

    @property
    def is_in_task_explore(self) -> bool:
        return self.in_task_explore

    def has_solved(self, event: str) -> bool:
        return event in self._solved_map_event

    def mark_fleet_mechanism_partly_solved(self) -> None:
        self._solved_fleet_mechanism = True

    def wait_until_walk_stable(self, *_args: object, **kwargs: object) -> str:
        self.calls.append(("wait_until_walk_stable", kwargs))
        return self._next_result(self.wait_results, default="")

    def convert_radar_to_local(self, location: tuple[int, int]) -> _FleetLocation:
        self.calls.append(("convert_radar_to_local", location))
        return _FleetLocation(self.fleet_distance)

    def handle_akashi_supply_buy(self, grid: _Grid) -> None:
        self.calls.append(("handle_akashi_supply_buy", grid))

    def os_auto_search_run(self, *_args: object, **_kwargs: object) -> int:
        self.calls.append(("os_auto_search_run",))
        return 0


def assert_solved(runner: _MapRescan, event: str) -> None:
    assert runner.has_solved(event)


def test_map_rescan_current_handles_exploration_reward() -> None:
    runner = _MapRescan()
    runner.add_grid("is_exploration_reward")
    runner.wait_results = ["event"]

    assert runner.map_rescan_current() is True
    assert_solved(runner, "is_exploration_reward")


def test_map_rescan_current_walks_to_far_akashi() -> None:
    runner = _MapRescan()
    grid = runner.add_grid("is_akashi")
    runner.fleet_distance = 2
    runner.wait_results = ["akashi"]

    assert runner.map_rescan_current() is True
    assert runner.device.clicks == [grid]
    assert runner.config.temporary_entries == [{"STORY_ALLOW_SKIP": False}]
    assert_solved(runner, "is_akashi")


def test_map_rescan_current_buys_near_akashi_supply() -> None:
    runner = _MapRescan()
    grid = runner.add_grid("is_akashi")
    runner.fleet_distance = 1

    assert runner.map_rescan_current() is True
    assert runner.device.clicks == []
    assert ("handle_akashi_supply_buy", grid) in runner.calls
    assert_solved(runner, "is_akashi")


def test_map_rescan_current_marks_scanning_device_solved_in_cl1() -> None:
    runner = _MapRescan()
    runner.add_grid("is_scanning_device")
    runner.in_cl1_leveling = True

    assert runner.map_rescan_current() is True
    assert runner.device.clicks == []
    assert ("os_auto_search_run",) not in runner.calls
    assert_solved(runner, "is_scanning_device")


def test_map_rescan_current_finishes_second_fleet_mechanism() -> None:
    runner = _MapRescan()
    runner.add_grid("is_fleet_mechanism")
    runner.in_task_explore = True
    runner.mark_fleet_mechanism_partly_solved()

    assert runner.map_rescan_current() is True
    assert ("os_auto_search_run",) in runner.calls
    assert_solved(runner, "is_fleet_mechanism")


def test_map_rescan_current_returns_false_without_event() -> None:
    runner = _MapRescan()

    assert runner.map_rescan_current() is False
