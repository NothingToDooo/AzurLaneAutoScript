from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Protocol

from module.base.timer import Timer
from module.combat.emotion import Emotion, FleetEmotion
from module.equipment import assets as equipment_assets
from module.equipment.fleet_equipment import FleetEquipment
from module.exception import CampaignEnd, HumanTakeoverRequiredError, ScriptError
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
from module.ui.page import page_fleet

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator, Sequence

    from module.base.button import Button
    from module.base.template import Template
    from module.campaign.campaign_engine import CampaignEngine
    from module.retire.scanner import Ship

SIM_VALUE = 0.92
EMOTION_CONTROL_MESSAGE = "Emotion control"
INVALID_GEMS_FARMING_COMMON_DD_MESSAGE = "Invalid GemsFarming_CommonDD"
INVALID_COMMON_DD_SETTING_TEMPLATE = "Invalid CommonDD setting: {common_dd}"
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


class GemsShipReplacementDisposition(StrEnum):
    POLICY_SATISFIED = "policy_satisfied"
    FALLBACK_USED = "fallback_used"
    NO_CANDIDATE = "no_candidate"


@dataclass(frozen=True, slots=True)
class GemsShipReplacementResult:
    disposition: GemsShipReplacementDisposition
    selected_emotion: int | None

    def __post_init__(self) -> None:
        if not isinstance(self.disposition, GemsShipReplacementDisposition):
            message = "gems ship replacement disposition must be a GemsShipReplacementDisposition"
            raise TypeError(message)
        if self.disposition is GemsShipReplacementDisposition.NO_CANDIDATE:
            if self.selected_emotion is not None:
                message = "gems ship replacement without a candidate cannot have selected emotion"
                raise ValueError(message)
            return
        if type(self.selected_emotion) is not int:
            message = "gems ship replacement must include selected emotion"
            raise TypeError(message)
        if not 0 <= self.selected_emotion <= 150:
            message = "gems ship replacement selected emotion must be between 0 and 150"
            raise ValueError(message)


class GemsShipReplacementFactSink(Protocol):
    """在换舰已生效、后续装备回装尚未开始时接收持久化事实。"""

    def __call__(self, result: GemsShipReplacementResult, /) -> None: ...


def _require_replacement_fact_sink(value: object) -> None:
    if isinstance(value, type) or not callable(value):
        message = "replacement fact sink must be callable"
        raise TypeError(message)


def _deliver_replacement_fact(
    result: GemsShipReplacementResult,
    fact_sink: GemsShipReplacementFactSink,
    restore_equipment: Callable[[], None],
) -> None:
    """先交付事实再清理；双重失败时保留两个独立根因。"""

    try:
        fact_sink(result)
    except BaseException as fact_error:
        try:
            restore_equipment()
        except BaseException as restore_error:  # ruff:ignore[blind-except] - 必须把 cleanup 与原始持久化失败一起保留。
            message = "gems replacement fact persistence and equipment restoration both failed"
            raise BaseExceptionGroup(message, (fact_error, restore_error)) from None
        raise
    restore_equipment()


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
        if not self.replacement_required(battle):
            return
        self.config.GEMS_EMOTION_TRIGGERED = True
        raise CampaignEnd(EMOTION_CONTROL_MESSAGE)

    def replacement_required(self, battle: int, *, now: datetime | None = None) -> bool:
        """返回整图预计消耗是否要求换船，不修改跨 turn 的业务状态。"""
        if not self.is_calculate:
            return False

        expected_reduce = battle * self.reduce_per_battle_before_entering
        logger.info(f"Expect emotion reduce: {expected_reduce}")
        self.update()
        self.record()
        self.show()
        current = datetime.now() if now is None else now
        return self.fleet.get_recovered(expected_reduce) > current

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


class GemsFleetReplacement(FleetEquipment, Dock):
    """只负责 GemsFarming 的舰队更换 UI，不拥有地图装载或任务循环。"""

    campaign: CampaignEngine

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

        self.campaign.ensure_campaign_ui(name=self.config.Campaign_Name, mode="hard")
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

    def _is_fleet_slot_empty(self, button: Button) -> bool:
        """普通模式按钮是舰船入口，只有困难模式按钮可用于识别空槽。"""
        return self.is_hard_mode and self.appear(button, offset=(20, 20))

    def _change_equipment(self, button: Button, detail_button: Button, *, take_on: bool) -> None:
        if self.is_hard_mode:
            self.ship_info_enter(button, long_click=True, skip_first_screenshot=False)
        else:
            self.fleet_enter_ship(detail_button)

        success = self.code_apply() if take_on else self.code_clear()
        if not success:
            logger.critical(EQUIPMENT_CODE_CHANGE_FAILED_MESSAGE)
            raise HumanTakeoverRequiredError(EQUIPMENT_CODE_CHANGE_FAILED_MESSAGE)

        if self.is_hard_mode:
            self.ui_back(check_button=FLEET_PREPARATION)
        else:
            self.fleet_back()

    def flagship_change(self, fact_sink: GemsShipReplacementFactSink) -> GemsShipReplacementResult:
        """更换旗舰，并按配置用装备码转移装备。"""
        _require_replacement_fact_sink(fact_sink)
        logger.hr("Change flagship", level=1)
        logger.attr("ChangeFlagship", self.config.GemsFarming_ChangeFlagship)
        self._goto_fleet()
        button = self.fleet_backline_1_button
        equipment_taken_off = False

        if self.change_flagship_equip and not self._is_fleet_slot_empty(button):
            logger.hr("Unmount flagship equipments", level=2)
            self._change_equipment(
                button,
                equipment_assets.FLEET_DETAIL_ENTER_FLAGSHIP,
                take_on=False,
            )
            equipment_taken_off = True

        logger.hr("Change flagship", level=2)
        result = self.flagship_change_execute()

        def restore_equipment() -> None:
            if equipment_taken_off and not self._is_fleet_slot_empty(button):
                logger.hr("Mount flagship equipments", level=2)
                self._change_equipment(
                    button,
                    equipment_assets.FLEET_DETAIL_ENTER_FLAGSHIP,
                    take_on=True,
                )

        # 换舰确认已经改变真实舰队；先交付事实，回装失败也不能丢失心情账本。
        _deliver_replacement_fact(result, fact_sink, restore_equipment)
        return result

    def vanguard_change(self, fact_sink: GemsShipReplacementFactSink) -> GemsShipReplacementResult:
        """更换前排，并按配置用装备码转移装备。"""
        _require_replacement_fact_sink(fact_sink)
        logger.hr("Change vanguard", level=1)
        logger.attr("ChangeVanguard", self.config.GemsFarming_ChangeVanguard)
        self._goto_fleet()
        button = self.fleet_vanguard_1_button
        equipment_taken_off = False

        if self.change_vanguard_equip and not self._is_fleet_slot_empty(button):
            logger.hr("Unmount vanguard equipments", level=2)
            self._change_equipment(button, equipment_assets.FLEET_DETAIL_ENTER, take_on=False)
            equipment_taken_off = True

        logger.hr("Change vanguard", level=2)
        result = self.vanguard_change_execute()

        def restore_equipment() -> None:
            if equipment_taken_off and not self._is_fleet_slot_empty(button):
                logger.hr("Mount vanguard equipments", level=2)
                self._change_equipment(button, equipment_assets.FLEET_DETAIL_ENTER, take_on=True)

        # 与旗舰相同，事实交付点必须早于可能失败的装备回装。
        _deliver_replacement_fact(result, fact_sink, restore_equipment)
        return result

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

    def _ship_replacement_result(
        self,
        ship: Ship,
        disposition: GemsShipReplacementDisposition,
    ) -> GemsShipReplacementResult:
        emotion = self._ship_attribute(ship, "emotion")
        return GemsShipReplacementResult(disposition, emotion)

    def _select_low_level_cv(self, candidates: Sequence[Ship]) -> Ship:
        """优先选择低等级航母；同等级时选择心情更高的舰船。"""
        return min(
            candidates,
            key=lambda candidate: (
                self._ship_attribute(candidate, "level"),
                -self._ship_attribute(candidate, "emotion"),
            ),
        )

    def _normal_flagship_change_execute(self) -> GemsShipReplacementResult:
        self.ship_info_enter(
            equipment_assets.FLEET_ENTER_FLAGSHIP,
            check_button=DOCK_CHECK,
            long_click=False,
            skip_first_screenshot=False,
        )
        candidates = self.get_common_rarity_cv(min_emotion=self.min_emotion)
        if candidates:
            ship = self._select_low_level_cv(candidates)
            result = self._ship_replacement_result(ship, GemsShipReplacementDisposition.POLICY_SATISFIED)
            self._ship_change_confirm(ship.button, check_button=page_fleet.check_button)
            logger.info("Change flagship success")
            return result

        logger.info("Change flagship failed, no CV in common rarity")
        self._dock_reset()
        self.ui_back(check_button=page_fleet.check_button)
        return GemsShipReplacementResult(GemsShipReplacementDisposition.NO_CANDIDATE, None)

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

    def _hard_flagship_change_execute(self) -> GemsShipReplacementResult:
        unmount_button, mount_button = HARD_BACKLINE_BUTTONS[self.fleet_to_attack_slot]
        self._hard_unmount(unmount_button, ship_name="flagship")
        self._enter_hard_dock(mount_button)

        candidates = self.get_common_rarity_cv(max_level=31, min_emotion=self.min_emotion)
        if candidates:
            ship = self._select_low_level_cv(candidates)
            result = self._ship_replacement_result(ship, GemsShipReplacementDisposition.POLICY_SATISFIED)
            self._ship_change_confirm(ship.button, check_button=FLEET_PREPARATION)
            logger.info("Change flagship success")
            return result

        logger.info("Change flagship failed, try using leveled or exhausted CVs")
        candidates = self.get_common_rarity_cv(max_level=100)
        if candidates:
            ship = self._select_low_level_cv(candidates)
            result = self._ship_replacement_result(ship, GemsShipReplacementDisposition.FALLBACK_USED)
            self._ship_change_confirm(ship.button, check_button=FLEET_PREPARATION)
            return result

        logger.info("Change flagship failed, no CV was found")
        self._dock_reset()
        self.ui_back(check_button=FLEET_PREPARATION)
        return GemsShipReplacementResult(GemsShipReplacementDisposition.NO_CANDIDATE, None)

    def flagship_change_execute(self) -> GemsShipReplacementResult:
        if self.is_hard_mode:
            return self._hard_flagship_change_execute()
        return self._normal_flagship_change_execute()

    def _normal_vanguard_change_execute(self) -> GemsShipReplacementResult:
        self.ship_info_enter(
            equipment_assets.FLEET_ENTER,
            check_button=DOCK_CHECK,
            long_click=False,
            skip_first_screenshot=False,
        )
        candidates = self.get_common_rarity_dd(min_emotion=self.min_emotion)
        if candidates:
            ship = max(candidates, key=lambda candidate: self._ship_attribute(candidate, "emotion"))
            result = self._ship_replacement_result(ship, GemsShipReplacementDisposition.POLICY_SATISFIED)
            self._ship_change_confirm(ship.button, check_button=page_fleet.check_button)
            logger.info("Change vanguard success")
            return result

        logger.info("Change vanguard failed, no DD in common rarity")
        self._dock_reset()
        self.ui_back(check_button=page_fleet.check_button)
        return GemsShipReplacementResult(GemsShipReplacementDisposition.NO_CANDIDATE, None)

    def _hard_vanguard_change_execute(self) -> GemsShipReplacementResult:
        unmount_button, mount_button = HARD_VANGUARD_BUTTONS[self.fleet_to_attack_slot]
        self._hard_unmount(unmount_button, ship_name="vanguard")
        self._enter_hard_dock(mount_button)

        candidates = self.get_common_rarity_dd(min_emotion=self.min_emotion)
        if candidates:
            ship = max(candidates, key=lambda candidate: self._ship_attribute(candidate, "emotion"))
            result = self._ship_replacement_result(ship, GemsShipReplacementDisposition.POLICY_SATISFIED)
            self._ship_change_confirm(ship.button, check_button=FLEET_PREPARATION)
            logger.info("Change vanguard success")
            return result

        logger.info("Change vanguard failed, try using exhausted DDs")
        candidates = self.get_common_rarity_dd()
        if candidates:
            ship = max(candidates, key=lambda candidate: self._ship_attribute(candidate, "emotion"))
            result = self._ship_replacement_result(ship, GemsShipReplacementDisposition.FALLBACK_USED)
            self._ship_change_confirm(ship.button, check_button=FLEET_PREPARATION)
            return result

        logger.info("Change vanguard failed, no DD was found")
        self._dock_reset()
        self.ui_back(check_button=FLEET_PREPARATION)
        return GemsShipReplacementResult(GemsShipReplacementDisposition.NO_CANDIDATE, None)

    def vanguard_change_execute(self) -> GemsShipReplacementResult:
        if self.is_hard_mode:
            return self._hard_vanguard_change_execute()
        return self._normal_vanguard_change_execute()

    def hard_fleet_prepare(
        self,
        fact_sink: GemsShipReplacementFactSink,
    ) -> Iterator[GemsShipReplacementResult]:
        """补齐困难模式空位，并逐项返回已经完成的换舰结果。"""
        _require_replacement_fact_sink(fact_sink)
        if self.appear(self.fleet_backline_1_button, offset=(20, 20)):
            logger.info("Backline is empty, change flagship")
            yield self.flagship_change(fact_sink)
        if self.appear(self.fleet_vanguard_1_button, offset=(20, 20)):
            logger.info("Vanguard is empty, change vanguard")
            yield self.vanguard_change(fact_sink)
