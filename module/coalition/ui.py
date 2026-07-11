from module.base.timer import Timer
from module.coalition import assets as coalition_assets
from module.combat.assets import BATTLE_PREPARATION
from module.combat.combat import Combat
from module.exception import CampaignNameError, RequestHumanTakeover, ScriptError
from module.logger import logger
from module.ui.assets import BACK_ARROW
from module.ui.page import page_coalition
from module.ui.switch import Switch


class NeoncitySwitch(Switch):
    def get(self, main):
        # 红字表示当前模式。
        for data in self.state_list:
            if main.image_color_count(data["check_button"], color=(123, 41, 41), threshold=221, count=100):
                return data["state"]

        return "unknown"


class CoalitionUI(Combat):
    def in_coalition(self):
        return self.ui_page_appear(page_coalition, offset=(20, 20))

    def in_coalition_20251120_difficulty_selection(self):
        return self.appear(coalition_assets.DAL_DIFFICULTY_EXIT, offset=(20, 20))

    def coalition_ensure_mode(self, event, mode):
        """在联合作战页按活动切换 story 或 battle；2025-11-20 活动没有模式开关。"""
        if event == "coalition_20230323":
            mode_switch = Switch("CoalitionMode", offset=(20, 20))
            mode_switch.add_state("story", coalition_assets.FROSTFALL_MODE_STORY)
            mode_switch.add_state("battle", coalition_assets.FROSTFALL_MODE_BATTLE)
        elif event == "coalition_20240627":
            mode_switch = Switch("CoalitionMode", offset=(20, 20))
            mode_switch.add_state("story", coalition_assets.ACADEMY_MODE_BATTLE)
            mode_switch.add_state("battle", coalition_assets.ACADEMY_MODE_STORY)
        elif event == "coalition_20250626":
            mode_switch = NeoncitySwitch("CoalitionMode", offset=(20, 20))
            mode_switch.add_state("story", coalition_assets.NEONCITY_MODE_STORY)
            mode_switch.add_state("battle", coalition_assets.NEONCITY_MODE_BATTLE)
        elif event == "coalition_20251120":
            logger.info("Coalition event coalition_20251120 has no mode switch")
            return
        elif event == "coalition_20260122":
            mode_switch = Switch("CoalitionMode", offset=(20, 20))
            mode_switch.add_state("story", coalition_assets.FASHION_MODE_STORY)
            mode_switch.add_state("battle", coalition_assets.FASHION_MODE_BATTLE)
        else:
            logger.error(f"MODE_SWITCH is not defined in event {event}")
            raise ScriptError

        if mode == "story":
            mode_switch.set("story", main=self)
        elif mode == "battle":
            mode_switch.set("battle", main=self)
        else:
            logger.warning(f"Unknown coalition campaign mode: {mode}")

    def coalition_set_fleet(self, event, mode):
        """在舰队准备页切换 single 或 multi，并返回是否点击切换。"""
        fleet_switch = Switch("FleetMode", is_selector=True, offset=0)  # 颜色匹配不使用 offset。
        if event == "coalition_20230323":
            fleet_switch.add_state("single", coalition_assets.FROSTFALL_SWITCH_SINGLE)
            fleet_switch.add_state("multi", coalition_assets.FROSTFALL_SWITCH_MULTI)
        elif event == "coalition_20240627":
            fleet_switch.add_state("single", coalition_assets.ACADEMY_SWITCH_SINGLE)
            fleet_switch.add_state("multi", coalition_assets.ACADEMY_SWITCH_MULTI)
        elif event == "coalition_20250626":
            fleet_switch.add_state("single", coalition_assets.NEONCITY_SWITCH_SINGLE)
            fleet_switch.add_state("multi", coalition_assets.NEONCITY_SWITCH_MULTI)
        elif event == "coalition_20251120":
            fleet_switch.add_state("single", coalition_assets.DAL_SWITCH_SINGLE)
            fleet_switch.add_state("multi", coalition_assets.DAL_SWITCH_MULTI)
        elif event == "coalition_20260122":
            fleet_switch.add_state("single", coalition_assets.FASHION_SWITCH_SINGLE)
            fleet_switch.add_state("multi", coalition_assets.FASHION_SWITCH_MULTI)
        else:
            logger.error(f"FLEET_SWITCH is not defined in event {event}")
            raise ScriptError

        if fleet_switch.get(main=self) == mode:
            return False
        if mode == "single":
            fleet_switch.set("single", main=self)
            return True
        if mode == "multi":
            fleet_switch.set("multi", main=self)
            return True
        logger.warning(f"Unknown coalition fleet mode: {mode}")
        return False

    @staticmethod
    def coalition_get_entrance(event, stage):
        """按活动和关卡返回入口按钮；组合不受支持时抛出 CampaignNameError。"""
        dic = {
            ("coalition_20230323", "tc1"): coalition_assets.FROSTFALL_TC1,
            ("coalition_20230323", "tc2"): coalition_assets.FROSTFALL_TC2,
            ("coalition_20230323", "tc3"): coalition_assets.FROSTFALL_TC3,
            ("coalition_20230323", "sp"): coalition_assets.FROSTFALL_SP,
            ("coalition_20230323", "ex"): coalition_assets.FROSTFALL_EX,
            ("coalition_20240627", "easy"): coalition_assets.ACADEMY_EASY,
            ("coalition_20240627", "normal"): coalition_assets.ACADEMY_NORMAL,
            ("coalition_20240627", "hard"): coalition_assets.ACADEMY_HARD,
            ("coalition_20240627", "sp"): coalition_assets.ACADEMY_SP,
            ("coalition_20240627", "ex"): coalition_assets.ACADEMY_EX,
            ("coalition_20250626", "easy"): coalition_assets.NEONCITY_EASY,
            ("coalition_20250626", "normal"): coalition_assets.NEONCITY_NORMAL,
            ("coalition_20250626", "hard"): coalition_assets.NEONCITY_HARD,
            ("coalition_20250626", "sp"): coalition_assets.NEONCITY_SP,
            ("coalition_20250626", "ex"): coalition_assets.NEONCITY_EX,
            ("coalition_20251120", "area1-normal"): coalition_assets.DAL_AREA1,
            ("coalition_20251120", "area2-normal"): coalition_assets.DAL_AREA2,
            ("coalition_20251120", "area3-normal"): coalition_assets.DAL_AREA3,
            ("coalition_20251120", "area4-normal"): coalition_assets.DAL_AREA4,
            ("coalition_20251120", "area5-normal"): coalition_assets.DAL_AREA5,
            ("coalition_20251120", "area6-normal"): coalition_assets.DAL_AREA6,
            ("coalition_20251120", "area1-hard"): coalition_assets.DAL_AREA1,
            ("coalition_20251120", "area2-hard"): coalition_assets.DAL_AREA2,
            ("coalition_20251120", "area3-hard"): coalition_assets.DAL_AREA3,
            ("coalition_20251120", "area4-hard"): coalition_assets.DAL_AREA4,
            ("coalition_20251120", "area5-hard"): coalition_assets.DAL_AREA5,
            ("coalition_20251120", "area6-hard"): coalition_assets.DAL_AREA6,
            ("coalition_20260122", "easy"): coalition_assets.FASHION_EASY,
            ("coalition_20260122", "normal"): coalition_assets.FASHION_NORMAL,
            ("coalition_20260122", "hard"): coalition_assets.FASHION_HARD,
            ("coalition_20260122", "sp"): coalition_assets.FASHION_SP,
            ("coalition_20260122", "ex"): coalition_assets.FASHION_EX,
        }
        stage = stage.lower()
        try:
            return dic[(event, stage)]
        except KeyError as e:
            logger.error(e)
            raise CampaignNameError from e

    @staticmethod
    def coalition_20251120_get_entrance_difficulty(event, stage):
        """返回 2025-11-20 活动关卡的难度按钮；组合不受支持时抛出 CampaignNameError。"""
        dic = {
            ("coalition_20251120", "area1-normal"): coalition_assets.DAL_NORMAL,
            ("coalition_20251120", "area2-normal"): coalition_assets.DAL_NORMAL,
            ("coalition_20251120", "area3-normal"): coalition_assets.DAL_NORMAL,
            ("coalition_20251120", "area4-normal"): coalition_assets.DAL_NORMAL,
            ("coalition_20251120", "area5-normal"): coalition_assets.DAL_NORMAL,
            ("coalition_20251120", "area6-normal"): coalition_assets.DAL_NORMAL,
            ("coalition_20251120", "area1-hard"): coalition_assets.DAL_HARD,
            ("coalition_20251120", "area2-hard"): coalition_assets.DAL_HARD,
            ("coalition_20251120", "area3-hard"): coalition_assets.DAL_HARD,
            ("coalition_20251120", "area4-hard"): coalition_assets.DAL_HARD,
            ("coalition_20251120", "area5-hard"): coalition_assets.DAL_HARD,
            ("coalition_20251120", "area6-hard"): coalition_assets.DAL_HARD,
        }
        stage = stage.lower()
        try:
            return dic[(event, stage)]
        except KeyError as e:
            logger.error(e)
            raise CampaignNameError from e

    @staticmethod
    def coalition_get_battles(event, stage):
        """返回活动关卡的战斗次数；组合不受支持时抛出 CampaignNameError。"""
        dic = {
            ("coalition_20230323", "tc1"): 1,
            ("coalition_20230323", "tc2"): 2,
            ("coalition_20230323", "tc3"): 3,
            ("coalition_20230323", "sp"): 1,
            ("coalition_20230323", "ex"): 1,
            ("coalition_20240627", "easy"): 1,
            ("coalition_20240627", "normal"): 2,
            ("coalition_20240627", "hard"): 3,
            ("coalition_20240627", "sp"): 4,
            ("coalition_20240627", "ex"): 5,
            ("coalition_20250626", "easy"): 1,
            ("coalition_20250626", "normal"): 2,
            ("coalition_20250626", "hard"): 3,
            ("coalition_20250626", "sp"): 4,
            ("coalition_20250626", "ex"): 5,
            ("coalition_20251120", "area1-normal"): 2,
            ("coalition_20251120", "area2-normal"): 3,
            ("coalition_20251120", "area3-normal"): 3,
            ("coalition_20251120", "area4-normal"): 3,
            ("coalition_20251120", "area5-normal"): 3,
            ("coalition_20251120", "area6-normal"): 4,
            ("coalition_20251120", "area1-hard"): 2,
            ("coalition_20251120", "area2-hard"): 3,
            ("coalition_20251120", "area3-hard"): 3,
            ("coalition_20251120", "area4-hard"): 3,
            ("coalition_20251120", "area5-hard"): 3,
            ("coalition_20251120", "area6-hard"): 4,
            ("coalition_20260122", "easy"): 1,
            ("coalition_20260122", "normal"): 2,
            ("coalition_20260122", "hard"): 3,
            ("coalition_20260122", "sp"): 4,
            ("coalition_20260122", "ex"): 5,
        }
        stage = stage.lower()
        try:
            return dic[(event, stage)]
        except KeyError as e:
            logger.error(e)
            raise CampaignNameError from e

    @staticmethod
    def coalition_get_fleet_preparation(event):
        """返回活动专用舰队准备按钮；活动不受支持时抛出 ScriptError。"""
        if event == "coalition_20230323":
            return coalition_assets.FROSTFALL_FLEET_PREPARATION
        if event == "coalition_20240627":
            return coalition_assets.ACEDEMY_FLEET_PREPARATION
        if event == "coalition_20250626":
            return coalition_assets.NEONCITY_FLEET_PREPARATION
        if event == "coalition_20251120":
            return coalition_assets.DAL_FLEET_PREPARATION
        if event == "coalition_20260122":
            # FASHION 复用 NEONCITY，只整体偏移 (-12, -12)。
            return coalition_assets.NEONCITY_FLEET_PREPARATION
        logger.error(f"FLEET_PREPARATION is not defined in event {event}")
        raise ScriptError

    def handle_fleet_preparation(self, event, stage, mode):
        """在舰队准备页按 single 或 multi 切换并返回是否点击。

        固定舰队关卡直接返回 False；编队不完整时抛出 RequestHumanTakeover。
        """
        stage = stage.lower()

        # TC1 和 SP 没有舰队切换。
        if event == "coalition_20230323" and stage in ["tc1", "sp"]:
            return False
        # easy 是单舰队，SP 和 EX 必须使用多舰队。
        if event in [
            "coalition_20240627",
            "coalition_20250626",
            "coalition_20260122",
        ] and stage in ["easy", "sp", "ex"]:
            return False

        clicked = self.coalition_set_fleet(event, mode)

        if self.appear(coalition_assets.FLEET_NOT_PREPARED, offset=(20, 20)):
            logger.critical("FLEET_NOT_PREPARED")
            logger.critical("Please prepare you fleets before running coalition battles")
            raise RequestHumanTakeover
        if self.appear(coalition_assets.EMPTY_FLAGSHIP, offset=(20, 20)):
            logger.critical("EMPTY_FLAGSHIP, Please prepare you fleets before running coalition battles")
            raise RequestHumanTakeover
        if self.appear(coalition_assets.EMPTY_VANGUARD, offset=(20, 20)):
            logger.critical("EMPTY_VANGUARD, Please prepare you fleets before running coalition battles")
            raise RequestHumanTakeover

        return clicked

    def coalition_map_exit(self, event):
        """从战斗或活动舰队准备页返回联合作战页；误到主页时也结束。"""
        logger.info("Coalition map exit")
        fleet_preparation = self.coalition_get_fleet_preparation(event)
        for _ in self.loop():
            if self.in_coalition():
                break
            if self.is_in_main():
                break

            if self.appear(BATTLE_PREPARATION, offset=(20, 20), interval=3):
                logger.info(f"{BATTLE_PREPARATION} -> {BACK_ARROW}")
                self.device.click(BACK_ARROW)
                continue
            if self.appear(fleet_preparation, offset=(20, 20), interval=3):
                logger.info(f"{fleet_preparation} -> {coalition_assets.NEONCITY_PREPARATION_EXIT}")
                self.device.click(coalition_assets.NEONCITY_PREPARATION_EXIT)
                continue
            if self.appear_then_click(coalition_assets.DAL_DIFFICULTY_EXIT, offset=(20, 20), interval=3):
                logger.info(f"{coalition_assets.DAL_DIFFICULTY_EXIT} -> {coalition_assets.DAL_DIFFICULTY_EXIT}")
                continue

    @staticmethod
    def _coalition_difficulty_button(event, stage):
        if event != "coalition_20251120":
            return None
        return CoalitionUI.coalition_20251120_get_entrance_difficulty(event, stage)

    @staticmethod
    def _check_coalition_enter_clicks(
        button, button_difficulty, campaign_click, campaign_difficulty_click, fleet_click
    ):
        if campaign_click > 5:
            logger.critical(f"Failed to enter {button}, too many click on {button}")
            logger.critical("Possible reason #1: You haven't cleared previous stage to unlock the stage.")
            raise RequestHumanTakeover
        if campaign_difficulty_click > 5:
            logger.critical(f"Failed to enter {button_difficulty}, too many click on {button_difficulty}")
            logger.critical("Possible reason #1: The difficulty asset is not correct.")
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

    def _click_coalition_stage(self, button, campaign_timer):
        if not campaign_timer.reached() or not self.in_coalition():
            return False
        self.device.click(button)
        campaign_timer.reset()
        return True

    def _click_coalition_difficulty(self, event, button_difficulty, campaign_difficulty_timer):
        if event != "coalition_20251120" or not button_difficulty:
            return False
        if not campaign_difficulty_timer.reached() or not self.in_coalition_20251120_difficulty_selection():
            return False
        self.device.click(button_difficulty)
        campaign_difficulty_timer.reset()
        return True

    def _handle_coalition_enter_interrupts(self, campaign_timer):
        if self.handle_auto_search_continue():
            campaign_timer.reset()
            return True
        if self.handle_retirement():
            return True
        if self.handle_combat_low_emotion():
            return True
        if self.handle_urgent_commission():
            return True
        if self.handle_story_skip():
            campaign_timer.reset()
            return True
        return self.handle_combat_automation_confirm() or self.handle_popup_confirm("COALITION")

    def enter_map(self, event, stage, mode):
        """从联合作战页进入指定活动关卡，按 single 或 multi 编队，结束于战斗准备页。

        连续点击失败或编队不满足限制时抛出 RequestHumanTakeover。
        """
        button = self.coalition_get_entrance(event, stage)
        button_difficulty = self._coalition_difficulty_button(event, stage)
        fleet_preparation = self.coalition_get_fleet_preparation(event)
        campaign_timer = Timer(5)
        campaign_difficulty_timer = Timer(5)
        fleet_timer = Timer(5)
        campaign_click = 0
        campaign_difficulty_click = 0
        fleet_click = 0

        for _ in self.loop():
            self._check_coalition_enter_clicks(
                button, button_difficulty, campaign_click, campaign_difficulty_click, fleet_click
            )

            if self.appear(BATTLE_PREPARATION, offset=(20, 20)):
                break

            if self.handle_guild_popup_cancel():
                continue

            if self._click_coalition_stage(button, campaign_timer):
                campaign_click += 1
                continue
            if self._click_coalition_difficulty(event, button_difficulty, campaign_difficulty_timer):
                campaign_difficulty_click += 1
                continue
            if fleet_timer.reached() and self.appear(fleet_preparation, offset=(20, 50)):
                self.handle_fleet_preparation(event, stage, mode)
                self.device.click(fleet_preparation)
                fleet_timer.reset()
                campaign_timer.reset()
                fleet_click += 1
                continue

            if self._handle_coalition_enter_interrupts(campaign_timer):
                continue
