import operator

import numpy as np


class SelectedGrids:
    def __init__(self, grids):
        self.grids = grids
        self.indexes: dict[tuple, SelectedGrids] = {}

    def __iter__(self):
        return iter(self.grids)

    def __getitem__(self, item):
        if isinstance(item, int):
            return self.grids[item]
        return SelectedGrids(self.grids[item])

    def __contains__(self, item):
        return item in self.grids

    def __str__(self):
        return "[" + ", ".join([str(grid) for grid in self]) + "]"

    def __len__(self):
        return len(self.grids)

    def __bool__(self):
        return self.count > 0

    @property
    def location(self):
        return [grid.location for grid in self.grids]

    @property
    def cost(self):
        return [grid.cost for grid in self.grids]

    @property
    def weight(self):
        return [grid.weight for grid in self.grids]

    @property
    def count(self):
        return len(self.grids)

    def select(self, **kwargs):
        def matched(obj):
            flag = True
            for k, v in kwargs.items():
                obj_v = getattr(obj, k)
                if type(obj_v) is not type(v) or obj_v != v:
                    flag = False
            return flag

        return SelectedGrids([grid for grid in self.grids if matched(grid)])

    def create_index(self, *attrs):
        indexes = {}
        for grid in self.grids:
            k = tuple(getattr(grid, attr) for attr in attrs)
            try:
                indexes[k].append(grid)
            except KeyError:
                indexes[k] = [grid]

        indexes = {k: SelectedGrids(v) for k, v in indexes.items()}
        self.indexes = indexes
        return indexes

    def indexed_select(self, *values):
        return self.indexes.get(values, SelectedGrids([]))

    def left_join(self, right, on_attr, set_attr, default=None):
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

    def filter(self, func):
        """func 接收单个格子并返回是否保留。"""
        return SelectedGrids([grid for grid in self if func(grid)])

    def set(self, **kwargs):
        for grid in self:
            for key, value in kwargs.items():
                setattr(grid, key, value)

    def get(self, attr):
        return [getattr(grid, attr) for grid in self.grids]

    def call(self, func, **kwargs):
        return [getattr(grid, func)(**kwargs) for grid in self]

    def first_or_none(self):
        try:
            return self.grids[0]
        except IndexError:
            return None

    def add(self, grids):
        return SelectedGrids(list(set(self.grids + grids.grids)))

    def add_by_eq(self, grids):
        """按 __eq__ 而非 __hash__ 去重后合并。"""
        new = []
        for grid in self.grids + grids.grids:
            if grid not in new:
                new.append(grid)

        return SelectedGrids(new)

    def intersect(self, grids):
        return SelectedGrids(list(set(self.grids).intersection(set(grids.grids))))

    def intersect_by_eq(self, grids):
        """按 __eq__ 而非 __hash__ 求交集。"""
        return SelectedGrids([grid for grid in self.grids if grid in grids.grids])

    def delete(self, grids):
        g = [grid for grid in self.grids if grid not in grids]
        return SelectedGrids(g)

    def sort(self, *args):
        if not self:
            return self
        if args:
            grids = sorted(self.grids, key=operator.attrgetter(*args))
            return SelectedGrids(grids)
        return self

    def sort_by_camera_distance(self, camera):
        if not self:
            return self
        location = np.array(self.location)
        diff = np.sum(np.abs(location - camera), axis=1)
        grids = tuple(np.array(self.grids)[np.argsort(diff)])
        return SelectedGrids(grids)

    def sort_by_clock_degree(self, center=(0, 0), start=(0, 1), clockwise=True):
        """以 center 为原点、start 方向为 0°，按顺时针或逆时针排序。"""
        if not self:
            return self
        vector = np.subtract(self.location, center)
        theta = np.arctan2(vector[:, 1], vector[:, 0]) / np.pi * 180
        vector = np.subtract(start, center)
        theta -= np.arctan2(vector[1], vector[0]) / np.pi * 180
        if not clockwise:
            theta = -theta
        theta[theta < 0] += 360
        grids = tuple(np.array(self.grids)[np.argsort(theta)])
        return SelectedGrids(grids)


class RoadGrids:
    def __init__(self, grids):
        self.grids = []
        for grid in grids:
            if isinstance(grid, list):
                self.grids.append(SelectedGrids(grids=grid))
            else:
                self.grids.append(SelectedGrids(grids=[grid]))

    def __str__(self):
        return str(" - ".join([str(grid) for grid in self.grids]))

    def roadblocks(self):
        grids = []
        for block in self.grids:
            if block.count == block.select(is_enemy=True).count:
                grids += block.grids
        return SelectedGrids(grids)

    def potential_roadblocks(self):
        grids = []
        for block in self.grids:
            if any(grid.is_fleet for grid in block):
                continue
            if any(grid.is_cleared for grid in block):
                continue
            if block.count - block.select(is_enemy=True).count == 1:
                grids += block.select(is_enemy=True).grids
        return SelectedGrids(grids)

    def first_roadblocks(self):
        grids = []
        for block in self.grids:
            if any(grid.is_fleet for grid in block):
                continue
            if any(grid.is_cleared for grid in block):
                continue
            if block.select(is_enemy=True).count >= 1:
                grids += block.select(is_enemy=True).grids
        return SelectedGrids(grids)

    def combine(self, road):
        out = RoadGrids([])
        for select_1 in self.grids:
            for select_2 in road.grids:
                select = select_1.add(select_2)
                out.grids.append(select)

        return out
