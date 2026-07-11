from typing import TYPE_CHECKING

from module.map_detection.homography import Homography
from module.map_detection.perspective import Perspective

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable
    from typing import Any

    import numpy as np

    from module.config.config import AzurLaneConfig

type DetectionBackend = Homography | Perspective


class MapDetector:
    image: np.ndarray
    config: AzurLaneConfig

    left_edge: bool
    right_edge: bool
    lower_edge: bool
    upper_edge: bool
    backend: DetectionBackend

    generate: Callable[..., Iterable[tuple[tuple[int, int], Any]]]

    def __init__(self, config):
        self.config = config
        self.detector_set_backend()

    def detector_set_backend(self, name=""):
        """name 应为 `homography` 或 `perspective`；空值读取配置。"""
        if not name:
            name = self.config.DETECTION_BACKEND

        if name == "homography":
            self.backend = Homography(config=self.config)
        else:
            self.backend = Perspective(config=self.config)

    def load(self, image):
        """加载 (720, 1280, 3) 截图。"""
        self.backend.load(image)

        self.left_edge = bool(self.backend.left_edge)
        self.right_edge = bool(self.backend.right_edge)
        self.lower_edge = bool(self.backend.lower_edge)
        self.upper_edge = bool(self.backend.upper_edge)
        self.generate = self.backend.generate
