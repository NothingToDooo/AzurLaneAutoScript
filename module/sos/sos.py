from campaign.campaign_sos.campaign_base import CampaignBase
from module.base.decorator import cached_property
from module.base.utils import area_pad
from module.campaign.run import CampaignRun
from module.logger import logger
from module.ocr.ocr import Digit
from module.sos import assets as sos_assets
from module.ui.assets import CAMPAIGN_CHECK
from module.ui.page import page_campaign
from module.ui.scroll import Scroll

OCR_SOS_SIGNAL = Digit(sos_assets.OCR_SIGNAL, letter=(255, 255, 255), threshold=128, name="OCR_SOS_SIGNAL")


class CampaignSos(CampaignRun, CampaignBase):
    @cached_property
    def _sos_chapter_crop(self):
        return [-403, 8, -381, 35]

    @cached_property
    def _sos_scroll(self):
        return Scroll(sos_assets.SOS_SCROLL_AREA, color=(164, 173, 189), name="SOS_SCROLL")

    @cached_property
    def _sos_chapter_ocr(self):
        return Digit([], letter=[132, 230, 115], threshold=136, name="OCR_SOS_CHAPTER")

    def _find_target_chapter(self, chapter):
        """
        find the target chapter search button or goto button.

        Args:
            chapter (int): SOS target chapter

        Returns:
            Button: signal search button or goto button of the target chapter
        """
        signal_search_buttons = sos_assets.TEMPLATE_SIGNAL_SEARCH.match_multi(self.device.image)
        sos_goto_buttons = sos_assets.TEMPLATE_SIGNAL_GOTO.match_multi(self.device.image)
        sos_confirm_buttons = sos_assets.TEMPLATE_SIGNAL_CONFIRM.match_multi(self.device.image)
        all_buttons = sos_goto_buttons + signal_search_buttons + sos_confirm_buttons
        if not len(all_buttons):
            logger.info("No SOS chapter found")
            return None

        chapter_buttons = [button.crop(self._sos_chapter_crop) for button in all_buttons]
        self._sos_chapter_ocr.buttons = chapter_buttons
        chapter_list = self._sos_chapter_ocr.ocr(self.device.image)
        if not isinstance(chapter_list, list):
            chapter_list = [chapter_list]
        if chapter in chapter_list:
            logger.info("Target SOS chapter found")
            return all_buttons[chapter_list.index(chapter)]
        else:
            logger.info("Target SOS chapter not found")
            return None

    def _sos_signal_select(self, chapter):
        """
        select a SOS signal

        Args:
            chapter (int): 3 to 10.

        Pages:
            in: page_campaign
            out: page_campaign, in target chapter

        Returns:
            bool: whether select successful
        """
        logger.hr(f"Select chapter {chapter} signal ")
        self.ui_click(
            sos_assets.SIGNAL_SEARCH_ENTER,
            appear_button=CAMPAIGN_CHECK,
            check_button=sos_assets.SIGNAL_LIST_CHECK,
            skip_first_screenshot=True,
        )
        if chapter in [3, 4, 5]:
            positions = [0.0, 0.5, 1.0]
        elif chapter in [6, 7]:
            positions = [0.5, 1.0, 0.0]
        elif chapter in [8, 9, 10]:
            positions = [1.0, 0.5, 0.0]
        else:
            logger.warning(f"Unknown SOS chapter: {chapter}")
            positions = [0.0, 0.5, 1.0]

        for scroll_position in positions:
            if self._sos_scroll.appear(main=self):
                self._sos_scroll.set(scroll_position, main=self, distance_check=False)
            else:
                logger.info("SOS signal scroll not appear, skip setting scroll position")
            target_button = self._find_target_chapter(chapter)
            if target_button is not None:
                self._sos_signal_confirm(entrance=target_button)
                return True
        return False

    def _sos_signal_confirm(self, entrance, skip_first_screenshot=True):
        """
        Search a SOS signal, goto target chapter.

        Args:
            entrance (Button): Entrance button.
            skip_first_screenshot (bool):

        Pages:
            in: SIGNAL_SEARCH
            out: page_campaign
        """
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if self.appear(sos_assets.SIGNAL_LIST_CHECK, offset=(20, 20), interval=2):
                image = self.image_crop(area_pad(entrance.area, pad=-30), copy=False)
                if sos_assets.TEMPLATE_SIGNAL_SEARCH.match(image):
                    self.device.click(entrance)
                if sos_assets.TEMPLATE_SIGNAL_GOTO.match(image):
                    self.device.click(entrance)
                if sos_assets.TEMPLATE_SIGNAL_CONFIRM.match(image):
                    self.device.click(entrance)

            # 结束。
            if self.appear(CAMPAIGN_CHECK, offset=(20, 20)):
                break

    def run(self, name=None, folder="campaign_sos", mode="normal", total=1):
        """
        Args:
            name (str): Default to None, because stages in SOS are dynamic.
            folder (str): Default to 'campaign_sos'.
            mode (str): Must be `normal` in SOS
            total (int): Default to 1, because SOS stages can only run once.

        Pages:
            in: Any page
            out: page_campaign
        """
        logger.warning("AL no longer has SOS maps, disable task")
        self.config.Scheduler_Enable = False
        self.config.task_stop()

        logger.hr("Campaign SOS", level=1)
        self.ui_ensure(page_campaign)

        while 1:
            # 结束。
            remain = OCR_SOS_SIGNAL.ocr(self.device.image)
            logger.attr("SOS signal", remain)
            if remain <= 0:
                logger.info("All SOS signals cleared")
                break

            # 执行。
            if self._sos_signal_select(self.config.Sos_Chapter):
                name = f"campaign_{self.config.Sos_Chapter}_5"
                self.config.override(Campaign_Name=name)
                super().run(name, folder=folder, mode=mode, total=total)
                if self.run_count > 0:
                    continue
                else:
                    self.config.task_stop()
            else:
                self.ui_click(
                    sos_assets.SIGNAL_SEARCH_CLOSE,
                    appear_button=sos_assets.SIGNAL_LIST_CHECK,
                    check_button=CAMPAIGN_CHECK,
                    skip_first_screenshot=True,
                )
                logger.warning(f"Failed to clear SOS signals, cannot locate chapter {self.config.Sos_Chapter}")
                break

        # 调度器。
        self.config.task_delay(server_update=True)
