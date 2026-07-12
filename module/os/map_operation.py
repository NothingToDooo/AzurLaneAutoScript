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


def strip_zone_name_edges(name: str) -> str:
    start = 0
    end = len(name)
    while start < end and name[start] in ZONE_NAME_EDGE_CHARS:
        start += 1
    while end > start and name[end - 1] in ZONE_NAME_EDGE_CHARS:
        end -= 1
    return name[start:end]


def rstrip_zone_name_chars(name: str, chars: str) -> str:
    end = len(name)
    while end > 0 and name[end - 1] in chars:
        end -= 1
    return name[:end]


class OSMapOperation(MapOrderHandler, MissionHandler, PortHandler, StorageHandler, OSFleetSelector):
    zone: Zone
    is_zone_name_hidden = False

    def get_current_zone_from_globe(self) -> Zone:
        message = f"{type(self).__name__} must implement get_current_zone_from_globe()"
        raise NotImplementedError(message)

    def is_meowfficer_searching(self) -> bool:
        """在区域地图返回猫指挥搜索是否进行中。"""
        return self.appear(MEOWFFICER_SEARCHING, offset=(10, 10))

    def get_meowfficer_searching_percentage(self) -> float:
        """在猫指挥搜索进行中返回进度，范围为 0 至 1。"""
        return color_bar_percentage(
            self.device.image, area=MEOWFFICER_SEARCHING_PERCENTAGE.area, prev_color=(74, 223, 255)
        )

    def get_zone_name(self) -> str:
        ocr = Ocr(MAP_NAME, lang="cnocr", letter=(214, 231, 255), threshold=127, name="OCR_OS_MAP_NAME")
        name = ocr.ocr_single(self.device.image)
        name = strip_zone_name_edges(name)
        self.is_zone_name_hidden = "安全" in name
        return name.split("-", 1)[0] if "-" in name else rstrip_zone_name_chars(name, ZONE_NAME_CN_SUFFIX_CHARS)

    def get_current_zone(self) -> Zone:
        """返回当前 Zone；海域名解析失败时抛出 MapDetectionError 或 ScriptError。"""
        name = self.get_zone_name()
        logger.info(f"Map name processed: {name}")
        try:
            self.zone = self.name_to_zone(name)
        except ScriptError as e:
            raise MapDetectionError(*e.args) from e
        logger.attr("Zone", self.zone)
        self.zone_config_set()
        return self.zone

    def zone_config_set(self) -> None:
        if self.zone.region == 5:
            self.config.HOMO_EDGE_COLOR_RANGE = (0, 8)
            self.config.MAP_ENSURE_EDGE_INSIGHT_CORNER = "bottom"
        else:
            self.config.HOMO_EDGE_COLOR_RANGE = (0, 33)
            self.config.MAP_ENSURE_EDGE_INSIGHT_CORNER = ""

    def _handle_zone_init_blocker(self, timeout: Timer) -> bool:
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

    def _try_get_current_zone_from_map(self, timeout: Timer) -> Zone | None:
        if not self.is_in_map():
            timeout.reset()
            return None
        try:
            return self.get_current_zone()
        except MapDetectionError:
            return None

    def _fallback_zone_init(self, *, fallback_init: bool) -> Zone | None:
        if not fallback_init:
            return None
        logger.warning("Unable to get zone name, get current zone from globe map instead")
        return self.get_current_zone_from_globe()

    def zone_init(self, *, fallback_init: bool = True) -> Zone | None:
        """进入新海域后初始化 self.zone，并处理地图事件和海域名动画。

        解析失败时，fallback_init 控制是否从全球地图兜底；仍失败则抛出 MapDetectionError。
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

        return self._fallback_zone_init(fallback_init=fallback_init)

    def is_in_special_zone(self) -> bool:
        """返回当前是否位于隐秘、深渊或要塞海域。"""
        return self.appear(MAP_EXIT, offset=(20, 20))

    def map_exit(self) -> None:
        """从特殊海域退出到进入前的普通海域，结束时仍在区域地图。"""
        logger.hr("Map exit")
        confirm_timer = Timer(1, count=2)
        changed = False
        for _ in self.loop():
            if changed and self.is_in_map():
                if confirm_timer.reached():
                    break
            else:
                confirm_timer.reset()
            # MAP_EXIT 仍出现说明尚未离开特殊海域。
            if self.appear(MAP_EXIT, offset=(20, 20)):
                confirm_timer.reset()

            if self.appear_then_click(MAP_EXIT, offset=(20, 20), interval=3):
                continue
            if self.handle_popup_confirm("MAP_EXIT"):
                self.interval_reset(MAP_EXIT)
                continue
            if self.appear_then_click(AUTO_SEARCH_REWARD, offset=(50, 50)):
                # 自动搜索奖励可能在退出过程中延迟出现。
                self.device.screenshot_interval_set()
                continue
            if self.handle_map_event():
                self.interval_reset(MAP_EXIT)
                changed = True
                continue

        self.zone_init()
