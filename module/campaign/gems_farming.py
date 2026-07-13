from datetime import datetime
from typing import TYPE_CHECKING

from module.base.decorator import cached_property
from module.base.timer import Timer
from module.campaign.campaign_base import CampaignBase
from module.campaign.run import CampaignMode, CampaignRun
from module.combat.assets import BATTLE_PREPARATION
from module.combat.emotion import Emotion, FleetEmotion
from module.equipment import assets as equipment_assets
from module.equipment.fleet_equipment import FleetEquipment
from module.exception import CampaignEnd, HardNotSatisfied, RequestHumanTakeover, ScriptError
from module.handler.assets import AUTO_SEARCH_MAP_OPTION_OFF
from module.logger import logger
from module.map.assets import FLEET_PREPARATION, MAP_PREPARATION
from module.retire.assets import (
    DOCK_CHECK,
    DOCK_UNMOUNT,
    TEMPLATE_AULICK,
    TEMPLATE_BOGUE,
    TEMPLATE_CASSIN_1,
    TEMPLATE_CASSIN_2,
    TEMPLATE_DOWNES_1,
    TEMPLATE_DOWNES_2,
    TEMPLATE_FOOTE,
    TEMPLATE_HERMES,
    TEMPLATE_LANGLEY,
    TEMPLATE_RANGER,
)
from module.retire.dock import Dock
from module.retire.scanner import ShipScanner
from module.ui.assets import BACK_ARROW
from module.ui.page import page_fleet

if TYPE_CHECKING:
    from collections.abc import Sequence

    from module.base.button import Button
    from module.base.template import Template
    from module.retire.scanner import Ship

SIM_VALUE = 0.92
EMOTION_WITHDRAW_MESSAGE = "Emotion withdraw"
EMOTION_CONTROL_MESSAGE = "Emotion control"
INVALID_GEMS_FARMING_COMMON_DD_MESSAGE = "Invalid GemsFarming_CommonDD"
INVALID_COMMON_DD_SETTING_TEMPLATE = "Invalid CommonDD setting: {common_dd}"
GEMS_FARMING_CAMPAIGN_MODULE_MISSING_MESSAGE = "Gems farming campaign module is not loaded"
UNCACHED_SHIP_SCAN_MESSAGE = "Uncached ship scan must return ships"
UNREADABLE_SHIP_ATTRIBUTE_MESSAGE = "Ship scan returned an unreadable {attribute}"
EQUIPMENT_CODE_CHANGE_FAILED_MESSAGE = "GemsFarming equipment code change failed"

HARD_BACKLINE_BUTTONS = {
    1: (equipment_assets.FLEET_1_BACKLINE_1, equipment_assets.FLEET_1_BACKLINE_3),
    2: (equipment_assets.FLEET_2_BACKLINE_1, equipment_assets.FLEET_2_BACKLINE_3),
}
HARD_VANGUARD_BUTTONS = {
    1: (equipment_assets.FLEET_1_VANGUARD_1, equipment_assets.FLEET_1_VANGUARD_3),
    2: (equipment_assets.FLEET_2_VANGUARD_1, equipment_assets.FLEET_2_VANGUARD_3),
}


class GemsCampaignOverride(CampaignBase):
    gems_farming: GemsFarming

    def bind_gems_farming(self, runner: GemsFarming) -> None:
        self.gems_farming = runner

    @cached_property
    def emotion(self) -> GemsEmotion:
        return GemsEmotion(config=self.config)

    def fleet_preparation(self) -> bool:
        try:
            return super().fleet_preparation()
        except HardNotSatisfied:
            pass

        prepared = self.gems_farming.hard_fleet_prepare()
        if prepared:
            try:
                return super().fleet_preparation()
            except HardNotSatisfied:
                logger.warning("Hard fleet still not satisfied after GemsFarming preparation")
        else:
            logger.warning("No ship available for GemsFarming hard fleet preparation")

        self.gems_farming.config.task_delay(minute=30)
        self.gems_farming.config.task_stop()
        return False

    def handle_combat_low_emotion(self) -> bool:
        """启用前排更换时，低心情会撤出战斗并更换旗舰和前排。"""
        if self.config.GemsFarming_ChangeVanguard == "disabled":
            return self._handle_low_emotion_ignore()

        if not self.handle_popup_cancel("IGNORE_LOW_EMOTION"):
            return False

        self.config.GEMS_EMOTION_TRIGGERED = True
        logger.hr("EMOTION WITHDRAW")
        self._withdraw_for_low_emotion()
        raise CampaignEnd(EMOTION_WITHDRAW_MESSAGE)

    def _handle_low_emotion_ignore(self) -> bool:
        result = self.handle_popup_confirm("IGNORE_LOW_EMOTION")
        if result:
            # 避免点击 AUTO_SEARCH_MAP_OPTION_OFF。
            self.interval_reset(AUTO_SEARCH_MAP_OPTION_OFF)
        return result

    def _withdraw_for_low_emotion(self) -> None:
        while 1:
            self.device.screenshot()
            handled, finished = self._low_emotion_withdraw_step()
            if finished:
                break
            if handled:
                continue

    def _low_emotion_withdraw_step(self) -> tuple[bool, bool]:
        if self._low_emotion_skip_dialogs():
            return True, False
        if self._low_emotion_leave_battle_preparation():
            return True, False
        if self.handle_auto_search_exit():
            return True, False
        return self._low_emotion_finish_withdraw()

    def _low_emotion_skip_dialogs(self) -> bool:
        return self.handle_story_skip() or self.handle_popup_cancel("IGNORE_LOW_EMOTION")

    def _low_emotion_leave_battle_preparation(self) -> bool:
        if not self.appear(BATTLE_PREPARATION, offset=(20, 20), interval=2):
            return False

        self.device.click(BACK_ARROW)
        return True

    def _low_emotion_finish_withdraw(self) -> tuple[bool, bool]:
        if self.is_in_stage():
            return True, True
        if self.is_in_map():
            self.withdraw()
            return True, True
        if self._low_emotion_at_preparation():
            self.enter_map_cancel()
            return True, True
        return False, False

    def _low_emotion_at_preparation(self) -> bool:
        return self.appear(FLEET_PREPARATION, offset=(20, 50), interval=2) or self.appear(
            MAP_PREPARATION, offset=(20, 20), interval=2
        )


class GemsEmotion(Emotion):
    """只用 Fleet1 记录实际攻击队的心情，不等待未参战的支援队。"""

    @property
    def fleet(self) -> FleetEmotion:
        return self.fleet_1

    def update(self) -> None:
        self.fleet.update()

    def record(self) -> None:
        self.config.set_record(**{self.fleet.value_name: self.fleet.current})

    def show(self) -> None:
        logger.attr("Emotion fleet_attack", self.fleet.value)

    def check_reduce(self, battle: int) -> None:
        if not self.is_calculate:
            return

        expected_reduce = battle * self.reduce_per_battle_before_entering
        logger.info(f"Expect emotion reduce: {expected_reduce}")
        self.update()
        self.record()
        self.show()
        if self.fleet.get_recovered(expected_reduce) > datetime.now():
            self.config.GEMS_EMOTION_TRIGGERED = True
            raise CampaignEnd(EMOTION_CONTROL_MESSAGE)

    def wait(self, fleet_index: int) -> None:
        del fleet_index
        self.update()
        self.record()
        self.show()
        if self.fleet.get_recovered(expected_reduce=self.reduce_per_battle) > datetime.now():
            self.config.GEMS_EMOTION_TRIGGERED = True

    def reduce(self, fleet_index: int) -> None:
        del fleet_index
        logger.hr("Emotion reduce")
        self.update()
        self.fleet.current -= self.reduce_per_battle
        self.total_reduced += self.reduce_per_battle
        self.record()
        self.show()


class GemsFarming(CampaignRun, FleetEquipment, Dock):
    @staticmethod
    def _campaign_with_gems_override(campaign_class: type[CampaignBase]) -> type[GemsCampaignOverride]:
        return type("GemsCampaign", (GemsCampaignOverride, campaign_class), {})

    def load_campaign(self, name: str, folder: str = "campaign_main") -> bool:
        loaded = super().load_campaign(name, folder=folder)

        loaded_stage = self.loaded_stage
        if loaded_stage is None:
            raise ScriptError(GEMS_FARMING_CAMPAIGN_MODULE_MISSING_MESSAGE)
        campaign_class = self._campaign_with_gems_override(loaded_stage.campaign_class)
        campaign = campaign_class(device=self.campaign.device, config=self.campaign.config)
        campaign.bind_gems_farming(self)
        self.campaign = campaign
        if not self.change_vanguard:
            self.campaign.config.override(Emotion_Mode="ignore")
        self.campaign.config.override(EnemyPriority_EnemyScaleBalanceWeight="S1_enemy_first")
        return loaded

    @property
    def change_flagship_equip(self) -> bool:
        return "equip" in self.config.GemsFarming_ChangeFlagship

    @property
    def change_vanguard(self) -> bool:
        return "ship" in self.config.GemsFarming_ChangeVanguard

    @property
    def change_vanguard_equip(self) -> bool:
        return "equip" in self.config.GemsFarming_ChangeVanguard

    @property
    def is_hard_mode(self) -> bool:
        return self.config.Campaign_Mode == "hard"

    @property
    def min_emotion(self) -> int:
        return (2 + self.campaign.map_battle_count) * self.campaign.emotion.reduce_per_battle

    @property
    def fleet_to_attack_slot(self) -> int:
        if self.config.Fleet_FleetOrder == "fleet1_standby_fleet2_all":
            return 2
        return 1

    @property
    def fleet_to_attack(self) -> int:
        if self.fleet_to_attack_slot == 2:
            return self.config.Fleet_Fleet2
        return self.config.Fleet_Fleet1

    def _goto_hard_fleet(self) -> None:
        if self.appear(FLEET_PREPARATION, offset=(20, 50)):
            return

        self.campaign.ensure_campaign_ui(name=self.stage, mode="hard")
        self.campaign.ENTRANCE.area = self.campaign.ENTRANCE.button
        campaign_timer = Timer(5)
        map_timer = Timer(5)
        for _ in self.loop():
            if self.appear(FLEET_PREPARATION, offset=(20, 50)):
                return
            if (
                map_timer.reached()
                and self.campaign.handle_map_mode_switch("hard")
                and self.campaign.handle_map_preparation()
            ):
                self.device.click(MAP_PREPARATION)
                map_timer.reset()
                campaign_timer.reset()
            if self.campaign.handle_retirement():
                continue
            if campaign_timer.reached() and self.appear_then_click(self.campaign.ENTRANCE):
                campaign_timer.reset()

    def _goto_fleet(self) -> None:
        if self.is_hard_mode:
            self._goto_hard_fleet()
        else:
            self.fleet_enter(self.fleet_to_attack)

    @property
    def fleet_backline_1_button(self) -> Button:
        if self.is_hard_mode:
            return HARD_BACKLINE_BUTTONS[self.fleet_to_attack_slot][0]
        return equipment_assets.FLEET_ENTER_FLAGSHIP

    @property
    def fleet_vanguard_1_button(self) -> Button:
        if self.is_hard_mode:
            return HARD_VANGUARD_BUTTONS[self.fleet_to_attack_slot][0]
        return equipment_assets.FLEET_ENTER

    def _change_equipment(self, button: Button, detail_button: Button, *, take_on: bool) -> None:
        if self.is_hard_mode:
            self.ship_info_enter(button, long_click=True, skip_first_screenshot=False)
        else:
            self.fleet_enter_ship(detail_button)

        success = self.code_apply() if take_on else self.code_clear()
        if not success:
            logger.critical(EQUIPMENT_CODE_CHANGE_FAILED_MESSAGE)
            raise RequestHumanTakeover(EQUIPMENT_CODE_CHANGE_FAILED_MESSAGE)

        if self.is_hard_mode:
            self.ui_back(check_button=FLEET_PREPARATION)
        else:
            self.fleet_back()

    def flagship_change(self) -> bool:
        """更换旗舰，并按配置用装备码转移装备。"""
        logger.hr("Change flagship", level=1)
        logger.attr("ChangeFlagship", self.config.GemsFarming_ChangeFlagship)
        self._goto_fleet()
        button = self.fleet_backline_1_button
        equipment_taken_off = False

        if self.change_flagship_equip and not self.appear(button, offset=(20, 20)):
            logger.hr("Unmount flagship equipments", level=2)
            self._change_equipment(
                button,
                equipment_assets.FLEET_DETAIL_ENTER_FLAGSHIP,
                take_on=False,
            )
            equipment_taken_off = True

        logger.hr("Change flagship", level=2)
        success = self.flagship_change_execute()

        if equipment_taken_off:
            logger.hr("Mount flagship equipments", level=2)
            self._change_equipment(
                button,
                equipment_assets.FLEET_DETAIL_ENTER_FLAGSHIP,
                take_on=True,
            )
        return success

    def vanguard_change(self) -> bool:
        """更换前排，并按配置用装备码转移装备。"""
        logger.hr("Change vanguard", level=1)
        logger.attr("ChangeVanguard", self.config.GemsFarming_ChangeVanguard)
        self._goto_fleet()
        button = self.fleet_vanguard_1_button
        equipment_taken_off = False

        if self.change_vanguard_equip and not self.appear(button, offset=(20, 20)):
            logger.hr("Unmount vanguard equipments", level=2)
            self._change_equipment(button, equipment_assets.FLEET_DETAIL_ENTER, take_on=False)
            equipment_taken_off = True

        logger.hr("Change vanguard", level=2)
        success = self.vanguard_change_execute()

        if equipment_taken_off:
            logger.hr("Mount vanguard equipments", level=2)
            self._change_equipment(button, equipment_assets.FLEET_DETAIL_ENTER, take_on=True)
        return success

    def _dock_reset(self) -> None:
        self.dock_favourite_set(enable=False, wait_loading=False)
        self.dock_sort_method_dsc_set(wait_loading=False)
        self.dock_filter_set()

    def _ship_change_confirm(self, button: Button, *, check_button: Button) -> None:
        self.dock_select_one(button)
        self._dock_reset()
        self.dock_select_confirm(check_button=check_button)

    def _scan_ships(self, scanner: ShipScanner, *, output: bool = True) -> list[Ship]:
        ships = scanner.scan(self.device.image, output=output)
        if ships is None:
            raise RuntimeError(UNCACHED_SHIP_SCAN_MESSAGE)
        return ships

    def find_candidates(
        self,
        templates: Sequence[Template],
        scanner: ShipScanner,
        *,
        output: bool,
    ) -> list[Ship]:
        ships = self._scan_ships(scanner, output=output)
        if not templates:
            return ships
        return [
            ship
            for ship in ships
            if any(
                template.match(self.image_crop(ship.button, copy=False), similarity=SIM_VALUE) for template in templates
            )
        ]

    def get_cv_templates(self) -> list[Template]:
        if self.config.GemsFarming_CommonCV == "any":
            return []
        templates = {
            "bogue": TEMPLATE_BOGUE,
            "hermes": TEMPLATE_HERMES,
            "langley": TEMPLATE_LANGLEY,
            "ranger": TEMPLATE_RANGER,
        }
        return [templates[self.config.GemsFarming_CommonCV]]

    def get_common_rarity_cv(self, *, max_level: int = 31, min_emotion: int = 0) -> list[Ship]:
        """选择满足等级和心情要求的普通航母。"""
        self.dock_favourite_set(enable=False, wait_loading=False)
        self.dock_sort_method_dsc_set(enable=False, wait_loading=False)
        self.dock_filter_set(index="cv", rarity="common", extra="enhanceable", sort="total")

        logger.hr("FINDING FLAGSHIP")
        templates = self.get_cv_templates()
        scanner = ShipScanner(
            level=(1, max_level),
            emotion=(min_emotion, 150),
            fleet=self.fleet_to_attack,
            status="free",
        )
        scanner.disable("rarity")

        candidates = self.find_candidates(templates, scanner, output=True)
        if candidates:
            return candidates

        scanner.set_limitation(fleet=0)
        candidates = self.find_candidates(templates, scanner, output=False)
        if candidates or not templates:
            return candidates

        logger.info("No specific CV was found, try reversed order.")
        self.dock_sort_method_dsc_set(enable=True)
        return self.find_candidates(templates, scanner, output=True)

    def get_dd_faction(self) -> str | list[str]:
        if self.config.GemsFarming_CommonDD == "any":
            return ["eagle", "iron"]
        if self.config.GemsFarming_CommonDD == "favourite":
            return "all"
        if self.config.GemsFarming_CommonDD == "z20_or_z21":
            return "iron"
        if self.config.GemsFarming_CommonDD in ["aulick_or_foote", "cassin_or_downes"]:
            return "eagle"
        message = INVALID_COMMON_DD_SETTING_TEMPLATE.format(common_dd=self.config.GemsFarming_CommonDD)
        logger.error(message)
        raise ScriptError(INVALID_GEMS_FARMING_COMMON_DD_MESSAGE)

    def get_common_rarity_dd(self, *, min_emotion: int = 0) -> list[Ship]:
        """选择满足心情要求的 100 级国服普通驱逐。"""
        faction = self.get_dd_faction()

        favourite = self.config.GemsFarming_CommonDD == "favourite"
        self.dock_favourite_set(enable=favourite, wait_loading=False)
        self.dock_sort_method_dsc_set(enable=True, wait_loading=False)
        self.dock_filter_set(index="dd", rarity="common", faction=faction, extra="can_limit_break")

        logger.hr("FINDING VANGUARD")
        templates = self.get_templates(self.config.GemsFarming_CommonDD)
        scanner = ShipScanner(
            level=(100, 100),
            emotion=(min_emotion, 150),
            fleet=[0, self.fleet_to_attack],
            status="free",
        )
        scanner.disable("rarity")

        candidates = self.find_candidates(templates, scanner, output=True)
        if candidates or not templates:
            return candidates

        logger.info("No specific DD was found, try reversed order.")
        self.dock_sort_method_dsc_set(enable=False)
        return self.find_candidates(templates, scanner, output=True)

    @staticmethod
    def get_templates(common_dd: str) -> list[Template]:
        if common_dd == "aulick_or_foote":
            return [TEMPLATE_AULICK, TEMPLATE_FOOTE]
        if common_dd == "cassin_or_downes":
            return [TEMPLATE_CASSIN_1, TEMPLATE_CASSIN_2, TEMPLATE_DOWNES_1, TEMPLATE_DOWNES_2]
        if common_dd in {"any", "favourite", "z20_or_z21"}:
            return []
        message = INVALID_COMMON_DD_SETTING_TEMPLATE.format(common_dd=common_dd)
        logger.error(message)
        raise ScriptError(message)

    @staticmethod
    def _ship_attribute(ship: Ship, attribute: str) -> int:
        value = getattr(ship, attribute)
        if not isinstance(value, int):
            message = UNREADABLE_SHIP_ATTRIBUTE_MESSAGE.format(attribute=attribute)
            raise TypeError(message)
        return value

    def _record_new_ship_emotion(self, ship: Ship) -> None:
        emotion = self._ship_attribute(ship, "emotion")
        if self._new_fleet_emotion:
            self._new_fleet_emotion = min(emotion, self._new_fleet_emotion)
        else:
            self._new_fleet_emotion = emotion

    def _select_low_level_cv(self, candidates: Sequence[Ship]) -> Ship:
        """优先选择低等级航母；同等级时选择心情更高的舰船。"""
        return min(
            candidates,
            key=lambda candidate: (
                self._ship_attribute(candidate, "level"),
                -self._ship_attribute(candidate, "emotion"),
            ),
        )

    def _normal_flagship_change_execute(self) -> bool:
        self.ship_info_enter(
            equipment_assets.FLEET_ENTER_FLAGSHIP,
            check_button=DOCK_CHECK,
            long_click=False,
            skip_first_screenshot=False,
        )
        candidates = self.get_common_rarity_cv(min_emotion=self.min_emotion)
        if candidates:
            ship = self._select_low_level_cv(candidates)
            self._record_new_ship_emotion(ship)
            self._ship_change_confirm(ship.button, check_button=page_fleet.check_button)
            logger.info("Change flagship success")
            return True

        logger.info("Change flagship failed, no CV in common rarity")
        self._new_fleet_emotion = 0
        self._dock_reset()
        self.ui_back(check_button=page_fleet.check_button)
        return False

    def _hard_unmount(self, button: Button, *, ship_name: str) -> None:
        if self.appear(button, offset=(20, 20)):
            logger.info(f"No {ship_name} to unmount, skip unmounting")
            return
        self.ship_info_enter(
            button,
            check_button=DOCK_CHECK,
            long_click=False,
            skip_first_screenshot=False,
        )
        self.ui_click(
            DOCK_UNMOUNT,
            check_button=FLEET_PREPARATION,
            appear_button=DOCK_CHECK,
            additional=self.ensure_no_info_bar,
            confirm_wait=1,
            retry_wait=5,
        )

    def _enter_hard_dock(self, button: Button) -> None:
        self.ship_info_enter(
            button,
            check_button=DOCK_CHECK,
            long_click=False,
            skip_first_screenshot=False,
        )

    def _hard_flagship_change_execute(self) -> bool:
        unmount_button, mount_button = HARD_BACKLINE_BUTTONS[self.fleet_to_attack_slot]
        self._hard_unmount(unmount_button, ship_name="flagship")
        self._enter_hard_dock(mount_button)

        candidates = self.get_common_rarity_cv(max_level=31, min_emotion=self.min_emotion)
        if candidates:
            ship = self._select_low_level_cv(candidates)
            self._record_new_ship_emotion(ship)
            self._ship_change_confirm(ship.button, check_button=FLEET_PREPARATION)
            logger.info("Change flagship success")
            return True

        logger.info("Change flagship failed, try using leveled or exhausted CVs")
        candidates = self.get_common_rarity_cv(max_level=100)
        if candidates:
            ship = self._select_low_level_cv(candidates)
            self._record_new_ship_emotion(ship)
            self._ship_change_confirm(ship.button, check_button=FLEET_PREPARATION)
            return False

        logger.info("Change flagship failed, no CV was found")
        self._new_fleet_emotion = 0
        self._dock_reset()
        self.ui_back(check_button=FLEET_PREPARATION)
        return False

    def flagship_change_execute(self) -> bool:
        if self.is_hard_mode:
            return self._hard_flagship_change_execute()
        return self._normal_flagship_change_execute()

    def _normal_vanguard_change_execute(self) -> bool:
        self.ship_info_enter(
            equipment_assets.FLEET_ENTER,
            check_button=DOCK_CHECK,
            long_click=False,
            skip_first_screenshot=False,
        )
        candidates = self.get_common_rarity_dd(min_emotion=self.min_emotion)
        if candidates:
            ship = max(candidates, key=lambda candidate: self._ship_attribute(candidate, "emotion"))
            self._record_new_ship_emotion(ship)
            self._ship_change_confirm(ship.button, check_button=page_fleet.check_button)
            logger.info("Change vanguard success")
            return True

        logger.info("Change vanguard failed, no DD in common rarity")
        self._new_fleet_emotion = 0
        self._dock_reset()
        self.ui_back(check_button=page_fleet.check_button)
        return False

    def _hard_vanguard_change_execute(self) -> bool:
        unmount_button, mount_button = HARD_VANGUARD_BUTTONS[self.fleet_to_attack_slot]
        self._hard_unmount(unmount_button, ship_name="vanguard")
        self._enter_hard_dock(mount_button)

        candidates = self.get_common_rarity_dd(min_emotion=self.min_emotion)
        if candidates:
            ship = max(candidates, key=lambda candidate: self._ship_attribute(candidate, "emotion"))
            self._record_new_ship_emotion(ship)
            self._ship_change_confirm(ship.button, check_button=FLEET_PREPARATION)
            logger.info("Change vanguard success")
            return True

        logger.info("Change vanguard failed, try using exhausted DDs")
        candidates = self.get_common_rarity_dd()
        if candidates:
            ship = max(candidates, key=lambda candidate: self._ship_attribute(candidate, "emotion"))
            self._record_new_ship_emotion(ship)
            self._ship_change_confirm(ship.button, check_button=FLEET_PREPARATION)
            return False

        logger.info("Change vanguard failed, no DD was found")
        self._new_fleet_emotion = 0
        self._dock_reset()
        self.ui_back(check_button=FLEET_PREPARATION)
        return False

    def vanguard_change_execute(self) -> bool:
        if self.is_hard_mode:
            return self._hard_vanguard_change_execute()
        return self._normal_vanguard_change_execute()

    def hard_fleet_prepare(self) -> bool:
        """困难模式退役后补齐空位；所有替换都有效时才允许重试进图。"""
        change_results: list[bool] = []
        if self.appear(self.fleet_backline_1_button, offset=(20, 20)):
            logger.info("Backline is empty, change flagship")
            change_results.append(self.flagship_change())
        if self.appear(self.fleet_vanguard_1_button, offset=(20, 20)):
            logger.info("Vanguard is empty, change vanguard")
            change_results.append(self.vanguard_change())
        return bool(change_results) and all(change_results)

    _trigger_lv32 = False
    _trigger_emotion = False
    _new_fleet_emotion = 0

    def triggered_stop_condition(self, *, oil_check: bool = True) -> bool:
        # 等级上限为 32。
        if self.campaign.config.LV32_TRIGGERED:
            self._trigger_lv32 = True
            logger.hr("TRIGGERED LV32 LIMIT")
            return True

        if self.campaign.config.GEMS_EMOTION_TRIGGERED:
            self._trigger_emotion = True
            logger.hr("TRIGGERED EMOTION LIMIT")
            return True

        return super().triggered_stop_condition(oil_check=oil_check)

    def run(
        self,
        name: str,
        folder: str = "campaign_main",
        mode: CampaignMode = "normal",
        total: int = 0,
    ) -> None:
        """运行指定地图文件；mode 接受 normal 或 hard。"""
        self.config.override(STOP_IF_REACH_LV32=True)

        while 1:
            self._trigger_lv32 = False
            self._trigger_emotion = False
            is_limit = self.config.StopCondition_RunCount

            try:
                super().run(name=name, folder=folder, mode=mode, total=total)
            except CampaignEnd as e:
                if str(e) in {EMOTION_WITHDRAW_MESSAGE, EMOTION_CONTROL_MESSAGE}:
                    self._trigger_emotion = True
                else:
                    raise

            if self._trigger_lv32 or self._trigger_emotion:
                self._new_fleet_emotion = 150
                success = self.flagship_change()
                if self.change_vanguard:
                    success = success and self.vanguard_change()
                self.campaign.config.set_record(Emotion_Fleet1Value=self._new_fleet_emotion)

                if is_limit and self.config.StopCondition_RunCount <= 0:
                    logger.hr("Triggered stop condition: Run count")
                    self.config.StopCondition_RunCount = 0
                    self.config.Scheduler_Enable = False
                    self._notify_campaign_finished("reached run count limit")
                    break

                self._trigger_lv32 = False
                self._trigger_emotion = False
                self.campaign.config.LV32_TRIGGERED = False
                self.campaign.config.GEMS_EMOTION_TRIGGERED = False

                if self.config.task_switched():
                    self.campaign.ensure_auto_search_exit()
                    self.config.task_stop()
                elif not success:
                    self.campaign.ensure_auto_search_exit()
                    self.config.task_delay(minute=30)
                    self.config.task_stop()

                continue
            break
