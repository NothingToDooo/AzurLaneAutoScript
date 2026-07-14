from module.event import assets as event_assets
from module.exception import CampaignEnd
from module.logger import logger
from module.map.map_operation import MapOperation
from module.maritime_escort.result import MaritimeEscortExecutionResult, MaritimeEscortExecutionStatus
from module.ocr.ocr import DigitCounter

OCR_REMAIN = DigitCounter(event_assets.ESCORT_REMAIN, letter=(148, 255, 99), threshold=64)


class MaritimeEscort(MapOperation):
    def is_in_escort(self) -> bool:
        return self.appear(event_assets.ESCORT_CHECK, offset=(20, 20))

    def handle_in_stage(self) -> bool:
        if self.is_in_escort():
            return bool(self.in_stage_timer.reached())
        self.in_stage_timer.reset()
        return False

    def execute_once(self) -> MaritimeEscortExecutionResult:
        """尝试一次护航并把次数耗尽与成功撤退转换为领域结果。"""
        logger.hr("Maritime escort", level=1)
        try:
            self.enter_map(event_assets.ESCORT_HARD_ENTRANCE, mode="escort")
        except CampaignEnd:
            logger.info("Maritime escort attempts exhausted")
            return MaritimeEscortExecutionResult(MaritimeEscortExecutionStatus.ATTEMPTS_EXHAUSTED)

        try:
            self.withdraw()
        except CampaignEnd:
            logger.info("Maritime escort finished")
            return MaritimeEscortExecutionResult(MaritimeEscortExecutionStatus.WITHDRAWAL_COMPLETED)
