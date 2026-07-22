from typing import TYPE_CHECKING, Protocol, override

from module.logger import logger
from module.ui.page import page_campaign_menu, page_event
from module.war_archives.assets import WAR_ARCHIVES_CAMPAIGN_CHECK

if TYPE_CHECKING:
    from module.base.button import Button, MatchOffset
    from module.ui.page import Page


class EventDestinationHost(Protocol):
    def ui_get_current_page(self, *, skip_first_screenshot: bool = True) -> Page: ...

    def appear(
        self,
        button: Button,
        offset: MatchOffset | None = 0,
        interval: float = 0,
        similarity: float = 0.85,
        threshold: int = 10,
    ) -> bool: ...

    def ui_goto_main(self) -> bool: ...

    def ui_goto(
        self,
        destination: Page,
        *,
        get_ship: bool = True,
        offset: MatchOffset | None = (30, 30),
        skip_first_screenshot: bool = True,
    ) -> None: ...

    def is_event_entrance_available(self) -> bool: ...


class EventDestination(Protocol):
    """打开当前关卡所属的活动入口。"""

    def open(self, runtime: EventDestinationHost) -> bool: ...


class StandardEventDestination(EventDestination):
    @override
    def open(self, runtime: EventDestinationHost) -> bool:
        if runtime.ui_get_current_page() == page_event:
            if runtime.appear(WAR_ARCHIVES_CAMPAIGN_CHECK, offset=(20, 20)):
                logger.info("At war archives")
                runtime.ui_goto_main()
            else:
                logger.info("Already at page_event")
                return True
        runtime.ui_goto(page_campaign_menu)
        if not runtime.is_event_entrance_available():
            return False
        runtime.ui_goto(page_event)
        return True


STANDARD_EVENT_DESTINATION = StandardEventDestination()
