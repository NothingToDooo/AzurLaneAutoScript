import time
from typing import TYPE_CHECKING

import cv2
import numpy as np

from module.base.utils import float2str, load_image
from module.logger import logger
from module.map_detection.homography import Homography
from module.map_detection.perspective import Perspective
from module.map_detection.utils import perspective_transform

if TYPE_CHECKING:
    from collections.abc import Sequence

    from module.base.type_alias import ImageArray, NumericArray, Point, Scalar
    from module.config.config import AzurLaneConfig
    from module.config.config_manual import FindPeaksParameter

GLOBE_MAP = "./assets/map_detection/os_globe_map.png"
GLOBE_MAP_SHAPE = (2570, 1696)


class GlobeDetection:
    globe: ImageArray | None = None
    homo_center: NumericArray
    center_loca: tuple[Scalar, Scalar]

    def __init__(self, config: AzurLaneConfig) -> None:
        self.config = config
        self.perspective = Perspective(config)
        self.homography = Homography(config)
        self._globe_map_loaded = False

    def load_globe_map(self) -> bool:
        """使用检测器前必须先载入全局地图模板。"""
        if self._globe_map_loaded:
            return False

        logger.info("Loading OS globe map")

        image = load_image(GLOBE_MAP)
        image = self.find_peaks(image, para=self.config.OS_GLOBE_FIND_PEAKS_PARAMETERS)
        pad = self.config.OS_GLOBE_IMAGE_PAD
        image = np.pad(image, ((pad, pad), (pad, pad)), mode="constant", constant_values=0)
        image = image.astype(np.uint8)
        image = cv2.resize(image, None, fx=self.config.OS_GLOBE_IMAGE_RESIZE, fy=self.config.OS_GLOBE_IMAGE_RESIZE)
        image = image.astype(np.uint8, copy=False)
        self.globe = image

        backup = self.config.temporary(
            HOMO_STORAGE=self.config.OS_GLOBE_HOMO_STORAGE, DETECTING_AREA=self.config.OS_GLOBE_DETECTING_AREA
        )
        size, source_points = self.config.OS_GLOBE_HOMO_STORAGE
        self.homography.find_homography(size, source_points, overflow=False)
        self.homo_center = self.screen2globe([self.config.SCREEN_CENTER])[0].astype(int)
        backup.recover()

        self._globe_map_loaded = True
        return True

    def screen2globe(self, points: Sequence[Point] | NumericArray) -> NumericArray:
        return perspective_transform(points, data=self.homography.homo_data)

    def globe2screen(self, points: Sequence[Point] | NumericArray) -> NumericArray:
        return perspective_transform(points, data=self.homography.homo_invt)

    def find_peaks(self, image: ImageArray, para: dict[str, FindPeaksParameter]) -> ImageArray:
        """返回地图边界为白色、其余为黑色的单色图。"""
        r, g, b = cv2.split(image)
        cv2.convertScaleAbs(g, alpha=0.6, dst=g)
        cv2.convertScaleAbs(b, alpha=0.4, dst=b)
        cv2.add(g, b, dst=b)
        cv2.subtract(b, r, dst=b)
        image = b.astype(np.uint8, copy=False)

        hori = self.perspective.find_peaks(image, is_horizontal=True, param=para, mask=None)
        vert = self.perspective.find_peaks(image, is_horizontal=False, param=para, mask=None)
        image = cv2.bitwise_or(hori, vert).astype(np.uint8, copy=False)

        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
        cv2.dilate(image, kernel, dst=image)

        return image.astype(np.uint8, copy=False)

    def perspective_transform(self, image: ImageArray) -> ImageArray:
        """把带透视的截图转换为无透视二维地图图像。"""
        transformed = cv2.warpPerspective(image, self.homography.homo_data, self.homography.homo_size)
        return transformed.astype(np.uint8, copy=False)

    def load(self, image: ImageArray) -> None:
        self.load_globe_map()
        start_time = time.time()

        local = self.find_peaks(self.perspective_transform(image), para=self.config.OS_LOCAL_FIND_PEAKS_PARAMETERS)
        local = local.astype(np.uint8)
        local = cv2.resize(local, None, fx=self.config.OS_GLOBE_IMAGE_RESIZE, fy=self.config.OS_GLOBE_IMAGE_RESIZE)

        if self.globe is None:
            message = "OS globe map was not loaded"
            raise RuntimeError(message)
        result = cv2.matchTemplate(self.globe, local, cv2.TM_CCOEFF_NORMED)
        _, similarity, _, loca = cv2.minMaxLoc(result)
        loca = np.array(loca) / self.config.OS_GLOBE_IMAGE_RESIZE
        loca = tuple(self.homo_center + loca - self.config.OS_GLOBE_IMAGE_PAD)
        self.center_loca = loca

        time_cost = round(time.time() - start_time, 3)
        logger.attr_align("globe_center", loca)
        logger.attr_align("similarity", float2str(similarity), front=float2str(time_cost) + "s")
        if similarity < 0.1:
            logger.warning("Low similarity when matching OS globe")
