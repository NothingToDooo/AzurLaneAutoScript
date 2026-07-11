import time
import warnings
from dataclasses import dataclass
from typing import TYPE_CHECKING

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageOps
from scipy import optimize, signal

from module.base.utils import crop, float2str, point2str, rgb2gray
from module.exception import MapDetectionError
from module.logger import logger
from module.map_detection.utils import Lines, Points, get_map_inner, points_to_area_generator, separate_edges
from module.map_detection.utils_assets import ASSETS

if TYPE_CHECKING:
    from module.config.config import AzurLaneConfig

warnings.filterwarnings("ignore")

NO_HORIZONTAL_LINE_MESSAGE = "No horizontal line detected"
NO_VERTICAL_LINE_MESSAGE = "No vertical line detected"
VANISH_POINT_TOO_CLOSE_MESSAGE = "Vanish point and distant point too close"


@dataclass(frozen=True, slots=True)
class LineDetectionOptions:
    is_horizontal: bool
    peak_params: dict
    hough_threshold: int
    theta_threshold: float
    pad: int = 0


class Perspective:
    """从地图截图检测透视消失点、远点与网格线。"""

    image: np.ndarray
    config: AzurLaneConfig
    # 四条边可为 bool，或实现 __bool__。
    left_edge: Lines
    right_edge: Lines
    lower_edge: Lines
    upper_edge: Lines

    horizontal: Lines
    vertical: Lines
    crossings: Points
    vanish_point: tuple
    distant_point: tuple
    map_inner: np.ndarray

    def __init__(self, config):
        self.config = config

    def load(self, image):
        """加载 (720, 1280, 3) 截图。"""
        start_time = time.time()
        self.image = image

        image = self.load_image(image)

        inner_h = self.detect_lines(
            image,
            LineDetectionOptions(
                is_horizontal=True,
                peak_params=self.config.INTERNAL_LINES_FIND_PEAKS_PARAMETERS,
                hough_threshold=self.config.INTERNAL_LINES_HOUGHLINES_THRESHOLD,
                theta_threshold=self.config.HORIZONTAL_LINES_THETA_THRESHOLD,
            ),
        ).move(*self.config.DETECTING_AREA[:2])
        inner_v = self.detect_lines(
            image,
            LineDetectionOptions(
                is_horizontal=False,
                peak_params=self.config.INTERNAL_LINES_FIND_PEAKS_PARAMETERS,
                hough_threshold=self.config.INTERNAL_LINES_HOUGHLINES_THRESHOLD,
                theta_threshold=self.config.VERTICAL_LINES_THETA_THRESHOLD,
            ),
        ).move(*self.config.DETECTING_AREA[:2])
        edge_h = self.detect_lines(
            image,
            LineDetectionOptions(
                is_horizontal=True,
                peak_params=self.config.EDGE_LINES_FIND_PEAKS_PARAMETERS,
                hough_threshold=self.config.EDGE_LINES_HOUGHLINES_THRESHOLD,
                theta_threshold=self.config.HORIZONTAL_LINES_THETA_THRESHOLD,
                pad=self.config.DETECTING_AREA[2] - self.config.DETECTING_AREA[0],
            ),
        ).move(*self.config.DETECTING_AREA[:2])
        edge_v = self.detect_lines(
            image,
            LineDetectionOptions(
                is_horizontal=False,
                peak_params=self.config.EDGE_LINES_FIND_PEAKS_PARAMETERS,
                hough_threshold=self.config.EDGE_LINES_HOUGHLINES_THRESHOLD,
                theta_threshold=self.config.VERTICAL_LINES_THETA_THRESHOLD,
                pad=self.config.DETECTING_AREA[3] - self.config.DETECTING_AREA[1],
            ),
        ).move(*self.config.DETECTING_AREA[:2])

        horizontal = inner_h.add(edge_h).group()
        vertical = inner_v.add(edge_v).group()
        edge_h = edge_h.group()
        edge_v = edge_v.group()
        if not self.config.TRUST_EDGE_LINES:
            # 实验选项：用内部线排除不可信边缘线。
            edge_h = edge_h.delete(inner_h, threshold=self.config.TRUST_EDGE_LINES_THRESHOLD)
            edge_v = edge_v.delete(inner_v, threshold=self.config.TRUST_EDGE_LINES_THRESHOLD)
        self.horizontal = horizontal
        self.vertical = vertical
        if not self.horizontal:
            raise MapDetectionError(NO_HORIZONTAL_LINE_MESSAGE)
        if not self.vertical:
            raise MapDetectionError(NO_VERTICAL_LINE_MESSAGE)

        self.crossings = self.horizontal.cross(self.vertical)
        self.vanish_point = optimize.brute(self._vanish_point_value, self.config.VANISH_POINT_RANGE)
        distance_point_x = optimize.brute(self._distant_point_value, self.config.DISTANCE_POINT_X_RANGE)[0]
        self.distant_point = (distance_point_x, self.vanish_point[1])
        logger.attr_align("vanish_point", point2str(*self.vanish_point, length=5))
        logger.attr_align("distant_point", point2str(*self.distant_point, length=5))
        if np.linalg.norm(np.subtract(self.vanish_point, self.distant_point)) < 10:
            raise MapDetectionError(VANISH_POINT_TOO_CLOSE_MESSAGE)

        self.map_inner = get_map_inner(self.crossings.points)
        self.horizontal, self.lower_edge, self.upper_edge = self.line_cleanse(
            self.horizontal, inner=inner_h.group(), edge=edge_h
        )
        self.vertical, self.left_edge, self.right_edge = self.line_cleanse(
            self.vertical, inner=inner_v.group(), edge=edge_v
        )

        time_cost = round(time.time() - start_time, 3)
        lower_edge = "_" if self.lower_edge else " "
        left_edge = "/" if self.left_edge else " "
        upper_edge = "_" if self.upper_edge else " "
        right_edge = "\\" if self.right_edge else " "
        logger.info(
            f"{float2str(time_cost)}s  {lower_edge}   "
            f"Horizontal: {len(self.horizontal)} ({len(horizontal)} inner, {len(edge_h)} edge)"
        )
        logger.info(
            f"Edges: {left_edge}{upper_edge}{right_edge}    "
            f"Vertical: {len(self.vertical)} ({len(vertical)} inner, {len(edge_v)} edge)"
        )

    def load_image(self, image):
        """裁剪检测区域并屏蔽 UI，返回反色单通道图。"""
        image = rgb2gray(crop(image, self.config.DETECTING_AREA, copy=False))
        cv2.bitwise_and(image, ASSETS.ui_mask, dst=image)
        cv2.bitwise_not(image, dst=image)
        return image

    @staticmethod
    def find_peaks(image, is_horizontal, param, pad=0, mask=None):
        """沿指定轴提取峰值，应用可选填充与二维掩码后保持原图形状。"""
        if is_horizontal:
            image = image.T
        if pad:
            image = np.pad(image, ((0, 0), (0, pad)), mode="constant", constant_values=255)
        origin_shape = image.shape
        out = np.zeros(origin_shape[0] * origin_shape[1], dtype="uint8")
        peaks, _ = signal.find_peaks(image.ravel(), **param)
        out[peaks] = 255
        out = out.reshape(origin_shape)
        if pad:
            out = out[:, :-pad]
        if is_horizontal:
            out = out.T
        if mask is not None:
            out &= mask
        return out

    def hough_lines(self, image, is_horizontal, threshold, theta):
        """从峰值图提取水平或垂直 Lines；theta 的单位为度。"""
        lines = cv2.HoughLines(image, 1, np.pi / 180, threshold)
        if lines is None:
            return Lines(None, is_horizontal=is_horizontal)
        lines = lines[:, 0, :]
        if is_horizontal:
            lines = lines[(np.deg2rad(90 - theta) < lines[:, 1]) & (lines[:, 1] < np.deg2rad(90 + theta))]
        else:
            lines = lines[(lines[:, 1] < np.deg2rad(theta)) | (np.deg2rad(180 - theta) < lines[:, 1])]
            lines = [[-rho, theta - np.pi] if rho < 0 else [rho, theta] for rho, theta in lines]
        return Lines(lines, is_horizontal=is_horizontal)

    def detect_lines(self, image, options):
        peaks = self.find_peaks(
            image,
            is_horizontal=options.is_horizontal,
            param=options.peak_params,
            pad=options.pad,
            mask=ASSETS.ui_mask_stroke,
        )
        return self.hough_lines(
            peaks,
            is_horizontal=options.is_horizontal,
            threshold=options.hough_threshold,
            theta=options.theta_threshold,
        )

    @staticmethod
    def show_array(arr):
        image = Image.fromarray(arr.astype(np.uint8), mode="L")
        image.show()

    def draw(self, lines=None, bg=None, expend=0):
        image = (self.image if bg is None else bg).copy()
        if isinstance(image, np.ndarray):
            image = Image.fromarray(image)
        if expend:
            image = ImageOps.expand(image, border=expend, fill=0)
        draw = ImageDraw.Draw(image)
        if lines is None:
            lines = self.horizontal.add(self.vertical)
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

    def _vanish_point_value(self, point):
        """衡量候选点接近透视消失点的程度，值越小越好。"""
        # 加 0.001 避免 log10(0)。
        return np.sum(np.log10(np.abs(self.vertical.distance_to_point(point)) + 0.001))

    def _distant_point_value(self, x):
        """衡量候选点接近透视远点的程度，值越小越好。"""
        links = self.crossings.link((x[0], self.vanish_point[1]))
        mid = np.sort(links.mid)
        # 加 0.001 避免 log10(0)。
        return np.sum(np.log10(np.diff(mid) + 0.001))

    def mid_cleanse(self, mids, is_horizontal, threshold=3):
        """拟合等距线中点，返回 DETECTING_AREA 内的有效 mids；threshold 单位为像素。"""
        right_distant_point = (self.vanish_point[0] * 2 - self.distant_point[0], self.distant_point[1])
        encourage = self.config.COINCIDENT_POINT_ENCOURAGE_DISTANCE**2

        def convert_to_x(ys):
            return Points([[self.config.SCREEN_CENTER[0], y] for y in ys]).link(right_distant_point).mid

        def convert_to_y(xs):
            return (
                Points([[x, self.config.SCREEN_CENTER[1]] for x in xs])
                .link(right_distant_point)
                .get_y(x=self.config.SCREEN_CENTER[0])
            )

        def coincident_point_value(point):
            """衡量候选点接近重合点的程度，值越小越好。"""
            x, y = point
            # 不要直接使用到点距离。
            distance = np.abs(x - coincident.get_x(y))

            # 激活函数。
            distance = 1 / (1 + np.exp(encourage / distance) / distance)
            return np.sum(distance)

        if is_horizontal:
            mids = convert_to_x(mids)

        lines = []
        for index, mid in enumerate(mids):
            for n in range(self.config.ERROR_LINES_TOLERANCE[0], self.config.ERROR_LINES_TOLERANCE[1] + 1):
                theta = np.arctan(index + n)
                rho = mid * np.cos(theta)
                lines.append([rho, theta])
        coincident = Lines(np.vstack(lines), is_horizontal=False)
        mid_diff_range = self.config.MID_DIFF_RANGE_H if is_horizontal else self.config.MID_DIFF_RANGE_V
        coincident_point_range = ((-abs(self.config.ERROR_LINES_TOLERANCE[0]) * mid_diff_range[1], 200), mid_diff_range)
        coincident_point = optimize.brute(coincident_point_value, coincident_point_range)

        diff = np.max([mid_diff_range[0] - coincident_point[1], coincident_point[1] - mid_diff_range[1]])
        if diff > 0:
            direction = "Horizontal" if is_horizontal else "Vertical"
            logger.info(f"{direction} coincident point unexpected: {coincident_point}")

        if is_horizontal:
            border = (
                Points(
                    [
                        [self.config.SCREEN_CENTER[0], self.config.DETECTING_AREA[1]],
                        [self.config.SCREEN_CENTER[0], self.config.DETECTING_AREA[3]],
                    ]
                )
                .link(right_distant_point)
                .mid
            )
        else:
            border = (
                Points([self.config.DETECTING_AREA[0:2], self.config.DETECTING_AREA[1:3][::-1]])
                .link(self.vanish_point)
                .mid
            )

        left, right = border
        mids = np.arange(-25, 25) * coincident_point[1] + coincident_point[0]
        mids = mids[(mids > left - threshold) & (mids < right + threshold)]
        if is_horizontal:
            mids = convert_to_y(mids)

        return mids

    def line_cleanse(self, lines, inner, edge, threshold=3):
        origin = lines.mid
        clean = self.mid_cleanse(origin, is_horizontal=lines.is_horizontal, threshold=threshold)

        edge = edge.mid
        inner = inner.mid
        inner_clean = [inner_mid for inner_mid in inner if np.any(np.abs(inner_mid - clean) < 5)]
        if len(inner_clean) > 0:
            edge = edge[(edge > np.max(inner_clean) - threshold) | (edge < np.min(inner_clean) + threshold)]
        edge = [c for c in clean if np.any(np.abs(c - edge) < 5)]

        lower, upper = separate_edges(edge, inner=self.map_inner[1] if lines.is_horizontal else self.map_inner[0])

        if lower:
            clean = clean[clean > lower - threshold]
        if upper:
            clean = clean[clean < upper + threshold]

        if lines.is_horizontal:
            lines = Points([[self.config.SCREEN_CENTER[0], y] for y in clean]).link(None, is_horizontal=True)
            lower = (
                Points([self.config.SCREEN_CENTER[0], lower]).link(None, is_horizontal=True)
                if lower
                else Lines(None, is_horizontal=True)
            )
            upper = (
                Points([self.config.SCREEN_CENTER[0], upper]).link(None, is_horizontal=True)
                if upper
                else Lines(None, is_horizontal=True)
            )
        else:
            lines = Points([[x, self.config.SCREEN_CENTER[1]] for x in clean]).link(self.vanish_point)
            lower = (
                Points([lower, self.config.SCREEN_CENTER[1]]).link(self.vanish_point)
                if lower
                else Lines(None, is_horizontal=False)
            )
            upper = (
                Points([upper, self.config.SCREEN_CENTER[1]]).link(self.vanish_point)
                if upper
                else Lines(None, is_horizontal=False)
            )

        return lines, lower, upper

    def generate(self):
        """逐格产出 ((x, y), [左上, 右上, 左下, 右下])。"""
        points = self.horizontal.cross(self.vertical).points
        yield from points_to_area_generator(points, shape=(len(self.vertical), len(self.horizontal)))
