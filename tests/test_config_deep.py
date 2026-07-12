from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from module.config.deep import deep_iter

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

    from module.config.deep import DeepValue


class _MappingLike:
    def __init__(self, data: Mapping[str, DeepValue]) -> None:
        self.data = data

    def items(self) -> Iterable[tuple[str, DeepValue]]:
        return self.data.items()


_NESTED_CONFIG = {
    "task": {
        "scheduler": {
            "enable": True,
            "next_run": "2026-07-08 00:00:00",
        },
        "combat": {
            "fleet": 1,
        },
    },
    "plain": "value",
    "empty": {},
}


def test_deep_iter_returns_items_at_depth_one() -> None:
    assert list(deep_iter(_NESTED_CONFIG, depth=1)) == [
        (["task"], _NESTED_CONFIG["task"]),
        (["plain"], "value"),
        (["empty"], {}),
    ]


def test_deep_iter_returns_items_at_target_depth() -> None:
    assert list(deep_iter(_NESTED_CONFIG, depth=2)) == [
        (["task", "scheduler"], {"enable": True, "next_run": "2026-07-08 00:00:00"}),
        (["task", "combat"], {"fleet": 1}),
    ]
    assert list(deep_iter(_NESTED_CONFIG, depth=3)) == [
        (["task", "scheduler", "enable"], True),
        (["task", "scheduler", "next_run"], "2026-07-08 00:00:00"),
        (["task", "combat", "fleet"], 1),
    ]


def test_deep_iter_can_include_shallow_leaf_values() -> None:
    assert list(deep_iter(_NESTED_CONFIG, min_depth=1, depth=3)) == [
        (["plain"], "value"),
        (["task", "scheduler", "enable"], True),
        (["task", "scheduler", "next_run"], "2026-07-08 00:00:00"),
        (["task", "combat", "fleet"], 1),
    ]
    assert list(deep_iter(_NESTED_CONFIG, min_depth=2, depth=3)) == [
        (["task", "scheduler", "enable"], True),
        (["task", "scheduler", "next_run"], "2026-07-08 00:00:00"),
        (["task", "combat", "fleet"], 1),
    ]


def test_deep_iter_accepts_mapping_like_root() -> None:
    data = _MappingLike({"root": {"leaf": 1}})

    assert list(deep_iter(data, depth=2)) == [(["root", "leaf"], 1)]


def test_deep_iter_ignores_non_mapping_root() -> None:
    assert list(deep_iter([], depth=2)) == []
    assert list(deep_iter(None, depth=2)) == []


@pytest.mark.parametrize(
    ("min_depth", "depth"),
    [
        (0, 1),
        (2, 1),
    ],
)
def test_deep_iter_rejects_invalid_depth_range(min_depth: int, depth: int) -> None:
    with pytest.raises(ValueError, match="Invalid depth range"):
        list(deep_iter(_NESTED_CONFIG, min_depth=min_depth, depth=depth))
