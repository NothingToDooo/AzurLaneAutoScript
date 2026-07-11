from module.ocr.ocr import Digit
from module.shop.assets import SHOP_GEMS, SHOP_OCR_BALANCE, SHOP_VOUCHER
from module.ui.ui import UI

OCR_SHOP_GEMS = Digit(SHOP_GEMS, letter=(255, 243, 82), name="OCR_SHOP_GEMS")
OCR_SHOP_GOLD_COINS = Digit(SHOP_OCR_BALANCE, letter=(100, 100, 100), name="OCR_SHOP_GOLD_COINS")
OCR_SHOP_MEDAL = Digit(SHOP_OCR_BALANCE, letter=(100, 100, 100), name="OCR_SHOP_MEDAL")
OCR_SHOP_MERIT = Digit(SHOP_OCR_BALANCE, letter=(100, 100, 100), name="OCR_SHOP_MERIT")
OCR_SHOP_GUILD_COINS = Digit(SHOP_OCR_BALANCE, letter=(100, 100, 100), name="OCR_SHOP_GUILD_COINS")
OCR_SHOP_CORE = Digit(SHOP_OCR_BALANCE, letter=(100, 100, 100), name="OCR_SHOP_CORE")

OCR_SHOP_VOUCHER = Digit(SHOP_VOUCHER, letter=(255, 255, 255), name="OCR_SHOP_VOUCHER")


class ShopStatus(UI):
    def status_get_gold_coins(self):
        return OCR_SHOP_GOLD_COINS.ocr(self.device.image)

    def status_get_gems(self):
        return OCR_SHOP_GEMS.ocr(self.device.image)

    def status_get_medal(self):
        return OCR_SHOP_MEDAL.ocr(self.device.image)

    def status_get_merit(self):
        return OCR_SHOP_MERIT.ocr(self.device.image)

    def status_get_guild_coins(self):
        return OCR_SHOP_GUILD_COINS.ocr(self.device.image)

    def status_get_core(self):
        return OCR_SHOP_CORE.ocr(self.device.image)

    def status_get_voucher(self):
        return OCR_SHOP_VOUCHER.ocr(self.device.image)
