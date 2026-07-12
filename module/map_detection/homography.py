import time
from typing import TYPE_CHECKING, cast

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageOps

from module.base.decorator import cached_property
from module.base.utils import crop, float2str, load_image, point2str, rgb2gray
from module.exception import MapDetectionError
from module.logger import logger
from module.map_detection.perspective import Perspective
from module.map_detection.utils import (
    Lines,
    Points,
    area2corner,
    fit_points,
    get_map_inner,
    perspective_transform,
    points_to_area_generator,
    separate_edges,
)
from module.map_detection.utils_assets import ASSETS

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence

    from module.base.type_alias import FilePath, ImageArray, NumericArray, Point, Scalar, Size
    from module.config.config import AzurLaneConfig
    from module.map.type_alias import GridLocation

NO_HOMOGRAPHY_INPUT_MESSAGE = "No data feed to load_homography, please input at least one."
FREE_TILE_NOT_FOUND_MESSAGE = "Failed to find a free tile"


class Homography:
    """从截图估计单应矩阵，并生成各网格的四角坐标。"""

    image: ImageArray
    config: AzurLaneConfig
    # 四条边可为 bool，或实现 __bool__。
    left_edge: Scalar | bool | None
    right_edge: Scalar | bool | None
    lower_edge: Scalar | bool | None
    upper_edge: Scalar | bool | None

    homo_storage: tuple[Size, list[tuple[Scalar, Scalar]]]
    homo_data: NumericArray
    homo_invt: NumericArray
    homo_size: tuple[int, int]
    homo_loca: NumericArray
    homo_loaded: bool

    map_inner: NumericArray
    _map_edge_count: tuple[int, int]

    def __init__(self, config: AzurLaneConfig) -> None:
        self.config = config
        self.homo_loaded = False

    @cached_property
    def ui_mask_homo_stroke(self) -> ImageArray:
        mask = ASSETS.ui_mask_os if self.config.Scheduler_Command.startswith("Opsi") else ASSETS.ui_mask
        image = cv2.warpPerspective(mask, self.homo_data, self.homo_size)
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5))
        image = cv2.erode(image, kernel).astype("uint8")
        # 透视变换会产生边缘混叠，因此裁掉边缘。
        pad = 2
        image[:pad, :] = 0
        image[-pad:, :] = 0
        image[:, :pad] = 0
        image[:, -pad:] = 0
        return cast("ImageArray", image)

    def load(self, image: ImageArray) -> None:
        """加载 (720, 1280, 3) 截图。"""
        if not self.homo_loaded:
            self.load_homography(storage=self.config.HOMO_STORAGE, image=image)

        self.detect(image)

    def load_homography(
        self,
        storage: tuple[Size, Sequence[Point]] | None = None,
        perspective: Perspective | None = None,
        image: ImageArray | None = None,
        file: FilePath | None = None,
    ) -> None:
        """从 storage、Perspective、截图或文件加载单应矩阵。
        storage 形状为 ((x, y), [左上, 右上, 左下, 右下])。
        """
        if storage is not None:
            self.find_homography(*storage)
        elif perspective is not None:
            hori = perspective.horizontal[0].add(perspective.horizontal[-1])
            vert = perspective.vertical[0].add(perspective.vertical[-1])
            src_pts = hori.cross(vert).points
            x = len(perspective.vertical) - 1
            y = len(perspective.horizontal) - 1
            self.find_homography(size=(x, y), src_pts=src_pts)
        elif image is not None:
            perspective_ = Perspective(self.config)
            perspective_.load(image)
            self.load_homography(perspective=perspective_)
        elif file is not None:
            image_ = load_image(file)
            perspective_ = Perspective(self.config)
            perspective_.load(image_)
            self.load_homography(perspective=perspective_)
        else:
            raise MapDetectionError(NO_HOMOGRAPHY_INPUT_MESSAGE)

    def find_homography(self, size: Size, src_pts: Sequence[Point] | NumericArray, *, overflow: bool = True) -> None:
        """由网格尺寸和四角坐标求单应矩阵。
        overflow=True 保留完整变换图，否则只保留有效内接区域。
        """
        src_pts = np.asarray(src_pts, dtype=float).copy()
        self.homo_storage = (size, [(x, y) for x, y in np.round(src_pts, 3)])
        logger.attr("homo_storage", self.homo_storage)

        src_pts -= self.config.DETECTING_AREA[:2]
        dst_pts = src_pts[0] + area2corner((0, 0, *np.multiply(size, self.config.HOMO_TILE)))
        homo = cast("NumericArray", cv2.getPerspectiveTransform(src_pts.astype(np.float32), dst_pts.astype(np.float32)))

        area = area2corner(self.config.DETECTING_AREA) - self.config.DETECTING_AREA[:2]
        transformed = perspective_transform(area, data=homo)
        if overflow:
            transformed -= np.min(transformed, axis=0)
            size = np.ceil(np.max(transformed, axis=0)).astype(int)
        else:
            x0, y0, x1, y1, x2, y2, x3, y3 = transformed.flatten()
            inner = np.array((max(x0, x2), max(y0, y1), min(x1, x3), min(y2, y3)))
            transformed -= inner[:2]
            size = np.ceil(inner[2:] - inner[:2]).astype(int)
        homo = cast(
            "NumericArray", cv2.getPerspectiveTransform(area.astype(np.float32), transformed.astype(np.float32))
        )

        self.homo_data = homo
        self.homo_invt = cast("NumericArray", cv2.invert(homo)[1])
        self.homo_size = tuple(size.tolist())
        self.homo_loaded = True

    def detect(self, image: ImageArray) -> None:
        """在截图中定位网格与边界，返回是否成功。"""
        start_time = time.time()
        self.image = image

        image = rgb2gray(crop(image, self.config.DETECTING_AREA, copy=False))

        image_trans = cv2.warpPerspective(image, self.homo_data, self.homo_size)

        image_edge = cast("ImageArray", cv2.Canny(image_trans, *self.config.HOMO_CANNY_THRESHOLD))
        cv2.bitwise_and(image_edge, self.ui_mask_homo_stroke, dst=image_edge)
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
        cv2.morphologyEx(image_edge, cv2.MORPH_CLOSE, kernel, dst=image_edge)

        if (
            self.search_tile_center(
                image_edge,
                threshold_good=self.config.HOMO_CENTER_GOOD_THRESHOLD,
                threshold=self.config.HOMO_CENTER_THRESHOLD,
            )
            or self.search_tile_corner(image_edge, threshold=self.config.HOMO_CORNER_THRESHOLD)
            or self.search_tile_rectangle(image_edge, threshold=self.config.HOMO_RECTANGLE_THRESHOLD)
        ):
            pass
        else:
            raise MapDetectionError(FREE_TILE_NOT_FOUND_MESSAGE)

        self.homo_loca %= self.config.HOMO_TILE

        self.lower_edge, self.upper_edge, self.left_edge, self.right_edge = False, False, False, False
        self._map_edge_count = (0, 0)
        if self.config.HOMO_EDGE_DETECT:
            cv2.dilate(image_edge, kernel, dst=image_edge)
            cv2.inRange(image_trans, *self.config.HOMO_EDGE_COLOR_RANGE, dst=image_trans)
            cv2.bitwise_and(image_edge, image_trans, dst=image_edge)
            cv2.bitwise_and(image_edge, self.ui_mask_homo_stroke, dst=image_edge)
            self.detect_edges(image_edge, hough_th=self.config.HOMO_EDGE_HOUGHLINES_THRESHOLD)

        time_cost = round(time.time() - start_time, 3)
        lower_edge = "_" if self.lower_edge else " "
        left_edge = "/" if self.left_edge else " "
        upper_edge = "_" if self.upper_edge else " "
        right_edge = "\\" if self.right_edge else " "
        logger.info(
            f"{float2str(time_cost)}s  {lower_edge}   "
            f"edge_lines: {self._map_edge_count[1]} hori, {self._map_edge_count[0]} vert"
        )
        logger.info(f"Edges: {left_edge}{upper_edge}{right_edge}   homo_loca: {point2str(*self.homo_loca, length=3)}")

    def search_tile_center(
        self, image: ImageArray, threshold_good: float = 0.9, threshold: float = 0.8, encourage: float = 1.0
    ) -> bool:
        """主路径：在单通道图中搜索空格中心，返回是否成功。
        `len(res[res > 0.8])` 比 `np.sum(res > 0.8)` 快约三倍。
        """
        result = cv2.matchTemplate(image, ASSETS.tile_center_image, cv2.TM_CCOEFF_NORMED)
        _, similarity, _, loca = cv2.minMaxLoc(result)
        if similarity > threshold_good:
            self.homo_loca = np.array(loca) - self.config.HOMO_CENTER_OFFSET
            self.map_inner = np.array(loca)
            message = "good match"
        elif similarity > threshold:
            location = np.argwhere(result > threshold)[:, ::-1]
            self.homo_loca = (
                fit_points(location, mod=self.config.HOMO_TILE, encourage=encourage) - self.config.HOMO_CENTER_OFFSET
            )
            self.map_inner = get_map_inner(location)
            message = f"{len(location)} matches"
        else:
            message = "bad match"

        logger.attr_align("tile_center", f"{float2str(similarity)} ({message})")
        return message != "bad match"

    def search_tile_corner(self, image: ImageArray, threshold: float = 0.8, encourage: float = 1.0) -> bool:
        """后备路径：在单通道图中搜索空格角点，误差约 0.5～1 像素。"""
        similarity = 0
        location = np.empty((0, 2))
        for index in range(4):
            template = ASSETS.tile_corner_image_list[index]
            result = cv2.matchTemplate(image, template, cv2.TM_CCOEFF_NORMED)
            similarity = max(similarity, np.max(result))
            loca = np.argwhere(result > threshold)[:, ::-1] - self.config.HOMO_CORNER_OFFSET_LIST[index]
            location = np.append(location, loca, axis=0) if len(location) else loca

        if similarity > threshold:
            self.homo_loca = (
                fit_points(location, mod=self.config.HOMO_TILE, encourage=encourage) - self.config.HOMO_CENTER_OFFSET
            )
            self.map_inner = get_map_inner(location)
            message = f"{len(location)} matches"
        else:
            message = "bad match"

        logger.attr_align("tile_corner", f"{float2str(similarity)} ({message})")
        return message != "bad match"

    def search_tile_rectangle(
        self,
        image: ImageArray,
        threshold: int = 10,
        encourage: float = 5.1,
        close_kernel: tuple[int, ...] = (5, 10, 15, 20, 25),
    ) -> bool:
        """末级后备：从单通道图的矩形轮廓定位角点，误差约 2 像素。"""
        location = np.empty((0, 2))
        for kernel_size in close_kernel:
            kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (kernel_size, kernel_size))
            image_closed = cv2.morphologyEx(image, cv2.MORPH_CLOSE, kernel)
            contours, _ = cv2.findContours(image_closed, cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE)
            rectangle = np.array([cv2.boundingRect(cv2.convexHull(cont).astype(np.float32)) for cont in contours])

            try:
                rectangle = rectangle[(rectangle[:, 2] > 100) & (rectangle[:, 3] > 100)]
                shape = rectangle[:, 2:]
                diff = np.abs(shape - np.round(shape / self.config.HOMO_TILE) * self.config.HOMO_TILE)
                rectangle = rectangle[np.all(diff < encourage, axis=1)]
                location = np.append(location, rectangle[:, :2], axis=0)
            except IndexError:
                location = np.empty((0, 2))

        if len(location) > threshold:
            self.homo_loca = fit_points(location, mod=self.config.HOMO_TILE, encourage=encourage)
            self.map_inner = get_map_inner(location)
            message = "good match"
        else:
            message = "bad match"

        logger.attr_align("tile_rectangle", f"{len(location)} rectangles ({message})")
        return message != "bad match"

    def detect_edges(self, image: ImageArray, hough_th: int = 120, theta_th: float = 0.005, edge_th: float = 9) -> None:
        """在单通道图中检测地图边缘；theta_th 单位为度，edge_th 单位为像素。"""
        lines = cv2.HoughLines(image, 1, np.pi / 180, hough_th)
        if lines is None:
            self.lower_edge, self.upper_edge = separate_edges([], inner=self.map_inner[1])
            self.left_edge, self.right_edge = separate_edges([], inner=self.map_inner[0])
            self._map_edge_count = (0, 0)
            return

        lines = lines[:, 0, :]
        theta = lines[:, 1]
        area = self.config.DETECTING_AREA
        area = area2corner([0, 0, *np.subtract(area[2:], area[:2])])
        area = np.mean(area.reshape((2, 2, 2)), axis=0)
        area = perspective_transform(area, self.homo_data)
        mid_left, _, mid_right, _ = area.flatten()

        horizontal_lines = Lines(
            lines[(np.deg2rad(90 - theta_th) < theta) & (theta < np.deg2rad(90 + theta_th))],
            is_horizontal=True,
        ).group()
        vert = lines[(theta < np.deg2rad(theta_th)) | (np.deg2rad(180 - theta_th) < theta)]
        vert = [[-rho, theta - np.pi] if rho < 0 else [rho, theta] for rho, theta in vert]
        vert = [[rho, theta] for rho, theta in vert if mid_left < rho < mid_right]
        vertical_lines = Lines(vert, is_horizontal=False).group()

        self._map_edge_count = (len(vertical_lines), len(horizontal_lines))

        horizontal = horizontal_lines.rho
        if horizontal_lines:
            diff = (horizontal - self.homo_loca[1]) % self.config.HOMO_TILE[1]
            horizontal = horizontal[(diff < edge_th) | (diff > self.config.HOMO_TILE[1] - edge_th)]
        vertical = vertical_lines.rho
        if vertical_lines:
            diff = (vertical - self.homo_loca[0]) % self.config.HOMO_TILE[0]
            vertical = vertical[(diff < edge_th) | (diff > self.config.HOMO_TILE[0] - edge_th)]

        self.lower_edge, self.upper_edge = separate_edges(horizontal, inner=self.map_inner[1])
        self.left_edge, self.right_edge = separate_edges(vertical, inner=self.map_inner[0])

    def generate(self, edge_th: float = 9) -> Iterator[tuple[GridLocation, NumericArray]]:
        """逐格产出 ((x, y), [左上, 右上, 左下, 右下])。"""
        area = [
            self.left_edge - edge_th if self.left_edge else 0,
            self.lower_edge - edge_th if self.lower_edge else 0,
            self.right_edge + edge_th if self.right_edge else self.homo_size[0],
            self.upper_edge + edge_th if self.upper_edge else self.homo_size[1],
        ]
        x = np.arange(-25, 25) * self.config.HOMO_TILE[0] + self.homo_loca[0]
        x = x[(x > area[0]) & (x < area[2])]
        y = np.arange(-25, 25) * self.config.HOMO_TILE[1] + self.homo_loca[1]
        y = y[(y > area[1]) & (y < area[3])]

        shape = (len(x), len(y))
        points = np.array(np.meshgrid(x, y)).reshape((2, -1)).T
        points = perspective_transform(points, data=self.homo_invt) + self.config.DETECTING_AREA[:2]
        yield from points_to_area_generator(points.reshape(*shape[::-1], 2), shape=shape)

    def to_perspective(self) -> tuple[Lines, Lines]:
        """返回 (水平线集, 垂直线集)。"""
        grids = dict(self.generate())
        shape = np.max(list(grids.keys()), axis=0)

        hori = Points([640, grids[(0, 0)][1, 1]]).link(None, is_horizontal=True)
        for y in range(shape[1] + 1):
            hori = hori.add(Points([640, grids[(0, y)][3, 1]]).link(None, is_horizontal=True))
        vert = Points(grids[(0, 0)][0]).link(grids[(0, shape[1])][2])
        for x in range(shape[0] + 1):
            vert = vert.add(Points(grids[(x, 0)][1]).link(grids[(x, shape[1])][3]))
        return hori, vert

    def draw(self, lines: Lines | None = None, bg: ImageArray | None = None, expend: int = 0) -> None:
        if lines is None:
            hori, vert = self.to_perspective()
            lines = hori.add(vert)
        image = (self.image if bg is None else bg).copy()
        image = Image.fromarray(image)
        if expend:
            image = ImageOps.expand(image, border=expend, fill=0)
        draw = ImageDraw.Draw(image)
        for rho, theta in zip(lines.rho, lines.theta, strict=True):
            a = np.cos(theta)
            b = np.sin(theta)
            x0 = a * rho
            y0 = b * rho
            x1 = int(x0 + 10000 * (-b)) + expend
            y1 = int(y0 + 10000 * a) + expend
            x2 = int(x0 - 10000 * (-b)) + expend
            y2 = int(y0 - 10000 * a) + expend
            draw.line([x1, y1, x2, y2], "white")

        image.show()
