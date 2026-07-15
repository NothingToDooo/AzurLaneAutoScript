from typing import TYPE_CHECKING, Literal

from module.base.timer import Timer
from module.base.utils import rgb2gray
from module.combat.combat import Combat
from module.eventstory import assets as eventstory_assets
from module.eventstory.profile import (
    EventStoryClientProfile,
    EventStoryLandingPage,
    EventStoryPopupHandler,
    EventStorySpecialEntryProbe,
)
from module.eventstory.ui import EventStoryMode, EventStoryUiCapability
from module.exception import RequestHumanTakeover
from module.handler.login import LoginHandler
from module.logger import logger
from module.ui.page import page_event, page_sp

if TYPE_CHECKING:
    from module.base.button import Button
    from module.config.config import AzurLaneConfig
    from module.device.device import Device

type EventStoryState = Literal["finish", "story", "story_alchemist", "unknown"]
type EventStoryResult = Literal["battle", "finish"]


class EventStory(EventStoryUiCapability, Combat, LoginHandler):
    def __init__(
        self,
        config: AzurLaneConfig,
        *,
        profile: EventStoryClientProfile,
        device: Device,
    ) -> None:
        if not isinstance(profile, EventStoryClientProfile):
            message = "profile must be an EventStoryClientProfile"
            raise TypeError(message)
        self._client_profile = profile
        super().__init__(config, device=device)

    @property
    def client_profile(self) -> EventStoryClientProfile:
        return self._client_profile

    def _ensure_landing_page(self) -> None:
        if self._client_profile.landing_page is EventStoryLandingPage.EVENT:
            self.ui_ensure(page_event)
            return
        self.ui_ensure(page_sp)

    def ui_goto_event_story(self) -> EventStoryState:
        """进入 profile 指定的活动剧情页并返回当前状态。"""
        self._ensure_landing_page()
        self.ensure_event_story_mode(EventStoryMode.STORY)

        state = "unknown"
        for _ in range(3):
            timeout = Timer(2, count=6).start()
            for _ in self.loop():
                state = self.get_event_story_state()
                logger.attr("EventStoryState", state)
                if state != "unknown":
                    break
                if timeout.reached():
                    logger.warning("Wait EventStoryState timeout")
                    break
            if state == "unknown":
                # 剧情页可能被滑动过，导致找不到入口；重置模式以恢复位置。
                self.ensure_event_story_mode(EventStoryMode.COMBAT)
                self.ensure_event_story_mode(EventStoryMode.STORY)
                continue
            break

        return state

    def _get_alchemist_entry_button(self) -> Button | None:
        """以 0.85 相似度查找炼金联动入口，返回下移 44px 的按钮；未找到时返回 None。"""
        area = (0, 72, 1280, 560)
        image = self.image_crop(area, copy=False)
        image = rgb2gray(image)
        sim, button = eventstory_assets.TEMPLATE_ALCHEMIST_STORY.match_result(image)
        if sim >= 0.85:
            button = button.move(area[:2])
            return button.move((0, 44))
        sim, button = eventstory_assets.TEMPLATE_ALCHEMIST_BATTLE.match_result(image)
        if sim >= 0.85:
            button = button.move(area[:2])
            return button.move((0, 44))
        return None

    def _handle_alchemist_entry(self, interval: float = 2) -> bool:
        """处理炼金 profile 的全页面剧情入口，并返回是否点击。"""
        timer = self.get_interval_timer(eventstory_assets.TEMPLATE_ALCHEMIST_STORY, interval=interval)
        if not timer.reached():
            return False
        button = self._get_alchemist_entry_button()
        if button:
            self.device.click(button)
            timer.reset()
            return True
        return False

    def _event_story_clear_intervals(self) -> None:
        self.story_skip_interval_clear()
        self.popup_interval_clear()
        self.device.click_record_clear()

    def _handle_event_story_entry(self) -> bool:
        if self.appear_then_click(eventstory_assets.STORY_FIRST, offset=(20, 20), interval=3):
            return True
        if self.match_template_color(eventstory_assets.STORY_LAST, offset=(20, 20), interval=3):
            self.device.click(eventstory_assets.STORY_LAST)
            return True
        if self.appear_then_click(eventstory_assets.STORY_MIDDLE, offset=(20, 200), interval=3):
            return True
        if self.appear_then_click(eventstory_assets.BATTLE_MIDDLE, offset=(20, 200), interval=3):
            return True
        return (
            self._client_profile.special_entry_probe is EventStorySpecialEntryProbe.ALCHEMIST
            and self._handle_alchemist_entry()
        )

    def _handle_profile_popup(self) -> bool:
        if self._client_profile.popup_handler is not EventStoryPopupHandler.RPG_STATUS:
            return False
        return self.appear_then_click(eventstory_assets.POPUP_RPG_STATUS, offset=(20, 20), interval=3)

    def _event_story_finished(self) -> bool:
        if self.match_template_color(eventstory_assets.STORY_FINISHED, offset=(20, 20)):
            return True
        return self.appear(eventstory_assets.REWARD_GOT, offset=(50, 30))

    def _event_story_regular_available(self) -> bool:
        return (
            self.appear_then_click(eventstory_assets.STORY_FIRST, offset=(20, 20))
            or self.match_template_color(eventstory_assets.STORY_LAST, offset=(20, 20))
            or self.appear_then_click(eventstory_assets.STORY_MIDDLE, offset=(20, 200))
            or self.appear_then_click(eventstory_assets.BATTLE_MIDDLE, offset=(20, 200))
        )

    def event_story(self, *, skip_first_screenshot: bool = True) -> EventStoryResult:
        """推进活动剧情；进入战斗返回 battle，剧情结束返回 finish。"""
        logger.hr("Event story", level=1)
        timeout = Timer.from_seconds(300).start()
        while not timeout.reached():
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if self.is_combat_executing() or self.is_combat_loading():
                logger.info("run_story end at battle")
                return "battle"
            if self.match_template_color(eventstory_assets.STORY_FINISHED, offset=(20, 20), interval=3):
                logger.info("run_story end at STORY_FINISHED")
                return "finish"
            if self.appear(eventstory_assets.REWARD_GOT, offset=(50, 30)):
                logger.info("run_story end at REWARD_GOT")
                return "finish"

            if self.handle_story_skip():
                self.interval_clear([eventstory_assets.STORY_MIDDLE, eventstory_assets.BATTLE_MIDDLE])
                continue
            if self.handle_get_items():
                continue

            if self._handle_event_story_entry():
                self._event_story_clear_intervals()
                continue
            if self._handle_profile_popup():
                continue
        message = "event story did not reach a safe point within 300 seconds"
        raise RequestHumanTakeover(message)

    def get_event_story_state(self) -> EventStoryState:
        """返回 finish、story、story_alchemist 或 unknown。"""
        if self._event_story_finished():
            return "finish"

        if self._event_story_regular_available():
            return "story"
        if (
            self._client_profile.special_entry_probe is EventStorySpecialEntryProbe.ALCHEMIST
            and self._get_alchemist_entry_button()
        ):
            return "story_alchemist"

        return "unknown"
