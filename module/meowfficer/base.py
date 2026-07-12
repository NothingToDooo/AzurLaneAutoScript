from typing import TYPE_CHECKING

from module.base.timer import Timer
from module.combat.assets import GET_ITEMS_1
from module.config.utils import get_server_next_update
from module.logger import logger
from module.meowfficer import assets as meow_assets
from module.ui.assets import MEOWFFICER_CHECK, MEOWFFICER_INFO
from module.ui.ui import UI

if TYPE_CHECKING:
    from module.base.button import Button


class MeowfficerBase(UI):
    def meow_additional(self) -> bool:
        return self.appear_then_click(MEOWFFICER_INFO, offset=(30, 30), interval=3)

    def meow_enter(
        self,
        click_button: Button,
        check_button: Button,
        *,
        skip_first_screenshot: bool = True,
    ) -> None:
        """从指挥喵主页进入子页，并处理信息弹窗和误入的其他子页。"""
        accident_page = [
            meow_assets.MEOWFFICER_TRAIN_START,
            meow_assets.MEOWFFICER_BUY,
            meow_assets.MEOWFFICER_FORT_CHECK,
        ]
        accident_page = [page for page in accident_page if page != check_button]
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if self.appear(check_button, offset=(20, 20)):
                break
            if self.appear_then_click(click_button, offset=(20, 20), interval=3):
                continue
            if self.meow_additional():
                continue
            for button in accident_page:
                if self.appear(button, offset=(20, 20), interval=3):
                    self.device.click(MEOWFFICER_CHECK)
                    self.interval_clear(click_button)
                    break

    def meow_menu_close(self, *, skip_first_screenshot: bool = True) -> None:
        """从强化、购买或训练等子页和弹窗退回指挥喵主页。"""
        logger.hr("Meowfficer menu close")
        click_timer = Timer(3)
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if self._meow_menu_closed():
                break
            if self._meow_menu_safe_click(click_timer):
                continue
            if self._meow_menu_handle_known_page(click_timer):
                continue
            if self._meow_menu_handle_popup(click_timer):
                continue

    def _meow_menu_closed(self) -> bool:
        return self.match_template_color(MEOWFFICER_CHECK, offset=(20, 20))

    def _meow_menu_safe_click(self, click_timer: Timer) -> bool:
        if not click_timer.reached():
            return False

        # MEOWFFICER_CHECK 可以安全点击。
        self.device.click(MEOWFFICER_CHECK)
        click_timer.reset()
        return True

    def _meow_menu_handle_known_page(self, click_timer: Timer) -> bool:
        for button in (
            meow_assets.MEOWFFICER_FORT_CHECK,
            meow_assets.MEOWFFICER_BUY,
            meow_assets.MEOWFFICER_TRAIN_FILL_QUEUE,
            meow_assets.MEOWFFICER_TRAIN_FINISH_ALL,
        ):
            if self.appear(button, offset=(20, 20), interval=3):
                self.device.click(MEOWFFICER_CHECK)
                click_timer.reset()
                return True
        return False

    def _meow_menu_handle_popup(self, click_timer: Timer) -> bool:
        for button in (meow_assets.MEOWFFICER_CONFIRM, meow_assets.MEOWFFICER_CANCEL):
            if self.appear(button, offset=(40, 20), interval=3):
                self.device.click(MEOWFFICER_CHECK)
                click_timer.reset()
                return True
        if self.appear_then_click(GET_ITEMS_1, offset=5, interval=3):
            click_timer.reset()
            return True
        if not self.meow_additional():
            return False

        click_timer.reset()
        return True

    def handle_meow_popup_confirm(self) -> bool:
        return self.appear_then_click(meow_assets.MEOWFFICER_CONFIRM, offset=(40, 20), interval=5)

    def handle_meow_popup_cancel(self) -> bool:
        return self.appear_then_click(meow_assets.MEOWFFICER_CANCEL, offset=(40, 20), interval=5)

    def handle_meow_popup_dismiss(self) -> bool:
        if self.appear(meow_assets.MEOWFFICER_CONFIRM, offset=(40, 20), interval=5) or self.appear(
            meow_assets.MEOWFFICER_CANCEL, offset=(40, 20), interval=5
        ):
            self.device.click(MEOWFFICER_CHECK)
            return True
        return False

    def meow_is_sunday(self) -> bool:
        """下一次服务器刷新落在周一即表示本次运行是周日。"""
        return get_server_next_update(self.config.Scheduler_ServerUpdate).weekday() == 0
