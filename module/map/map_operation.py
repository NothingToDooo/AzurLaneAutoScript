import cv2

from module.base.timer import Timer
from module.exception import CampaignEnd, RequestHumanTakeover, ScriptEnd
from module.handler.fast_forward import FastForwardHandler
from module.handler.mystery import MysteryHandler
from module.logger import logger
from module.map import assets as map_assets
from module.map.map_fleet_preparation import FleetPreparation
from module.retire.retirement import Retirement
from module.ui.assets import BACK_ARROW, DAILY_CHECK

MAP_ACHIEVEMENT_REACHED_TEMPLATE = "Reach condition: {condition}"
MAP_WITHDRAW_MESSAGE = "Withdraw"


class MapOperation(MysteryHandler, FleetPreparation, Retirement, FastForwardHandler):
    map_cat_attack_timer = Timer(2)
    map_clear_percentage_prev = -1
    map_clear_percentage_timer = Timer(0.3, count=1)

    # 屏幕上显示的舰队。
    fleet_show_index = 1
    # 注意这里不同于 get_fleet_current_index()。
    # 在 fleet_current_index 中，1 表示道中队，2 表示 Boss 队。
    fleet_current_index = 1

    def get_fleet_show_index(self):
        """
        Get the fleet that shows on screen.

        Returns:
            int: 1 or 2

        Pages:
            in: in_map
        """
        if self.appear(map_assets.FLEET_NUM_1, offset=(20, 20)):
            self.fleet_show_index = 1
            return 1
        if self.appear(map_assets.FLEET_NUM_2, offset=(20, 20)):
            self.fleet_show_index = 2
            return 2
        logger.warning("Unknown fleet current index, use 1 by default")
        self.fleet_show_index = 1
        return 1

    def get_fleet_current_index(self):
        """
        Returns:
            int: 1 or 2
        """
        if self.fleets_reversed:
            self.fleet_current_index = 3 - self.fleet_show_index
            return self.fleet_current_index
        self.fleet_current_index = self.fleet_show_index
        return self.fleet_current_index

    def fleet_set(self, index=None, skip_first_screenshot=True):
        """
        Args:
            index (int): Target fleet_current_index
            skip_first_screenshot (bool):

        Returns:
            bool: If switched.
        """
        logger.info(f"Fleet set to {index}")
        timeout = Timer(5, count=10).start()
        count = 0
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if timeout.reached():
                logger.warning("Fleet set timeout, assume current fleet is correct")
                break

            if self.handle_story_skip():
                timeout.reset()
                continue
            if self.handle_in_stage():
                timeout.reset()
                continue

            self.get_fleet_show_index()
            self.get_fleet_current_index()
            logger.info(f"Fleet: {self.fleet_show_index}, fleet_current_index: {self.fleet_current_index}")
            if self.fleet_current_index == index:
                break
            if self.appear_then_click(map_assets.SWITCH_OVER):
                count += 1
                self.device.sleep((1, 1.5))
                timeout.reset()
                continue
            logger.warning("SWITCH_OVER not found")
            continue

        return count > 0

    @staticmethod
    def _check_enter_map_clicks(button, campaign_click, fleet_click):
        if campaign_click > 5:
            logger.critical(f"Failed to enter {button}, too many click on {button}")
            logger.critical("Possible reason #1: You haven't reached the commander level to unlock this stage.")
            raise RequestHumanTakeover
        if fleet_click <= 5:
            return
        logger.critical(f"Failed to enter {button}, too many click on FLEET_PREPARATION")
        logger.critical("Possible reason #1: Your fleets haven't satisfied the stat restrictions of this stage.")
        logger.critical(
            "Possible reason #2: "
            "This stage can only be farmed once a day, "
            "but it's the second time that you are entering"
        )
        raise RequestHumanTakeover

    def _handle_daily_misclick(self):
        if not self.appear(DAILY_CHECK, offset=(20, 20), interval=3):
            return False
        logger.info(f"{DAILY_CHECK} -> {BACK_ARROW}")
        self.device.click(BACK_ARROW)
        return True

    def _handle_map_preparation_entry(self, mode, map_timer, campaign_timer):
        if not map_timer.reached() or not self.handle_map_mode_switch(mode) or not self.handle_map_preparation():
            return False
        self.map_get_info()
        self.handle_map_walk_speedup()
        self.handle_fast_forward()
        self.handle_auto_search()
        if self.triggered_map_stop():
            self.enter_map_cancel()
            self.handle_map_stop()
            message = MAP_ACHIEVEMENT_REACHED_TEMPLATE.format(condition=self.config.StopCondition_MapAchievement)
            raise ScriptEnd(message)
        self.device.click(map_assets.MAP_PREPARATION)
        map_timer.reset()
        campaign_timer.reset()
        return True

    def _handle_fleet_preparation_entry(self, mode, fleet_timer, campaign_timer):
        if not fleet_timer.reached() or not self.appear(map_assets.FLEET_PREPARATION, offset=(20, 50)):
            return False
        if mode in {"normal", "hard"}:
            self.handle_2x_book_setting(mode="prep")
            self.fleet_preparation()
            self.handle_auto_submarine_call_disable()
            self.handle_auto_search_setting()
            self.map_fleet_checked = True
        self.device.click(map_assets.FLEET_PREPARATION)
        fleet_timer.reset()
        campaign_timer.reset()
        return True

    def _handle_enter_map_interrupts(self, campaign_timer):
        if self.handle_auto_search_continue():
            campaign_timer.reset()
            return True
        if any(
            handler()
            for handler in (
                self.handle_retirement,
                self.handle_use_data_key,
                self.handle_submarine_support_popup,
                self.handle_combat_low_emotion,
                self.handle_urgent_commission,
                self.handle_2x_book_popup,
            )
        ):
            return True
        if self.handle_story_skip():
            campaign_timer.reset()
            return True
        return False

    def _click_stage_entrance(self, button, campaign_timer):
        if not campaign_timer.reached() or not self.appear_then_click(button):
            return False
        campaign_timer.reset()
        return True

    def _is_combat_loading_appeared(self):
        is_combat_loading = getattr(self, "is_combat_loading", None)
        if callable(is_combat_loading) and is_combat_loading():
            logger.warning("Entered map with is_combat_loading appeared")
            return True
        return False

    def _enter_map_finished(self):
        if self.map_is_auto_search:
            if self.is_auto_search_running():
                logger.info("is_auto_search_running appeared")
                return True
            return self._is_combat_loading_appeared()
        return self._is_combat_loading_appeared() or self.handle_in_map_with_enemy_searching()

    def enter_map(self, button, mode="normal", skip_first_screenshot=True):
        """Enter a campaign.

        Args:
            button: Campaign to enter.
            mode (str): 'normal' or 'hard'
            skip_first_screenshot (bool):
        """
        logger.hr("Enter map")
        campaign_timer = Timer(5)
        map_timer = Timer(5)
        fleet_timer = Timer(5)
        campaign_click = 0
        fleet_click = 0
        checked_in_map = False
        self.stage_entrance = button
        self.map_clear_percentage_prev = -1
        self.map_clear_percentage_timer.reset()

        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            # 检查异常。
            self._check_enter_map_clicks(button, campaign_click, fleet_click)

            # 已经在地图内。
            if not checked_in_map and self.is_in_map():
                logger.info("Already in map, skip enter_map.")
                return False
            checked_in_map = True

            # 误点击。
            if self._handle_daily_misclick():
                continue

            # 地图准备。
            if self._handle_map_preparation_entry(mode, map_timer, campaign_timer):
                continue

            # 舰队准备。
            if self._handle_fleet_preparation_entry(mode, fleet_timer, campaign_timer):
                fleet_click += 1
                continue

            if self._handle_enter_map_interrupts(campaign_timer):
                continue

            # 进入关卡。
            if self._click_stage_entrance(button, campaign_timer):
                campaign_click += 1
                continue

            # 结束。
            if self._enter_map_finished():
                break

        return True

    def enter_map_cancel(self, skip_first_screenshot=True):
        logger.hr("Enter map cancel")
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            # 结束。
            if self.is_in_stage():
                break

            if self.appear(map_assets.MAP_PREPARATION, offset=(20, 20), interval=2):
                self.device.click(map_assets.MAP_PREPARATION_CANCEL)
                continue
            if self.appear(map_assets.FLEET_PREPARATION, offset=(20, 50), interval=2):
                self.device.click(map_assets.MAP_PREPARATION_CANCEL)
                continue

        return True

    def handle_map_mode_switch(self, mode):
        """
        Args:
            mode (str): 'normal' or 'hard'

        Returns:
            bool: If map mode satisfied
                Always True if map doesn't have mode switch in map preparation
        """
        if not self.config.MAP_HAS_MODE_SWITCH:
            return True

        if mode == "normal":
            return self._handle_map_mode_switch_normal()
        if mode == "hard":
            return self._handle_map_mode_switch_hard()
        logger.attr("MAP_MODE_SWITCH", "unknown")
        return False

    def _handle_map_mode_switch_normal(self):
        if self.match_template_color(map_assets.MAP_MODE_SWITCH_NORMAL, offset=(20, 20)):
            logger.attr("MAP_MODE_SWITCH", "normal")
            return True
        if self._is_mod_switch_hard_appear(active=False, interval=2):
            logger.attr("MAP_MODE_SWITCH", "hard")
            map_assets.MAP_MODE_SWITCH_NORMAL.clear_offset()
            self.device.click(map_assets.MAP_MODE_SWITCH_NORMAL)
            self.interval_reset(map_assets.MAP_MODE_SWITCH_HARD)
        return False

    def _handle_map_mode_switch_hard(self):
        if self._is_mod_switch_hard_appear(active=True):
            logger.attr("MAP_MODE_SWITCH", "hard")
            return True
        if self.match_template_color(map_assets.MAP_MODE_SWITCH_NORMAL, offset=(20, 20), interval=2):
            logger.attr("MAP_MODE_SWITCH", "normal")
            map_assets.MAP_MODE_SWITCH_HARD.clear_offset()
            self.device.click(map_assets.MAP_MODE_SWITCH_HARD)
        return False

    def _is_mod_switch_hard_appear(self, active=True, interval=0):
        if interval:
            interval = self.get_interval_timer(map_assets.MAP_MODE_SWITCH_HARD, interval=interval)
            if not interval.reached():
                return False

        for button in [
            map_assets.MAP_MODE_SWITCH_HARD,
            map_assets.MAP_MODE_SWITCH_HARD2,
            map_assets.MAP_MODE_SWITCH_HARD3,
            map_assets.MAP_MODE_SWITCH_HARD4,
            map_assets.MAP_MODE_SWITCH_HARD5,
            map_assets.MAP_MODE_SWITCH_HARD6,
        ]:
            if self.appear(button, offset=(20, 20), similarity=0.7):
                if active:
                    return self._is_mod_switch_hard_active(button)
                return True
        return False

    def _is_mod_switch_hard_active(self, button):
        image = self.image_crop(button.button)
        # rgbmax
        r, g, b = cv2.split(image)
        cv2.max(r, g, dst=r)
        cv2.max(r, b, dst=r)
        # 激活按钮有白色图标，检查是否存在大于 235 的颜色。
        cv2.inRange(r, 235, 255, dst=r)
        sum_ = cv2.countNonZero(r)
        total = r.shape[0] * r.shape[1]
        return sum_ / total > 0.5

    def handle_map_preparation(self):
        """
        Returns:
            bool: If MAP_PREPARATION and tha animation of map information finished
        """
        if not self._map_preparation_appeared():
            return False

        if self._map_preparation_has_no_percentage_wait():
            return True
        # info_bar 会遮住百分比和 MAP_GREEN。
        if self.info_bar_count():
            return False

        return self._map_clear_percentage_stable()

    def _map_preparation_appeared(self):
        if self.appear(map_assets.MAP_PREPARATION, offset=(20, 20)):
            return True

        self.map_clear_percentage_prev = -1
        self.map_clear_percentage_timer.reset()
        return False

    def _map_preparation_has_no_percentage_wait(self):
        if not self.config.MAP_HAS_CLEAR_PERCENTAGE:
            logger.attr("MAP_HAS_CLEAR_PERCENTAGE", self.config.MAP_HAS_CLEAR_PERCENTAGE)
            return True
        if self.config.MAP_IS_ONE_TIME_STAGE:
            logger.attr("MAP_IS_ONE_TIME_STAGE", self.config.MAP_IS_ONE_TIME_STAGE)
            return True
        return False

    def _map_clear_percentage_stable(self):
        percent = self.get_map_clear_percentage()
        logger.attr("Map_clear_percentage", f"{int(percent * 100)}%")
        # 百分比会从 100% 开始，再从 0% 增加到实际值。
        # 2022.08.21：当 percent 从 0 提升时仍然启用该判断。
        if percent > 0.95 and 0 <= self.map_clear_percentage_prev < 0.95:
            # 地图清理百分比 100%，直接退出。
            return True
        if abs(percent - self.map_clear_percentage_prev) < 0.02:
            self.map_clear_percentage_prev = percent
            return bool(self.map_clear_percentage_timer.reached())
        self.map_clear_percentage_prev = percent
        self.map_clear_percentage_timer.reset()
        return False

    def withdraw(self, skip_first_screenshot=True):
        """
        Withdraw campaign.
        """
        logger.hr("Map withdraw")
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if self.handle_popup_confirm("WITHDRAW"):
                continue
            if self.appear_then_click(map_assets.WITHDRAW, interval=5):
                continue
            if self.handle_auto_search_exit():
                continue
            # 误点击。
            if self.appear(DAILY_CHECK, offset=(20, 20), interval=3):
                logger.info(f"{DAILY_CHECK} -> {BACK_ARROW}")
                self.device.click(BACK_ARROW)
                continue

            # 结束。
            if self.handle_in_stage():
                raise CampaignEnd(MAP_WITHDRAW_MESSAGE)

    def handle_map_cat_attack(self):
        """
        Click to skip the animation when cat attacks.
        """
        if not self.map_cat_attack_timer.reached():
            return False
        if self.image_color_count(map_assets.MAP_CAT_ATTACK, color=(255, 231, 123), threshold=221, count=100):
            logger.info("Skip map cat attack")
            self.device.click(map_assets.MAP_CAT_ATTACK)
            self.map_cat_attack_timer.reset()
            return True
        # 威胁等级 Med 有 106 个像素，MAP_CAT_ATTACK_MIRROR 有 290 个像素。
        if not self.map_is_clear_mode and self.image_color_count(
            map_assets.MAP_CAT_ATTACK_MIRROR, color=(255, 231, 123), threshold=221, count=200
        ):
            logger.info("Skip map being attack")
            self.device.click(map_assets.MAP_CAT_ATTACK)
            self.map_cat_attack_timer.reset()
            return True

        return False

    @property
    def fleets_reversed(self):
        if not self.config.FLEET_2:
            return False
        return self.config.Fleet_FleetOrder in ["fleet1_boss_fleet2_mob", "fleet1_standby_fleet2_all"]

    def handle_fleet_reverse(self):
        """
        The game chooses the fleet with a smaller index to be the first fleet,
        no matter what we choose in fleet preparation.

        After the update of auto-search, the game no longer ignore user settings.

        Returns:
            bool: Fleet changed
        """
        if not self.map_is_hard_mode and self.config.Fleet_FleetOrder in [
            "fleet1_boss_fleet2_mob",
            "fleet1_standby_fleet2_all",
        ]:
            logger.warning(f"You shouldn't use a reversed fleet order ({self.config.Fleet_FleetOrder}) in normal mode.")
            logger.warning(
                'Please reverse your Fleet 1 and Fleet 2, use "fleet1_mob_fleet2_boss" or "fleet1_all_fleet2_standby"'
            )
            # raise RequestHumanTakeover

        if not self.fleets_reversed:
            return False

        return self.fleet_set(index=2)
