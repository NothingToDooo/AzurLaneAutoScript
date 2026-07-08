import re
from contextlib import suppress

from module.campaign.campaign_event import CampaignEvent
from module.coalition import assets as coalition_assets
from module.coalition.combat import CoalitionCombat
from module.exception import ScriptEnd, ScriptError
from module.logger import logger
from module.ocr.ocr import Digit
from module.ui.page import page_campaign_menu


class AcademyPtOcr(Digit):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.alphabet += ":"

    def after_process(self, result):
        logger.attr(self.name, result)
        with suppress(IndexError):
            # 累计: 840
            result = result.rsplit(":")[1]
        return super().after_process(result)


class DALPtOcr(Digit):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.alphabet += "X"

    def after_process(self, result):
        logger.attr(self.name, result)
        with suppress(IndexError):
            # X9100
            result = result.rsplit("X")[1]
        return super().after_process(result)


class Coalition(CoalitionCombat, CampaignEvent):
    run_count: int
    run_limit: int

    def get_event_pt(self):
        """
        Returns:
            int: PT amount, or 0 if unable to parse
        """
        event = self.config.Campaign_Event
        if event == "coalition_20230323":
            ocr = Digit(coalition_assets.FROSTFALL_OCR_PT, name="OCR_PT", letter=(198, 158, 82), threshold=128)
        elif event == "coalition_20240627":
            ocr = AcademyPtOcr(coalition_assets.ACADEMY_PT_OCR, name="OCR_PT", letter=(255, 255, 255), threshold=128)
        elif event == "coalition_20250626":
            # 使用通用 OCR 模型。
            ocr = Digit(
                coalition_assets.NEONCITY_PT_OCR, name="OCR_PT", lang="cnocr", letter=(208, 208, 208), threshold=128
            )
        elif event == "coalition_20251120":
            ocr = DALPtOcr(coalition_assets.DAL_PT_OCR, name="OCR_PT", letter=(255, 213, 69), threshold=128)
        elif event == "coalition_20260122":
            ocr = Digit(coalition_assets.FASHION_PT_OCR, name="OCR_PT", letter=(41, 40, 40), threshold=128)
        else:
            logger.error(f"ocr object is not defined in event {event}")
            raise ScriptError

        pt = 0
        for _ in self.loop(timeout=1.5):
            pt = ocr.ocr(self.device.image)
            # 999999 看起来是默认值，继续等待。
            if pt != 999999:
                break
        else:
            logger.warning("Wait PT timeout, assume it is")

        return pt

    @property
    def _coalition_has_oil_icon(self):
        """返回当前共斗活动是否显示油量图标。"""
        return self.config.Campaign_Event != "coalition_20260122"

    def triggered_stop_condition(self, oil_check=False, pt_check=False):
        """
        Returns:
            bool: 是否触发停止条件。
        """
        # 运行次数限制。
        if self.run_limit and self.config.StopCondition_RunCount <= 0:
            logger.hr("Triggered stop condition: Run count")
            self.config.StopCondition_RunCount = 0
            self.config.Scheduler_Enable = False
            return True
        # 当前页面油量限制。
        if oil_check and self.get_oil() < max(500, self.config.StopCondition_OilLimit):
            logger.hr("Triggered stop condition: Oil limit")
            self.config.task_delay(minute=(120, 240))
            return True
        # 活动 PT 限制。
        if pt_check and self.event_pt_limit_triggered():
            logger.hr("Triggered stop condition: Event PT limit")
            return True
        # 任务平衡器。
        if self.run_count >= 1 and self.config.TaskBalancer_Enable and self.triggered_task_balancer():
            logger.hr("Triggered stop condition: Coin limit")
            self.handle_task_balancer()
            return True

        return False

    def coalition_execute_once(self, event, stage, fleet):
        """
        Args:
            event:
            stage:
            fleet:

        Pages:
            in: in_coalition
            out: in_coalition
        """
        self.config.override(
            Campaign_Name=f"{event}_{stage}",
            Campaign_UseAutoSearch=False,
            Fleet_FleetOrder="fleet1_all_fleet2_standby",
        )
        if self.config.Coalition_Fleet == "single" and self.config.Emotion_Fleet1Control == "prevent_red_face":
            logger.warning(
                "AL does not allow single coalition with emotion < 30, emotion control is forced to prevent_yellow_face"
            )
            self.config.override(Emotion_Fleet1Control="prevent_yellow_face")
        if stage == "sp":
            # Multiple fleets are required in SP
            self.config.override(
                Coalition_Fleet="multi",
            )
        try:
            self.emotion.check_reduce(battle=self.coalition_get_battles(event, stage))
        except ScriptEnd:
            self.coalition_map_exit(event)
            raise

        if self._coalition_has_oil_icon and self.triggered_stop_condition(oil_check=True):
            self.coalition_map_exit(event)
            raise ScriptEnd

        self.enter_map(event=event, stage=stage, mode=fleet)
        self.coalition_combat()

    @staticmethod
    def handle_stage_name(event, stage):
        stage = re.sub("[ \t\n]", "", str(stage)).lower()
        if event == "coalition_20230323":
            stage = stage.replace("-", "")

        return event, stage

    def run(self, event="", mode="", fleet="", total=0):
        event, mode, fleet = self._coalition_run_arguments(event, mode, fleet)
        event, mode = self.handle_stage_name(event, mode)
        self.run_count = 0
        self.run_limit = self.config.StopCondition_RunCount

        while not self._coalition_total_reached(total):
            if self.event_time_limit_triggered():
                self.config.task_stop()

            self._coalition_log_run(event, mode)
            if not self._coalition_prepare_run(event):
                break
            if self.triggered_stop_condition(pt_check=True):
                break
            if not self._coalition_run_once(event, mode, fleet):
                break

            self._coalition_after_run()
            if self.triggered_stop_condition(pt_check=True):
                break
            if self.config.task_switched():
                self.config.task_stop()

    def _coalition_run_arguments(self, event, mode, fleet):
        event = event or self.config.Campaign_Event
        mode = mode or self.config.Coalition_Mode
        fleet = fleet or self.config.Coalition_Fleet
        if not event or not mode or not fleet:
            raise ScriptError(f"Coalition arguments unfilled. name={event}, mode={mode}, fleet={fleet}")
        return event, mode, fleet

    def _coalition_total_reached(self, total):
        return bool(total and self.run_count == total)

    def _coalition_log_run(self, event, mode):
        logger.hr(f"{event}_{mode}", level=2)
        if self.config.StopCondition_RunCount > 0:
            logger.info(f"Count remain: {self.config.StopCondition_RunCount}")
            return
        logger.info(f"Count: {self.run_count}")

    def _coalition_prepare_run(self, event):
        if not self._coalition_has_oil_icon:
            self.ui_goto(page_campaign_menu)
            if self.triggered_stop_condition(oil_check=True):
                return False

        self.device.stuck_record_clear()
        self.device.click_record_clear()
        self.ui_goto_coalition()
        self.disable_event_on_raid()
        self.coalition_ensure_mode(event, "battle")
        return True

    def _coalition_run_once(self, event, mode, fleet):
        self.device.stuck_record_clear()
        self.device.click_record_clear()
        try:
            self.coalition_execute_once(event=event, stage=mode, fleet=fleet)
        except ScriptEnd as e:
            logger.hr("Script end")
            logger.info(str(e))
            return False
        return True

    def _coalition_after_run(self):
        self.run_count += 1
        if self.config.StopCondition_RunCount:
            self.config.StopCondition_RunCount -= 1


if __name__ == "__main__":
    self = Coalition("alas5", task="Coalition")
    self.device.screenshot()
    self.get_event_pt()
