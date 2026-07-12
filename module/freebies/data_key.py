from module.combat.assets import GET_ITEMS_1
from module.freebies import assets as freebies_assets
from module.logger import logger
from module.ocr.ocr import DigitCounter
from module.ui.assets import CAMPAIGN_MENU_GOTO_WAR_ARCHIVES, WAR_ARCHIVES_CHECK
from module.ui.page import page_archives, page_campaign_menu
from module.ui.ui import UI

DATA_KEY = DigitCounter(freebies_assets.OCR_DATA_KEY, letter=(255, 247, 247), threshold=64)


class DataKey(UI):
    def _data_key_collect(self, *, skip_first_screenshot: bool = True) -> None:
        """在档案页领取数据钥匙，结束时仍在档案页并显示 DATA_KEY_COLLECTED。"""
        logger.hr("Data Key Collect")
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if self.appear_then_click(freebies_assets.DATA_KEY_COLLECT, offset=(20, 20), interval=3):
                continue
            if self.appear(GET_ITEMS_1, offset=20, interval=3):
                self.device.click(freebies_assets.DATA_KEY_COLLECT)
                continue
            if self.handle_popup_confirm("DATA_KEY_LIMIT"):
                # 接近 30 把上限说明档案使用不频繁，允许少量溢出并直接补满。
                continue
            if self.appear_then_click(CAMPAIGN_MENU_GOTO_WAR_ARCHIVES, offset=(20, 20), interval=3):
                # 游戏偶尔会误退到战役菜单，重新进入档案页。
                continue

            if self.appear(WAR_ARCHIVES_CHECK, offset=(20, 20)) and self.appear(
                freebies_assets.DATA_KEY_COLLECTED, offset=(20, 20)
            ):
                logger.info("Data key collect finished")
                break

    def data_key_collect(self) -> bool:
        """在档案页按容量领取数据钥匙；ForceCollect 可忽略满容量，未领取返回 False。"""
        if self.appear(freebies_assets.DATA_KEY_COLLECTED, offset=(20, 20)):
            logger.info("Data key has been collected")
            return False

        current, remain, total = DATA_KEY.ocr(self.device.image)
        logger.info(f"Inventory: {current} / {total}, Remain: {remain}")
        if not self.config.DataKey_ForceCollect and remain <= 0:
            logger.info("No more room for additional data key")
            return False

        self._data_key_collect()
        return True

    def run(self) -> None:
        """从任意页面进入档案页处理数据钥匙。"""
        self.ui_ensure(page_archives)

        self.data_key_collect()

        # 清除页面点击间隔，避免下一次 ui_goto() 被旧计时拖慢。
        self.interval_clear([page_archives.check_button, page_campaign_menu.check_button])
