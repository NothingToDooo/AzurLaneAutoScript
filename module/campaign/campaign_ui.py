from contextlib import suppress
from typing import TYPE_CHECKING, override

from module.base.button import Button
from module.base.timer import Timer
from module.base.utils import area_offset
from module.campaign import assets as campaign_assets
from module.campaign.campaign_ocr import CampaignOcr
from module.campaign.event_navigation import EventCampaignNavigation
from module.exception import CampaignEnd, CampaignNameError, CampaignSelectionError
from module.logger import logger
from module.map.assets import WITHDRAW
from module.map.map_operation import MapOperation
from module.ui.assets import CAMPAIGN_CHECK
from module.ui.switch import Switch

if TYPE_CHECKING:
    from collections.abc import Mapping

    from module.base.base import ModuleBase

CAMPAIGN_NAME_ERROR_MESSAGE = "Campaign name error"


class ModeSwitch(Switch):
    @override
    def handle_additional(self, _main: ModuleBase) -> bool:
        if _main.appear(WITHDRAW, offset=(30, 30)):
            logger.warning("ModeSwitch: WITHDRAW appears")
            raise CampaignNameError
        return False


MODE_SWITCH_1 = ModeSwitch("Mode_switch_1", offset=(30, 10))
MODE_SWITCH_1.add_state("normal", campaign_assets.SWITCH_1_NORMAL)
MODE_SWITCH_1.add_state("hard", campaign_assets.SWITCH_1_HARD)
MODE_SWITCH_2 = ModeSwitch("Mode_switch_2", offset=(30, 10))
MODE_SWITCH_2.add_state("hard", campaign_assets.SWITCH_2_HARD)
MODE_SWITCH_2.add_state("ex", campaign_assets.SWITCH_2_EX)

# 活动模式开关从 20240725 到 20241219 期间变化过。
# 看起来从 20241219 开始稳定，所以使用 20241219 日期命名。
MODE_SWITCH_20241219 = ModeSwitch("Mode_switch_20241219", is_selector=True, offset=(30, 30))
MODE_SWITCH_20241219.add_state("combat", campaign_assets.SWITCH_20241219_COMBAT)
MODE_SWITCH_20241219.add_state("story", campaign_assets.SWITCH_20241219_STORY)
ASIDE_SWITCH_20241219 = ModeSwitch("Aside_switch_20241219", is_selector=True, offset=(20, 20))
ASIDE_SWITCH_20241219.add_state("part1", campaign_assets.CHAPTER_20241219_PART1)
ASIDE_SWITCH_20241219.add_state("part2", campaign_assets.CHAPTER_20241219_PART2)
ASIDE_SWITCH_20241219.add_state("sp", campaign_assets.CHAPTER_20241219_SP)
ASIDE_SWITCH_20241219.add_state("ex", campaign_assets.CHAPTER_20241219_EX)
# 缩短 unknown_timer，加快异常状态处理。
# 游戏 bug 可能导致关卡撤退或结束后侧边指示器消失。
ASIDE_SWITCH_20241219.set_unknown_timer = Timer(0.6, count=2)

_CHAPTER_SWITCH_20241219_ASIDE = {
    "a": "part1",
    "c": "part1",
    "t": "part1",
    "b": "part2",
    "d": "part2",
    "ttl": "part2",
    "ex_sp": "sp",
    "ex_ex": "ex",
}
_CHAPTER_SWITCH_20241219_SP_ASIDE = {
    "sp": "part2",
    "t": "part2",
    "ht": "part2",
    "ex_sp": "sp",
}
_CHAPTER_SWITCH_20241219_SPEX_ASIDE = {
    **_CHAPTER_SWITCH_20241219_SP_ASIDE,
    "ex_ex": "ex",
}


def is_digit_chapter(chapter: str | int) -> bool:
    if isinstance(chapter, int):
        return True
    try:
        return chapter[0].isdigit()
    except IndexError:
        return False


class CampaignUI(MapOperation, EventCampaignNavigation, CampaignOcr):
    ENTRANCE = Button(area=(), color=(), button=(), name="default_button")
    stage_entrance: dict[str, Button]

    def campaign_ensure_chapter(self, chapter: str | int, *, skip_first_screenshot: bool = True) -> None:
        """chapter 接受数字章节或 d、sp 等活动章节名。"""
        index = self.campaign_get_chapter_index(chapter)
        isdigit = is_digit_chapter(chapter)

        # 复用 ui_ensure_index 的索引切换逻辑。
        logger.hr("UI ensure index")
        retry = Timer(1, count=2)
        error_confirm = Timer(0.2, count=0)
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if self.handle_chapter_additional():
                continue

            current = self.get_chapter_index()
            current_isdigit = is_digit_chapter(self.campaign_chapter)

            logger.attr("Index", current)
            diff = index - current
            if diff == 0:
                break

            # 查找 D3 时可能 OCR 到 3-7。
            if isdigit != current_isdigit:
                continue

            # 动画较慢时 14-4 可能被 OCR 成 4-1，需要先确认。
            if index >= 11 and index % 10 == current:
                error_confirm.start()
                if not error_confirm.reached():
                    continue
            else:
                error_confirm.reset()

            # 切换章节。
            if retry.reached():
                button = campaign_assets.CHAPTER_NEXT if diff > 0 else campaign_assets.CHAPTER_PREV
                self.device.multi_click(button, n=abs(diff), interval=(0.2, 0.3))
                retry.reset()

    @staticmethod
    def handle_chapter_additional() -> bool:
        """子类扩展钩子；处理后返回 True，默认不处理。"""
        return False

    def campaign_ensure_mode(self, mode: str = "normal") -> None:
        """mode 接受 normal、hard 或 ex。"""
        if mode == "hard":
            self.config.apply_runtime_overlay(Campaign_Mode="hard")

        switch_2 = MODE_SWITCH_2.get(main=self)

        if switch_2 == "unknown":
            if mode == "ex":
                logger.warning("Trying to goto EX, but no EX mode switch")
            elif mode == "normal":
                MODE_SWITCH_1.set("hard", main=self)
            elif mode == "hard":
                MODE_SWITCH_1.set("normal", main=self)
            else:
                logger.warning(f"Unknown campaign mode: {mode}")
        elif mode == "ex":
            MODE_SWITCH_2.set("hard", main=self)
        elif mode == "normal":
            MODE_SWITCH_2.set("ex", main=self)
            MODE_SWITCH_1.set("hard", main=self)
        elif mode == "hard":
            MODE_SWITCH_2.set("ex", main=self)
            MODE_SWITCH_1.set("normal", main=self)
        else:
            logger.warning(f"Unknown campaign mode: {mode}")

    def campaign_ensure_mode_20241219(self, mode: str = "combat") -> None:
        """mode 接受 combat 或 story。"""
        if mode in ["normal", "hard", "ex", "combat"]:
            MODE_SWITCH_20241219.set("combat", main=self)
        elif mode == "story":
            MODE_SWITCH_20241219.set("story", main=self)
        else:
            logger.warning(f"Unknown campaign mode: {mode}")

    def campaign_ensure_aside_20241219(self, chapter: str) -> None:
        """chapter 接受 part1、part2、sp 或 ex。"""
        if chapter in ["part1", "a", "c", "t"]:
            ASIDE_SWITCH_20241219.set("part1", main=self)
        elif chapter in ["part2", "b", "d"]:
            ASIDE_SWITCH_20241219.set("part2", main=self)
        elif chapter in ["sp", "ex_sp"]:
            ASIDE_SWITCH_20241219.set("sp", main=self)
        elif chapter in ["ex", "ex_ex"]:
            ASIDE_SWITCH_20241219.set("ex", main=self)
        else:
            logger.warning(f"Unknown campaign aside: {chapter}")

    @staticmethod
    def campaign_get_mode_names(name: str) -> list[str]:
        """返回普通/困难关卡名对，例如 t1 → [t1, ht1]、a1 → [a1, c1]。"""
        if name.startswith("t"):
            return [f"t{name[1:]}", f"ht{name[1:]}"]
        if name.startswith("ht"):
            return [f"t{name[2:]}", f"ht{name[2:]}"]
        if name.startswith(("a", "c")):
            return [f"a{name[1:]}", f"c{name[1:]}"]
        if name.startswith(("b", "d")):
            return [f"b{name[1:]}", f"d{name[1:]}"]
        return [name]

    def _campaign_name_is_hard(self, name: str) -> bool:
        mode_names = self.campaign_get_mode_names(name)
        return len(mode_names) == 2 and mode_names[1] == name

    def campaign_get_entrance(self, name: str) -> Button:
        """name 接受 7-2、d3 或 sp3 等关卡名。"""
        entrance_name = name
        stage_entrance = self.stage_entrance
        if self.config.MAP_HAS_MODE_SWITCH:
            for mode_name in self.campaign_get_mode_names(name):
                if mode_name in stage_entrance:
                    name = mode_name

        if name not in stage_entrance:
            logger.warning(f"Stage not found: {name}")
            raise CampaignNameError

        entrance = stage_entrance[name]
        entrance.name = entrance_name
        return entrance

    def campaign_set_chapter_main(self, chapter: str, mode: str = "normal") -> bool:
        if chapter.isdigit():
            self.ui_goto_campaign()
            self.campaign_ensure_mode("normal")
            self.campaign_ensure_chapter(chapter)
            if mode == "hard":
                self.campaign_ensure_mode("hard")
                # info_bar 显示：该图的困难模式暂未开放。
                # EN 服还有一个游戏 bug，HM12 显示未开放但实际可进入。
                self.handle_info_bar()
                self.campaign_ensure_chapter(chapter)
            return True
        return False

    def campaign_set_chapter_event(self, chapter: str, mode: str = "normal") -> bool:
        del mode
        if chapter in ["a", "b", "c", "d", "ex_sp", "as", "bs", "cs", "ds", "t", "ts", "tss", "ht", "hts"]:
            self.ui_goto_event()
            if chapter in ["a", "b", "as", "bs", "t", "ts", "tss"]:
                self.campaign_ensure_mode("normal")
            elif chapter in ["c", "d", "cs", "ds", "ht", "hts"]:
                self.campaign_ensure_mode("hard")
            elif chapter == "ex_sp":
                self.campaign_ensure_mode("ex")
            self.campaign_ensure_chapter(chapter)
            return True
        return False

    def campaign_set_chapter_sp(self, chapter: str, mode: str = "normal") -> bool:
        del mode
        if chapter == "sp":
            self.ui_goto_sp()
            self.campaign_ensure_chapter(chapter)
            return True
        return False

    def _set_20241219_hard_mode(self, chapter: str, stage: str) -> None:
        if self._campaign_name_is_hard(f"{chapter}{stage}"):
            self.config.apply_runtime_overlay(Campaign_Mode="hard")

    def _campaign_set_chapter_20241219_aside(
        self,
        chapter: str,
        aside_by_chapter: Mapping[str, str],
    ) -> bool:
        aside = aside_by_chapter.get(chapter)
        if aside is None:
            return False

        self.ui_goto_event()
        self.campaign_ensure_mode_20241219("combat")
        self.campaign_ensure_aside_20241219(aside)
        self.campaign_ensure_chapter(chapter)
        return True

    def campaign_set_chapter_20241219(self, chapter: str, stage: str, mode: str = "combat") -> bool:
        if self.config.MAP_CHAPTER_SWITCH_20241219:
            self._set_20241219_hard_mode(chapter, stage)
            if mode == "story":
                self.campaign_ensure_mode_20241219("story")
                return True
            if self._campaign_set_chapter_20241219_aside(chapter, _CHAPTER_SWITCH_20241219_ASIDE):
                return True
        if self.config.MAP_CHAPTER_SWITCH_20241219_SP:
            self._set_20241219_hard_mode(chapter, stage)
            if self._campaign_set_chapter_20241219_aside(chapter, _CHAPTER_SWITCH_20241219_SP_ASIDE):
                return True
        if self.config.MAP_CHAPTER_SWITCH_20241219_SPEX:
            self._set_20241219_hard_mode(chapter, stage)
            try:
                ASIDE_SWITCH_20241219.offset = area_offset((-20, -20, 20, 20), (0, -37))
                if self._campaign_set_chapter_20241219_aside(chapter, _CHAPTER_SWITCH_20241219_SPEX_ASIDE):
                    return True
            finally:
                ASIDE_SWITCH_20241219.offset = (20, 20)
        return False

    def campaign_set_chapter(self, name: str, mode: str = "normal") -> None:
        """设置 7-2、d3 或 sp3 等关卡；mode 接受 normal 或 hard。"""
        chapter, stage = self.campaign_separate_name(name)

        if (
            self.campaign_set_chapter_main(chapter, mode)
            or self.campaign_set_chapter_20241219(chapter, stage, mode)
            or self.campaign_set_chapter_event(chapter, mode)
            or self.campaign_set_chapter_sp(chapter, mode)
        ):
            pass
        else:
            logger.warning(f"Unknown campaign chapter: {name}")

    def handle_campaign_ui_additional(self) -> bool:
        if self.appear(WITHDRAW, offset=(30, 30)):
            self.ensure_no_info_bar(timeout=2)
            with suppress(CampaignEnd):
                self.withdraw()
            return True
        return False

    def ensure_campaign_ui(
        self,
        name: str,
        mode: str = "normal",
        *,
        skip_first_screenshot: bool = True,
    ) -> bool:
        """切换到指定关卡和 normal/hard 模式；重试后仍失败则抛出 CampaignSelectionError。"""
        timeout = Timer(5, count=20).start()
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if timeout.reached():
                break
            try:
                self.campaign_set_chapter(name, mode)
                self.ENTRANCE = self.campaign_get_entrance(name=name)
            except CampaignNameError:
                pass
            else:
                return True

            if self.handle_campaign_ui_additional():
                continue

        logger.warning(CAMPAIGN_NAME_ERROR_MESSAGE)
        raise CampaignSelectionError(CAMPAIGN_NAME_ERROR_MESSAGE)

    def commission_notice_show_at_campaign(self) -> bool:
        return self.appear(CAMPAIGN_CHECK, offset=(20, 20)) and self.appear(
            campaign_assets.COMMISSION_NOTICE_AT_CAMPAIGN
        )
