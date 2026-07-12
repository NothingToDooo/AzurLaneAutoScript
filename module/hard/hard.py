import importlib
from typing import TYPE_CHECKING

from module.campaign.run import CampaignRun
from module.handler.fast_forward import to_map_file_name
from module.hard import assets as hard_assets
from module.logger import logger
from module.ocr.ocr import Digit

if TYPE_CHECKING:
    from campaign.campaign_hard.campaign_hard import Campaign

OCR_HARD_REMAIN = Digit(hard_assets.OCR_HARD_REMAIN, letter=(123, 227, 66), threshold=128, alphabet="0123")


class CampaignHard(CampaignRun):
    equipment_has_take_on = False
    campaign: Campaign

    def run(self, name: str = "", folder: str = "campaign_main", mode: str = "normal", total: int = 0) -> None:
        _ = (name, folder, mode, total)
        logger.hr("Campaign hard", level=1)
        name = to_map_file_name(self.config.Hard_HardStage)
        self.config.override(
            Campaign_Mode="hard",
            Campaign_UseFleetLock=True,
            Campaign_UseAutoSearch=True,
            Fleet_FleetOrder="fleet1_all_fleet2_standby"
            if self.config.Hard_HardFleet == 1
            else "fleet1_standby_fleet2_all",
            Emotion_Mode="nothing",  # 不计算心情，也不忽略心情限制。
        )
        self.load_campaign_helper(name="campaign_hard", folder="campaign_hard")
        module = importlib.import_module("." + name, "campaign.campaign_main")
        self.campaign.MAP = module.MAP

        self.device.screenshot()
        self.campaign.device.image = self.device.image
        self.campaign.ensure_campaign_ui(name=self.config.Hard_HardStage, mode="hard")

        remain = OCR_HARD_REMAIN.ocr_single(self.device.image)
        logger.attr("Remain", remain)
        for _n in range(remain):
            self.campaign.run()

        self.campaign.ensure_auto_search_exit()

        self.config.task_delay(server_update=True)
        self.config.task_call("Reward")
