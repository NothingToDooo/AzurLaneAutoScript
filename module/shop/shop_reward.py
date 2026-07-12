from module.shop.shop_core import CoreShop250814
from module.shop.shop_general import GeneralShop250814
from module.shop.shop_guild import GuildShop250814
from module.shop.shop_medal import MedalShop2V250814
from module.shop.shop_merit import MeritShop250814
from module.shop.ui import ShopUI


class RewardShop(ShopUI):
    def run_frequent(self) -> None:
        self.ui_goto_shop()
        self.device.click_record_clear()
        self.shop_nav_250814.set("general", main=self)
        self.shop_tab_250814.set("general", main=self)
        GeneralShop250814(self.config, self.device).run()

        self.config.task_delay(server_update=True)

    def run_once(self) -> None:
        self.ui_goto_shop()
        self.device.click_record_clear()
        self.shop_nav_250814.set("general", main=self)
        self.shop_tab_250814.set("merit", main=self)
        MeritShop250814(self.config, self.device).run()

        self.device.click_record_clear()
        self.shop_nav_250814.set("general", main=self)
        self.shop_tab_250814.set("guild", main=self)
        GuildShop250814(self.config, self.device).run()

        self.device.click_record_clear()
        self.shop_nav_250814.set("monthly", main=self)
        self.shop_tab_250814.set("core_monthly", main=self)
        CoreShop250814(self.config, self.device).run()

        self.device.click_record_clear()
        self.shop_nav_250814.set("monthly", main=self)
        self.shop_tab_250814.set("medal", main=self)
        MedalShop2V250814(self.config, self.device).run()

        self.config.task_delay(server_update=True)


if __name__ == "__main__":
    self = RewardShop("alas")
    self.device.screenshot()
    self.run_once()
