from module.base.timer import Timer
from module.campaign.campaign_event import CampaignEvent
from module.exception import ScriptEnd, ScriptError
from module.logger import logger
from module.raid.assets import RAID_REWARDS
from module.raid.raid import Raid, RaidMode, raid_ocr
from module.ui.page import page_campaign_menu, page_raid, page_rpg_stage

RAID_RUN_ARGUMENTS_UNFILLED_TEMPLATE = "RaidRun arguments unfilled. name={name}, mode={mode}"
RAID_RUN_MODE_INVALID_TEMPLATE = "Invalid RaidRun mode: {mode}"


class RaidRun(Raid, CampaignEvent):
    run_count: int
    run_limit: int

    def triggered_stop_condition(
        self, *, oil_check: bool = False, pt_check: bool = False, coin_check: bool = False
    ) -> bool:
        """检查运行次数及父类停止条件，触发后返回 True。"""
        if self.run_limit and self.config.StopCondition_RunCount <= 0:
            logger.hr("Triggered stop condition: Run count")
            self.config.StopCondition_RunCount = 0
            self.config.Scheduler_Enable = False
            return True

        return super().triggered_stop_condition(oil_check=oil_check, pt_check=pt_check, coin_check=coin_check)

    def get_remain(self, mode: RaidMode, *, skip_first_screenshot: bool = True) -> int:
        """OCR easy、normal、hard 或 ex 剩余次数，等待读数稳定后返回。"""
        confirm_timer = Timer(0.3, count=0)
        prev = 30
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if mode == "ex":
                remain = raid_ocr(raid=self.config.Campaign_Event, mode=mode).ocr_single(self.device.image)
            else:
                remain, _, _ = raid_ocr(raid=self.config.Campaign_Event, mode=mode).ocr(self.device.image)
            logger.attr(f"{mode.capitalize()} Remain", remain)

            if self.appear_then_click(RAID_REWARDS, offset=(30, 30), interval=3):
                confirm_timer.reset()
                continue

            if remain == prev:
                if confirm_timer.reached():
                    break
            else:
                confirm_timer.reset()

            prev = remain

        return remain

    def run(self, name: str = "", mode: str = "", total: int = 0) -> None:
        """按活动和难度运行至 total 或停止条件；空参数读取配置，仍缺失时抛出 ScriptError。"""
        name, mode = self._resolve_raid_run_args(name, mode)
        self.run_count = 0
        self.run_limit = self.config.StopCondition_RunCount
        while 1:
            if self._raid_run_total_reached(total):
                break

            self._handle_raid_event_time_limit()
            self._log_raid_run_status(name, mode)
            if not self._prepare_raid_run_ui():
                break

            if self._stop_ex_raid_without_ticket(mode):
                break

            if not self._execute_raid_once(name, mode):
                break

            if self._handle_raid_after_run():
                break

    def _resolve_raid_run_args(self, name: str, mode: str) -> tuple[str, RaidMode]:
        name = name or self.config.Campaign_Event
        mode = mode or self.config.Raid_Mode
        if not name or not mode:
            message = RAID_RUN_ARGUMENTS_UNFILLED_TEMPLATE.format(name=name, mode=mode)
            raise ScriptError(message)
        match mode:
            case "easy":
                return name, "easy"
            case "normal":
                return name, "normal"
            case "hard":
                return name, "hard"
            case "ex":
                return name, "ex"
            case _:
                message = RAID_RUN_MODE_INVALID_TEMPLATE.format(mode=mode)
                raise ScriptError(message)

    def _raid_run_total_reached(self, total: int) -> bool:
        return bool(total and self.run_count == total)

    def _handle_raid_event_time_limit(self) -> None:
        if self.event_time_limit_triggered():
            self.config.task_stop()

    def _log_raid_run_status(self, name: str, mode: RaidMode) -> None:
        logger.hr(f"{name}_{mode}", level=2)
        if self.config.StopCondition_RunCount > 0:
            logger.info(f"Count remain: {self.config.StopCondition_RunCount}")
        else:
            logger.info(f"Count: {self.run_count}")

    def _prepare_raid_run_ui(self) -> bool:
        if not self._raid_has_oil_icon:
            self.ui_ensure(page_campaign_menu)
            if self.triggered_stop_condition(oil_check=True, coin_check=True):
                return False

        self.device.stuck_record_clear()
        self.device.click_record_clear()
        if not self.is_raid_rpg():
            self.ui_ensure(page_raid)
        else:
            self.ui_ensure(page_rpg_stage)
            self.raid_rpg_swipe()
        self.disable_event_on_raid()
        return True

    def _stop_ex_raid_without_ticket(self, mode: RaidMode) -> bool:
        if mode != "ex" or self.is_raid_rpg() or self.get_remain(mode):
            return False

        logger.info("Triggered stop condition: Zero raid tickets to do EX mode")
        if self.config.task.command == "Raid":
            with self.config.multi_set():
                self.config.StopCondition_RunCount = 0
                self.config.Scheduler_Enable = False
        return True

    def _execute_raid_once(self, name: str, mode: RaidMode) -> bool:
        self.device.stuck_record_clear()
        self.device.click_record_clear()
        try:
            self.raid_execute_once(mode=mode, raid=name)
        except ScriptEnd as e:
            logger.hr("Script end")
            logger.info(str(e))
            return False
        return True

    def _handle_raid_after_run(self) -> bool:
        self.run_count += 1
        if self.config.StopCondition_RunCount:
            self.config.StopCondition_RunCount -= 1
        if self.triggered_stop_condition():
            return True
        if self.config.task_switched():
            self.config.task_stop()
        return False
