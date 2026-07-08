from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from module.commission import commission as commission_module
from module.commission.commission import RewardCommission
from module.commission.preset import SHORTEST_FILTER
from module.map.map_grids import SelectedGrids

if TYPE_CHECKING:
    from collections.abc import Callable


class _Config:
    Commission_PresetFilter = "custom"
    Commission_CustomFilter = "custom-filter"
    Commission_DoMajorCommission = True


class _Commission:
    def __init__(self, name: str, *, genre: str = "daily", status: str = "pending") -> None:
        self.name = name
        self.genre = genre
        self.status = status
        self.valid = True
        self.category_str = "minor"

    def __eq__(self, other: object) -> bool:
        return isinstance(other, _Commission) and self.name == other.name

    def __hash__(self) -> int:
        return hash(self.name)

    def __str__(self) -> str:
        return self.name


class _Filter:
    def __init__(self, results: list[list[object]]) -> None:
        self.results = results
        self.loads: list[str] = []

    def load(self, string: str) -> None:
        self.loads.append(string)

    def apply(self, grids: list[object], *, func: Callable[[object], bool]) -> list[object]:
        if self.results:
            return self.results.pop(0)
        return [grid for grid in grids if func(grid)]


class _CommissionUI(RewardCommission):
    def __init__(self) -> None:
        self.config = _Config()

    def choose(self, daily: SelectedGrids, urgent: SelectedGrids):
        return self._commission_choose(daily, urgent)


@pytest.fixture
def ui() -> _CommissionUI:
    return _CommissionUI()


def test_commission_choose_splits_custom_filter_results(monkeypatch: pytest.MonkeyPatch, ui: _CommissionUI) -> None:
    daily_a = _Commission("daily-a")
    daily_b = _Commission("daily-b")
    daily_c = _Commission("daily-c")
    urgent = _Commission("urgent")
    fake_filter = _Filter([[urgent, daily_a, daily_b, daily_c]])
    monkeypatch.setattr(commission_module, "COMMISSION_FILTER", fake_filter)

    daily_choose, urgent_choose = ui.choose(
        SelectedGrids([daily_a, daily_b, daily_c]),
        SelectedGrids([urgent]),
    )

    assert list(daily_choose) == [daily_a, daily_b, daily_c]
    assert list(urgent_choose) == [urgent]
    assert fake_filter.loads == ["custom-filter"]


def test_commission_choose_adds_shortest_daily_when_not_enough(
    monkeypatch: pytest.MonkeyPatch, ui: _CommissionUI
) -> None:
    daily = _Commission("daily")
    fake_filter = _Filter([["shortest"], [daily]])
    monkeypatch.setattr(commission_module, "COMMISSION_FILTER", fake_filter)

    daily_choose, urgent_choose = ui.choose(SelectedGrids([daily]), SelectedGrids([]))

    assert list(daily_choose) == [daily]
    assert list(urgent_choose) == []
    assert fake_filter.loads == ["custom-filter", SHORTEST_FILTER]
