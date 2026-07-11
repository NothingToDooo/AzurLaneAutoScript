import re
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, ClassVar, Literal, override

import cv2
import numpy as np

from module.base.button import Button, ButtonGrid
from module.base.filter import Filter
from module.base.timer import Timer
from module.base.utils import (
    color_similar,
    color_similarity_2d,
    crop,
    get_color,
    image_left_strip,
    image_size,
    resize,
    rgb2gray,
    rgb2hsv,
)
from module.combat.level import LevelOcr
from module.config.utils import get_server_next_update
from module.exception import ScriptError
from module.handler.assets import GET_MISSION, MISSION_POPUP_ACK, MISSION_POPUP_GO, POPUP_CANCEL, POPUP_CONFIRM
from module.logger import logger
from module.map.map_grids import SelectedGrids
from module.ocr.ocr import DigitCounter, Duration, Ocr
from module.retire.assets import DOCK_CHECK, DOCK_EMPTY, SHIP_CONFIRM
from module.retire.dock import CARD_GRIDS, CARD_LEVEL_GRIDS, Dock
from module.tactical.assets import (
    ADD_NEW_STUDENT,
    BOOK_EMPTY_POPUP,
    OCR_SKILL_EXP,
    RAPID_TRAINING,
    REWARD_2,
    SKILL_CONFIRM,
    TACTICAL_CLASS_CANCEL,
    TACTICAL_CLASS_START,
    TACTICAL_META,
)
from module.ui.assets import BACK_ARROW, REWARD_CHECK, REWARD_GOTO_TACTICAL, TACTICAL_CHECK
from module.ui.page import page_reward
from module.ui_white.assets import REWARD_2_WHITE, REWARD_GOTO_TACTICAL_WHITE

if TYPE_CHECKING:
    from collections.abc import Callable

    from module.base.type_alias import ImageArray
    from module.config.config import AzurLaneConfig
    from module.device.device import Device

type TacticalReceiveStep = Literal["continue", "return_true"]
type TacticalHandler = Callable[[], bool]

SKILL_GRIDS = ButtonGrid(origin=(315, 140), delta=(621, 132), button_shape=(621, 119), grid_shape=(1, 3), name="SKILL")
SKILL_LEVEL_GRIDS = SKILL_GRIDS.crop(area=(406, 98, 618, 116), name="EXP")


@dataclass(slots=True)
class _TacticalReceiveContext:
    received: bool = False
    study_finished: bool = False
    book_empty: bool = False


class ExpOnBookSelect(DigitCounter):
    @override
    def pre_process(self, image: ImageArray) -> ImageArray:
        # 原图类似 NEXT:1900+500/5800；先定位绿色加成经验，再从白色经验文本中抹除。
        hsv = rgb2hsv(image)
        h = (60, 180)
        s = (50, 100)
        v = (50, 100)
        lower = (h[0], s[0], v[0])
        upper = (h[1], s[1], v[1])
        green = np.mean(cv2.inRange(hsv, lower, upper), axis=0)
        r, g, b = cv2.split(image)
        max_channel = cv2.max(cv2.max(r, g), b)
        matched = np.where(green > 0.5)[0]
        if len(matched):
            max_channel[:, matched[0] - 8 : matched[-1] + 2] = 0

        processed = np.asarray(255 - max_channel, dtype=np.uint8)

        # 去掉“下次升级”前缀，只保留 current/total。
        return image_left_strip(processed, threshold=105, length=42)

    @staticmethod
    def normalize_text(result: str) -> str:
        result = DigitCounter.normalize_text(result)

        if result.endswith("580"):
            new = result[:-3] + "5800"
            logger.info(f"ExpOnBookSelect result {result} is revised to {new}")
            result = new
        if "/" not in result:
            for exp in [5800, 4400, 3200, 2200, 1400, 800, 400, 200, 100]:
                res = re.match(rf"^(\d+){exp}$", result)
                if res:
                    # OCR 可能漏掉斜杠，例如 10005800 应为 1000/5800。
                    new = f"{res.group(1)}/{exp}"
                    logger.info(f"ExpOnBookSelect result {result} is revised to {new}")
                    result = new
                    break

        return result


class ExpOnSkillSelect(Ocr):
    @override
    def pre_process(self, image: ImageArray) -> ImageArray:
        r, g, b = cv2.split(image)
        max_channel = cv2.max(cv2.max(r, g), b)

        processed = np.asarray(255 - max_channel, dtype=np.uint8)

        return image_left_strip(processed, threshold=105, length=42)


SKILL_EXP = ExpOnBookSelect(buttons=OCR_SKILL_EXP)
BOOKS_GRID = ButtonGrid(origin=(213, 292), delta=(147, 117), button_shape=(98, 98), grid_shape=(6, 2))
NO_TACTICAL_BOOK_FOUND_MESSAGE = "No book found, after 15 attempts."


class Book:
    # 教材类型依次为攻击、防御、支援，对应红、蓝、黄。
    color_genre: ClassVar[dict[int, tuple[int, int, int]]] = {
        1: (214, 69, 74),
        2: (115, 178, 255),
        3: (247, 190, 99),
    }
    genre_name: ClassVar[dict[int, str]] = {
        1: "Red",
        2: "Blue",
        3: "Yellow",
    }
    # 教材阶级依次对应蓝、紫、金、彩边框。
    color_tier: ClassVar[dict[int, tuple[int, int, int]]] = {
        1: (104, 181, 238),
        2: (151, 129, 203),
        3: (235, 208, 120),
        4: (225, 181, 212),
    }
    exp_tier: ClassVar[dict[int, int]] = {
        0: 0,
        1: 100,
        2: 300,
        3: 800,
        4: 1500,
    }

    def __init__(self, image: ImageArray, button: Button) -> None:
        image = crop(image, button.area, copy=False)
        # 2025-08-14 后图标为 64×64，放大到旧版 98×98 坐标系，否则颜色采样为 0。
        if image_size(image) < (98, 98):
            image = resize(image, (98, 98))
        self.button = button

        # 40 张截图中阈值 50～70 均通过；超过 75 会把彩色误识别为紫色。
        self.genre = 0
        color = get_color(image, (65, 35, 72, 42))
        for key, value in self.color_genre.items():
            if color_similar(color1=color, color2=value, threshold=50):
                self.genre = key

        self.tier = 0
        color = get_color(image, (83, 61, 92, 70))
        for key, value in self.color_tier.items():
            if color_similar(color1=color, color2=value, threshold=50):
                self.tier = key

        color = color_similarity_2d(crop(image, (15, 0, 97, 13), copy=False), color=(148, 251, 99))
        self.exp = bool(np.sum(color > 221) > 50)

        self.valid = bool(self.genre and self.tier)
        self.genre_str = self.genre_name.get(self.genre, "unknown")
        self.tier_str = f"T{self.tier}" if self.tier else "Tn"
        self.same_str = "same" if self.exp else "unknown"

        factor = 1 if not self.exp else 1.5 if self.tier < 4 else 2
        self.exp_value = int(self.exp_tier[self.tier] * factor)

    def check_selected(self, image: ImageArray) -> bool:
        area = self.button.area
        check_area = (area[0], area[3] + 2, area[2], area[3] + 4)
        im = rgb2gray(crop(image, check_area, copy=False))
        return bool(np.mean(im) > 127)

    def __str__(self) -> str:
        text = f"{self.genre_str}_{self.tier_str}"
        if self.exp:
            text += "_Exp"
        return text


BOOK_FILTER: Filter[Book] = Filter(
    regex=re.compile(r"(same)?(red|blue|yellow)?-?(t[1234])?"),
    attr=("same_str", "genre_str", "tier_str"),
    preset=("first",),
)


class RewardTacticalClass(Dock):
    books: SelectedGrids[Book]
    dock_select_index = 0

    def __init__(
        self,
        config: AzurLaneConfig | str,
        device: Device | str | None = None,
        task: str | None = None,
    ) -> None:
        self.tactical_finish: list[datetime | str] = []
        super().__init__(config, device, task)

    def _tactical_books_get(self, *, skip_first_screenshot: bool = True) -> SelectedGrids[Book] | Literal[False]:
        """在教材选择页等待教材稳定；最多检测 15 次，持续加载时抛出 ScriptError。"""
        prev = SelectedGrids([])
        for n in range(1, 16):
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            # 庆典委托获得舰船时可能残留 info_bar。
            self.handle_info_bar()
            if not self.appear(TACTICAL_CLASS_START, offset=(30, 30)):
                logger.info("Not in TACTICAL_CLASS_START anymore, exit")
                return False

            books = SelectedGrids([Book(self.device.image, button) for button in BOOKS_GRID.buttons]).select(valid=True)
            self.books = books
            logger.attr("Book_count", books.count)
            logger.attr("Books", str(books))

            if books and books.count == prev.count:
                return books
            prev = books
            if n % 3 == 0:
                self.device.sleep(3)
            continue

        logger.warning("No book found.")
        raise ScriptError(NO_TACTICAL_BOOK_FOUND_MESSAGE)

    def _tactical_book_select(self, book: Book, *, skip_first_screenshot: bool = True) -> None:
        logger.info(f"Book select {book}")
        interval = Timer(2, count=6)
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if book.check_selected(self.device.image):
                break

            if interval.reached():
                self.device.click(book.button)
                interval.reset()
                continue

    def _tactical_books_filter_exp(self) -> None:
        """按技能进度过滤会造成经验浪费的教材。"""
        # 首本教材经验已计入界面，因此 current 和 remain 并非选择前的值。
        current, remain, total = SKILL_EXP.ocr_single(self.device.image)

        # 仅在即将升到 10 级时控制溢出。
        if total == 5800:
            logger.info(
                "About to reach level 10; will remove "
                "detected books based on actual "
                f"progress: {current}/{total}; {remain}"
            )

            def filter_exp_func(book: Book) -> bool:
                if book.exp_value == 100:
                    return True

                overflow = 0
                if self.config.ControlExpOverflow_Enable:
                    overflow = getattr(self.config, f"ControlExpOverflow_T{book.tier}Allow")

                return current + book.exp_value <= total + overflow

            before = self.books.count
            self.books = SelectedGrids([book for book in self.books if filter_exp_func(book)])
            logger.attr("Filtered", before - self.books.count)
            logger.attr("Books", str(self.books))

    def _tactical_books_choose(self) -> bool:
        """按配置选教材；可能留在选择页、战术页或训练动画页。"""
        logger.hr("Tactical books choose", level=2)
        if not self._tactical_books_get():
            return False

        self.device.click_record_clear()
        # 慢速设备上默认选中项可能变化，先重新聚焦第一本。
        first = self.books[0]
        self._tactical_book_select(first)

        self._tactical_books_filter_exp()

        BOOK_FILTER.load(self.config.Tactical_TacticalFilter)
        books = BOOK_FILTER.apply(self.books.grids)
        logger.attr("Book_sort", " > ".join([str(book) for book in books]))

        if len(books):
            book = books[0]
            if isinstance(book, Book):
                self._tactical_book_select(book)
            else:
                logger.info("Choose first book")
                self._tactical_book_select(first)
            logger.info(f"_tactical_books_choose -> {TACTICAL_CLASS_START}")
            self.device.click(TACTICAL_CLASS_START)
        else:
            logger.info("Cancel tactical")
            logger.info(f"_tactical_books_choose -> {TACTICAL_CLASS_CANCEL}")
            self.device.click(TACTICAL_CLASS_CANCEL)
        return True

    def handle_rapid_training(self) -> bool:
        slot = self.config.Tactical_RapidTrainingSlot
        if slot == "slot_1":
            slot = 0
        elif slot == "slot_2":
            slot = 1
        elif slot == "slot_3":
            slot = 2
        elif slot == "slot_4":
            slot = 3
        else:
            return False

        offset = (slot * 220 - 20, -20, slot * 220 + 20, 20)
        if self.appear(RAPID_TRAINING, offset=offset, interval=1):
            self.device.click(RAPID_TRAINING)
            # 清除间隔以立即进入教材选择。
            self.interval_clear(TACTICAL_CLASS_START, interval=2)
            return True

        return False

    def _tactical_get_finish(self) -> list[datetime | str]:
        """OCR 各训练槽剩余时间并返回绝对结束时间。"""
        logger.hr("Tactical get finish")
        grids = ButtonGrid(
            origin=(421, 596), delta=(223, 0), button_shape=(139, 27), grid_shape=(4, 1), name="TACTICAL_REMAIN"
        )

        is_running = [self.image_color_count(button, color=(148, 255, 99), count=50) for button in grids.buttons]
        logger.info(f"Tactical status: {['running' if s else 'empty' for s in is_running]}")

        buttons = [b for b, s in zip(grids.buttons, is_running, strict=True) if s]
        ocr = Duration(buttons, letter=(148, 255, 99), name="TACTICAL_REMAIN")
        images = [self.image_crop(button, copy=False) for button in buttons]
        remains = ocr.ocr_many(images)

        now = datetime.now()
        self.tactical_finish = [(now + remain).replace(microsecond=0) for remain in remains if remain.total_seconds()]
        logger.info(f"Tactical finish: {[str(f) for f in self.tactical_finish]}")
        return self.tactical_finish

    def _handle_tactical_new_student(self, context: _TacticalReceiveContext) -> bool:
        if context.study_finished:
            return False
        if not self.appear(TACTICAL_CHECK, offset=(20, 20)):
            return False
        if not self.appear_then_click(ADD_NEW_STUDENT, offset=(800, 20), interval=1):
            return False
        self.interval_reset([TACTICAL_CHECK, RAPID_TRAINING])
        self.interval_clear([POPUP_CONFIRM, POPUP_CANCEL, GET_MISSION, DOCK_CHECK, SKILL_CONFIRM])
        return True

    def _handle_tactical_rapid_training(self) -> bool:
        if not self.handle_rapid_training():
            return False
        self.interval_reset(TACTICAL_CHECK)
        self.interval_clear([POPUP_CONFIRM, POPUP_CANCEL, GET_MISSION, DOCK_CHECK, SKILL_CONFIRM])
        return True

    def _handle_tactical_finish_check(self, context: _TacticalReceiveContext, empty_confirm: Timer) -> bool:
        if self.appear(TACTICAL_CLASS_START, offset=(20, 20)) or not self.appear(
            TACTICAL_CHECK, offset=(20, 20), interval=2
        ):
            empty_confirm.reset()
            return False

        self.interval_clear([POPUP_CONFIRM, POPUP_CANCEL, GET_MISSION])
        if context.book_empty:
            self.device.click(BACK_ARROW)
            self.interval_reset(TACTICAL_CHECK)
            return True
        if self._tactical_get_finish():
            self.device.click(BACK_ARROW)
            self.interval_reset(TACTICAL_CHECK)
            empty_confirm.reset()
            context.received = True
            return True
        self.interval_clear(TACTICAL_CHECK)
        if empty_confirm.reached():
            self.device.click(BACK_ARROW)
            empty_confirm.reset()
            context.received = True
            return True
        return False

    def _handle_tactical_reward_navigation(self) -> bool:
        if self.appear_then_click(REWARD_2, offset=(20, 20), interval=3):
            self.interval_reset(REWARD_2_WHITE)
            return True
        if self.appear_then_click(REWARD_2_WHITE, offset=(20, 20), interval=3):
            self.interval_reset(REWARD_2)
            return True
        if self.appear_then_click(REWARD_GOTO_TACTICAL, offset=(20, 20), interval=3):
            self.interval_reset(REWARD_GOTO_TACTICAL_WHITE)
            return True
        if self.appear_then_click(REWARD_GOTO_TACTICAL_WHITE, offset=(20, 20), interval=3):
            self.interval_reset(REWARD_GOTO_TACTICAL)
            return True
        return self.ui_main_appear_then_click(page_reward, interval=3)

    def _handle_tactical_common_popups(self) -> bool:
        if self.handle_popup_confirm("TACTICAL"):
            self.interval_reset([BOOK_EMPTY_POPUP])
            return True
        if self.handle_urgent_commission():
            # 技能满级提示只有中间一个按钮。
            return True
        if self.ui_page_main_popups():
            self.interval_reset([BOOK_EMPTY_POPUP])
            return True
        if self.appear(MISSION_POPUP_GO, offset=self._popup_offset, interval=2):
            self.device.click(MISSION_POPUP_ACK)
            return True
        return False

    def _handle_tactical_books(self, context: _TacticalReceiveContext) -> bool:
        if not self.appear(TACTICAL_CLASS_START, offset=(30, 30), interval=2):
            return False
        if self._tactical_books_choose():
            self.dock_select_index = 0
            self.interval_reset([TACTICAL_CLASS_START, BOOK_EMPTY_POPUP])
            self.interval_clear([POPUP_CONFIRM, POPUP_CANCEL, GET_MISSION])
        else:
            context.study_finished = True
        return True

    def _handle_tactical_dock(self, context: _TacticalReceiveContext) -> bool:
        if not self.appear(DOCK_CHECK, offset=(20, 20), interval=3):
            return False
        if self.dock_selected():
            # 从主页点舰船进入船坞时会预选该船，需返回清除状态后重进。
            logger.info("Having pre-selected ship in dock, re-enter")
            self.device.click(BACK_ARROW)
            self.interval_reset([BOOK_EMPTY_POPUP, DOCK_CHECK], interval=3)
            return True
        if self.config.AddNewStudent_Enable:
            if not self.select_suitable_ship():
                context.study_finished = True
                self.device.click(BACK_ARROW)
        else:
            logger.info("Not going to learn skill but in dock, close it")
            context.study_finished = True
            self.device.click(BACK_ARROW)
        self.interval_timer.pop(DOCK_CHECK.name, None)
        self.interval_reset([BOOK_EMPTY_POPUP, DOCK_CHECK], interval=3)
        return True

    def _handle_tactical_skill_confirm(self, context: _TacticalReceiveContext) -> bool:
        if not self.appear(SKILL_CONFIRM, offset=(20, 20), interval=3):
            return False
        if self.config.AddNewStudent_Enable:
            if not self._tactical_skill_choose():
                context.study_finished = True
                self.device.click(BACK_ARROW)
        else:
            logger.info("Not going to learn skill but having SKILL_CONFIRM, close it")
            context.study_finished = True
            self.device.click(BACK_ARROW)
        self.interval_reset([BOOK_EMPTY_POPUP, SKILL_CONFIRM], interval=3)
        return True

    def _handle_tactical_meta_skill(self) -> bool:
        if not self.appear(TACTICAL_META, offset=(200, 20), interval=3):
            return False
        logger.info("META skill found, exit")
        self.device.click(BACK_ARROW)
        # META 舰船不适用战术教室，退出后改选下一艘。
        self.dock_select_index += 1
        self.interval_reset([TACTICAL_CHECK, BOOK_EMPTY_POPUP])
        self.interval_clear(ADD_NEW_STUDENT)
        return True

    def _handle_tactical_book_empty(self, context: _TacticalReceiveContext) -> bool:
        if not self.appear(BOOK_EMPTY_POPUP, offset=(20, 20), interval=3):
            return False
        self.device.click(BOOK_EMPTY_POPUP)
        context.study_finished = True
        context.received = True
        context.book_empty = True
        return True

    def _tactical_receive_before_tips_handlers(
        self,
        context: _TacticalReceiveContext,
        empty_confirm: Timer,
    ) -> tuple[TacticalHandler, ...]:
        return (
            lambda: self._handle_tactical_new_student(context),
            self._handle_tactical_rapid_training,
            lambda: self._handle_tactical_finish_check(context, empty_confirm),
            self._handle_tactical_reward_navigation,
            self._handle_tactical_common_popups,
            lambda: self._handle_tactical_books(context),
        )

    def _tactical_receive_after_tips_handlers(
        self,
        context: _TacticalReceiveContext,
    ) -> tuple[TacticalHandler, ...]:
        return (
            lambda: self._handle_tactical_dock(context),
            lambda: self._handle_tactical_skill_confirm(context),
            self._handle_tactical_meta_skill,
            lambda: self._handle_tactical_book_empty(context),
        )

    def _handle_tactical_receive_step(
        self,
        context: _TacticalReceiveContext,
        empty_confirm: Timer,
    ) -> TacticalReceiveStep | None:
        for handler in self._tactical_receive_before_tips_handlers(context, empty_confirm):
            if handler():
                return "continue"
        if self.handle_game_tips():
            return "return_true"
        for handler in self._tactical_receive_after_tips_handlers(context):
            if handler():
                return "continue"
        return None

    def tactical_class_receive(self, *, skip_first_screenshot: bool = True) -> bool:
        """从奖励页领取战术奖励并补充教材，最后回到奖励页。"""
        logger.hr("Tactical class receive", level=1)
        context = _TacticalReceiveContext(study_finished=not self.config.AddNewStudent_Enable)
        # 训练卡片加载较慢，连续确认后才判定空槽。
        empty_confirm = Timer(0.6, count=2).start()
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if context.received and self.appear(REWARD_CHECK, offset=(20, 20)):
                break

            step = self._handle_tactical_receive_step(context, empty_confirm)
            if step == "return_true":
                return True
            if step == "continue":
                continue

        if context.book_empty:
            logger.warning("Tactical books empty, delay to tomorrow")
            self.tactical_finish = [get_server_next_update(self.config.Scheduler_ServerUpdate)]
            logger.info(f"Tactical finish: {self.tactical_finish}")
        return True

    def _tactical_skill_select(self, selected_skill: Button, *, skip_first_screenshot: bool = True) -> None:
        logger.info("Tactical skill select")
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if not self.check_skill_selected(selected_skill, self.device.image):
                self.device.click(selected_skill)
                self.device.sleep((0.3, 0.5))
            else:
                break

    @staticmethod
    def check_skill_selected(button: Button, image: ImageArray) -> bool:
        area = button.area
        check_area = (area[0], area[3] + 2, area[2], area[3] + 4)
        im = rgb2gray(crop(image, check_area, copy=False))
        return bool(np.mean(im) > 127)

    def _tactical_skill_choose(self) -> bool:
        """在技能确认页选择未满级技能；可能回到教材选择页或战术页。"""
        logger.hr("Tactical skill choose")
        selected_skill = self.find_not_full_level_skill()

        if selected_skill is None:
            logger.info("No available skill to learn")
            return False

        self._tactical_skill_select(selected_skill)
        self.device.click(SKILL_CONFIRM)

        return True

    def select_suitable_ship(self) -> bool:
        logger.hr("Select suitable ship")

        self.dock_favourite_set(enable=self.config.AddNewStudent_Favorite, wait_loading=False)

        # 重置筛选时排除 META 舰船。
        self.dock_filter_set(
            faction=[
                value
                for setting, value in self.dock_filter.settings
                if setting == "faction" and isinstance(value, str) and value not in {"all", "meta", "not_available"}
            ]
        )

        if self.appear(DOCK_EMPTY, offset=(30, 30)):
            logger.info("Dock is empty or favorite ships is empty")
            return False

        # 舰船卡片加载较慢，等待等级 OCR 区域从零散亮块变为整行稳定亮块。
        level_ocr = LevelOcr(CARD_LEVEL_GRIDS.buttons, name="DOCK_LEVEL_OCR", threshold=64)
        list_level: list[int] = []
        for _ in self.loop(timeout=1):
            images = [self.image_crop(button, copy=False) for button in CARD_LEVEL_GRIDS.buttons]
            list_level = level_ocr.ocr_many(images)
            first_ship = next((i for i, x in enumerate(list_level) if x > 0), len(list_level))
            first_empty = next((i for i, x in enumerate(list_level) if x == 0), len(list_level))
            if first_empty >= first_ship:
                break
        else:
            logger.warning("Wait ship cards timeout")

        try:
            min_level = int(self.config.AddNewStudent_MinLevel)
            min_level = max(min_level, 1)
        except (ValueError, TypeError) as e:
            logger.warning(f"Invalid AddNewStudent_MinLevel: {self.config.AddNewStudent_MinLevel}, {e}")
            min_level = 1
        logger.attr("AddNewStudent_MinLevel", min_level)

        should_select_button = None
        for button, level in list(zip(CARD_GRIDS.buttons, list_level, strict=True))[self.dock_select_index :]:
            if level >= min_level:
                should_select_button = button
                break

        if should_select_button is None:
            logger.info(f"No ships with level >= {min_level} in dock")
            return False

        self.dock_select_one(should_select_button, skip_first_screenshot=True)
        # 如果刚从 META 技能选择中退出，需要清理间隔计时。
        self.interval_clear(SHIP_CONFIRM)

        # 不再使用 TACTICAL_SKILL_LIST，因为英文服普通技能列表用 "Select skills"，
        # META 技能列表用 "Choose skills"。
        def check_button() -> bool:
            if self.appear(SKILL_CONFIRM, offset=(30, 30)):
                return True
            return bool(self.appear(TACTICAL_META, offset=(200, 30)))

        self.dock_select_confirm(check_button=check_button)

        return True

    def find_not_full_level_skill(self, *, skip_first_screenshot: bool = True) -> Button | None:
        """在技能确认页检查最多三个技能，返回首个未满级技能按钮。"""
        if not skip_first_screenshot:
            self.device.screenshot()

        skill_level_ocr = ExpOnSkillSelect(buttons=SKILL_LEVEL_GRIDS.buttons, lang="cnocr", name="SKILL_LEVEL")
        images = [self.image_crop(button, copy=False) for button in SKILL_LEVEL_GRIDS.buttons]
        skill_level_list = skill_level_ocr.ocr_many(images)
        for skill_button, skill_level in list(zip(SKILL_GRIDS.buttons, skill_level_list, strict=True)):
            level = skill_level.upper().replace(" ", "")
            # 空技能槽。
            # 可能是所有收藏舰船的技能都已满级。
            # '———l', '—l'
            if not level:
                continue
            if re.search(r"[—\-一]{2,}", level):
                continue
            if re.search(r"[—一]+", level):
                continue
            # OCR 区域偶尔下移，只用 MA 判断 MAX；经验文本可能识别成 /1D] 或 /14[]]。
            if "MA" not in level:
                logger.attr("LEVEL", "EMPTY" if len(level) == 0 else level)
                return skill_button

        return None

    def run(self) -> None:
        """从任意页面执行战术教室，结束于战术页。"""
        self.ui_ensure(page_reward)

        self.tactical_class_receive()

        if self.tactical_finish:
            self.config.task_delay(target=self.tactical_finish)
        else:
            logger.info("No tactical running")
            self.config.task_delay(success=False)
