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
        """
        Returns:
            bool: True if success to add to queue,
                False if project requirements not satisfied, can't be added to queue

        Pages:
            in: RESEARCH_QUEUE_ADD (is_in_research, DETAIL_NEXT)
            out: is_in_research and stabled
        """
        logger.hr("Research queue add")
        # POPUP_CONFIRM has just been clicked in research_project_start()
        self.popup_interval_clear()
        self.interval_clear([research_assets.RESEARCH_QUEUE_ADD])
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            # End
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
        """
        Returns:
            bool: True if able add to queue,
                False if project requirements not satisfied, can't be added to queue
        """
        # RESEARCH_QUEUE_ADD.area 是 `Queue` 文字区域。
        # RESEARCH_QUEUE_ADD.button 是按钮的完整可点击区域。
        # 可用：(90, 142, 203)
        # 不可用：(153, 160, 170)
        r, g, b = get_color(self.device.image, research_assets.RESEARCH_QUEUE_ADD.button)
        return b - min(r, g) > 60

    @cached_property
    def queue_status_grids(self):
        """
        Status icons on the left
        """
        return ButtonGrid(
            origin=(18, 259), delta=(0, 40.5), button_shape=(25, 25), grid_shape=(1, 5), name="QUEUE_STATUS"
        )

    def _queue_status_detect(self, button):
        """
        Args:
            button: Button of status icon

        Returns:
            str:
                'finished': Orange ✓ surrounded by orange border
                'running': Black ✓ surrounded by research progress, gray and blue
                'waiting': Gray … surrounded by gray border
                'empty': Black … surrounded by black border or just nothing
        """
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
        """
        Returns:
            int: Number of empty slots in queue

        Pages:
            in: is_in_queue
        """
        status = [self._queue_status_detect(button) for button in self.queue_status_grids.buttons]
        logger.info(f"Research queue: {status}")
        status = status[::-1]
        for index, s in enumerate(status):
            if s != "empty":
                logger.attr("Research queue slot", index)
                return index
        index = len(status)
        logger.attr("Research queue slot", index)
        return index

    def get_research_ended(self):
        """
        Returns:
            datetime: Time of the end of the first research in the queue.

        Pages:
            in: is_in_queue

        Raises:
            GameBugError:
        """
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
