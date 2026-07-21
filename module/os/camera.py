from typing import TYPE_CHECKING, cast

import numpy as np

from module.base.button import Button
from module.base.decorator import cached_property
from module.exception import MapDetectionError
from module.logger import logger
from module.map.camera import Camera
from module.map.map_base import location2node, location_ensure
from module.map_detection.homography import Homography
from module.map_detection.os_grid import OSGrid
from module.map_detection.utils import Lines
from module.map_detection.view import View
from module.os.map_operation import OSMapOperation
from module.os.radar import Radar

if TYPE_CHECKING:
    from module.base.type_alias import Area, ImageArray, Point
    from module.map.type_alias import GridLocation
    from module.map.utils import HasLocation


class OSCamera(OSMapOperation, Camera):
    radar: Radar
    fleet_current: GridLocation

    def _map_swipe(self, vector: Point, box: Area | None = (239, 128, 993, 628)) -> bool:
        return super()._map_swipe(vector, box=box)

    @staticmethod
    def _homography_backend(view: View) -> Homography:
        backend = view.backend
        if not isinstance(backend, Homography):
            msg = "OS map view should use homography backend"
            raise TypeError(msg)
        return backend

    @staticmethod
    def _homography_loca(view: View) -> np.ndarray | tuple[int, int] | None:
        backend = view.backend
        if not hasattr(backend, "homo_loca"):
            msg = "OS map view backend should expose homo_loca"
            raise TypeError(msg)
        homo_loca = backend.homo_loca
        if homo_loca is None or isinstance(homo_loca, (np.ndarray, tuple)):
            return cast("np.ndarray | tuple[int, int] | None", homo_loca)
        msg = "OS map view backend homo_loca has invalid type"
        raise TypeError(msg)

    def _view_init(self) -> None:
        if not hasattr(self, "view"):
            storage = ((10, 7), [(110.307, 103.657), (1012.311, 103.657), (-32.959, 600.567), (1113.057, 600.567)])
            view = View(self.config, mode="os", grid_class=OSGrid)
            view.detector_set_backend("homography")
            self._homography_backend(view).load_homography(storage=storage)
            self.view = view

    @cached_property
    def radar(self) -> Radar:
        return Radar(self.config)

    def predict_radar(self) -> None:
        self.radar.predict(self.device.image)
        self.radar.show()

    def grid_is_in_sight(
        self,
        grid: HasLocation | str | Point,
        camera: HasLocation | str | Point | None = None,
        sight: tuple[int, int, int, int] | None = None,
    ) -> bool:
        location = location_ensure(grid)
        camera = location_ensure(camera) if camera is not None else self.camera
        if sight is None:
            sight = self.map.layout.camera_sight

        diff = np.array(location) - camera
        if diff[1] > sight[3]:
            y = diff[1] - sight[3]
        elif diff[1] < sight[1]:
            y = diff[1] - sight[1]
        else:
            y = 0
        if diff[0] > sight[2]:
            x = diff[0] - sight[2]
        elif diff[0] < sight[0]:
            x = diff[0] - sight[0]
        else:
            x = 0
        return x == 0 and y == 0

    def _get_map_outside_button(self) -> Button | None:
        for _ in range(2):
            backend = self.view.backend
            if self.view.left_edge:
                edge = backend.left_edge
                if not isinstance(edge, Lines):
                    self.ensure_edge_insight()
                    continue
                area = (113, 185, float(edge.get_x(290)[0]), 290)
            elif self.view.right_edge:
                edge = backend.right_edge
                if not isinstance(edge, Lines):
                    self.ensure_edge_insight()
                    continue
                area = (float(edge.get_x(360)[0]), 360, 1280, 560)
            else:
                logger.info("No left edge or right edge")
                self.ensure_edge_insight()
                continue

            return Button(area=area, color=(), button=area, name="MAP_OUTSIDE")
        return None

    def update_os(self) -> None:
        self._view_init()

        try:
            self.view.load(self.device.image)
        except (MapDetectionError, AttributeError) as e:
            logger.warning(e)
            logger.warning("Assuming camera is focused on grid center")

            def empty(_image: ImageArray) -> None:
                return None

            backend = self._homography_backend(self.view)
            backup = backend.load
            vars(backend)["load"] = empty
            backend.homo_loca = np.array((53, 60))
            backend.left_edge = None
            backend.right_edge = None
            backend.lower_edge = None
            backend.upper_edge = None
            self.view.load(self.device.image)
            vars(backend)["load"] = backup

    def convert_radar_to_local(self, location: HasLocation | str | Point) -> OSGrid:
        """把雷达坐标转换为本地视野格子。

        游戏偶尔不会把镜头聚焦到当前舰队，此时必须改用实际舰队位置校正。
        """
        location = location_ensure(location)

        fleets = self.view.select(is_current_fleet=True)
        if fleets.count == 1:
            center = fleets[0].location
        elif fleets.count > 1:
            logger.warning(f"Convert radar to local, but found multiple current fleets: {fleets}")
            fleets = fleets.sort_by_camera_distance(self.view.center_loca)
            center = fleets[0].location
            if center is None:
                message = "Current fleet grid has no location"
                raise MapDetectionError(message)
            logger.warning(f"Assuming the nearest fleet to camera canter is current fleet: {location2node(center)}")
        else:
            logger.warning(
                f"Convert radar to local, but current fleet not found. "
                f"Assuming camera center is current fleet: {location2node(self.view.center_loca)}"
            )
            center = self.view.center_loca

        if center is None:
            message = "Current fleet grid has no location"
            raise MapDetectionError(message)

        try:
            local = self.view[np.add(location, center)]
        except KeyError:
            logger.warning(
                f"Convert radar to local, but target grid not in local view. "
                f"Assuming camera center is current fleet: {location2node(self.view.center_loca)}"
            )
            center = self.view.center_loca
            local = self.view[np.add(location, center)]

        if not isinstance(local, OSGrid) or local.location is None:
            message = "Radar target is not an initialized OS grid"
            raise MapDetectionError(message)
        logger.info(f"Radar {location} -> Local {location2node(local.location)} (fleet={location2node(center)})")
        return local
