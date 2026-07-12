from typing import TYPE_CHECKING

import numpy as np
from scipy import optimize

from module.base.utils import area_pad

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence

    from module.base.type_alias import Area, NumericArray, Point, Scalar, Size


class Points:
    def __init__(self, points: Sequence[Point] | Point | NumericArray | None) -> None:
        if points is None or len(points) == 0:
            self._bool = False
            self.points = np.empty((0, 2))
        else:
            self._bool = True
            self.points = np.array(points)
            if len(self.points.shape) == 1:
                self.points = np.array([self.points])
            self.x, self.y = self.points.T

    def __str__(self) -> str:
        return str(self.points)

    __repr__ = __str__

    def __iter__(self) -> Iterator[NumericArray]:
        return iter(self.points)

    def __getitem__(self, item: int | slice | tuple[int, ...]) -> Scalar | NumericArray:
        return self.points[item]

    def __len__(self) -> int:
        if self:
            return len(self.points)
        return 0

    def __bool__(self) -> bool:
        return self._bool

    def link(self, point: Point | None, *, is_horizontal: bool = False) -> Lines:
        if is_horizontal:
            lines = [[y, np.pi / 2] for y in self.y]
            return Lines(lines, is_horizontal=True)
        if point is None:
            msg = "非水平线需要连接目标点"
            raise ValueError(msg)
        x, y = point
        theta = -np.arctan((self.x - x) / (self.y - y))
        rho = self.x * np.cos(theta) + self.y * np.sin(theta)
        lines = np.array([rho, theta]).T
        return Lines(lines, is_horizontal=False)

    def mean(self) -> NumericArray | None:
        if not self:
            return None

        return np.round(np.mean(self.points, axis=0)).astype(int)

    def group(self, threshold: Scalar = 3) -> NumericArray:
        if not self:
            return np.array([])
        groups = []
        points = self.points
        if len(points) == 1:
            return np.array([points[0]])

        while len(points):
            p0, p1 = points[0], points[1:]
            distance = np.sum(np.abs(p1 - p0), axis=1)
            center = Points(np.append(p1[distance <= threshold], [p0], axis=0)).mean()
            if center is None:
                msg = "非空点组缺少中心点"
                raise RuntimeError(msg)
            groups.append(center.tolist())
            points = p1[distance > threshold]

        return np.array(groups)


class Lines:
    MID_Y = 360

    def __init__(self, lines: Sequence[Point] | Point | NumericArray | None, *, is_horizontal: bool) -> None:
        if lines is None or len(lines) == 0:
            self._bool = False
            self.lines = np.empty((0, 2))
            self.rho = np.array([])
            self.theta = np.array([])
        else:
            self._bool = True
            self.lines = np.array(lines)
            if len(self.lines.shape) == 1:
                self.lines = np.array([self.lines])
            self.rho, self.theta = self.lines.T
        self.is_horizontal = is_horizontal

    def __str__(self) -> str:
        return str(self.lines)

    __repr__ = __str__

    def __iter__(self) -> Iterator[NumericArray]:
        return iter(self.lines)

    def __getitem__(self, item: int | slice) -> Lines:
        return Lines(self.lines[item], is_horizontal=self.is_horizontal)

    def __len__(self) -> int:
        if self:
            return len(self.lines)
        return 0

    def __bool__(self) -> bool:
        return self._bool

    @property
    def sin(self) -> NumericArray:
        return np.sin(self.theta)

    @property
    def cos(self) -> NumericArray:
        return np.cos(self.theta)

    @property
    def mean(self) -> NumericArray | None:
        if not self:
            return None
        if self.is_horizontal:
            return np.mean(self.lines, axis=0)
        x = np.mean(self.mid)
        theta = np.mean(self.theta)
        rho = x * np.cos(theta) + self.MID_Y * np.sin(theta)
        return np.array((rho, theta))

    @property
    def mid(self) -> NumericArray:
        if not self:
            return np.array([])
        if self.is_horizontal:
            return self.rho
        return (self.rho - self.MID_Y * self.sin) / self.cos

    def get_x(self, y: Scalar) -> NumericArray:
        return (self.rho - y * self.sin) / self.cos

    def get_y(self, x: Scalar) -> NumericArray:
        return (self.rho - x * self.cos) / self.sin

    def add(self, other: Lines) -> Lines:
        if not other:
            return self
        if not self:
            return other
        lines = np.append(self.lines, other.lines, axis=0)
        return Lines(lines, is_horizontal=self.is_horizontal)

    def move(self, x: Scalar, y: Scalar) -> Lines:
        if not self:
            return self
        if self.is_horizontal:
            self.lines[:, 0] += y
        else:
            self.lines[:, 0] += x * self.cos + y * self.sin
        return Lines(self.lines, is_horizontal=self.is_horizontal)

    def sort(self) -> Lines:
        if not self:
            return self
        lines = self.lines[np.argsort(self.mid)]
        return Lines(lines, is_horizontal=self.is_horizontal)

    def group(self, threshold: Scalar = 3) -> Lines:
        if not self:
            return self
        lines = self.sort()
        prev = 0
        regrouped = []
        group = []
        for mid, raw_line in zip(lines.mid, lines.lines, strict=True):
            line = raw_line.tolist()
            if mid - prev > threshold:
                if len(regrouped) == 0:
                    if len(group) != 0:
                        regrouped = [group]
                else:
                    regrouped += [group]
                group = [line]
            else:
                group.append(line)
            prev = mid
        regrouped += [group]
        means = []
        for group in regrouped:
            mean = Lines(group, is_horizontal=self.is_horizontal).mean
            if mean is None:
                msg = "非空线组缺少平均线"
                raise RuntimeError(msg)
            means.append(mean)
        regrouped = np.vstack(means)
        return Lines(regrouped, is_horizontal=self.is_horizontal)

    def distance_to_point(self, point: Point) -> NumericArray:
        x, y = point
        return self.rho - x * self.cos - y * self.sin

    @staticmethod
    def cross_two_lines(lines1: Lines, lines2: Lines) -> Iterator[NumericArray]:
        for rho1, sin1, cos1 in zip(lines1.rho, lines1.sin, lines1.cos, strict=True):
            for rho2, sin2, cos2 in zip(lines2.rho, lines2.sin, lines2.cos, strict=True):
                a = np.array([[cos1, sin1], [cos2, sin2]])
                b = np.array([rho1, rho2])
                yield np.linalg.solve(a, b)

    def cross(self, other: Lines) -> Points:
        points = np.vstack(list(self.cross_two_lines(self, other)))
        return Points(points)

    def delete(self, other: Lines, threshold: Scalar = 3) -> Lines:
        if not self:
            return self

        other_mid = other.mid
        lines = []
        for mid, line in zip(self.mid, self.lines, strict=True):
            if np.any(np.abs(other_mid - mid) < threshold):
                continue
            lines.append(line)

        return Lines(lines, is_horizontal=self.is_horizontal)


def area2corner(area: Area) -> NumericArray:
    """把 (x1, y1, x2, y2) 转为 [左上, 右上, 左下, 右下]。"""
    return np.array([[area[0], area[1]], [area[2], area[1]], [area[0], area[3]], [area[2], area[3]]])


def corner2area(corner: Sequence[Point] | NumericArray) -> NumericArray:
    """把四角坐标转为外接区域 (x1, y1, x2, y2)。"""
    x, y = np.array(corner).T
    return np.rint([np.min(x), np.min(y), np.max(x), np.max(y)]).astype(int)


def corner2inner(corner: Sequence[Point] | NumericArray) -> tuple[Scalar, Scalar, Scalar, Scalar]:
    """返回四角梯形的最大内接矩形 (x1, y1, x2, y2)。"""
    x0, y0, x1, y1, x2, y2, x3, y3 = np.array(corner).flatten()
    return tuple(np.rint((max(x0, x2), max(y0, y1), min(x1, x3), min(y2, y3))).astype(int))


def corner2outer(corner: Sequence[Point] | NumericArray) -> tuple[Scalar, Scalar, Scalar, Scalar]:
    """返回四角梯形的最小外接矩形 (x1, y1, x2, y2)。"""
    x0, y0, x1, y1, x2, y2, x3, y3 = np.array(corner).flatten()
    return tuple(np.rint((min(x0, x2), min(y0, y1), max(x1, x3), max(y2, y3))).astype(int))


def trapezoid2area(corner: Sequence[Point] | NumericArray, pad: int = 0) -> Area:
    """把四角梯形转为矩形区域；pad>0 取内接，pad<0 取外接。"""
    if pad > 0:
        return area_pad(corner2inner(corner), pad=pad)
    if pad < 0:
        return area_pad(corner2outer(corner), pad=pad)
    return area_pad(corner2area(corner), pad=pad)


def points_to_area_generator(points: NumericArray, shape: Size) -> Iterator[tuple[tuple[int, int], NumericArray]]:
    """从 shape=(x, y) 的点阵逐格产出 ((x, y), [左上, 右上, 左下, 右下])。"""
    points = points.reshape(*shape[::-1], 2)
    for y in range(shape[1] - 1):
        for x in range(shape[0] - 1):
            area = np.array([points[y, x], points[y, x + 1], points[y + 1, x], points[y + 1, x + 1]])
            yield ((x, y), area)


def get_map_inner(points: Sequence[Point] | NumericArray) -> NumericArray:
    """返回 (n, 2) 点集的平均坐标。"""
    points = np.array(points)
    if len(points.shape) == 1:
        points = np.array([points])

    return np.mean(points, axis=0)


def separate_edges(edges: Sequence[Scalar] | NumericArray, inner: Scalar) -> tuple[Scalar | None, Scalar | None]:
    """以 inner 拆分边缘，返回 (下界, 上界)，缺失一侧时为 None。"""
    if len(edges) == 0:
        return None, None
    if len(edges) == 1:
        edge = edges[0]
        return (None, edge) if edge > inner else (edge, None)
    lower = [edge for edge in edges if edge < inner]
    upper = [edge for edge in edges if edge > inner]
    lower = lower[0] if lower else None
    upper = upper[-1] if upper else None
    return lower, upper


def perspective_transform(points: Sequence[Point] | NumericArray, data: NumericArray) -> NumericArray:
    """用 (3, 3) 透视矩阵变换 (n, 2) 点集，并返回 (n, 2)。
    公式参考 https://web.archive.org/web/20150222120106/xenia.media.mit.edu/~cwren/interpolator/。
    """
    points = np.pad(np.array(points), ((0, 0), (0, 1)), mode="constant", constant_values=1)
    matrix = data.dot(points.T)
    x, y = matrix[0] / matrix[2], matrix[1] / matrix[2]
    return np.array([x, y]).T


def fit_points(points: Sequence[Point] | NumericArray, mod: Point, encourage: Scalar = 1) -> NumericArray:
    """在 (n, 2) 点集中拟合间距为 mod 的格点原点，并忽略远点。
    encourage 单位为像素；越小越偏向局部最小值，越大越偏向全局最小值。
    """
    encourage = np.square(encourage)
    mod = np.array(mod)
    points = np.array(points) % mod
    points = np.append(points - mod, points, axis=0)

    def cal_distance(point: NumericArray) -> Scalar:
        distance = np.linalg.norm(points - point, axis=1)
        return np.sum(1 / (1 + np.exp(encourage / distance) / distance))

    # 使用暴力全局最小化，避免局部最优。
    area = np.append(-mod - 10, mod + 10)
    result = optimize.brute(cal_distance, ((area[0], area[2]), (area[1], area[3])))
    return result % mod
