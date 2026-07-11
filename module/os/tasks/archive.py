from typing import TYPE_CHECKING

from module.config.utils import get_nearest_weekday_date
from module.logger import logger
from module.os.map import OSMap
from module.os_handler.assets import EXCHANGE_CHECK, EXCHANGE_ENTER
from module.shop.shop_voucher import VoucherShop


class OpsiArchive(OSMap):
    if TYPE_CHECKING:

        def os_finish_daily_mission(self, question=True, rescan=None) -> int: ...

    def _os_voucher_enter(self):
        self.os_map_goto_globe(unpin=False)
        self.ui_click(
            click_button=EXCHANGE_ENTER,
            check_button=EXCHANGE_CHECK,
            offset=(200, 20),
            retry_wait=3,
            skip_first_screenshot=True,
        )

    def _os_voucher_exit(self):
        self.ui_back(
            check_button=EXCHANGE_ENTER,
            appear_button=EXCHANGE_CHECK,
            offset=(200, 20),
            retry_wait=3,
            skip_first_screenshot=True,
        )
        self.os_globe_goto_map()

    def os_archive(self):
        """每周清理已有档案海域，并重复购买、清理新档案直至售罄。"""
        if self.is_in_opsi_explore():
            logger.info("OpsiExplore is under scheduling, stop OpsiArchive")
            self.config.task_delay(server_update=True)
            self.config.task_stop()

        shop = VoucherShop(self.config, self.device)
        while True:
            # 先处理可能由手动购买留下的档案海域。
            self.os_finish_daily_mission(question=False, rescan=False)

            logger.hr("OS voucher", level=1)
            self._os_voucher_enter()
            bought = shop.run_once()
            self._os_voucher_exit()
            if not bought:
                break

        # 周三再检查维护后可能新增的档案。
        next_reset = get_nearest_weekday_date(target=2)
        logger.info("All archive zones finished, delay to next reset")
        logger.attr("OpsiNextReset", next_reset)
        self.config.task_delay(target=next_reset)
