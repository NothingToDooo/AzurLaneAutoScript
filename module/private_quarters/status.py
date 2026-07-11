from module.ocr.ocr import Digit, DigitCounter
from module.private_quarters import assets as pq_assets
from module.shop.shop_status import ShopStatus

OCR_DAILY_COUNT = DigitCounter(pq_assets.PRIVATE_QUARTERS_DAILY_COUNT, letter=(218, 219, 221))
OCR_SHOP_GOLD_COINS = Digit(
    pq_assets.PRIVATE_QUARTERS_SHOP_GOLD_COINS, letter=(239, 239, 239), name="OCR_SHOP_GOLD_COINS"
)
OCR_SHOP_GEMS = Digit(pq_assets.PRIVATE_QUARTERS_SHOP_GEMS, letter=(255, 243, 82), name="OCR_SHOP_GEMS")

OCR_SHOP_PRICE = Digit([], letter=(64, 72, 77), name="OCR_SHOP_PRICE")


class PQStatus(ShopStatus):
    def status_get_gold_coins(self):
        return OCR_SHOP_GOLD_COINS.ocr(self.device.image)

    def status_get_gems(self):
        return OCR_SHOP_GEMS.ocr(self.device.image)

    def status_get_daily_count(self):
        count, _, _ = OCR_DAILY_COUNT.ocr(self.device.image)
        return count
