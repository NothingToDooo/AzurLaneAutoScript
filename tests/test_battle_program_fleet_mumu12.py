from dataclasses import dataclass

import pytest

from module.adapters.battle_program_fleet_mumu12 import Mumu12FleetActionDriver
from module.adapters.battle_program_mumu12_contracts import BattleProgramMumu12AdapterError
from module.content.cell import CellId
from module.content.mechanic_rules import EncounterExpectation
from module.map_detection.grid_info import GridInfo

A1 = CellId(0, 0)


class _Cancellation:
    @staticmethod
    def raise_if_requested() -> None:
        pass


@dataclass(frozen=True, slots=True)
class _NavigationSnapshot:
    fleet_1: tuple[int, int] | tuple[()]
    fleet_2: tuple[int, int] | tuple[()]
    current_index: int


class _Navigation:
    def __init__(self, runtime: _Runtime) -> None:
        self._runtime = runtime
        self.fleet_1: tuple[int, int] | tuple[()] = (1, 0)
        self.fleet_2: tuple[int, int] | tuple[()] = (2, 0)
        self.current_index = 1

    @property
    def snapshot(self) -> _NavigationSnapshot:
        return _NavigationSnapshot(self.fleet_1, self.fleet_2, self.current_index)

    def activate(self, index: int) -> bool:
        changed = self.current_index != index
        self.current_index = index
        return changed

    def goto(self, _grid: GridInfo, expected: str = "") -> None:
        self._runtime.events.append(("move", expected))
        location = self._runtime.goto_locations.pop(0) if self._runtime.goto_locations else (0, 0)
        if self.current_index == 1:
            self.fleet_1 = location
        else:
            self.fleet_2 = location


class _Runtime:
    def __init__(self) -> None:
        self.map = {(0, 0): GridInfo()}
        self.goto_locations: list[tuple[int, int]] = []
        self.events: list[tuple[str, object]] = []
        self.navigation = _Navigation(self)

    def clear_chosen_enemy(self, _grid: GridInfo, expected: str = "") -> bool:
        self.events.append(("clear", expected))
        return True

    def pick_up_ammo(self, _grid: GridInfo) -> bool:
        self.events.append(("pickup_ammo", None))
        return True

    def ensure_no_info_bar(self) -> bool:
        self.events.append(("ensure_no_info_bar", None))
        return True

    def clear_chosen_mystery(self, _grid: GridInfo) -> None:
        self.events.append(("clear_mystery", None))


def test_fortress_clear_uses_the_runtime_fortress_expectation() -> None:
    runtime = _Runtime()
    driver = Mumu12FleetActionDriver(runtime)

    applied = driver.clear_target(
        1,
        A1,
        EncounterExpectation.FORTRESS,
        _Cancellation(),
    )

    assert applied
    assert runtime.events == [("clear", "fortress")]


def test_fortress_move_uses_the_runtime_combat_fortress_expectation() -> None:
    runtime = _Runtime()
    driver = Mumu12FleetActionDriver(runtime)

    moved = driver.move(
        1,
        A1,
        EncounterExpectation.FORTRESS,
        _Cancellation(),
    )

    assert moved
    assert runtime.events == [("move", "combat_fortress")]


def test_move_is_idempotent_when_the_fleet_is_already_at_destination() -> None:
    runtime = _Runtime()
    runtime.navigation.fleet_1 = (A1.x, A1.y)
    driver = Mumu12FleetActionDriver(runtime)

    moved = driver.move(
        1,
        A1,
        EncounterExpectation.ANY,
        _Cancellation(),
    )

    assert not moved
    assert runtime.events == []


def test_move_retries_an_unchanged_origin_up_to_three_times() -> None:
    runtime = _Runtime()
    runtime.goto_locations = [(1, 0), (1, 0), (A1.x, A1.y)]
    driver = Mumu12FleetActionDriver(runtime)

    moved = driver.move(
        1,
        A1,
        EncounterExpectation.ANY,
        _Cancellation(),
    )

    assert moved
    assert runtime.events == [("move", "")] * 3


def test_move_rejects_arrival_at_an_unexpected_cell() -> None:
    runtime = _Runtime()
    runtime.goto_locations = [(9, 9)]
    driver = Mumu12FleetActionDriver(runtime)

    with pytest.raises(BattleProgramMumu12AdapterError, match="unexpected cell"):
        driver.move(
            1,
            A1,
            EncounterExpectation.ANY,
            _Cancellation(),
        )

    assert runtime.events == [("move", "")]


def test_move_rejects_three_attempts_that_leave_the_fleet_at_origin() -> None:
    runtime = _Runtime()
    runtime.goto_locations = [(1, 0)] * 3
    driver = Mumu12FleetActionDriver(runtime)

    with pytest.raises(BattleProgramMumu12AdapterError, match="after 3 attempts"):
        driver.move(
            1,
            A1,
            EncounterExpectation.ANY,
            _Cancellation(),
        )

    assert runtime.events == [("move", "")] * 3
