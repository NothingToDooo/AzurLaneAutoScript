from module.ui.page import page_event

from ..campaign_war_archives.campaign_base import CampaignBase as CampaignBase_


class CampaignBase(CampaignBase_):
    def handle_clear_mode_config_cover(self) -> bool:
        handled = super().handle_clear_mode_config_cover()
        if handled:
            # 清图覆盖只在本次运行生效，必须绕过配置持久化绑定。
            object.__setattr__(self.config, "MAP_SIREN_TEMPLATE", ["SS"])  # noqa: PLC2801
            object.__setattr__(self.config, "MAP_HAS_SIREN", True)  # noqa: PLC2801
        return handled

    def handle_exp_info(self) -> bool:
        # Random background hits EXP_INFO_B
        if self.ui_page_appear(page_event):
            return False
        return super().handle_exp_info()
