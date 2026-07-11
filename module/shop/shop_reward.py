from module.shop.assets import NAV_GENERAL, NAV_MONTHLY, TAB_CORE_MONTHLY, TAB_GENERAL, TAB_GUILD, TAB_MEDAL, TAB_MERIT
from module.shop.shop_core import CoreShop250814
from module.shop.shop_general import GeneralShop250814
from module.shop.shop_guild import GuildShop250814
from module.shop.shop_medal import MedalShop2V250814
from module.shop.shop_merit import MeritShop250814
from module.shop.ui import ShopUI


class RewardShop(ShopUI):
    def run_frequent(self):
        self.ui_goto_shop()
        self.device.click_record_clear()
        self.shop_nav_250814.set(NAV_GENERAL, main=self)
        self.shop_tab_250814.set(TAB_GENERAL, main=self)
        GeneralShop250814(self.config, self.device).run()

        self.config.task_delay(server_update=True)

    def run_once(self):
        self.ui_goto_shop()
        self.device.click_record_clear()
        self.shop_nav_250814.set(NAV_GENERAL, main=self)
        self.shop_tab_250814.set(TAB_MERIT, main=self)
        MeritShop250814(self.config, self.device).run()

        self.device.click_record_clear()
        self.shop_nav_250814.set(NAV_GENERAL, main=self)
        self.shop_tab_250814.set(TAB_GUILD, main=self)
        GuildShop250814(self.config, self.device).run()

        self.device.click_record_clear()
        self.shop_nav_250814.set(NAV_MONTHLY, main=self)
        self.shop_tab_250814.set(TAB_CORE_MONTHLY, main=self)
        CoreShop250814(self.config, self.device).run()

        self.device.click_record_clear()
        self.shop_nav_250814.set(NAV_MONTHLY, main=self)
        self.shop_tab_250814.set(TAB_MEDAL, main=self)
        MedalShop2V250814(self.config, self.device).run()

        self.config.task_delay(server_update=True)


if __name__ == "__main__":
    self = RewardShop("alas")
    self.device.screenshot()
    self.run_once()
