from module.base.mask import Mask
from module.campaign.campaign_base import CampaignBase as CampaignBase_
from module.map_detection.utils_assets import ASSETS

MASK_MAP_UI_20211125 = Mask(file="./assets/mask/MASK_MAP_UI_20211125.png")


class CampaignBase(CampaignBase_):
    STAGE_INCREASE = (
        "T1 > T2 > T3 > T4",
        "TSS1 > TSS2 > TSS3 > TSS4 > TSS5",
    )

    def map_data_init(self, map_):
        super().map_data_init(map_)
        # Patch ui_mask, get rid of map mechanism
        _ = ASSETS.ui_mask
        ASSETS.ui_mask = MASK_MAP_UI_20211125.image

    def campaign_ensure_mode(self, mode="normal"):
        """该活动不需要切换模式。"""

    def campaign_get_chapter_index(self, name):
        """将整数或章节名转换为章节序号。"""
        if name == "t":
            return 1
        if name == "ex_sp":
            return 2
        if name == "ex_ex":
            return 3
        if name == "tss":
            return 4

        return super(CampaignBase, CampaignBase).campaign_get_chapter_index(name)

    @staticmethod
    def campaign_separate_name(name: str) -> tuple[str, str]:
        """名称含 sss 时映射为 (ex_sp, 1)，含 ex 时映射为 (ex_ex, 1)，其余按通用规则分解。"""
        if "sss" in name:
            return "ex_sp", "1"
        if "ex" in name:
            return "ex_ex", "1"

        return super(CampaignBase, CampaignBase).campaign_separate_name(name)

    def campaign_get_entrance(self, name):
        """返回指定关卡的入口按钮。"""
        if name == "sp":
            for stage_name in self.stage_entrance or {}:
                if "sss" in stage_name.lower():
                    name = stage_name

        return super().campaign_get_entrance(name)
