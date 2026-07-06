from module.base.timer import Timer
from module.equipment import assets as equipment_assets
from module.equipment.equipment_change import EquipmentChange
from module.logger import logger
from module.ocr.ocr import Digit
from module.ui.assets import FLEET_CHECK
from module.ui.page import page_fleet

OCR_FLEET_INDEX = Digit(equipment_assets.OCR_FLEET_INDEX, letter=(90, 154, 255), threshold=128, alphabet="123456")


class FleetEquipment(EquipmentChange):
    def fleet_enter(self, fleet):
        self.ui_ensure(page_fleet)

        # 切换到目标舰队编号。
        letter = OCR_FLEET_INDEX
        next_button = equipment_assets.FLEET_NEXT
        prev_button = equipment_assets.FLEET_PREV
        interval = (0.2, 0.3)

        retry = Timer(1, count=2)
        for _ in self.loop():
            current = letter.ocr(self.device.image)
            logger.attr("Index", current)

            # 忽略 OCR 默认值 0，避免从 1 切到 4 时多点一次。
            if current == 0:
                continue

            diff = fleet - current
            if diff == 0:
                break

            if retry.reached():
                button = next_button if diff > 0 else prev_button
                self.device.multi_click(button, n=abs(diff), interval=interval)
                retry.reset()

    def fleet_equipment_take_on_preset(
        self,
        preset_record,
        enter=equipment_assets.FLEET_DETAIL_ENTER_FLAGSHIP,
        long_click=False,
        out=equipment_assets.FLEET_DETAIL_CHECK,
    ):
        self.ui_click(
            equipment_assets.FLEET_DETAIL,
            appear_button=page_fleet.check_button,
            check_button=equipment_assets.FLEET_DETAIL_CHECK,
            skip_first_screenshot=True,
        )
        super().fleet_equipment_take_on_preset(
            preset_record=preset_record,
            enter=equipment_assets.FLEET_DETAIL_ENTER_FLAGSHIP,
            long_click=False,
            out=equipment_assets.FLEET_DETAIL_CHECK,
        )
        self.ui_back(FLEET_CHECK)

    def fleet_equipment_take_off(
        self,
        enter=equipment_assets.FLEET_DETAIL_ENTER_FLAGSHIP,
        long_click=False,
        out=equipment_assets.FLEET_DETAIL_CHECK,
    ):
        self.ui_click(
            equipment_assets.FLEET_DETAIL,
            appear_button=page_fleet.check_button,
            check_button=equipment_assets.FLEET_DETAIL_CHECK,
            skip_first_screenshot=True,
        )
        super().fleet_equipment_take_off(enter=enter, long_click=long_click, out=out)
        self.ui_back(FLEET_CHECK)

    def fleet_enter_ship(self, button):
        self.ui_click(
            equipment_assets.FLEET_DETAIL,
            appear_button=page_fleet.check_button,
            check_button=equipment_assets.FLEET_DETAIL_CHECK,
            skip_first_screenshot=True,
        )
        self.ship_info_enter(button, long_click=False)

    def fleet_back(self):
        self.ui_back(equipment_assets.FLEET_DETAIL_CHECK)
        self.ui_back(FLEET_CHECK)
