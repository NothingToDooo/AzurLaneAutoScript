import cv2
import numpy as np
from scipy import signal

from module.base.base import ModuleBase
from module.base.button import Button
from module.base.timer import Timer
from module.base.utils import area_offset, area_pad, color_similar, color_similarity_2d, get_color
from module.exception import GameNotRunningError
from module.handler import assets as handler_assets
from module.logger import logger
from module.os_handler.assets import CLICK_SAFE_AREA as OS_CLICK_SAFE_AREA
from module.ui_white.assets import POPUP_CANCEL_WHITE, POPUP_CONFIRM_WHITE, POPUP_SINGLE_WHITE


def info_letter_preprocess(image):
    """
    Args:
        image (np.ndarray):

    Returns:
        np.ndarray
    """
    image = image.astype(float)
    image = (image - 64) / 0.75
    image[image > 255] = 255
    image[image < 0] = 0
    image = image.astype("uint8")
    return image


class InfoHandler(ModuleBase):
    """
    Class to handle all kinds of message.
    """

    """
    Info bar
    """

    def info_bar_count(self):
        """
        Detect info bar by the blue lines on the top of it.

        Returns:
            int:
        """
        image = self.image_crop(handler_assets.INFO_BAR_AREA, copy=False)
        line = cv2.reduce(image, 1, cv2.REDUCE_AVG)
        line = color_similarity_2d(line, color=(107, 158, 255))[:, 0]

        parameters = {
            "height": 235,
            "prominence": 50,
            # Blue lines are in a interval of 56
            "distance": 50,
        }
        peaks, _ = signal.find_peaks(line, **parameters)
        return len(peaks)

    def wait_until_info_bar_disappear(self):
        while 1:
            self.device.screenshot()
            if not self.info_bar_count():
                break

    def handle_info_bar(self):
        if self.info_bar_count():
            self.wait_until_info_bar_disappear()
            return True
        return False

    def ensure_no_info_bar(self, timeout=0.6, skip_first_screenshot=True):
        timeout = Timer(timeout).start()
        handled = False
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if self.handle_info_bar():
                handled = True

            # 结束。
            if timeout.reached():
                break

        return handled

    """
    Popup info
    """
    _popup_offset = (3, 30)

    def handle_popup_confirm(self, name="", offset=None, interval=2):
        if offset is None:
            offset = self._popup_offset
        if self.appear(handler_assets.POPUP_CANCEL, offset=offset) and self.appear(
            handler_assets.POPUP_CONFIRM, offset=offset, interval=interval
        ):
            handler_assets.POPUP_CONFIRM.name = handler_assets.POPUP_CONFIRM.name + "_" + name
            self.device.click(handler_assets.POPUP_CONFIRM)
            handler_assets.POPUP_CONFIRM.name = handler_assets.POPUP_CONFIRM.name[: -len(name) - 1]
            return True
        if self.appear(POPUP_CONFIRM_WHITE, offset=offset, interval=interval):
            POPUP_CONFIRM_WHITE.name = POPUP_CONFIRM_WHITE.name + "_" + name
            self.device.click(POPUP_CONFIRM_WHITE)
            POPUP_CONFIRM_WHITE.name = POPUP_CONFIRM_WHITE.name[: -len(name) - 1]
            return True
        return False

    def handle_popup_cancel(self, name="", offset=None, interval=2):
        if offset is None:
            offset = self._popup_offset
        if self.appear(handler_assets.POPUP_CONFIRM, offset=offset) and self.appear(
            handler_assets.POPUP_CANCEL, offset=offset, interval=interval
        ):
            handler_assets.POPUP_CANCEL.name = handler_assets.POPUP_CANCEL.name + "_" + name
            self.device.click(handler_assets.POPUP_CANCEL)
            handler_assets.POPUP_CANCEL.name = handler_assets.POPUP_CANCEL.name[: -len(name) - 1]
            return True
        if self.appear(POPUP_CANCEL_WHITE, offset=offset, interval=interval):
            POPUP_CANCEL_WHITE.name = POPUP_CANCEL_WHITE.name + "_" + name
            self.device.click(POPUP_CANCEL_WHITE)
            POPUP_CANCEL_WHITE.name = POPUP_CANCEL_WHITE.name[: -len(name) - 1]
            return True
        return False

    def handle_popup_single(self, name="", offset=None, interval=2):
        if offset is None:
            offset = self._popup_offset
        if self.appear(handler_assets.GET_MISSION, offset=offset, interval=interval):
            prev_name = handler_assets.GET_MISSION.name
            handler_assets.GET_MISSION.name = handler_assets.POPUP_CONFIRM.name + "_" + name
            self.device.click(handler_assets.GET_MISSION)
            handler_assets.GET_MISSION.name = prev_name
            return True

        return False

    def handle_popup_single_white(self, interval=2):
        return self.appear_then_click(POPUP_SINGLE_WHITE, offset=(20, 20), interval=interval)

    def popup_interval_clear(self):
        self.interval_clear(
            [
                handler_assets.POPUP_CANCEL,
                handler_assets.POPUP_CONFIRM,
                POPUP_CANCEL_WHITE,
                POPUP_CONFIRM_WHITE,
            ]
        )

    _hot_fix_check_wait = Timer(6)

    def handle_urgent_commission(self, drop=None):
        """
        Args:
            drop (DropImage):

        Returns:
            bool:
        """
        appear = self.appear(handler_assets.GET_MISSION, offset=True, interval=2)
        if appear:
            logger.info("Get urgent commission")
            if drop:
                self.handle_info_bar()
                drop.add(self.device.image)
            self.device.click(handler_assets.GET_MISSION)
            self._hot_fix_check_wait.reset()

        # Check game client existence after 3s to 6s
        # Hot fixes will kill AL if you clicked the confirm button
        if self._hot_fix_check_wait.reached():
            self._hot_fix_check_wait.clear()
        if self._hot_fix_check_wait.started() and 3 <= self._hot_fix_check_wait.current_time() <= 6:
            if not self.device.app_is_running():
                logger.error("Detected hot fixes from game server, game died")
                raise GameNotRunningError
            # 维护弹窗会干扰颜色匹配，这里只用模板匹配。
            if self.appear(handler_assets.LOGIN_CHECK, offset=(30, 30)):
                logger.error(
                    "Account logged out, probably because account kicked by server maintenance or another log in"
                )
                # Kill game, because game patches after maintenance can only be downloaded at game startup
                self.device.app_stop()
                raise GameNotRunningError
            self._hot_fix_check_wait.clear()

        return appear

    def handle_combat_low_emotion(self):
        if not self.emotion.is_ignore:
            return False

        result = self.handle_popup_confirm("IGNORE_LOW_EMOTION")
        if result:
            # 避免点击 AUTO_SEARCH_MAP_OPTION_OFF。
            self.interval_reset(handler_assets.AUTO_SEARCH_MAP_OPTION_OFF)
        return result

    def handle_use_data_key(self):
        if not self.config.USE_DATA_KEY:
            return False

        if not self.appear(handler_assets.POPUP_CONFIRM, offset=self._popup_offset) and not self.appear(
            handler_assets.POPUP_CANCEL, offset=self._popup_offset, interval=2
        ):
            return False

        if self.appear(handler_assets.USE_DATA_KEY, offset=(20, 20)):
            # 启用 USE_DATA_KEY_NOTIFIED。
            for _ in self.loop():
                enabled = self.image_color_count(
                    handler_assets.USE_DATA_KEY_NOTIFIED, color=(140, 207, 66), threshold=180, count=10
                )
                if enabled:
                    break
                if self.appear(handler_assets.USE_DATA_KEY, offset=(20, 20), interval=5):
                    self.device.click(handler_assets.USE_DATA_KEY_NOTIFIED)
                    continue

            self.config.USE_DATA_KEY = False  # Reset on success as task can be stopped before can be recovered

            # 点击确认。
            # 数据钥匙页面的 POPUP_CONFIRM 和标准按钮略有不同，因此这里直接绑定点击。
            self.interval_clear(handler_assets.USE_DATA_KEY, interval=5)
            for _ in self.loop():
                if not self.appear(handler_assets.USE_DATA_KEY, offset=(20, 20)):
                    break
                if self.appear(handler_assets.USE_DATA_KEY, offset=(20, 20), interval=5):
                    self.device.click(handler_assets.POPUP_CONFIRM)
                    continue

            return True

        return False

    def handle_vote_popup(self):
        """
        Dismiss vote pop-ups.

        Returns:
            bool:
        """
        # Vote popups are removed in 2023
        # return self.appear_then_click(VOTE_CANCEL, offset=(20, 20), interval=2)
        return False

    def handle_get_skin(self):
        """
        Returns:
            bool:
        """
        return self.appear_then_click(handler_assets.GET_SKIN, offset=(20, 20), interval=2)

    def handle_get_items_ship(self, drop=None):
        """
        2026.06.12 added different GET_ITEMS popup when getting ship

        Args:
            drop (DropImage):

        Returns:
            bool:
        """
        if self.appear(handler_assets.GET_ITEMS_SHIP_1, offset=5, interval=2):
            if drop:
                drop.handle_add(self)
            self.device.click(handler_assets.GET_ITEMS_SHIP_1)
            return True

        return False

    """
    Guild popup info
    """

    def handle_guild_popup_confirm(self):
        if self.appear(handler_assets.GUILD_POPUP_CANCEL, offset=self._popup_offset) and self.appear(
            handler_assets.GUILD_POPUP_CONFIRM, offset=self._popup_offset, interval=2
        ):
            self.device.click(handler_assets.GUILD_POPUP_CONFIRM)
            return True

        return False

    def handle_guild_popup_cancel(self):
        if self.appear(handler_assets.GUILD_POPUP_CONFIRM, offset=self._popup_offset) and self.appear(
            handler_assets.GUILD_POPUP_CANCEL, offset=self._popup_offset, interval=2
        ):
            self.device.click(handler_assets.GUILD_POPUP_CANCEL)
            return True

        return False

    """
    Mission popup info
    """

    def handle_mission_popup_go(self):
        if self.appear(handler_assets.MISSION_POPUP_ACK, offset=self._popup_offset) and self.appear(
            handler_assets.MISSION_POPUP_GO, offset=self._popup_offset, interval=2
        ):
            self.device.click(handler_assets.MISSION_POPUP_GO)
            return True

        return False

    def handle_mission_popup_ack(self):
        if self.appear(handler_assets.MISSION_POPUP_GO, offset=self._popup_offset) and self.appear(
            handler_assets.MISSION_POPUP_ACK, offset=self._popup_offset, interval=2
        ):
            self.device.click(handler_assets.MISSION_POPUP_ACK)
            return True

        return False

    """
    Story
    """
    story_popup_timeout = Timer(10, count=20)
    map_has_clear_mode = False  # 会在 fast_forward.py 中覆盖。
    map_is_threat_safe = False

    _story_confirm = Timer(0.5, count=1)
    _story_option_timer = Timer(2)
    _story_option_record = 0
    _story_option_confirm = Timer(0.3, count=0)

    def _story_option_buttons(self):
        """
        Returns:
            list[Button]: List of story options, from upper to bottom. If no option found, return an empty list.
        """
        # Area to detect the options, should include at least 3 options.
        story_option_area = (730, 188, 1140, 480)
        # Background color of the left part of the option.
        story_option_color = (99, 121, 156)
        image = color_similarity_2d(self.image_crop(story_option_area, copy=False), color=story_option_color) > 225
        x_count = np.where(np.sum(image, axis=0) > 40)[0]
        if not len(x_count):
            return []
        x_min, x_max = np.min(x_count), np.max(x_count)

        parameters = {
            # Option is 300`320px x 50~52px.
            "height": 280,
            "width": 45,
            "distance": 50,
            # Chooses the relative height at which the peak width is measured as a percentage of its prominence.
            # 1.0 calculates the width of the peak at its lowest contour line,
            # while 0.5 evaluates at half the prominence height.
            # Must be at least 0.
            "rel_height": 5,
        }
        y_count = np.sum(image, axis=1)
        peaks, properties = signal.find_peaks(y_count, **parameters)
        buttons = []
        total = len(peaks)
        if not total:
            return []
        for n, bases in enumerate(zip(properties["left_bases"], properties["right_bases"], strict=True)):
            area = (x_min, bases[0], x_max, bases[1])
            area = area_pad(area_offset(area, offset=story_option_area[:2]), pad=5)
            buttons.append(
                Button(area=area, color=story_option_color, button=area, name=f"STORY_OPTION_{n + 1}_OF_{total}")
            )

        return buttons

    def _story_option_buttons_2(self):
        """
        Returns:
            list[Button]: List of story options, from upper to bottom. If no option found, return an empty list.
        """
        # Area to detect the options, should include at least 3 options.
        story_option_area = (330, 135, 980, 555)
        story_detect_area = (330, 135, 355, 555)
        story_option_color = (247, 247, 247)

        image = color_similarity_2d(self.image_crop(story_detect_area, copy=False), color=story_option_color)
        cv2.morphologyEx(image, cv2.MORPH_CLOSE, kernel=np.ones((5, 5), dtype=np.uint8), dst=image)
        line = cv2.reduce(image, 1, cv2.REDUCE_AVG).flatten()
        line[line < 200] = 0
        line[line >= 200] = 255

        parameters = {
            # Option is 300`320px x 50~52px.
            "height": 200,
            "width": 40,
            "distance": 40,
            # Chooses the relative height at which the peak width is measured as a percentage of its prominence.
            # 1.0 calculates the width of the peak at its lowest contour line,
            # while 0.5 evaluates at half the prominence height.
            # Must be at least 0.
            # rel_height is about 240 / 48
            "rel_height": 4,
        }
        peaks, properties = signal.find_peaks(line, **parameters)
        buttons = []
        total = len(peaks)
        if not total:
            return []
        for n, bases in enumerate(zip(properties["left_bases"], properties["right_bases"], strict=True)):
            area = (
                story_option_area[0],
                story_option_area[1] + bases[0],
                story_option_area[2],
                story_option_area[1] + bases[1],
            )
            area = area_pad(area, pad=5)
            buttons.append(
                Button(area=area, color=story_option_color, button=area, name=f"STORY_OPTION_{n + 1}_OF_{total}")
            )

        return buttons

    def _is_story_black(self):
        color = get_color(self.device.image, area=handler_assets.STORY_LETTER_BLACK.area)
        # 深色背景、少量文字的剧情。
        # STORY_LETTER_BLACK.color 是 (16, 20, 16)。
        if color_similar(color, handler_assets.STORY_LETTER_BLACK.color, threshold=10):
            return True
        # 黑色背景、少量文字的剧情。
        return color_similar(color, (0, 0, 0), threshold=10)

    def story_skip(self, drop=None):
        """
        2023.09.14 Story options changed with big white options in the middle,
            Check STORY_SKIP_3 but click the original STORY_SKIP.
        """
        if self.story_popup_timeout.started() and not self.story_popup_timeout.reached():
            if self.handle_popup_confirm("STORY_SKIP"):
                self.story_popup_timeout = Timer(10)
                self.interval_reset(handler_assets.STORY_SKIP_3)
                self.interval_reset(handler_assets.STORY_LETTERS_ONLY)
                return True
        if self._is_story_black():
            if self.appear_then_click(handler_assets.STORY_LETTERS_ONLY, offset=(20, 20), interval=2):
                self.story_popup_timeout.reset()
                return True
        if self._story_option_timer.reached() and self.appear(handler_assets.STORY_SKIP_3, offset=(20, 20), interval=0):
            options = self._story_option_buttons_2()
            options_count = len(options)
            logger.attr("Story_options", options_count)
            if not options_count:
                self._story_option_record = 0
                self._story_option_confirm.reset()
            elif options_count == self._story_option_record:
                if self._story_option_confirm.reached():
                    try:
                        select = options[self.config.STORY_OPTION]
                    except IndexError:
                        select = options[0]
                    self.device.click(select)
                    self._story_option_timer.reset()
                    self.story_popup_timeout.reset()
                    self.interval_reset(handler_assets.STORY_SKIP_3)
                    self.interval_reset(handler_assets.STORY_LETTERS_ONLY)
                    self._story_option_record = 0
                    self._story_option_confirm.reset()
                    return True
            else:
                self._story_option_record = options_count
                self._story_option_confirm.reset()
        if self.appear(handler_assets.STORY_SKIP_3, offset=(20, 20), interval=2):
            # 确认这是剧情。
            # 剧情播放速度为 Very Fast 时，Alas 点击跳过时剧情可能刚好消失。
            # 这次点击会中断自动搜索。
            self.interval_reset([handler_assets.STORY_SKIP_3])
            if self._story_confirm.reached():
                if drop:
                    drop.handle_add(self, before=2)
                if self.config.STORY_ALLOW_SKIP:
                    logger.info(f"{handler_assets.STORY_SKIP_3} -> {handler_assets.STORY_SKIP}")
                    self.device.click(handler_assets.STORY_SKIP)
                else:
                    logger.info(f"{handler_assets.STORY_SKIP_3} -> {OS_CLICK_SAFE_AREA}")
                    self.device.click(OS_CLICK_SAFE_AREA)
                self._story_confirm.reset()
                self.story_popup_timeout.reset()
                return True
            self.interval_clear(handler_assets.STORY_SKIP_3)
        else:
            self._story_confirm.reset()
        if self.appear_then_click(handler_assets.STORY_CLOSE, offset=(10, 10), interval=2):
            self.story_popup_timeout.reset()
            return True

        return False

    def story_skip_interval_clear(self):
        self.interval_clear(handler_assets.STORY_SKIP_3)
        self.interval_clear(handler_assets.STORY_LETTERS_ONLY)

    def handle_story_skip(self, drop=None):
        # 复刻活动在 clear mode 下仍可能有剧情。
        # clear mode 通常没有剧情，但 B3/D3 在威胁安全前仍有剧情。
        # 威胁安全后不再有剧情。
        if self.map_is_threat_safe and self.config.Campaign_Event != "event_20201012_cn":
            return False

        return self.story_skip(drop=drop)

    def ensure_no_story(self, skip_first_screenshot=True):
        logger.info("Ensure no story")
        story_timer = Timer(3, count=6).start()
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if self.story_skip():
                story_timer.reset()

            if story_timer.reached():
                break

    def handle_map_after_combat_story(self):
        if not self.config.MAP_HAS_MAP_STORY:
            return False

        self.ensure_no_story()

    """
    Game tips
    """

    def handle_game_tips(self):
        """
        Returns:
            bool: If handled
        """
        if self.appear(handler_assets.GAME_TIPS, offset=(20, 20), interval=2) and self.image_color_count(
            handler_assets.GAME_TIPS.button, color=(40, 40, 40), threshold=240, count=50
        ):
            self.device.click(handler_assets.GAME_TIPS)
            return True
        if self.appear(handler_assets.GAME_TIPS3, offset=(20, 20), interval=2) and self.image_color_count(
            handler_assets.GAME_TIPS3.button, color=(40, 40, 40), threshold=240, count=50
        ):
            self.device.click(handler_assets.GAME_TIPS)
            return True
        if self.appear(handler_assets.GAME_TIPS4, offset=(20, 20), interval=2) and self.image_color_count(
            handler_assets.GAME_TIPS4.button, color=(40, 40, 40), threshold=240, count=50
        ):
            self.device.click(handler_assets.GAME_TIPS)
            return True

        return False

    """
    Manjuu loading
    """

    def manjuu_count(self):
        """
        detect manjuu count by template matching
        Returns:
            int: Number of manjuu
        """
        image = self.image_crop(handler_assets.MANJUU_AREA, copy=False)
        # Manjuu 表情会拉伸和缩小，默认 0.85 无法稳定匹配。
        # 使用 0.8 匹配变形后的表情。
        buttons = handler_assets.TEMPLATE_MANJUU.match_multi(image, similarity=0.8, name="INFO_MANJUU")
        return len(buttons)

    def wait_until_manjuu_disappear(self):
        """
        Wait until manjuu loading disappear.
        """
        while 1:
            self.device.screenshot()
            if not self.manjuu_count():
                break

    def handle_manjuu(self):
        """
        Handle manjuu loading.
        Returns:
            bool: If handled
        """
        count = self.manjuu_count()
        if count > 2:
            logger.info(f"Manjuu count: {count}, waiting for manjuu to disappear")
            self.wait_until_manjuu_disappear()
            return True
        return False
