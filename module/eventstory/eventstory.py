from typing import TYPE_CHECKING, Literal

from module.base.timer import Timer
from module.base.utils import rgb2gray
from module.campaign.campaign_ui import CampaignUI
from module.combat.combat import Combat
from module.eventstory import assets as eventstory_assets
from module.handler.login import LoginHandler
from module.logger import logger
from module.ui.page import page_event, page_sp

if TYPE_CHECKING:
    from module.base.button import Button

type EventStoryState = Literal["finish", "story", "story_alchemist", "unknown"]
type EventStoryResult = Literal["battle", "finish"]


class EventStory(CampaignUI, Combat, LoginHandler):
    def ui_goto_event_story(self) -> EventStoryState:
        """进入活动剧情页并返回 finish、story、story_alchemist 或 unknown。

        2025-10-23 国服活动使用 SP 页，其余使用活动页。
        """
        event = self.config.cross_get("Event.Campaign.Event", "")
        if event == "event_20251023_cn":
            self.ui_ensure(page_sp)
        else:
            self.ui_ensure(page_event)
        self.campaign_ensure_mode_20241219("story")

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
                self.campaign_ensure_mode_20241219("combat")
                self.campaign_ensure_mode_20241219("story")
                continue
            break

        return state

    def get_event_20250724_button(self) -> Button | None:
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

    def handle_event_20250724(self, interval: float = 2) -> bool:
        """处理第二次炼金联动中全页面可见的剧情按钮，并返回是否点击。"""
        timer = self.get_interval_timer(eventstory_assets.TEMPLATE_ALCHEMIST_STORY, interval=interval)
        if not timer.reached():
            return False
        button = self.get_event_20250724_button()
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
        return self.handle_event_20250724()

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
        while 1:
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
            # 深渊秘境（event_20250814_cn）全部剧情结束后会弹出状态窗口。
            if self.appear_then_click(eventstory_assets.POPUP_RPG_STATUS, offset=(20, 20), interval=3):
                continue
        return "finish"

    def run_event_story(self) -> None:
        """循环处理剧情和战斗，直到活动剧情结束。"""
        while 1:
            state = self.ui_goto_event_story()
            if state == "finish":
                break
            result = self.event_story()
            if result == "battle":
                # 关闭游戏会被视为战斗已清理，比等待活动战斗更快。
                logger.hr("Event Story Battle", level=2)
                self.config.override(Error_HandleError=True)
                self.app_stop()
                self.app_start()
                continue
            if result == "finish":
                # 剧情结束后再跑一次，用来关闭 GET_ITEMS。
                logger.hr("Event story finish", level=2)
                self.ui_goto_main()
                self.ui_goto_event_story()

    def get_event_story_state(self) -> EventStoryState:
        """返回 finish、story、story_alchemist 或 unknown。"""
        if self._event_story_finished():
            return "finish"

        if self._event_story_regular_available():
            return "story"
        if self.get_event_20250724_button():
            return "story_alchemist"

        return "unknown"

    def run(self) -> None:
        event = self.config.cross_get("Event.Campaign.Event", "")
        # 活动剧情在活动小游戏中。
        if event == "event_20260226_cn":
            logger.info(f"Current event ({event}) does not have event story, stopped")
            return

        if not self.device.app_is_running():
            logger.warning("Game is not running, start it")
            self.app_start()

        self.run_event_story()

        # 调度由外层任务处理。


if __name__ == "__main__":
    self = EventStory("alas")
    self.run()
