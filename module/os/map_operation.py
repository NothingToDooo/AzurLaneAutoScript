from typing import TYPE_CHECKING

from module.base.timer import Timer
from module.base.utils import color_bar_percentage
from module.exception import MapDetectionError, ScriptError
from module.logger import logger
from module.ocr.ocr import Ocr
from module.os.assets import MAP_EXIT, MAP_NAME, MEOWFFICER_SEARCHING, MEOWFFICER_SEARCHING_PERCENTAGE
from module.os.map_fleet_selector import OSFleetSelector
from module.os_handler.assets import AUTO_SEARCH_REWARD, EXCHANGE_CHECK
from module.os_handler.map_order import MapOrderHandler
from module.os_handler.mission import MissionHandler
from module.os_handler.port import PortHandler
from module.os_handler.storage import StorageHandler
from module.ui.assets import BACK_ARROW, OS_CHECK

if TYPE_CHECKING:
    from module.os.globe_zone import Zone

ZONE_NAME_EDGE_CHARS = "\\/-—–－"
ZONE_NAME_CN_SUFFIX_CHARS = "安全隐秘塞壬要塞深渊海域-"


def strip_zone_name_edges(name):
    start = 0
    end = len(name)
    while start < end and name[start] in ZONE_NAME_EDGE_CHARS:
        start += 1
    while end > start and name[end - 1] in ZONE_NAME_EDGE_CHARS:
        end -= 1
    return name[start:end]


def rstrip_zone_name_chars(name, chars):
    end = len(name)
    while end > 0 and name[end - 1] in chars:
        end -= 1
    return name[:end]


class OSMapOperation(MapOrderHandler, MissionHandler, PortHandler, StorageHandler, OSFleetSelector):
    zone: Zone
    is_zone_name_hidden = False

    def is_meowfficer_searching(self):
        """
        Returns:
            bool:

        Page:
            in: IN_MAP
        """
        return self.appear(MEOWFFICER_SEARCHING, offset=(10, 10))

    def get_meowfficer_searching_percentage(self):
        """
        Returns:
            float: 0 to 1.

        Pages:
            in: IN_MAP, is_meowfficer_searching == True
        """
        return color_bar_percentage(
            self.device.image, area=MEOWFFICER_SEARCHING_PERCENTAGE.area, prev_color=(74, 223, 255)
        )

    def get_zone_name(self):
        ocr = Ocr(MAP_NAME, lang="cnocr", letter=(214, 231, 255), threshold=127, name="OCR_OS_MAP_NAME")
        name = ocr.ocr(self.device.image)
        name = strip_zone_name_edges(name)
        self.is_zone_name_hidden = "安全" in name
        return name.split("-", 1)[0] if "-" in name else rstrip_zone_name_chars(name, ZONE_NAME_CN_SUFFIX_CHARS)

    def get_current_zone(self):
        """
        Returns:
            Zone:

        Raises:
            MapDetectionError: If failed to parse zone name.
            ScriptError:
        """
        name = self.get_zone_name()
        logger.info(f"Map name processed: {name}")
        try:
            self.zone = self.name_to_zone(name)
        except ScriptError as e:
            raise MapDetectionError(*e.args) from e
        logger.attr("Zone", self.zone)
        self.zone_config_set()
        return self.zone

    def zone_config_set(self):
        if self.zone.region == 5:
            self.config.HOMO_EDGE_COLOR_RANGE = (0, 8)
            self.config.MAP_ENSURE_EDGE_INSIGHT_CORNER = "bottom"
        else:
            self.config.HOMO_EDGE_COLOR_RANGE = (0, 33)
            self.config.MAP_ENSURE_EDGE_INSIGHT_CORNER = ""

    def _handle_zone_init_blocker(self, timeout):
        # 这些可见状态会挡住地图名 OCR，先处理再重试。
        if self.handle_map_event():
            timeout.reset()
            return True
        if self.appear_then_click(AUTO_SEARCH_REWARD, offset=(50, 50), interval=3):
            return True
        if self.is_in_globe():
            self.os_globe_goto_map()
            timeout.reset()
            return True
        if self.appear(EXCHANGE_CHECK, offset=(30, 30), interval=3):
            self.device.click(BACK_ARROW)
            timeout.reset()
            return True
        if self.is_in_map() and not self.appear(OS_CHECK, offset=(20, 20)):
            self.wait_until_appear(OS_CHECK)
            timeout.reset()
            return True
        return False

    def _try_get_current_zone_from_map(self, timeout):
        if not self.is_in_map():
            timeout.reset()
            return None
        try:
            return self.get_current_zone()
        except MapDetectionError:
            return None

    def _fallback_zone_init(self, fallback_init):
        if not fallback_init:
            return None
        logger.warning("Unable to get zone name, get current zone from globe map instead")
        if hasattr(self, "get_current_zone_from_globe"):
            return self.get_current_zone_from_globe()
        logger.warning("OperationSiren.get_current_zone_from_globe() not exists")
        if not self.is_in_map():
            logger.warning("Trying to get zone name, but not in OS map")
        return self.get_current_zone()

    def zone_init(self, fallback_init=True):
        """
        Wrap get_current_zone(), set self.zone to the current zone.
        This method must be called after entering a new zone.
        Handle map events and the animation that zone names appear from the top.

        Args:
            fallback_init (bool): Whether to get zone from globe map when unable to parse zone name.

        Returns:
            Zone: Current zone.

        Raises:
            MapDetectionError: If failed to parse zone name.
        """
        logger.hr("Zone init")
        self.wait_os_map_buttons()
        logger.info("Get zone name")
        timeout = Timer(1.5, count=5).start()
        for _ in self.loop():
            if self._handle_zone_init_blocker(timeout):
                continue

            if timeout.reached():
                logger.warning("Zone init timeout")
                break
            zone = self._try_get_current_zone_from_map(timeout)
            if zone is not None:
                return zone

        return self._fallback_zone_init(fallback_init)

    def is_in_special_zone(self):
        """
        Returns:
            bool: If in an obscure zone, abyssal zone, or stronghold.
        """
        return self.appear(MAP_EXIT, offset=(20, 20))

    def map_exit(self):
        """
        Exit from an obscure zone, abyssal zone, or stronghold.

        Pages:
            in: is_in_map
            out: is_in_map, zone that you came from
        """
        logger.hr("Map exit")
        confirm_timer = Timer(1, count=2)
        changed = False
        for _ in self.loop():
            # End
            if changed and self.is_in_map():
                if confirm_timer.reached():
                    break
            else:
                confirm_timer.reset()
            # If MAP_EXIT still appears, we haven't exit this zone yet
            if self.appear(MAP_EXIT, offset=(20, 20)):
                confirm_timer.reset()

            # Click
            if self.appear_then_click(MAP_EXIT, offset=(20, 20), interval=3):
                continue
            if self.handle_popup_confirm("MAP_EXIT"):
                self.interval_reset(MAP_EXIT)
                continue
            if self.appear_then_click(AUTO_SEARCH_REWARD, offset=(50, 50)):
                # Sometimes appeared
                self.device.screenshot_interval_set()
                continue
            if self.handle_map_event():
                self.interval_reset(MAP_EXIT)
                changed = True
                continue

        self.zone_init()
