from module.campaign.campaign_status import CampaignStatus
from module.logger import logger
from module.ui.assets import CAMPAIGN_MENU_NO_EVENT
from module.ui.page import page_campaign_menu, page_coalition, page_event, page_sp
from module.war_archives.assets import WAR_ARCHIVES_CAMPAIGN_CHECK


class EventCampaignNavigation(CampaignStatus):
    """活动入口导航；只观察和点击，不拥有任务调度。"""

    def is_event_entrance_available(self) -> bool:
        available = not self.appear(CAMPAIGN_MENU_NO_EVENT, offset=(20, 20))
        logger.info("Event available" if available else "Event unavailable")
        return available

    def ui_goto_event(self) -> bool:
        if self.ui_get_current_page() == page_event:
            if self.appear(WAR_ARCHIVES_CAMPAIGN_CHECK, offset=(20, 20)):
                logger.info("At war archives")
                self.ui_goto_main()
            else:
                logger.info("Already at page_event")
                return True
        self.ui_goto(page_campaign_menu)
        if not self.is_event_entrance_available():
            return False
        self.ui_goto(page_event)
        return True

    def ui_goto_sp(self) -> bool:
        if self.ui_get_current_page() == page_sp:
            if self.appear(WAR_ARCHIVES_CAMPAIGN_CHECK, offset=(20, 20)):
                logger.info("At war archives")
                self.ui_goto_main()
            else:
                logger.info("Already at page_sp")
                return True
        self.ui_goto(page_campaign_menu)
        if not self.is_event_entrance_available():
            return False
        self.ui_goto(page_sp)
        return True

    def ui_goto_coalition(self) -> bool:
        if self.ui_get_current_page() == page_coalition:
            logger.info("Already at page_coalition")
            return True
        self.ui_goto(page_campaign_menu)
        if not self.is_event_entrance_available():
            return False
        self.ui_goto(page_coalition)
        return True
