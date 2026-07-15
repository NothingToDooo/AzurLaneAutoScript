from module.meowfficer.assets import MEOWFFICER_BUY_ENTER
from module.meowfficer.buy import MeowfficerBuy
from module.meowfficer.fort import MeowfficerFort
from module.meowfficer.train import MeowfficerTrain


class RewardMeowfficer(MeowfficerBuy, MeowfficerFort, MeowfficerTrain):
    def wait_meowfficer_buttons(self, *, skip_first_screenshot: bool = True) -> None:
        """MEOWFFICER_INFO 和购买入口比主页检查点加载更慢，需额外等待。"""
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if self.appear(MEOWFFICER_BUY_ENTER, offset=(20, 20)):
                break

            if self.ui_additional():
                continue
