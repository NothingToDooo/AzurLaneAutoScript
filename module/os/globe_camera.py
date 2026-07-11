import cv2
import numpy as np

from module.base.button import Button
from module.base.timer import Timer
from module.base.utils import area_offset, point_in_area, point_limit, rgb2hsv
from module.device.control_options import SwipeVectorOptions
from module.exception import GameStuckError
from module.logger import logger
from module.os.assets import MAP_GOTO_GLOBE, MAP_GOTO_GLOBE_FOG, ZONE_PINNED
from module.os.globe_detection import GLOBE_MAP_SHAPE, GlobeDetection
from module.os.globe_operation import GlobeOperation
from module.os.globe_zone import ZoneManager
from module.os_ash.assets import ASH_QUIT, ASH_SHOWDOWN
from module.os_handler.assets import ACTION_POINT_CANCEL, ACTION_POINT_USE, AUTO_SEARCH_REWARD


class GlobeCamera(GlobeOperation, ZoneManager):
    globe: GlobeDetection
    globe_camera: tuple

    def _globe_init(self):
        """执行全局地图操作前必须先初始化检测器。"""
        if not hasattr(self, "globe"):
            self.globe = GlobeDetection(self.config)
            self.globe.load_globe_map()

    def globe_update(self):
        # 处理偶发黑屏截图。
        timeout = Timer(5, count=10).start()
        while 1:
            if timeout.reached():
                raise GameStuckError

            self.device.screenshot()

            if self.is_in_globe():
                break

            if self._globe_update_handle_blocker():
                timeout.reset()
                continue

            logger.warning("Trying to do globe_update(), but not in os globe map")
            continue

        self._globe_update_load_camera()

    def _globe_update_handle_blocker(self):
        if self._globe_update_handle_goto():
            return True
        if self._globe_update_handle_popup():
            return True
        return self._globe_update_leave_wrong_page()

    def _globe_update_handle_goto(self):
        # 逻辑来自 os_map_goto_globe()；这里也可能误入地图。
        if self.appear_then_click(MAP_GOTO_GLOBE, offset=(200, 5), interval=3):
            # 只用于初始化 MAP_GOTO_GLOBE_FOG 的 interval timer。
            self.appear(MAP_GOTO_GLOBE_FOG, interval=3)
            return True
        # 强敌据点里可能遇到；有探索奖励残留时，游戏不会阻止离开当前区域。
        if self.appear_then_click(MAP_GOTO_GLOBE_FOG, interval=3):
            self.interval_reset(MAP_GOTO_GLOBE)
            return True
        return False

    def _globe_update_handle_popup(self):
        if self.handle_map_event():
            return True
        # AUTO_SEARCH_REWARD 弹窗出现较慢。
        if self.appear_then_click(AUTO_SEARCH_REWARD, offset=(50, 50), interval=3):
            return True
        # 离开当前区域时，猫指挥搜索和潜艇可能被终止；搜索奖励会在进入新区后出现。
        return self.handle_popup_confirm("GOTO_GLOBE")

    def _globe_update_leave_wrong_page(self):
        # 不明原因误入 META 页面时退回。
        if self.appear(ASH_SHOWDOWN, offset=(20, 20), interval=3):
            self.device.click(ASH_QUIT)
            return True
        # 行动力弹窗直接取消。
        if self.appear(ACTION_POINT_USE, offset=(20, 20), interval=3):
            self.device.click(ACTION_POINT_CANCEL)
            return True
        return False

    def _globe_update_load_camera(self):
        self._globe_init()
        self.globe.load(self.device.image)
        self.globe_camera = self.globe.center_loca
        center = self.camera_to_zone(self.globe.center_loca)
        logger.attr("Globe_center", center.zone_id)

    def globe_swipe(self, vector, box=(20, 220, 980, 620)):
        name = "GLOBE_SWIPE_" + "_".join([str(round(x)) for x in vector])
        if np.linalg.norm(vector) <= 25:
            logger.warning(f"Globe swipe to short: {vector}")
            vector = np.sign(vector) * 25

        distance = self.config.MAP_SWIPE_MULTIPLY_MINITOUCH
        vector = np.array(distance) * vector

        vector = -vector
        self.device.swipe_vector(vector, SwipeVectorOptions(box=box, name=name))
        self.device.sleep(0.3)

        self.globe_update()

    def globe_wait_until_stable(self):
        prev = self.globe_camera
        interval = Timer(1)
        confirm = Timer(0.5, count=1).start()
        for _n in range(10):
            if not interval.reached():
                interval.wait()
            interval.reset()

            self.globe_update()

            # End
            if np.linalg.norm(np.subtract(self.globe_camera, prev)) < 10:
                if confirm.reached():
                    logger.info("Globe map stabled")
                    break
            else:
                confirm.reset()

            if self.handle_zone_pinned():
                continue

            prev = self.globe_camera

    def globe2screen(self, points):
        points = np.array(points) - self.globe_camera + self.globe.homo_center
        return self.globe.globe2screen(points).round()

    def screen2globe(self, points):
        points = self.globe.screen2globe(points).round()
        return points - self.globe.homo_center + self.globe_camera

    def zone_to_button(self, zone):
        pinned = self.globe2screen([zone.location])[0]
        # pinned 是实际标记位置的左下角。
        area = area_offset((0, -10, 16, 0), offset=pinned)
        return Button(area=area, color=(), button=area, name=f"ZONE_{zone.zone_id}")

    def globe_in_sight(self, zone, swipe_limit=(620, 340), sight=(20, 220, 980, 620)):
        zone = self.name_to_zone(zone)

        while 1:
            if point_in_area(self.globe2screen([zone.location])[0], area=sight):
                break

            area = (400, 200, GLOBE_MAP_SHAPE[0] - 400, GLOBE_MAP_SHAPE[1] - 250)
            loca = point_limit(zone.location, area=area)
            vector = np.array(loca) - self.globe_camera
            vector = vector / self.config.OS_GLOBE_SWIPE_MULTIPLY
            swipe = tuple(np.min([np.abs(vector), swipe_limit], axis=0) * np.sign(vector))
            self.globe_swipe(swipe)

    def get_globe_pinned_zone(self):
        location = self.screen2globe([ZONE_PINNED.button[:2]])[0] + (0, 5)
        return self.camera_to_zone(location)

    def globe_wait_until_zone_pinned(self, zone, skip_first_screenshot=True):
        """等待指定海域被钉选；超时返回 False。"""
        zone = self.name_to_zone(zone)
        timeout = Timer(5, count=5).start()
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()
                self.globe_update()

            if self.is_zone_pinned() and self.get_globe_pinned_zone() == zone:
                logger.attr("Globe_pinned", zone)
                return True
            if timeout.reached():
                logger.warning("Wait until zone pinned timeout")
                return False
        return False

    def globe_focus_to(self, zone):
        """先调用 globe_update，再把全局地图聚焦并钉选指定海域。

        页面保持在 IN_GLOBE，结束时显示 ZONE_ENTRANCE。
        """
        zone = self.name_to_zone(zone)
        logger.info(f"Globe focus_to: {zone.zone_id}")

        while 1:
            if self.handle_zone_pinned():
                self.globe_update()
                continue

            # Insight
            self.globe_in_sight(zone)
            # Click zone
            button = self.zone_to_button(zone)
            self.device.click(button)
            # Wait until zone pinned
            if self.globe_wait_until_zone_pinned(zone):
                break

    def _globe_predict_stronghold(self, zone):
        """调用前必须先用 globe_in_sight 把海域移入视野。"""
        zone = self.name_to_zone(zone)
        # The center of red whirlpool, on 2D map.
        location = np.add(zone.location, (-9.5, -12.5))
        # Area around the center, on 2D map.
        location = [np.subtract(location, (4, 4)), np.add(location, (4, 4))]
        # 取屏幕上的中心邻域。
        screen = self.globe2screen(location).flatten().round()
        screen = np.round(screen).astype(int).tolist()
        # 取漩涡中心的平均颜色。
        center = self.image_crop(screen, copy=False)
        center = np.array(
            [
                [
                    cv2.mean(center),
                ],
            ]
        ).astype(np.uint8)
        h, s, v = rgb2hsv(center)[0][0]
        # 漩涡中心通常接近 HSV (338, 74.9, 100)。
        return bool(285 < h <= 360 and s > 45 and v > 45)

    def _find_siren_stronghold(self, zones):
        """调用前必须先执行 globe_update；找到后仍在全局地图并钉选目标。"""
        sight = (20, 220, 980, 620)
        while zones:
            prev = self.camera_to_zone(self.globe_camera)
            zone = zones.sort_by_camera_distance(prev.location)[0]
            logger.info(f"Find siren stronghold around {zone}")
            self.globe_in_sight(zone, sight=sight)

            to_check = zones.filter(lambda z: point_in_area(self.globe2screen([z.location])[0], area=sight))
            for zone in to_check:
                if self._globe_predict_stronghold(zone):
                    logger.info(f"Zone {zone.zone_id} is a siren stronghold")
                    self.globe_focus_to(zone)
                    if self.get_zone_pinned_name() == "STRONGHOLD":
                        logger.info("Confirm it is a siren stronghold")
                        return zone
                    logger.warning("Not a siren stronghold, continue searching")
                    self.ensure_no_zone_pinned()
                else:
                    logger.info(f"Zone {zone.zone_id} is not a siren stronghold")

            zones = zones.delete(to_check)

        logger.info("Find siren stronghold finished")
        return None

    def find_siren_stronghold(self):
        """在全局地图查找要塞；找到后钉选目标，找不到返回 None。"""
        logger.hr("Find siren stronghold", level=1)
        region = self.camera_to_zone(self.globe_camera).region
        order = [1, 2, 4, 3]
        if region not in order:
            # Camera may focus on region 5, select the nearest non-region-5 zone
            zones = (
                self.zones.delete(self.zones.select(region=5))
                .delete(self.zones.select(is_port=True))
                .sort_by_camera_distance(self.globe_camera)
            )
            region = zones[0].region

        index = order.index(region)
        order = order * 2
        order = order[index : index + 4]
        for region in order:
            logger.hr(f"Find siren stronghold in region {region}", level=2)
            zones = self.zones.select(region=region, is_port=False)
            result = self._find_siren_stronghold(zones)
            if result is not None:
                return result

        logger.info("No more siren stronghold")
        return None
