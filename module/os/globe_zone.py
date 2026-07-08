import numpy as np

from module.base.decorator import cached_property
from module.exception import ScriptError
from module.map.map_grids import SelectedGrids
from module.os.globe_detection import GLOBE_MAP_SHAPE
from module.os.map_data import DIC_OS_MAP

OS_GLOBE_ZONE_NOT_FOUND_TEMPLATE = "Unable to find OS globe zone: {name}"
INVALID_HAZARD_LEVEL_TEMPLATE = "Invalid hazard_level of zones: {hazard_level}"


class Zone:
    zone_id: int
    # 地图尺寸，例如 J10。
    shape: str
    # 侵蚀等级，范围 1 到 7。
    hazard_level: int
    # 国区海域名。
    cn: str
    # 信息栏钉选坐标。
    area_pos: tuple
    # area_pos + offset_pos 是任务钉选坐标。
    offset_pos: tuple
    # 1 左上，2 右上，3 左下，4 右下，5 中心。
    region: int

    is_port: bool
    is_azur_port: bool

    def __init__(self, zone_id, data):
        self.zone_id = zone_id
        self.__dict__.update(data)
        self.location = self.point_convert(self.area_pos)
        self.mission = self.point_convert(np.add(self.area_pos, self.offset_pos))
        self.is_port = self.zone_id in [0, 1, 2, 3, 4, 5, 6, 7, 154]
        self.is_azur_port = self.zone_id in [0, 1, 2, 3]

    @staticmethod
    def point_convert(point):
        """把 world_chapter_colormask.lua 坐标转换到 os_globe_map.png。"""
        point = np.multiply(point, 1.25)
        # GLOBE_MAP_SHAPE[1] 是 os_globe_map.png 的高度。
        return np.array((point[0], GLOBE_MAP_SHAPE[1] - point[1]))

    def __str__(self):
        """
        Returns:
            str: Such as `[3|圣彼得伯格]`
        """
        return f"[{self.zone_id}|{self.cn}]"

    __repr__ = __str__

    def __eq__(self, other):
        return self.zone_id == other.zone_id

    __hash__ = None


class ZoneManager:
    zone: Zone

    @cached_property
    def zones(self):
        """
        Returns:
            SelectedGrids:
        """
        return SelectedGrids([Zone(zone_id, info) for zone_id, info in DIC_OS_MAP.items()])

    def camera_to_zone(self, camera, region=None):
        """
        Args:
            camera (tuple): Point in os_globe_map.png
            region (int): Limit zone in specific region.

        Returns:
            Zone:
        """
        zones = self.zones if region is None else self.zones.select(region=region)
        zones = zones.sort_by_camera_distance(camera=camera)
        return zones[0]

    @staticmethod
    def _zone_id_from_name(name):
        if isinstance(name, int):
            return name
        if isinstance(name, str) and name.isdigit():
            return int(name)
        return None

    @staticmethod
    def _normalize_zone_name(name):
        return str(name).replace(" ", "").lower()

    def _zone_by_id(self, zone_id, name):
        try:
            return self.zones.select(zone_id=zone_id)[0]
        except IndexError as e:
            message = OS_GLOBE_ZONE_NOT_FOUND_TEMPLATE.format(name=name)
            raise ScriptError(message) from e

    def name_to_zone(self, name):
        """
        Convert a zone id or CN name to zone instance.

        Args:
            name (str, int, Zone): CN name, zone id, or Zone instance.

        Returns:
            Zone:

        Raises:
            ScriptError: If Unable to find such zone.
        """
        if isinstance(name, Zone):
            return name

        zone_id = self._zone_id_from_name(name)
        if zone_id is not None:
            return self._zone_by_id(zone_id, name)

        parsed_name = self._normalize_zone_name(name)
        for zone in self.zones:
            if parsed_name == self._normalize_zone_name(zone.cn):
                return zone

        # 普通难度：仲裁者·XXX, 困难难度：仲裁者·XXX, 困难模拟战：仲裁机关。
        if any(keyword in parsed_name for keyword in ("普通", "困难", "仲裁")):
            return self.name_to_zone(154)
        message = OS_GLOBE_ZONE_NOT_FOUND_TEMPLATE.format(name=parsed_name)
        raise ScriptError(message)

    def zone_nearest_azur_port(self, zone):
        """
        Args:
            zone (str, int, Zone): CN name, zone id, or Zone instance.

        Returns:
            Zone:
        """
        zone = self.name_to_zone(zone)
        ports = self.zones.select(is_azur_port=True).delete(SelectedGrids([self.zone]))
        # In same region
        for port in ports:
            if zone.region == port.region:
                return port
        # In different region
        ports = ports.sort_by_camera_distance(camera=tuple(zone.location))
        return ports[0]

    def zone_select(self, hazard_level):
        """
        Similar to `self.zone.select(**kwargs)`, but delete zones in region 5.

        Args:
            hazard_level: 1-6, or 10 for center zones.

        Returns:
            SelectedGrids: SelectedGrids containing zone objects.
        """
        if 1 <= hazard_level <= 6:
            return self.zones.select(hazard_level=hazard_level).delete(self.zones.select(region=5))
        if hazard_level == 10:
            return self.zones.select(region=5)
        message = INVALID_HAZARD_LEVEL_TEMPLATE.format(hazard_level=hazard_level)
        raise ScriptError(message)
