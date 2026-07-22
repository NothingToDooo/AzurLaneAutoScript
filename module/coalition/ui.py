from typing import TYPE_CHECKING, Literal, override

from module.base.timer import Timer
from module.coalition import assets as coalition_assets
from module.coalition.profile import (
    CoalitionClientSession,
    CoalitionModeDriver,
    CoalitionPageMode,
)
from module.combat.assets import BATTLE_PREPARATION
from module.combat.combat import Combat
from module.content.activity_profile import CoalitionFleetMode, CoalitionFleetRule
from module.exception import HumanTakeoverRequiredError, ScriptError
from module.logger import logger
from module.ui.assets import BACK_ARROW
from module.ui.page import page_coalition
from module.ui.switch import Switch

if TYPE_CHECKING:
    from module.base.base import ModuleBase
    from module.base.button import Button

type CoalitionPageState = Literal["story", "battle", "unknown"]


class RedTextModeSwitch(Switch):
    @override
    def get(self, main: ModuleBase) -> CoalitionPageState:
        for switch_state in self.state_list:
            if main.image_color_count(
                switch_state["check_button"],
                color=(123, 41, 41),
                threshold=221,
                count=100,
            ):
                state = switch_state["state"]
                if state == CoalitionPageMode.STORY:
                    return "story"
                if state == CoalitionPageMode.BATTLE:
                    return "battle"
                message = f"red-text coalition mode switch received an invalid state: {state}"
                raise ScriptError(message)
        return "unknown"


class CoalitionUI(Combat):
    client: CoalitionClientSession

    def in_coalition(self) -> bool:
        return self.ui_page_appear(page_coalition, offset=(20, 20))

    def in_difficulty_selection(self) -> bool:
        difficulty_exit = self.client.profile.preparation.difficulty_exit
        return difficulty_exit is not None and self.appear(difficulty_exit, offset=(20, 20))

    def ui_goto_coalition(self) -> bool:
        if self.ui_get_current_page() == page_coalition:
            logger.info("Already at page_coalition")
            return True
        self.ui_goto(page_coalition)
        return True

    def coalition_ensure_mode(self, mode: CoalitionPageMode) -> None:
        if not isinstance(mode, CoalitionPageMode):
            message = "mode must be a CoalitionPageMode"
            raise TypeError(message)
        profile = self.client.profile
        if profile.mode_driver is CoalitionModeDriver.NONE:
            logger.info(f"Coalition profile {profile.profile_id.value} has no mode switch")
            return

        assets = profile.mode_switch
        if assets is None:
            message = "coalition profile mode switch assets are missing"
            raise ValueError(message)
        switch_type = RedTextModeSwitch if profile.mode_driver is CoalitionModeDriver.RED_TEXT else Switch
        mode_switch = switch_type("CoalitionMode", offset=(20, 20))
        mode_switch.add_state(CoalitionPageMode.STORY.value, assets.story)
        mode_switch.add_state(CoalitionPageMode.BATTLE.value, assets.battle)
        mode_switch.set(mode.value, main=self)

    def coalition_set_fleet(self) -> bool:
        desired = self.client.fleet
        assets = self.client.profile.fleet_switch
        fleet_switch = Switch("FleetMode", is_selector=True, offset=0)
        fleet_switch.add_state(CoalitionFleetMode.SINGLE.value, assets.single)
        fleet_switch.add_state(CoalitionFleetMode.MULTI.value, assets.multi)
        if fleet_switch.get(main=self) == desired.value:
            return False
        fleet_switch.set(desired.value, main=self)
        return True

    def handle_fleet_preparation(self) -> bool:
        """按内容声明切换舰队；固定舰队关卡不显示切换控件。"""
        if self.client.stage.fleet_rule is not CoalitionFleetRule.SELECTABLE:
            return False

        clicked = self.coalition_set_fleet()
        if self.appear(coalition_assets.FLEET_NOT_PREPARED, offset=(20, 20)):
            logger.critical("FLEET_NOT_PREPARED")
            logger.critical("Please prepare your fleets before running coalition battles")
            raise HumanTakeoverRequiredError
        if self.appear(coalition_assets.EMPTY_FLAGSHIP, offset=(20, 20)):
            logger.critical("EMPTY_FLAGSHIP, please prepare your fleets before running coalition battles")
            raise HumanTakeoverRequiredError
        if self.appear(coalition_assets.EMPTY_VANGUARD, offset=(20, 20)):
            logger.critical("EMPTY_VANGUARD, please prepare your fleets before running coalition battles")
            raise HumanTakeoverRequiredError
        return clicked

    def coalition_map_exit(self) -> None:
        """从战斗或舰队准备页返回联合作战页；误到主页时也结束。"""
        logger.info("Coalition map exit")
        preparation = self.client.profile.preparation
        for _ in self.loop():
            if self.in_coalition() or self.is_in_main():
                break
            if self.appear(BATTLE_PREPARATION, offset=(20, 20), interval=3):
                logger.info(f"{BATTLE_PREPARATION} -> {BACK_ARROW}")
                self.device.click(BACK_ARROW)
                continue
            if self.appear(preparation.enter, offset=(20, 20), interval=3):
                logger.info(f"{preparation.enter} -> {preparation.exit}")
                self.device.click(preparation.exit)
                continue
            if preparation.difficulty_exit is not None and self.appear_then_click(
                preparation.difficulty_exit,
                offset=(20, 20),
                interval=3,
            ):
                continue

    @staticmethod
    def _check_enter_clicks(
        entrance: Button,
        difficulty: Button | None,
        entrance_clicks: int,
        difficulty_clicks: int,
        fleet_clicks: int,
    ) -> None:
        if entrance_clicks > 5:
            logger.critical(f"Failed to enter {entrance}, too many clicks on {entrance}")
            logger.critical("Possible reason: the previous stage has not been cleared")
            raise HumanTakeoverRequiredError
        if difficulty_clicks > 5:
            logger.critical(f"Failed to enter {difficulty}, too many clicks on {difficulty}")
            logger.critical("Possible reason: the difficulty asset is not correct")
            raise HumanTakeoverRequiredError
        if fleet_clicks <= 5:
            return
        logger.critical(f"Failed to enter {entrance}, too many clicks on FLEET_PREPARATION")
        logger.critical("Possible reason: the fleets do not satisfy this stage's restrictions")
        logger.critical("Possible reason: this daily stage has already been completed")
        raise HumanTakeoverRequiredError

    def _click_stage(self, entrance: Button, timer: Timer) -> bool:
        if not timer.reached() or not self.in_coalition():
            return False
        self.device.click(entrance)
        timer.reset()
        return True

    def _click_difficulty(self, difficulty: Button | None, timer: Timer) -> bool:
        if difficulty is None or not timer.reached() or not self.in_difficulty_selection():
            return False
        self.device.click(difficulty)
        timer.reset()
        return True

    def _handle_enter_interrupts(self, campaign_timer: Timer) -> bool:
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

    def enter_coalition_map(self) -> None:
        """从联合作战页进入已解析的关卡，结束于战斗准备页。"""
        stage_assets = self.client.profile.stage_assets(self.client.stage.stage_id)
        entrance = stage_assets.entrance
        difficulty = stage_assets.difficulty
        preparation = self.client.profile.preparation.enter
        entrance_timer = Timer(5)
        difficulty_timer = Timer(5)
        fleet_timer = Timer(5)
        entrance_clicks = 0
        difficulty_clicks = 0
        fleet_clicks = 0

        for _ in self.loop():
            self._check_enter_clicks(
                entrance,
                difficulty,
                entrance_clicks,
                difficulty_clicks,
                fleet_clicks,
            )
            if self.appear(BATTLE_PREPARATION, offset=(20, 20)):
                break
            if self.handle_guild_popup_cancel():
                continue
            if self._click_stage(entrance, entrance_timer):
                entrance_clicks += 1
                continue
            if self._click_difficulty(difficulty, difficulty_timer):
                difficulty_clicks += 1
                continue
            if fleet_timer.reached() and self.appear(preparation, offset=(20, 50)):
                self.handle_fleet_preparation()
                self.device.click(preparation)
                fleet_timer.reset()
                entrance_timer.reset()
                fleet_clicks += 1
                continue
            if self._handle_enter_interrupts(entrance_timer):
                continue
