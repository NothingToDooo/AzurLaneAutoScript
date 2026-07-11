from datetime import datetime

from module.base.button import ButtonGrid
from module.base.decorator import cached_property
from module.base.utils import get_color
from module.exception import GameBugError
from module.logger import logger
from module.ocr.ocr import Duration
from module.research import assets as research_assets
from module.research.ui import ResearchUI

OCR_QUEUE_REMAIN = Duration(
    research_assets.QUEUE_REMAIN, letter=(255, 255, 255), threshold=128, name="OCR_QUEUE_REMAIN"
)


class ResearchQueue(ResearchUI):
    def research_queue_add(self, skip_first_screenshot=True):
        """从项目详情入队并回到稳定科研页；要求不满足时返回 False。"""
        logger.hr("Research queue add")
        # research_project_start() 刚点击过确认弹窗，需清除点击间隔。
        self.popup_interval_clear()
        self.interval_clear([research_assets.RESEARCH_QUEUE_ADD])
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if self.is_research_stabled():
                break

            if self.appear(research_assets.RESEARCH_QUEUE_ADD, offset=(20, 20), interval=5):
                if self._research_queue_add_available():
                    self.device.click(research_assets.RESEARCH_QUEUE_ADD)
                    continue
                logger.info("Project requirements not satisfied, cancel it")
                self.research_detail_cancel()
                return False

            if self.handle_popup_confirm("RESEARCH_QUEUE"):
                self.interval_reset(research_assets.RESEARCH_QUEUE_ADD)
                continue

        self.ensure_research_center_stable()
        return True

    def _research_queue_add_available(self):
        # 取完整按钮而非文字区域；可用色约为 (90, 142, 203)，不可用色约为 (153, 160, 170)。
        r, g, b = get_color(self.device.image, research_assets.RESEARCH_QUEUE_ADD.button)
        return b - min(r, g) > 60

    @cached_property
    def queue_status_grids(self):
        return ButtonGrid(
            origin=(18, 259), delta=(0, 40.5), button_shape=(25, 25), grid_shape=(1, 5), name="QUEUE_STATUS"
        )

    def _queue_status_detect(self, button):
        """按左侧图标颜色返回 finished、running、waiting 或 empty。"""
        center = button.crop((7, 7, 21, 21))
        if self.image_color_count(center, color=(255, 158, 57), threshold=180, count=20):
            return "finished"
        if self.image_color_count(center, color=(90, 97, 132), threshold=221, count=10):
            return "waiting"
        if self.image_color_count(center, color=(24, 24, 41), threshold=221, count=10):
            below = button.crop((7, 14, 21, 21))
            if self.image_color_count(below, color=(24, 24, 41), threshold=221, count=10):
                return "running"
            return "empty"
        logger.warning(f"Unknown queue status from {button}, assume running")
        return "running"

    def get_queue_slot(self):
        """在队列页返回空槽数量。"""
        status = [self._queue_status_detect(button) for button in self.queue_status_grids.buttons]
        logger.info(f"Research queue: {status}")
        status.reverse()
        for index, s in enumerate(status):
            if s != "empty":
                logger.attr("Research queue slot", index)
                return index
        index = len(status)
        logger.attr("Research queue slot", index)
        return index

    def get_research_ended(self):
        """返回首个项目结束时间；队列异常时抛出 GameBugError，空队列返回当前时间。"""
        if self.image_color_count(research_assets.QUEUE_REMAIN, color=(123, 125, 123), threshold=235, count=100):
            logger.error(
                "The first research of queue is not running,probably a game bug from AL,restart the game should fix it."
            )
            raise GameBugError
        if not self.image_color_count(research_assets.QUEUE_REMAIN, color=(255, 255, 255), threshold=221, count=100):
            logger.info("Research queue empty")
            return datetime.now()

        end_time = datetime.now() + OCR_QUEUE_REMAIN.ocr(self.device.image)
        logger.info(f"The first research ended at: {end_time}")
        return end_time
