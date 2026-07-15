from module.os.map import OSMap
from module.os_handler.assets import EXCHANGE_CHECK, EXCHANGE_ENTER


class OpsiVoucher(OSMap):
    def _os_voucher_enter(self) -> None:
        self.os_map_goto_globe(unpin=False)
        self.ui_click(
            click_button=EXCHANGE_ENTER,
            check_button=EXCHANGE_CHECK,
            offset=(200, 20),
            retry_wait=3,
            skip_first_screenshot=True,
        )

    def _os_voucher_exit(self) -> None:
        self.ui_back(
            check_button=EXCHANGE_ENTER,
            appear_button=EXCHANGE_CHECK,
            offset=(200, 20),
            retry_wait=3,
            skip_first_screenshot=True,
        )
        self.os_globe_goto_map()
