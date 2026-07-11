from typing import TYPE_CHECKING

from module.campaign.campaign_base import CampaignBase as CampaignBase_

if TYPE_CHECKING:
    from module.base.button import Button


class CampaignBase(CampaignBase_):
    def campaign_set_chapter_sp(self, chapter: str, mode: str = "normal") -> bool:
        del mode
        if chapter == "sp":
            self.ui_goto_event()
            self.campaign_ensure_chapter(chapter)
            return True
        return False

    def campaign_ensure_mode(self, mode: str = "normal") -> None:
        """该活动不需要切换模式。"""

    def campaign_get_chapter_index(self, name: str | int) -> int:
        """将整数或章节名转换为章节序号。"""
        if name == "t":
            return 1
        if name == "ex_sp":
            return 2
        if name == "ex_ex":
            return 3

        return super(CampaignBase, CampaignBase).campaign_get_chapter_index(name)

    @staticmethod
    def campaign_separate_name(name: str) -> tuple[str, str]:
        """名称含 esp 时映射为 (ex_sp, 1)，含 ex 时映射为 (ex_ex, 1)，其余按通用规则分解。"""
        if "esp" in name:
            return "ex_sp", "1"
        if "ex" in name:
            return "ex_ex", "1"

        return super(CampaignBase, CampaignBase).campaign_separate_name(name)

    def campaign_get_entrance(self, name: str) -> Button:
        """返回指定关卡的入口按钮。"""
        if name == "sp":
            for stage_name in self.stage_entrance or {}:
                if "esp" in stage_name.lower():
                    name = stage_name

        return super().campaign_get_entrance(name)
