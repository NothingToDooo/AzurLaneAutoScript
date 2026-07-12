from __future__ import annotations

from typing import TYPE_CHECKING

from module.base.utils import SwipePathOptions, random_rectangle_vector_opted

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable

    import pytest

    from module.base.type_alias import Area, Point


def _fixed_points(points: Iterable[Point]) -> Callable[[Area, int], Point]:
    point_iter = iter(points)

    def random_point(_area: Area, _n: int = 3) -> Point:
        return next(point_iter)

    return random_point


def test_random_rectangle_vector_uses_random_end_point(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("module.base.utils.random_rectangle_point", _fixed_points([(0, 0), (80, 50)]))

    assert random_rectangle_vector_opted((10, 0), SwipePathOptions(box=(0, 0, 100, 100), padding=0)) == (
        (70, 50),
        (80, 50),
    )


def test_random_rectangle_vector_prefers_whitelist_end_point(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("module.base.utils.random_rectangle_point", _fixed_points([(0, 0), (20, 30)]))

    assert random_rectangle_vector_opted(
        (10, 0),
        SwipePathOptions(box=(0, 0, 100, 100), padding=0, whitelist_area=[(10, 10, 30, 40)]),
    ) == ((10, 30), (20, 30))


def test_random_rectangle_vector_retries_blacklisted_path(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "module.base.utils.random_rectangle_point",
        _fixed_points([(0, 0), (20, 20), (50, 50)]),
    )

    assert random_rectangle_vector_opted(
        (10, 0),
        SwipePathOptions(box=(0, 0, 100, 100), padding=0, blacklist_area=[(19, 19, 21, 21)]),
    ) == ((40, 50), (50, 50))
