from module.meowfficer.assets import MEOWFFICER_BUY_ENTER
from module.meowfficer.buy import MeowfficerBuy
from module.meowfficer.fort import MeowfficerFort
from module.meowfficer.train import MeowfficerTrain
from module.ui.page import page_meowfficer


class RewardMeowfficer(MeowfficerBuy, MeowfficerFort, MeowfficerTrain):
    def wait_meowfficer_buttons(self, skip_first_screenshot=True):
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

    def run(self):
        """从任意页面执行已启用的购买、强化、训练和猫窝任务，结束于指挥喵主页。"""
        if (
            self.config.Meowfficer_BuyAmount <= 0
            and self.config.Meowfficer_OverflowCoins < 0
            and not self.config.Meowfficer_FortChoreMeowfficer
            and not self.config.MeowfficerTrain_Enable
        ):
            self.config.Scheduler_Enable = False
            self.config.task_stop()

        self.ui_ensure(page_meowfficer)
        self.wait_meowfficer_buttons()

        if self.config.Meowfficer_BuyAmount > 0 or self.config.Meowfficer_OverflowCoins >= 0:
            self.meow_buy()
        if self.config.Meowfficer_FortChoreMeowfficer:
            self.meow_fort()

        if self.config.MeowfficerTrain_Enable:
            self.meow_train()
            if self.config.MeowfficerTrain_Mode == "seamlessly" or self.meow_is_sunday():
                self.meow_enhance()

        if self.config.MeowfficerTrain_Enable:
            # 蓝、紫、金箱约需 2～2.5、5.5～6.5、9.5～10.5 小时；训练中每 2.5～3.5 小时检查。
            self.config.task_delay(minute=(150, 210), server_update=True)
        else:
            self.config.task_delay(server_update=True)
