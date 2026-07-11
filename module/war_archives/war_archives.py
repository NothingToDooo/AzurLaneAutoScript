import re

from campaign.campaign_war_archives.campaign_base import CampaignBase
from module.campaign.run import CampaignRun
from module.logger import logger
from module.ocr.ocr import DigitCounter
from module.war_archives.assets import OCR_DATA_KEY_CAMPAIGN, WAR_ARCHIVES_CAMPAIGN_CHECK


class OcrDataKey(DigitCounter):
    def after_process(self, result):
        result = super().after_process(result)
        return re.sub(r"(\d{1,2})60$", r"\1/60", result)


DATA_KEY_CAMPAIGN = OcrDataKey(OCR_DATA_KEY_CAMPAIGN, letter=(255, 247, 247), threshold=64)


class CampaignWarArchives(CampaignRun, CampaignBase):
    def triggered_stop_condition(self, oil_check=True):
        # 只有档案关卡页能可靠识别数据钥匙。
        if self.appear(WAR_ARCHIVES_CAMPAIGN_CHECK, offset=(20, 20)):
            current, remain, total = DATA_KEY_CAMPAIGN.ocr(self.device.image)
            logger.info(f"Inventory: {current} / {total}, Remain: {current}")
            if remain == total:
                logger.hr("Triggered out of data keys")
                # 仅数据钥匙耗尽时按服务器刷新时间延迟任务。
                self.config.task_delay(server_update=True)
                return True

        return super().triggered_stop_condition(oil_check)

    def can_use_auto_search_continue(self):
        """自律寻敌菜单的模糊背景会遮住 DATA_KEY_CAMPAIGN，因此必须关闭。"""
        return False

    def run(self, name=None, folder="campaign_main", mode="normal", total=0):
        self.config.override(USE_DATA_KEY=True)
        super().run(name, folder, mode, total)
