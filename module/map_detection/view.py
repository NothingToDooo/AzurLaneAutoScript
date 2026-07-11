import collections
import time

import cv2
import numpy as np

from module.base.utils import area_in_area, float2str
from module.exception import MapDetectionError
from module.logger import logger
from module.map.map_grids import SelectedGrids
from module.map_detection.detector import MapDetector
from module.map_detection.grid import Grid
from module.map_detection.utils import corner2area
from module.map_detection.utils_assets import ASSETS

NO_MAP_GRIDS_MESSAGE = "No map grids found"
CAMERA_OUTSIDE_MAP_MESSAGE = "Camera outside map"


class View(MapDetector):
    grids: dict
    shape: np.ndarray
    center_loca: tuple
    center_offset: np.ndarray
    swipe_base: np.ndarray

    def __init__(self, config, mode="main", grid_class=Grid):
        """mode 为 main 时识别普通地图，为 os 时识别大型作战地图。"""
        super().__init__(config)
        self.mode = mode
        self.grid_class = grid_class

    def __iter__(self):
        return iter(self.grids.values())

    def __getitem__(self, item):
        return self.grids[tuple(item)]

    def __contains__(self, item):
        return tuple(item) in self.grids

    def show(self):
        for y in range(self.shape[1] + 1):
            text = " ".join([self[(x, y)].str if (x, y) in self else ".." for x in range(self.shape[0] + 1)])
            logger.info(text)

    def _image_clear_ui(self, image):
        if self.mode == "os":
            return cv2.copyTo(image, ASSETS.ui_mask_os_in_map)
        return cv2.copyTo(image, ASSETS.ui_mask_in_map)

    def load(self, image):
        image = self._image_clear_ui(np.array(image))
        self.image = image
        super().load(image)

        grids = {}

        for loca, points in self.generate():
            if area_in_area(area1=corner2area(points), area2=self.config.DETECTING_AREA):
                grids[loca] = self.grid_class(location=loca, image=image, corner=points, config=self.config)

        offset = list(grids.keys())
        if not offset:
            raise MapDetectionError(NO_MAP_GRIDS_MESSAGE)
        offset = np.min(offset, axis=0)
        if np.sum(np.abs(offset)) > 0:
            logger.attr_align("grids_offset", tuple(offset.tolist()))
            self.grids = {}
            for loca, grid in grids.items():
                x, y = np.subtract(loca, offset)
                grid.location = (x, y)
                self.grids[(x, y)] = grid
        else:
            self.grids = grids
        self.shape = np.max(list(self.grids.keys()), axis=0)

        for loca, grid in self.grids.items():
            offset = grid.screen2grid([self.config.SCREEN_CENTER])[0].astype(int)
            points = grid.grid2screen(np.add([[0.5, 0], [-0.5, 0], [0, 0.5], [0, -0.5]], offset))
            self.swipe_base = np.array([np.linalg.norm(points[0] - points[1]), np.linalg.norm(points[2] - points[3])])
            self.center_loca = tuple(np.add(loca, offset).tolist())
            logger.attr_align("center_loca", self.center_loca)
            if self.center_loca in self:
                self.center_offset = self.grids[self.center_loca].screen2grid([self.config.SCREEN_CENTER])[0]
            else:
                x = max(self.center_loca[0] - self.shape[0], 0) if self.center_loca[0] > 0 else self.center_loca[0]
                y = max(self.center_loca[1] - self.shape[1], 0) if self.center_loca[1] > 0 else self.center_loca[1]
                self.center_offset = offset - self.center_loca
                message = f"{CAMERA_OUTSIDE_MAP_MESSAGE}: offset=({x}, {y})"
                raise MapDetectionError(message)
            break

    def predict(self):
        start_time = time.time()
        for grid in self:
            grid.predict()
        logger.attr_align("predict", len(self.grids.keys()), front=float2str(time.time() - start_time) + "s")

    def update(self, image):
        """相机位置不变时只更新所有格子的截图，并重置识别状态。"""
        image = self._image_clear_ui(image)
        self.image = image
        for grid in self:
            grid.reset()
            grid.image = image

    def select(self, **kwargs):
        result = []
        for grid in self:
            flag = True
            for k, v in kwargs.items():
                if getattr(grid, k) != v:
                    flag = False
            if flag:
                result.append(grid)

        return SelectedGrids(result)

    def predict_swipe(self, prev, with_current_fleet=True, with_sea_grids=True):
        """用当前舰队箭头或海面格匹配预测滑动偏移，返回 (x, y) 或 None。
        海面格匹配存在误判风险，可用 with_sea_grids=False 禁用。
        """
        start_time = time.time()
        offset = np.subtract(self.center_loca, prev.center_loca)

        if with_current_fleet:
            for grid in self:
                grid.is_fleet = grid.predict_fleet()
                grid.is_current_fleet = grid.predict_current_fleet()
            for grid in prev:
                grid.is_fleet = grid.predict_fleet()
                grid.is_current_fleet = grid.predict_current_fleet()

            current_fleet = self.select(is_fleet=True, is_current_fleet=True)
            previous_fleet = prev.select(is_fleet=True, is_current_fleet=True)
            if len(current_fleet) == 1 and len(previous_fleet) == 1:
                diff = np.subtract(current_fleet[0].location, previous_fleet[0].location) - offset
                diff = tuple(diff.tolist())
                logger.info(
                    f"Map swipe predict: {diff} ({float2str(time.time() - start_time) + 's'}, current fleet match)"
                )
                return diff

        if with_sea_grids:
            swipes = []
            for current_loca, current_piece in self.grids.items():
                for previous_loca, previous_piece in prev.grids.items():
                    if current_piece.is_similar_to(previous_piece):
                        diff = np.subtract(current_loca, previous_loca) - offset
                        swipes.append(tuple(diff.tolist()))

            counter = collections.Counter(swipes)
            diff = counter.most_common()
            if len(diff) == 1 or (len(diff) >= 2 and diff[0][1] > diff[1][1]):
                logger.info(
                    f"Map swipe predict: {diff[0][0]} "
                    f"({float2str(time.time() - start_time) + 's'}, {diff[0][1]} matches)"
                )
                return diff[0][0]

        logger.info(f"Map swipe predict: None ({float2str(time.time() - start_time) + 's'}, no match)")
        return None
