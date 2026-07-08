from module.base.button import ButtonGrid
from module.base.decorator import cached_property
from module.base.timer import Timer
from module.equipment import assets as equipment_assets
from module.logger import logger
from module.retire.assets import DOCK_CHECK
from module.retire.assets import EQUIP_CONFIRM as RETIRE_EQUIP_CONFIRM
from module.storage.storage import StorageHandler
from module.ui.assets import BACK_ARROW
from module.ui.navbar import Navbar

SWIPE_DISTANCE = 250
SWIPE_RANDOM_RANGE = (-40, -20, 40, 20)
# 同时兼容蓝色（收起）和橙色（展开）按钮。
equipment_assets.EQUIPMENT_OPEN.match = equipment_assets.EQUIPMENT_OPEN.match_luma


class Equipment(StorageHandler):
    equipment_has_take_on = False

    def _ship_view_swipe(self, distance, check_button=equipment_assets.EQUIPMENT_OPEN):
        swipe_count = 0
        swipe_timer = Timer(5, count=10)
        self.handle_info_bar()
        equipment_assets.SWIPE_CHECK.load_color(self.device.image)
        # 跳过 match() 里的 ensure_template()，让截图对比只判断舰船是否真的变化。
        equipment_assets.SWIPE_CHECK.mark_match_initialized()
        while 1:
            if not swipe_timer.started() or swipe_timer.reached():
                swipe_timer.reset()
                self.device.swipe_vector(
                    vector=(distance, 0),
                    box=equipment_assets.SWIPE_AREA.area,
                    random_range=SWIPE_RANDOM_RANGE,
                    padding=0,
                    duration=(0.1, 0.12),
                    name="SHIP_SWIPE",
                )
                # self.wait_until_appear(check_button, offset=(30, 30))
                skip_first_screenshot = True
                while 1:
                    if skip_first_screenshot:
                        skip_first_screenshot = False
                    else:
                        self.device.screenshot()
                    if self.appear(check_button, offset=(30, 30)):
                        break
                    if self.appear(RETIRE_EQUIP_CONFIRM, offset=(30, 30)):
                        logger.info("RETIRE_EQUIP_CONFIRM popup in _ship_view_swipe()")
                        return False
                    # 强化 NPC 舰船时可能出现确认弹窗。
                    if self.handle_popup_confirm("SHIP_VIEW_SWIPE"):
                        continue
                swipe_count += 1

            self.device.screenshot()

            if self.appear(RETIRE_EQUIP_CONFIRM, offset=(30, 30)):
                logger.info("RETIRE_EQUIP_CONFIRM popup in _ship_view_swipe()")
                return False
            if equipment_assets.SWIPE_CHECK.match(self.device.image):
                if swipe_count > 1:
                    logger.info("Same ship on multiple swipes")
                    return False
                continue

            if self.appear(check_button, offset=(30, 30)) and not equipment_assets.SWIPE_CHECK.match(self.device.image):
                logger.info("New ship detected on swipe")
                return True
        return False

    def ship_view_next(self, check_button=equipment_assets.EQUIPMENT_OPEN):
        return self._ship_view_swipe(distance=-SWIPE_DISTANCE, check_button=check_button)

    def ship_view_prev(self, check_button=equipment_assets.EQUIPMENT_OPEN):
        return self._ship_view_swipe(distance=SWIPE_DISTANCE, check_button=check_button)

    def ship_info_enter(
        self,
        click_button,
        check_button=equipment_assets.EQUIPMENT_OPEN,
        long_click=True,
        skip_first_screenshot=True,
    ):
        enter_timer = Timer(10)

        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            # 已进入目标页面。
            if self.appear(check_button, offset=(5, 5)):
                break

            # 长按意外变成普通点击时，会回到船坞，需要退出。
            if long_click and self.appear(DOCK_CHECK, offset=(20, 20), interval=3):
                logger.info(f"ship_info_enter {DOCK_CHECK} -> {BACK_ARROW}")
                self.device.click(BACK_ARROW)
                continue
            if enter_timer.reached():
                if long_click:
                    self.device.long_click(click_button, duration=(1.5, 1.7))
                else:
                    self.device.click(click_button)
                enter_timer.reset()
            if self.handle_game_tips():
                continue

    @cached_property
    def _ship_side_navbar(self):
        """
        侧边栏可能有 3、4 或 5 个入口。

        pry_sidebar:
            科研、装备、详情。

        regular_sidebar:
            强化、突破、装备、详情。

        retrofit_sidebar:
            改造、强化、突破、装备、详情。
        """
        ship_side_navbar = ButtonGrid(
            origin=(21, 118), delta=(0, 94.5), button_shape=(60, 75), grid_shape=(1, 5), name="SHIP_SIDE_NAVBAR"
        )

        return Navbar(
            grids=ship_side_navbar,
            active_color=(247, 255, 173),
            active_threshold=221,
            inactive_color=(140, 162, 181),
            inactive_threshold=221,
        )

    def ship_side_navbar_ensure(self, upper=None, bottom=None):
        """
        确保可以切换到目标页面。

        页面是否完全加载由调用方按需检查。

        Args:
            upper (int):
                pry|regular|retrofit
                1|N/A|N/A 科研。
                N/A|N/A|1 改造。
                N/A|1|2   强化。
                N/A|2|3   突破。
                2|3|4     装备。
                3|4|5     详情。
            bottom (int):
                pry|regular|retrofit
                3|N/A|N/A 科研。
                N/A|N/A|5 改造。
                N/A|4|4   强化。
                N/A|3|3   突破。
                2         装备。
                1         详情。

        Returns:
            bool: 是否切换成功。
        """
        if self._ship_side_navbar.get_total(main=self) == 3 and (upper == 1 or bottom == 3):
            logger.warning('Transitions to "research" is not supported')
            return False

        return self._ship_side_navbar.set(self, upper=upper, bottom=bottom)

    def ship_equipment_take_off(self, skip_first_screenshot=True):
        logger.info("Equipment take off")
        bar_timer = Timer(5)
        off_timer = Timer(5)
        confirm_timer = Timer(5)

        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            # 已脱下至少一件装备。
            # if self.handle_info_bar():
            #     break
            if off_timer.started() and self.info_bar_count():
                break

            if self.handle_storage_full():
                continue

            if confirm_timer.reached() and self.handle_popup_confirm("EQUIPMENT_TAKE_OFF"):
                confirm_timer.reset()
                off_timer.reset()
                bar_timer.reset()
                continue

            if (
                off_timer.reached()
                and not self.info_bar_count()
                and self.appear_then_click(equipment_assets.EQUIP_OFF, offset=(20, 20))
            ):
                off_timer.reset()
                bar_timer.reset()
                continue

            if (
                bar_timer.reached()
                and self.appear(equipment_assets.EQUIPMENT_OPEN, offset=(20, 20))
                and not self.appear(equipment_assets.EQUIP_OFF, offset=(20, 20))
            ):
                self.device.click(equipment_assets.EQUIPMENT_OPEN)
                bar_timer.reset()
                continue

        logger.info("Equipment take off ended")

    def fleet_equipment_take_off(self, enter, long_click, out):
        """
        Args:
            enter (Button): 进入装备编辑的按钮。
            long_click (bool): 是否长按进入。
            out (Button): 用于确认退出成功的按钮。
        """
        logger.hr("Equipment take off")
        self.ship_info_enter(enter, long_click=long_click)

        while True:
            self.ship_equipment_take_off()
            self.ui_click(
                equipment_assets.EQUIPMENT_CLOSE,
                check_button=equipment_assets.EQUIPMENT_OPEN,
                skip_first_screenshot=True,
            )
            if not self.ship_view_next():
                break

        self.ui_back(out)
        self.equipment_has_take_on = False

    def ship_equipment_take_on_preset(self, index, skip_first_screenshot=True):
        logger.info("Equipment take on preset")
        bar_timer = Timer(5)
        on_timer = Timer(5)

        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            # 已穿上一件装备。
            # if self.handle_info_bar():
            #     break
            if on_timer.started() and self.info_bar_count():
                break

            if bar_timer.reached() and not self.appear(equipment_assets.EQUIP_1, offset=10):
                self.device.click(equipment_assets.EQUIPMENT_OPEN)
                # self.device.sleep(0.3)
                bar_timer.reset()
                continue

            if on_timer.reached() and self.appear(equipment_assets.EQUIP_1, offset=10) and not self.info_bar_count():
                if index == 1:
                    self.device.click(equipment_assets.EQUIP_1)
                elif index == 2:
                    self.device.click(equipment_assets.EQUIP_2)
                elif index == 3:
                    self.device.click(equipment_assets.EQUIP_3)

                on_timer.reset()
                bar_timer.reset()
                continue

        logger.info("Equipment take on ended")

    def fleet_equipment_take_on_preset(self, preset_record, enter, long_click, out):
        """
        Args:
            preset_record (list[int]): 装备记录，例如 [3, 1, 1, 1, 1, 1]。
            enter (Button): 进入装备编辑的按钮。
            long_click (bool): 是否长按进入。
            out (Button): 用于确认退出成功的按钮。
        """
        logger.hr("Equipment take on")
        self.ship_info_enter(enter, long_click=long_click)

        for raw_index in "9".join([str(x) for x in preset_record if x > 0]):
            index = int(raw_index)
            if index == 9:
                self.ship_view_next()
            else:
                self.ship_equipment_take_on_preset(index=index)
                self.ui_click(
                    equipment_assets.EQUIPMENT_CLOSE,
                    check_button=equipment_assets.EQUIPMENT_OPEN,
                    skip_first_screenshot=True,
                )

        self.ui_back(out)
        self.equipment_has_take_on = True
