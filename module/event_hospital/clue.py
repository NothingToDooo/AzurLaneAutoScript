from functools import reduce
from operator import itemgetter
from typing import TYPE_CHECKING

import cv2
import numpy as np

from module.base.button import Button
from module.base.utils import area_offset, color_similarity_2d, image_size, rgb2gray, xywh2xyxy
from module.event_hospital import assets as hospital_assets
from module.event_hospital.ui import HospitalUI
from module.logger import logger
from module.raid.assets import RAID_FLEET_PREPARATION
from module.ui.page import page_hospital
from module.ui.scroll import Scroll

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator

type Rect = tuple[int, int, int, int]
type WordRect = tuple[Rect, int]


def merge_two_rects(r1: Rect, r2: Rect) -> Rect:
    return (
        min(r1[0], r2[0]),
        min(r1[1], r2[1]),
        max(r1[2], r2[2]),
        max(r1[3], r2[3]),
    )


def merge_rows(list_word: Iterable[WordRect], merge: int) -> list[Rect]:
    list_word = sorted(list_word, key=itemgetter(1))

    list_row: list[Rect] = []
    current_row: list[Rect] = []
    current_center: int | None = None
    for rect, center_y in list_word:
        if not current_row:
            current_row.append(rect)
            current_center = center_y
        elif current_center is not None and abs(center_y - current_center) <= merge:
            current_row.append(rect)
        else:
            list_row.append(reduce(merge_two_rects, current_row))
            current_row = [rect]
            current_center = center_y

    if current_row:
        list_row.append(reduce(merge_two_rects, current_row))

    return list_row


class HospitalClue(HospitalUI):
    def get_clue_list(self) -> list[Button]:
        """按灰白文字遮罩合并行，返回侧边栏按钮列表。"""
        area = hospital_assets.CLUE_LIST.area
        image = self.image_crop(area, copy=False)

        gray = color_similarity_2d(image, color=(132, 134, 148))
        cv2.inRange(gray, 215, 255, dst=gray)
        white = color_similarity_2d(image, color=(255, 255, 255))
        cv2.inRange(white, 215, 255, dst=white)
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (200, 20))
        white_expanded = cv2.dilate(white, kernel)
        cv2.subtract(gray, white_expanded, dst=gray)
        cv2.bitwise_or(gray, white, dst=gray)
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
        cv2.dilate(gray, kernel, dst=gray)

        list_word: list[WordRect] = []
        contours, _ = cv2.findContours(gray, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        for cont in contours:
            rect = cv2.boundingRect(cv2.convexHull(cont).astype(np.float32))
            # 文字高度通常约为 16，低于 12 视为噪声。
            converted = xywh2xyxy(rect)
            rect = (int(converted[0]), int(converted[1]), int(converted[2]), int(converted[3]))
            if rect[3] - rect[1] < 12:
                continue
            center_y = (rect[1] + rect[3]) // 2
            list_word.append((rect, center_y))

        list_row = merge_rows(list_word, merge=5)
        list_row = [area_offset(r, offset=area[:2]) for r in list_row]
        return [Button(area=rect, color=(), button=rect, name=f"CLUE_LIST_{i}") for i, rect in enumerate(list_row)]

    def get_invest_button(self) -> Button | None:
        """返回当前截图中仍有剩余次数的调查按钮；未找到时返回 None。"""
        area = hospital_assets.INVEST_SEARCH.area
        image = self.image_crop(area, copy=False)
        image = rgb2gray(image)

        buttons = hospital_assets.TEMPLATE_INVEST.match_multi(image)
        buttons += hospital_assets.TEMPLATE_INVEST2.match_multi(image)
        buttons = sorted(buttons, key=lambda b: b.area[1])
        count = len(buttons)
        if count == 0:
            return None
        buttons = [b.move(area[:2]) for b in buttons]
        if count == 1:
            # 只有一个调查按钮时，搜索按钮下方。
            button = buttons[0]
            search = (area[0], button.button[3], area[2], area[3])
        else:
            # 多个调查按钮时，只搜索前两个按钮之间。
            button = buttons[0]
            second = buttons[1]
            search = (area[0], button.button[3], area[2], second.button[1])
        image = self.image_crop(search, copy=False)
        image = rgb2gray(image)

        # 截图太小时没有足够空间显示剩余次数。
        _x, y = image_size(image)
        if y < 50:
            return None

        if hospital_assets.TEMPLATE_REMAIN_CURRENT.match(image):
            return button
        if hospital_assets.TEMPLATE_REMAIN_TIMES.match(image):
            return button
        return None

    def clue_enter(self, *, skip_first_screenshot: bool = True) -> None:
        """从医院任意子页进入线索页。"""
        logger.info("Hospital clue enter")
        self.interval_clear(page_hospital.check_button)
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()
            if self.is_in_clue():
                break
            if self.handle_clue_exit():
                continue

    def clue_exit(self, *, skip_first_screenshot: bool = True) -> None:
        """从医院任意子页返回活动主页。"""
        logger.info("Hospital clue exit")
        self.interval_clear(hospital_assets.HOSIPITAL_CLUE_CHECK)
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()
            if self.ui_page_appear(page_hospital):
                break
            if self.handle_clue_exit():
                continue
            if self.appear_then_click(hospital_assets.HOSIPITAL_CLUE_CHECK, offset=(20, 20), interval=2):
                continue

    def invest_enter(self, *, skip_first_screenshot: bool = True) -> bool:
        """从线索页进入舰队准备页；没有可调查项目时返回 False。"""
        logger.info("Clue invest")
        self.interval_clear(hospital_assets.HOSIPITAL_CLUE_CHECK)
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()
            if self.appear(RAID_FLEET_PREPARATION, offset=(30, 30)):
                return True

            if self.is_in_clue(interval=2):
                invest = next(self.iter_invest(), None)
                if invest is None:
                    logger.info("No more invest")
                    return False
                logger.info(f"is_in_clue -> {invest}")
                self.device.click(invest)
                self.interval_reset(hospital_assets.HOSIPITAL_CLUE_CHECK, interval=2)
                continue
            if self.appear_then_click(hospital_assets.HOSPITAL_BATTLE_PREPARE, offset=(20, 20), interval=2):
                continue
            if self.handle_get_clue():
                continue
        return False

    def iter_invest(self) -> Iterator[Button]:
        """按当前页、顶部到下方依次产生调查按钮；无滚动条时只检查当前页。"""
        logger.hr("Iter invest")
        scroll = Scroll(hospital_assets.INVEST_SCROLL, color=(107, 97, 107), name="INVEST_SCROLL")
        # 没有滚动条时，只返回当前页的一个按钮。
        if not scroll.appear(main=self):
            logger.info("No scroll")
            button = self.get_invest_button()
            if button:
                yield button
            return

        button = self.get_invest_button()
        if button:
            yield button

        if not scroll.at_top(main=self):
            scroll.set_top(main=self)
            button = self.get_invest_button()
            if button:
                yield button
        while 1:
            if scroll.at_bottom(main=self):
                logger.info(f"{scroll.name} reached end")
                return
            scroll.next_page(main=self, page=0.5)
            button = self.get_invest_button()
            if button:
                yield button

    def is_aside_selected(self, button: Button) -> bool:
        area = button.area
        search = hospital_assets.CLUE_LIST.area
        # 有深色背景时搜索整行。
        area = (search[0], area[1], search[2], area[3])
        return self.image_color_count(area, color=(82, 85, 107), threshold=221, count=500)

    def is_aside_checked(self, button: Button) -> bool:
        area = button.area
        search = hospital_assets.CLUE_LIST.area
        # 检查是否有青色标记；日服文字会溢出，所以右边界固定为 308。
        area = (search[0], area[1], 308, area[3])
        return self.image_color_count(area, color=(74, 130, 148), threshold=221, count=20)

    def iter_aside(self) -> Iterator[Button]:
        """依次产生未完成的侧边栏按钮。"""
        list_button = self.get_clue_list()
        for button in list_button:
            if self.is_aside_checked(button):
                continue
            yield button

    def select_aside(self, *, skip_first_screenshot: bool = True) -> bool:
        """在线索页选择未完成侧边任务；全部完成时返回 False。"""
        logger.info("Select aside")
        aside = None
        self.interval_clear(hospital_assets.HOSIPITAL_CLUE_CHECK)
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()
            if aside is not None and self.is_aside_selected(aside):
                return True
            if self.is_in_clue(interval=2):
                aside = next(self.iter_aside(), None)
                if aside is None:
                    logger.info("No more aside")
                    return False
                logger.info(f"is_in_clue -> {aside}")
                self.device.click(aside)
                self.interval_reset(hospital_assets.HOSIPITAL_CLUE_CHECK, interval=2)
                continue
            if self.handle_clue_exit():
                continue
        return False
