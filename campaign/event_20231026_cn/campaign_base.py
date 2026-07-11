from module.campaign.campaign_base import CampaignBase as CampaignBase_


class CampaignBase(CampaignBase_):
    STAGE_INCREASE = (
        """
        T1 > T2 > T3 > T4 > T5 > T6
        """,
    )

    def campaign_set_chapter_event(self, chapter: str, mode: str = "normal") -> bool:
        del mode
        self.ui_goto_event()
        self.campaign_ensure_chapter(chapter)
        return True

    def campaign_get_chapter_index(self, name: str | int) -> int:
        """将整数或章节名转换为章节序号。"""
        if name == "t1":
            return 1
        if name == "t2":
            return 2
        if name == "ex_sp":
            return 3
        if name == "ex_ex":
            return 4

        return super(CampaignBase, CampaignBase).campaign_get_chapter_index(name)

    @staticmethod
    def campaign_separate_name(name: str) -> tuple[str, str]:
        """将 T1～T3 归入 t1、T4～T6 归入 t2，并把 ESP/EX 映射为 ex_sp/ex_ex。"""
        if name in ["t1", "t2", "t3"]:
            return "t1", name[-1]
        if name in ["t4", "t5", "t6"]:
            return "t2", name[-1]
        if "esp" in name:
            return "ex_sp", "1"
        if "ex" in name:
            return "ex_ex", "1"

        return super(CampaignBase, CampaignBase).campaign_separate_name(name)
