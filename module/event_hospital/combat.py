from typing import TYPE_CHECKING

from module.base.decorator import run_once
from module.base.timer import Timer
from module.campaign.campaign_event import CampaignEvent
from module.combat.assets import BATTLE_PREPARATION
from module.combat.combat import Combat
from module.event_hospital.assets import HOSPITAL_BATTLE_PREPARE
from module.event_hospital.ui import HospitalUI
from module.exception import OilExhausted, RequestHumanTakeover
from module.logger import logger
from module.map.assets import (
    FLEET_1_ADVICE,
    FLEET_1_BAR,
    FLEET_1_CHOOSE,
    FLEET_1_CLEAR,
    FLEET_1_HARD_SATIESFIED,
    FLEET_1_IN_USE,
)
from module.map.map_fleet_preparation import FleetOperator, FleetOperatorAssets
from module.raid.assets import RAID_FLEET_PREPARATION

if TYPE_CHECKING:
    from collections.abc import Callable


class HospitalCombat(Combat, HospitalUI, CampaignEvent):
    def handle_fleet_recommend(self, *, recommend: bool = True) -> bool:
        fleet_1 = FleetOperator(
            assets=FleetOperatorAssets(
                choose=FLEET_1_CHOOSE,
                advice=FLEET_1_ADVICE,
                bar=FLEET_1_BAR,
                clear=FLEET_1_CLEAR,
                in_use=FLEET_1_IN_USE,
                hard_satisfied=FLEET_1_HARD_SATIESFIED,
            ),
            main=self,
        )
        if fleet_1.in_use():
            return False

        if recommend:
            logger.info("Recommend fleet")
            fleet_1.recommend()
            return True
        logger.error(
            "Fleet not prepared and fleet recommend is not enabled, please prepare fleets manually before running"
        )
        raise RequestHumanTakeover

    def _handle_hospital_preparation_page(
        self,
        *,
        auto: str,
        check_oil: Callable[[], object],
        check_coin: Callable[[], object],
    ) -> bool:
        if not self.appear(BATTLE_PREPARATION, offset=(30, 20)):
            return False
        if self.handle_combat_automation_set(auto=auto == "combat_auto"):
            return True
        check_oil()
        check_coin()
        return False

    def _handle_hospital_preparation_actions(self) -> bool:
        return (
            self.handle_retirement()
            or self.handle_combat_low_emotion()
            or self.appear_then_click(BATTLE_PREPARATION, offset=(30, 20), interval=2)
            or self.handle_combat_automation_confirm()
            or self.handle_story_skip()
        )

    def _handle_hospital_fleet_preparation(self) -> bool:
        if self.appear(RAID_FLEET_PREPARATION, offset=(30, 30), interval=2):
            if self.handle_fleet_recommend(recommend=self.config.Hospital_UseRecommendFleet):
                self.interval_clear(RAID_FLEET_PREPARATION)
                return True
            self.device.click(RAID_FLEET_PREPARATION)
            return True
        return self.appear_then_click(HOSPITAL_BATTLE_PREPARE, offset=(20, 20), interval=2)

    def _finish_hospital_preparation_if_combat_started(
        self,
        *,
        emotion_reduce: bool,
        fleet_index: int,
    ) -> bool:
        pause = self.is_combat_executing()
        if not pause:
            return False
        logger.attr("BattleUI", pause)
        if emotion_reduce:
            self.emotion.reduce(fleet_index)
        return True

    def combat_preparation(
        self,
        *,
        balance_hp: bool = False,
        emotion_reduce: bool = False,
        auto: str = "combat_auto",
        fleet_index: int = 1,
    ) -> None:
        logger.info("Combat preparation.")
        # 医院战斗复用普通战斗入口，但不执行普通战斗的血量平衡。
        del balance_hp
        # 不需要等待，raid_execute_once() 已经处理过。

        @run_once
        def check_oil() -> None:
            if self.get_oil() < max(500, self.config.StopCondition_OilLimit):
                logger.hr("Triggered oil limit")
                raise OilExhausted

        @run_once
        def check_coin() -> bool:
            if self.config.TaskBalancer_Enable and self.triggered_task_balancer():
                logger.hr("Triggered stop condition: Coin limit")
                self.handle_task_balancer()
                return True
            return False

        for _ in self.loop():
            if self._handle_hospital_preparation_page(auto=auto, check_oil=check_oil, check_coin=check_coin):
                continue
            if self._handle_hospital_preparation_actions():
                continue
            if self._handle_hospital_fleet_preparation():
                continue

            if self._finish_hospital_preparation_if_combat_started(
                emotion_reduce=emotion_reduce, fleet_index=fleet_index
            ):
                break

    in_clue_confirm = Timer(0.5, count=2)

    def hospital_expected_end(self) -> bool:
        """战斗结束回调：先处理线索退出，连续确认在线索页后才返回 True。"""
        if self.handle_clue_exit():
            return False
        if self.is_in_clue():
            self.in_clue_confirm.start()
            if self.in_clue_confirm.reached():
                return True
        else:
            self.in_clue_confirm.reset()
        return False

    def hospital_combat(self) -> None:
        """页面状态：FLEET_PREPARATION → is_in_clue。"""
        self.combat(balance_hp=False, expected_end=self.hospital_expected_end)
