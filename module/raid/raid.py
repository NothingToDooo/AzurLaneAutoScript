from typing import TYPE_CHECKING

from module.base.timer import Timer
from module.campaign.campaign_status import CampaignStatus
from module.combat.assets import BATTLE_PREPARATION
from module.device.control_options import SwipeVectorOptions
from module.logger import logger
from module.map.map_operation import MapOperation
from module.raid import assets as raid_assets
from module.raid.combat import RaidCombat
from module.raid.profile import (
    RaidNavigationStrategy,
    RaidRunPlan,
    ResolvedRaidProfile,
)
from module.raid.result import RaidExecutionResult

if TYPE_CHECKING:
    from module.config.config import AzurLaneConfig
    from module.device.device import Device


class Raid(MapOperation, RaidCombat, CampaignStatus):
    def __init__(
        self,
        config: AzurLaneConfig,
        *,
        profile: ResolvedRaidProfile,
        device: Device,
    ) -> None:
        if not isinstance(profile, ResolvedRaidProfile):
            message = "profile must be a ResolvedRaidProfile"
            raise TypeError(message)
        self._raid_profile = profile
        self._active_plan: RaidRunPlan | None = None
        super().__init__(config, device=device)

    @property
    def raid_profile(self) -> ResolvedRaidProfile:
        return self._raid_profile

    def _require_plan(self, plan: RaidRunPlan) -> None:
        if not isinstance(plan, RaidRunPlan):
            message = "plan must be a RaidRunPlan"
            raise TypeError(message)
        if plan.profile != self._raid_profile:
            message = "raid plan belongs to a different resolved profile"
            raise ValueError(message)

    def ensure_landing(self) -> None:
        """进入 profile 指定的共斗页，并执行该布局唯一需要的定位动作。"""
        self.ui_ensure(self._raid_profile.client.landing_page)
        if self._raid_profile.client.navigation is RaidNavigationStrategy.RPG_CAROUSEL:
            self._seek_carousel_end()

    def _seek_carousel_end(self, *, skip_first_screenshot: bool = True) -> None:
        interval = Timer(1)
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if self.appear(raid_assets.RPG_RAID_EASY, offset=(10, 10)):
                logger.info("Raid carousel already at rightmost")
                return
            if self.handle_story_skip() or self.handle_get_items():
                continue
            if interval.reached():
                self.device.swipe_vector((-900, 0), SwipeVectorOptions(box=(0, 130, 1280, 440)))
                interval.reset()

    def _handle_raid_preparation_page(self, *, auto: str) -> bool:
        if not self.appear(BATTLE_PREPARATION, offset=(30, 20)):
            return False
        return self.handle_combat_automation_set(auto=auto == "combat_auto")

    def _handle_raid_preparation_actions(self) -> bool:
        return (
            self.handle_raid_ticket_use()
            or self.handle_retirement()
            or self.handle_combat_low_emotion()
            or self.appear_then_click(BATTLE_PREPARATION, offset=(30, 20), interval=2)
            or self.handle_combat_automation_confirm()
            or self.handle_story_skip()
        )

    def _finish_raid_preparation_if_combat_started(self, *, emotion_reduce: bool, fleet_index: int) -> bool:
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
        """等待共斗战斗开始；资源与调度停止条件由外层 workflow 决定。"""
        logger.info("Combat preparation.")
        del balance_hp

        for _ in self.loop():
            if self._handle_raid_preparation_page(auto=auto):
                continue
            if self._handle_raid_preparation_actions():
                continue
            if self._finish_raid_preparation_if_combat_started(emotion_reduce=emotion_reduce, fleet_index=fleet_index):
                return

    def handle_raid_ticket_use(self) -> bool:
        """按当前已验证 plan 确认或取消共斗票。"""
        if not self.appear(raid_assets.TICKET_USE_CONFIRM, offset=(30, 30), interval=1):
            return False
        plan = self._active_plan
        if plan is None:
            message = "raid ticket prompt appeared outside an active raid plan"
            raise RuntimeError(message)
        button = raid_assets.TICKET_USE_CONFIRM if plan.use_ticket else raid_assets.TICKET_USE_CANCEL
        self.device.click(button)
        return True

    def raid_enter(self, plan: RaidRunPlan, *, skip_first_screenshot: bool = True) -> None:
        """从共斗页进入 plan 指定难度，结束于战斗准备页。"""
        self._require_plan(plan)
        entrance = plan.mode_profile.entrance
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if self.appear(entrance, offset=(10, 10), interval=5):
                self.device.click(entrance)
                continue
            if self.appear_then_click(raid_assets.RAID_FLEET_PREPARATION, offset=(20, 20), interval=5):
                continue
            if self.combat_appear():
                return

    def raid_expected_end(self) -> bool:
        """处理奖励弹窗，并用 profile 的显式结束检查点判断战斗结束。"""
        if self.appear_then_click(raid_assets.RAID_REWARDS, offset=(30, 30), interval=3):
            return False
        return self.appear(self._raid_profile.client.end_check, offset=(30, 30))

    def execute_once(
        self,
        plan: RaidRunPlan,
    ) -> RaidExecutionResult:
        """执行一次原子共斗；EX 临时启用每战潜艇并在结束后恢复。"""
        self._require_plan(plan)
        logger.hr("Raid Execute")
        content_id = plan.profile.activity.content_id.value
        self.config.apply_runtime_overlay(
            Campaign_Name=f"{content_id}_{plan.mode.value}",
            Campaign_UseAutoSearch=False,
            Fleet_FleetOrder="fleet1_all_fleet2_standby",
        )

        submarine_backup: tuple[int, str] | None = None
        if plan.mode.value == "ex":
            submarine_backup = (self.config.Submarine_Fleet, self.config.Submarine_Mode)
            self.config.apply_runtime_overlay(Submarine_Fleet=1, Submarine_Mode="every_combat")

        previous_plan = self._active_plan
        self._active_plan = plan
        try:
            self.raid_enter(plan)
            self.combat(balance_hp=False, expected_end=self.raid_expected_end)
        finally:
            self._active_plan = previous_plan
            if submarine_backup is not None:
                fleet, submarine_mode = submarine_backup
                self.config.apply_runtime_overlay(Submarine_Fleet=fleet, Submarine_Mode=submarine_mode)

        logger.hr("Raid End")
        return RaidExecutionResult(mode=plan.mode, runs_completed=1)

    def get_event_pt(self) -> int:
        """在共斗页读取 PT；profile 未声明 PT OCR 时返回 0。"""
        spec = self._raid_profile.client.point_ocr
        if spec is None:
            logger.info(f"Raid profile {self._raid_profile.client.profile_id.value} has no PT OCR")
            return 0

        skip_first_screenshot = True
        timeout = Timer(1.5, count=5).start()
        ocr = spec.create()
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            pt = ocr.ocr_single(self.device.image)
            if timeout.reached():
                logger.warning("Wait PT timeout, assume it is")
                break
            # 这两个值是部分 profile 页面未加载完成时的默认占位。
            if pt in {70000, 70001}:
                continue
            break
        return pt
