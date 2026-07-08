import cv2
import numpy as np

from module.base.button import Button, ButtonGrid
from module.base.utils import random_rectangle_vector
from module.equipment import assets as equipment_assets
from module.equipment.equipment import Equipment
from module.logger import logger
from module.ui.assets import BACK_ARROW
from module.ui.scroll import Scroll
from module.ui.switch import Switch

# 5 个装备按钮。
EQUIP_INFO_BAR = ButtonGrid(
    origin=(695, 127), delta=(86.25, 0), button_shape=(73, 73), grid_shape=(5, 1), name="EQUIP_INFO_BAR"
)
# EQUIP_INFO_BAR 左下角，用于检测格子是否已有装备。
EQUIPMENT_GRID = ButtonGrid(
    origin=(696, 170), delta=(86.25, 0), button_shape=(32, 32), grid_shape=(5, 1), name="EQUIPMENT_GRID"
)
EQUIPMENT_SCROLL = Scroll(equipment_assets.EQUIP_SCROLL, color=(247, 211, 66), name="EQUIP_SCROLL")
SIM_VALUE = 0.90
EQUIPMENT_INDEXES = range(5)

equipping_filter = Switch("Equipping_filter")
equipping_filter.add_state("on", check_button=equipment_assets.EQUIPPING_ON)
equipping_filter.add_state("off", check_button=equipment_assets.EQUIPPING_OFF)


class EquipmentChange(Equipment):
    def __init__(self, *args, **kwargs):
        self.equipment_list = {}
        super().__init__(*args, **kwargs)

    def equipping_set(self, enable=False):
        if equipping_filter.set("on" if enable else "off", main=self):
            self.wait_until_stable(equipment_assets.SWIPE_AREA)

    def ship_equipment_record_image(self, index_list=EQUIPMENT_INDEXES):
        """
        通过强化页面记录装备。

        注意：强化页面装备图标和装备状态页图标尺寸一致。
        """
        logger.info("RECORD EQUIPMENT")
        self.ship_side_navbar_ensure(bottom=1)

        # 确保 EQUIPMENT_GRID 位于正确位置。
        skip_first_screenshot = True
        while True:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()
            if self.appear(equipment_assets.EQUIPMENT_OPEN, offset=(5, 5)):
                break

        self.equipment_list = {}
        info_bar_disappeared = False
        for index, button in enumerate(EQUIPMENT_GRID.buttons):
            if index not in index_list:
                continue
            crop_image = self.image_crop(button, copy=False)
            edge_value = np.mean(np.abs(cv2.Sobel(crop_image, 3, 1, 1)))
            # 空位边缘值约为 0.15~1。
            # +1 约为 40。
            # +10 约为 46。
            if edge_value > 10:
                # 进入装备详情。
                self.ui_click(
                    appear_button=equipment_assets.EQUIPMENT_OPEN,
                    click_button=EQUIP_INFO_BAR[(index, 0)],
                    check_button=equipment_assets.UPGRADE_ENTER,
                )
                # 进入强化信息。
                self.ui_click(
                    click_button=equipment_assets.UPGRADE_ENTER,
                    check_button=equipment_assets.UPGRADE_ENTER_CHECK,
                    skip_first_screenshot=True,
                )
                # 保存装备模板。
                if not info_bar_disappeared:
                    self.handle_info_bar()
                    info_bar_disappeared = True
                self.equipment_list[index] = self.image_crop(equipment_assets.EQUIP_SAVE)
                # 退出强化信息。
                self.ui_click(
                    click_button=equipment_assets.UPGRADE_QUIT,
                    check_button=equipment_assets.EQUIPMENT_OPEN,
                    appear_button=equipment_assets.UPGRADE_ENTER_CHECK,
                    skip_first_screenshot=True,
                )
            else:
                logger.info(f"Equipment {index} is empty")

        logger.info(f"Recorded equipment index list: {list(self.equipment_list.keys())}")

    def ship_equipment_take_on_image(self, index_list=EQUIPMENT_INDEXES, skip_first_screenshot=True):
        """
        穿上之前记录的装备。
        """
        logger.info("Take on equipment")
        self.ship_side_navbar_ensure(bottom=2)

        for index in index_list:
            if index in self.equipment_list:
                logger.info(f"Take on {index}")
                enter_button = getattr(equipment_assets, f"EQUIP_TAKE_ON_{index}")

                self.ui_click(
                    enter_button,
                    check_button=equipment_assets.EQUIPPING_ON,
                    skip_first_screenshot=skip_first_screenshot,
                    offset=(5, 5),
                )
                self.handle_info_bar()
                self._find_equipment(index)

    def _equipment_swipe(self, distance=190):
        # 两个委托之间的距离是 146px。
        p1, p2 = random_rectangle_vector((0, -distance), box=(620, 67, 1154, 692), random_range=(-20, -5, 20, 5))
        self.device.drag(p1, p2, point_random=(0, 0, 0, 0))
        self.device.sleep(0.3)
        self.device.screenshot()

    def _equip_equipment(self, point, offset=(100, 100)):
        """
        穿上装备并回到舰船详情。

        过程里会确认弹窗。
        页面：
            进入：装备状态。
            退出：舰船侧栏装备页。
        """
        logger.info("Equip equipment")
        button = Button(
            area=(), color=(), button=(point[0], point[1], point[0] + offset[0], point[1] + offset[1]), name="EQUIPMENT"
        )
        self.ui_click(
            appear_button=equipment_assets.EQUIPPING_OFF,
            click_button=button,
            check_button=equipment_assets.EQUIP_CONFIRM,
        )
        logger.info("Equip confirm")
        self.ui_click(
            click_button=equipment_assets.EQUIP_CONFIRM,
            check_button=equipment_assets.SHIP_INFO_EQUIPMENT_CHECK,
        )

    def _find_equipment(self, index):
        """
        查找之前记录过的装备。

        页面：
            进入：装备状态。
        """
        enter_button = getattr(equipment_assets, f"EQUIP_TAKE_ON_{index}")

        self.equipping_set(enable=False)

        res = cv2.matchTemplate(self.device.screenshot(), np.array(self.equipment_list[index]), cv2.TM_CCOEFF_NORMED)
        _, sim, _, point = cv2.minMaxLoc(res)

        if sim > SIM_VALUE:
            self._equip_equipment(point)
            return

        if not EQUIPMENT_SCROLL.appear(main=self):
            logger.warning("No recorded equipment was found.")
            self.ui_back(check_button=enter_button, appear_button=equipment_assets.EQUIPPING_OFF)
            return

        for _ in range(15):
            self._equipment_swipe()

            if self.appear(equipment_assets.EQUIP_CONFIRM, offset=(20, 20), interval=2):
                self.device.click(BACK_ARROW)
                continue
            res = cv2.matchTemplate(
                self.device.screenshot(), np.array(self.equipment_list[index]), cv2.TM_CCOEFF_NORMED
            )
            _, sim, _, point = cv2.minMaxLoc(res)

            if sim > SIM_VALUE:
                self._equip_equipment(point)
                break
            if self.appear(equipment_assets.EQUIPMENT_SCROLL_BOTTOM):
                logger.warning("No recorded equipment was found.")
                self.ui_back(check_button=enter_button, appear_button=equipment_assets.EQUIPPING_OFF)
                break

        return
