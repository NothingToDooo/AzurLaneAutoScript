from module.exception import CampaignNameError
from module.logger import logger

from ..campaign_war_archives.campaign_base import CampaignBase as CampaignBase_


class CampaignBase(CampaignBase_):
    STAGE_INCREASE = [
        "SP0 > SP1 > SP2 > SP3",
    ]
