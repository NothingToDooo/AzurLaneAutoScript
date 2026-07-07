from module.config import server
from module.ocr.ocr import Digit
from module.shop.assets import SHOP_GEMS, SHOP_OCR_BALANCE, SHOP_VOUCHER
from module.ui.ui import UI

if server.server != "jp":
    OCR_SHOP_GEMS = Digit(SHOP_GEMS, letter=(255, 243, 82), name="OCR_SHOP_GEMS")
else:
    OCR_SHOP_GEMS = Digit(SHOP_GEMS, letter=(190, 180, 82), name="OCR_SHOP_GEMS")
# UI update in 20250814, but server TW is still old UI.
if server.server == "jp":
    OCR_SHOP_GOLD_COINS = Digit(SHOP_OCR_BALANCE, letter=(110, 120, 130), name="OCR_SHOP_GOLD_COINS")
    OCR_SHOP_MEDAL = Digit(SHOP_OCR_BALANCE, letter=(110, 120, 130), name="OCR_SHOP_MEDAL")
    OCR_SHOP_MERIT = Digit(SHOP_OCR_BALANCE, letter=(110, 120, 130), name="OCR_SHOP_MERIT")
    OCR_SHOP_GUILD_COINS = Digit(SHOP_OCR_BALANCE, letter=(110, 120, 130), name="OCR_SHOP_GUILD_COINS")
    OCR_SHOP_CORE = Digit(SHOP_OCR_BALANCE, letter=(110, 120, 130), name="OCR_SHOP_CORE")
else:
    OCR_SHOP_GOLD_COINS = Digit(SHOP_OCR_BALANCE, letter=(100, 100, 100), name="OCR_SHOP_GOLD_COINS")
    OCR_SHOP_MEDAL = Digit(SHOP_OCR_BALANCE, letter=(100, 100, 100), name="OCR_SHOP_MEDAL")
    OCR_SHOP_MERIT = Digit(SHOP_OCR_BALANCE, letter=(100, 100, 100), name="OCR_SHOP_MERIT")
    OCR_SHOP_GUILD_COINS = Digit(SHOP_OCR_BALANCE, letter=(100, 100, 100), name="OCR_SHOP_GUILD_COINS")
    OCR_SHOP_CORE = Digit(SHOP_OCR_BALANCE, letter=(100, 100, 100), name="OCR_SHOP_CORE")

OCR_SHOP_VOUCHER = Digit(SHOP_VOUCHER, letter=(255, 255, 255), name="OCR_SHOP_VOUCHER")


class ShopStatus(UI):
    def status_get_gold_coins(self):
        """读取金币数量。"""
        return OCR_SHOP_GOLD_COINS.ocr(self.device.image)

    def status_get_gems(self):
        """读取钻石数量。"""
        return OCR_SHOP_GEMS.ocr(self.device.image)

    def status_get_medal(self):
        """读取勋章数量。"""
        return OCR_SHOP_MEDAL.ocr(self.device.image)

    def status_get_merit(self):
        """读取功勋数量。"""
        return OCR_SHOP_MERIT.ocr(self.device.image)

    def status_get_guild_coins(self):
        """读取舰队币数量。"""
        return OCR_SHOP_GUILD_COINS.ocr(self.device.image)

    def status_get_core(self):
        """读取核心数据数量。"""
        return OCR_SHOP_CORE.ocr(self.device.image)

    def status_get_voucher(self):
        """读取兑换券数量。"""
        return OCR_SHOP_VOUCHER.ocr(self.device.image)
