from module.base.utils import get_color
from module.logger import logger
from module.os_handler import assets as os_assets
from module.os_handler.map_event import MapEventHandler
from module.ui.scroll import Scroll

STRATEGIC_SEARCH_SCROLL = Scroll(
    os_assets.STRATEGIC_SEARCH_SCROLL_AREA, color=(247, 211, 66), name="STRATEGIC_SEARCH_SCROLL"
)


class StrategicSearchHandler(MapEventHandler):
    def strategy_search_enter(self):
        logger.info("Strategic search enter")
        self.interval_clear(os_assets.STRATEGIC_SEARCH_MAP_OPTION_OFF)
        for _ in self.loop():
            if self.appear(os_assets.STRATEGIC_SEARCH_POPUP_CHECK, offset=(20, 20)):
                return True

            if self.handle_map_event():
                continue
            if self.appear(os_assets.AUTO_SEARCH_REWARD, offset=(50, 50)):
                continue
            if self.match_template_color(os_assets.STRATEGIC_SEARCH_MAP_OPTION_OFF, offset=(20, 20), interval=2):
                self.device.click(os_assets.STRATEGIC_SEARCH_MAP_OPTION_OFF)
                continue
        return False

    def strategic_search_set_tab(self):
        logger.info("Strategic search set tab")
        for _ in self.loop():
            tab_blue = get_color(self.device.image, os_assets.STRATEGIC_SEARCH_TAB_SECURED.area)[2]
            if tab_blue <= 150:
                self.device.click(os_assets.STRATEGIC_SEARCH_TAB_SECURED)
                continue
            if tab_blue > 150:
                break

    def _strategy_search_scroll_appear(self):
        for _ in self.loop(timeout=2):
            if STRATEGIC_SEARCH_SCROLL.appear(main=self):
                return True
            logger.warning("STRATEGIC_SEARCH_SCROLL disappeared")
        logger.warning("STRATEGIC_SEARCH_SCROLL disappeared confirm")
        return False

    def _strategy_option_selected(self, button):
        return self.image_color_count(button.button, color=(156, 255, 82), count=30)

    def strategic_search_set_option(self):
        """设置页异常关闭时返回 False。"""
        logger.info("Strategic search set option")
        self._strategic_search_set_zone_and_merchant()
        if not self._strategic_search_scroll_to_device():
            return False
        self._strategic_search_set_device()
        if not self._strategic_search_scroll_to_submit():
            return False
        self._strategic_search_set_submit()
        return True

    def _strategic_search_set_zone_and_merchant(self):
        selected = self._strategy_option_selected
        for _ in self.loop():
            if selected(os_assets.STRATEGIC_SEARCH_ZONEMODE_REPEAT) and selected(
                os_assets.STRATEGIC_SEARCH_MERCHANT_STOP
            ):
                logger.attr("zone_mode", "repeat")
                logger.attr("encounter_merchant", "stop")
                break
            if selected(os_assets.STRATEGIC_SEARCH_ZONEMODE_RANDOM):
                logger.attr("zone_mode", "random")
                self.device.click(os_assets.STRATEGIC_SEARCH_ZONEMODE_REPEAT)
                continue
            if selected(os_assets.STRATEGIC_SEARCH_MERCHANT_CONTINUE):
                logger.attr("encounter_merchant", "continue")
                self.device.click(os_assets.STRATEGIC_SEARCH_MERCHANT_STOP)
                continue

    def _strategic_search_scroll_to_device(self):
        STRATEGIC_SEARCH_SCROLL.drag_threshold = 0.1
        STRATEGIC_SEARCH_SCROLL.set(0.5, main=self)
        return self._strategy_search_scroll_appear()

    def _strategic_search_set_device(self):
        selected = self._strategy_option_selected
        for _ in self.loop():
            self._strategic_search_refresh_device_offsets()

            if selected(os_assets.STRATEGIC_SEARCH_DEVICE_STOP):
                logger.attr("encounter_device", "stop")
                break
            if selected(os_assets.STRATEGIC_SEARCH_DEVICE_CONTINUE):
                logger.attr("encounter_device", "continue")
                self.device.click(os_assets.STRATEGIC_SEARCH_DEVICE_STOP)
                continue

    def _strategic_search_refresh_device_offsets(self):
        self.appear(os_assets.STRATEGIC_SEARCH_DEVICE_CHECK, offset=(20, 200), similarity=0.7)
        os_assets.STRATEGIC_SEARCH_DEVICE_STOP.load_offset(os_assets.STRATEGIC_SEARCH_DEVICE_CHECK)
        os_assets.STRATEGIC_SEARCH_DEVICE_CONTINUE.load_offset(os_assets.STRATEGIC_SEARCH_DEVICE_CHECK)

    def _strategic_search_scroll_to_submit(self):
        STRATEGIC_SEARCH_SCROLL.drag_threshold = 0.05
        STRATEGIC_SEARCH_SCROLL.edge_add = (0.5, 0.8)
        STRATEGIC_SEARCH_SCROLL.set_bottom(main=self)
        return self._strategy_search_scroll_appear()

    def _strategic_search_set_submit(self):
        selected = self._strategy_option_selected
        for _ in self.loop():
            self._strategic_search_refresh_submit_offsets()

            if selected(os_assets.STRATEGIC_SEARCH_SUBMIT_ON):
                logger.attr("auto_submit", "on")
                break
            if selected(os_assets.STRATEGIC_SEARCH_SUBMIT_OFF):
                logger.attr("auto_submit", "off")
                self.device.click(os_assets.STRATEGIC_SEARCH_SUBMIT_ON)
                continue

    def _strategic_search_refresh_submit_offsets(self):
        self.appear(os_assets.STRATEGIC_SEARCH_SUBMIT_CHECK, offset=(20, 20), similarity=0.7)
        os_assets.STRATEGIC_SEARCH_SUBMIT_OFF.load_offset(os_assets.STRATEGIC_SEARCH_SUBMIT_CHECK)
        os_assets.STRATEGIC_SEARCH_SUBMIT_ON.load_offset(os_assets.STRATEGIC_SEARCH_SUBMIT_CHECK)

    def strategic_search_confirm(self):
        logger.info("Strategic search confirm")
        for _ in self.loop():
            if self.appear(os_assets.STRATEGIC_SEARCH_POPUP_CHECK, offset=(20, 20)) and self.handle_popup_confirm(
                offset=(30, 30), name="STRATEGIC_SEARCH"
            ):
                continue
            if self.is_in_map():
                return True
        return False

    def strategic_search_start(self):
        """在区域地图启动战略搜索，三次失败后返回 False。"""
        logger.hr("Strategic search start")
        for _ in range(3):
            self.strategy_search_enter()
            self.strategic_search_set_tab()
            success = self.strategic_search_set_option()
            if not success:
                continue
            self.strategic_search_confirm()
            return True

        logger.warning("Failed to start strategic search")
        return False
