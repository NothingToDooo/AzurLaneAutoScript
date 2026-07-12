import operator
from typing import TYPE_CHECKING, Protocol, cast, overload

import numpy as np

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Iterator

    from module.base.type_alias import Point, Scalar


class RoadGrid(Protocol):
    @property
    def is_enemy(self) -> bool: ...

    @property
    def is_fleet(self) -> bool: ...

    @property
    def is_cleared(self) -> bool: ...


class SortableItem(Protocol):
    @property
    def location(self) -> Point: ...

    @property
    def cost(self) -> Scalar: ...

    @property
    def weight(self) -> Scalar: ...


class SelectedGrids[T]:
    def __init__(self, grids: Iterable[T]) -> None:
        self.grids = list(grids)
        self.indexes: dict[tuple[object, ...], SelectedGrids[T]] = {}

    def __iter__(self) -> Iterator[T]:
        return iter(self.grids)

    @overload
    def __getitem__(self, item: int) -> T: ...

    @overload
    def __getitem__(self, item: slice) -> SelectedGrids[T]: ...

    def __getitem__(self, item: int | slice) -> T | SelectedGrids[T]:
        if isinstance(item, int):
            return self.grids[item]
        return SelectedGrids(self.grids[item])

    def __contains__(self, item: object) -> bool:
        return item in self.grids

    def __str__(self) -> str:
        return "[" + ", ".join([str(grid) for grid in self]) + "]"

    def __len__(self) -> int:
        return len(self.grids)

    def __bool__(self) -> bool:
        return self.count > 0

    @property
    def location(self) -> list[Point]:
        return [cast("SortableItem", grid).location for grid in self.grids]

    @property
    def cost(self) -> list[Scalar]:
        return [cast("SortableItem", grid).cost for grid in self.grids]

    @property
    def weight(self) -> list[Scalar]:
        return [cast("SortableItem", grid).weight for grid in self.grids]

    @property
    def count(self) -> int:
        return len(self.grids)

    def select(self, **kwargs: object) -> SelectedGrids[T]:
        def matched(obj: T) -> bool:
            flag = True
            for k, v in kwargs.items():
                obj_v = getattr(obj, k)
                if type(obj_v) is not type(v) or obj_v != v:
                    flag = False
            return flag

        return SelectedGrids([grid for grid in self.grids if matched(grid)])

    def create_index(self, *attrs: str) -> dict[tuple[object, ...], SelectedGrids[T]]:
        raw_indexes: dict[tuple[object, ...], list[T]] = {}
        for grid in self.grids:
            k = tuple(getattr(grid, attr) for attr in attrs)
            raw_indexes.setdefault(k, []).append(grid)

        indexes = {k: SelectedGrids(v) for k, v in raw_indexes.items()}
        self.indexes = indexes
        return indexes

    def indexed_select(self, *values: object) -> SelectedGrids[T]:
        return self.indexes.get(values, SelectedGrids([]))

    def left_join[U](
        self,
        right: SelectedGrids[U],
        on_attr: Iterable[str],
        set_attr: Iterable[str],
        default: object = None,
    ) -> SelectedGrids[T]:
        on_attr = tuple(on_attr)
        set_attr = tuple(set_attr)
        right.create_index(*on_attr)
        for grid in self:
            attr_value = tuple([getattr(grid, attr) for attr in on_attr])
            right_grid = right.indexed_select(*attr_value).first_or_none()
            if right_grid is not None:
                for attr in set_attr:
                    setattr(grid, attr, getattr(right_grid, attr))
            else:
                for attr in set_attr:
                    setattr(grid, attr, default)

        return self

    def filter(self, func: Callable[[T], bool]) -> SelectedGrids[T]:
        """func 接收单个格子并返回是否保留。"""
        return SelectedGrids([grid for grid in self if func(grid)])

    def set(self, **kwargs: object) -> None:
        for grid in self:
            for key, value in kwargs.items():
                setattr(grid, key, value)

    def get(self, attr: str) -> list[object]:
        return [getattr(grid, attr) for grid in self.grids]

    def call(self, func: str, **kwargs: object) -> list[object]:
        return [getattr(grid, func)(**kwargs) for grid in self]

    def first_or_none(self) -> T | None:
        try:
            return self.grids[0]
        except IndexError:
            return None

    def add(self, grids: SelectedGrids[T]) -> SelectedGrids[T]:
        return SelectedGrids(list(set(self.grids + grids.grids)))

    def add_by_eq(self, grids: SelectedGrids[T]) -> SelectedGrids[T]:
        """按 __eq__ 而非 __hash__ 去重后合并。"""
        new = []
        for grid in self.grids + grids.grids:
            if grid not in new:
                new.append(grid)

        return SelectedGrids(new)

    def intersect(self, grids: SelectedGrids[T]) -> SelectedGrids[T]:
        return SelectedGrids(list(set(self.grids).intersection(set(grids.grids))))

    def intersect_by_eq(self, grids: SelectedGrids[T]) -> SelectedGrids[T]:
        """按 __eq__ 而非 __hash__ 求交集。"""
        return SelectedGrids([grid for grid in self.grids if grid in grids.grids])

    def delete(self, grids: SelectedGrids[T]) -> SelectedGrids[T]:
        g = [grid for grid in self.grids if grid not in grids]
        return SelectedGrids(g)

    def sort(self, *args: str) -> SelectedGrids[T]:
        if not self:
            return self
        if args:
            grids = sorted(self.grids, key=operator.attrgetter(*args))
            return SelectedGrids(grids)
        return self

    def sort_by_camera_distance(self, camera: Point) -> SelectedGrids[T]:
        if not self:
            return self
        location = np.array(self.location)
        diff = np.sum(np.abs(location - camera), axis=1)
        grids = tuple(np.array(self.grids)[np.argsort(diff)])
        return SelectedGrids(grids)

    def sort_by_clock_degree(
        self, center: Point = (0, 0), start: Point = (0, 1), *, clockwise: bool = True
    ) -> SelectedGrids[T]:
        """以 center 为原点、start 方向为 0°，按顺时针或逆时针排序。"""
        if not self:
            return self
        vector = np.asarray(self.location, dtype=float) - np.asarray(center, dtype=float)
        theta = np.arctan2(vector[:, 1], vector[:, 0]) / np.pi * 180
        vector = np.asarray(start, dtype=float) - np.asarray(center, dtype=float)
        theta -= np.arctan2(vector[1], vector[0]) / np.pi * 180
        if not clockwise:
            theta = -theta
        theta[theta < 0] += 360
        grids = tuple(np.array(self.grids)[np.argsort(theta)])
        return SelectedGrids(grids)


class RoadGrids[T: RoadGrid]:
    def __init__(self, grids: Iterable[T | list[T]]) -> None:
        self.grids: list[SelectedGrids[T]] = []
        for grid in grids:
            if isinstance(grid, list):
                self.grids.append(SelectedGrids(grids=grid))
            else:
                self.grids.append(SelectedGrids(grids=[grid]))

    def __str__(self) -> str:
        return str(" - ".join([str(grid) for grid in self.grids]))

    def roadblocks(self) -> SelectedGrids[T]:
        grids: list[T] = []
        for block in self.grids:
            if block.count == block.select(is_enemy=True).count:
                grids += block.grids
        return SelectedGrids(grids)

    def potential_roadblocks(self) -> SelectedGrids[T]:
        grids: list[T] = []
        for block in self.grids:
            if any(grid.is_fleet for grid in block):
                continue
            if any(grid.is_cleared for grid in block):
                continue
            if block.count - block.select(is_enemy=True).count == 1:
                grids += block.select(is_enemy=True).grids
        return SelectedGrids(grids)

    def first_roadblocks(self) -> SelectedGrids[T]:
        grids: list[T] = []
        for block in self.grids:
            if any(grid.is_fleet for grid in block):
                continue
            if any(grid.is_cleared for grid in block):
                continue
            if block.select(is_enemy=True).count >= 1:
                grids += block.select(is_enemy=True).grids
        return SelectedGrids(grids)

    def combine(self, road: RoadGrids[T]) -> RoadGrids[T]:
        out = RoadGrids[T]([])
        for select_1 in self.grids:
            for select_2 in road.grids:
                select = select_1.add(select_2)
                out.grids.append(select)

        return out
