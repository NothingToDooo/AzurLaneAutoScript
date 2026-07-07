from module.campaign.campaign_event import CampaignEvent
from module.event import assets as event_assets
from module.exception import CampaignEnd
from module.logger import logger
from module.map.map_operation import MapOperation
from module.ocr.ocr import DigitCounter

OCR_REMAIN = DigitCounter(event_assets.ESCORT_REMAIN, letter=(148, 255, 99), threshold=64)


class MaritimeEscort(MapOperation, CampaignEvent):
    def is_in_escort(self):
        return self.appear(event_assets.ESCORT_CHECK, offset=(20, 20))

    def handle_in_stage(self):
        if self.is_in_escort():
            return bool(self.in_stage_timer.reached())
        self.in_stage_timer.reset()
        return False

    def run_escort(self):
        """
        Just enter and retreat, get about 70% of maximum rewards.

        Pages:
            in: ESCORT_CHECK
            out: ESCORT_CHECK
        """
        logger.hr("Maritime escort", level=1)
        try:
            self.enter_map(event_assets.ESCORT_HARD_ENTRANCE, mode="escort")
            self.withdraw()
        except CampaignEnd:
            pass

        logger.info("Maritime escort finished")

    def run(self):
        if self.event_time_limit_triggered():
            self.config.task_stop()

        self.ui_goto_main()
        self.ui_click(
            event_assets.MAIN_GOTO_ESCORT,
            check_button=event_assets.ESCORT_CHECK,
            offset=(20, 150),
            skip_first_screenshot=True,
        )

        current, _, _ = OCR_REMAIN.ocr(self.device.image)
        if current > 0:
            self.run_escort()
        else:
            logger.info("Maritime escort already finished")

        self.config.task_delay(server_update=True)
