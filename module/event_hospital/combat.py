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


class HospitalCombat(Combat, HospitalUI, CampaignEvent):
    def handle_fleet_recommend(self, recommend=True):
        """
        Args:
            recommend:

        Returns:
            bool: If clicked
        """
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

    def _handle_hospital_preparation_page(self, *, auto, check_oil, check_coin):
        if not self.appear(BATTLE_PREPARATION, offset=(30, 20)):
            return False
        if self.handle_combat_automation_set(auto=auto == "combat_auto"):
            return True
        check_oil()
        check_coin()
        return False

    def _handle_hospital_preparation_actions(self):
        return (
            self.handle_retirement()
            or self.handle_combat_low_emotion()
            or self.appear_then_click(BATTLE_PREPARATION, offset=(30, 20), interval=2)
            or self.handle_combat_automation_confirm()
            or self.handle_story_skip()
        )

    def _handle_hospital_fleet_preparation(self):
        if self.appear(RAID_FLEET_PREPARATION, offset=(30, 30), interval=2):
            if self.handle_fleet_recommend(recommend=self.config.Hospital_UseRecommendFleet):
                self.interval_clear(RAID_FLEET_PREPARATION)
                return True
            self.device.click(RAID_FLEET_PREPARATION)
            return True
        return self.appear_then_click(HOSPITAL_BATTLE_PREPARE, offset=(20, 20), interval=2)

    def _finish_hospital_preparation_if_combat_started(self, *, emotion_reduce, fleet_index):
        pause = self.is_combat_executing()
        if not pause:
            return False
        logger.attr("BattleUI", pause)
        if emotion_reduce:
            self.emotion.reduce(fleet_index)
        return True

    def combat_preparation(self, balance_hp=False, emotion_reduce=False, auto="combat_auto", fleet_index=1):
        """
        Args:
            balance_hp (bool):
            emotion_reduce (bool):
            auto (bool):
            fleet_index (int):
        """
        logger.info("Combat preparation.")
        # 医院战斗复用普通战斗入口，但不执行普通战斗的血量平衡。
        del balance_hp
        # 不需要等待，raid_execute_once() 已经处理过。
        # if emotion_reduce:
        #     self.emotion.wait(fleet_index)

        @run_once
        def check_oil():
            if self.get_oil() < max(500, self.config.StopCondition_OilLimit):
                logger.hr("Triggered oil limit")
                raise OilExhausted

        @run_once
        def check_coin():
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

            # End
            if self._finish_hospital_preparation_if_combat_started(
                emotion_reduce=emotion_reduce, fleet_index=fleet_index
            ):
                break

    in_clue_confirm = Timer(0.5, count=2)

    def hospital_expected_end(self):
        """
        Returns:
            bool: If combat ended
        """
        if self.handle_clue_exit():
            return False
        if self.is_in_clue():
            self.in_clue_confirm.start()
            if self.in_clue_confirm.reached():
                return True
        else:
            self.in_clue_confirm.reset()
        return False

    def hospital_combat(self):
        """
        Pages:
            in: FLEET_PREPARATION
            out: is_in_clue
        """
        self.combat(balance_hp=False, expected_end=self.hospital_expected_end)
