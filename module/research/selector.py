import re
from functools import partial

from module.base.filter import Filter
from module.base.timer import Timer
from module.config.config_generated import GeneratedConfig
from module.logger import logger
from module.research.assets import (
    DETAIL_NEXT,
    ENTRANCE_1,
    ENTRANCE_2,
    ENTRANCE_3,
    ENTRANCE_4,
    ENTRANCE_5,
    RESEARCH_COST_CHECKER,
)
from module.research.preset import DICT_FILTER_PRESET, FILTER_STRING_CHEAPEST, FILTER_STRING_SHORTEST
from module.research.project import ResearchProject, research_detect
from module.research.ui import ResearchUI

RESEARCH_ENTRANCE = [ENTRANCE_1, ENTRANCE_2, ENTRANCE_3, ENTRANCE_4, ENTRANCE_5]
FILTER_REGEX = re.compile(
    r"(s[123456789])?"
    r"-?"
    r"(neptune|monarch|ibuki|izumo|roon|saintlouis"
    r"|seattle|georgia|kitakaze|azuma|friedrich"
    r"|gascogne|champagne|cheshire|drake|mainz|odin"
    r"|anchorage|hakuryu|agir|august|marcopolo"
    r"|plymouth|rupprecht|harbin|chkalov|brest"
    r"|kearsarge|hindenburg|shimanto|schultz|flandre"
    r"|napoli|nakhimov|halford|bayard|daisen"
    r"|goudenleeuw|mecklenburg|dmitri|kansas|vittorio"
    r"|valparaiso|maximmelmann|duncan|takahashi|orage)?"
    r"(dr|pry)?"
    r"([bcdeghqt])?"
    r"-?"
    r"(\d{3})?"
    r"(\d.\d|\d\d?)?"
)
FILTER_ATTR = ("series", "ship", "ship_rarity", "genre", "number", "duration")
FILTER_PRESET = ("shortest", "cheapest", "reset")
FILTER = Filter[ResearchProject](FILTER_REGEX, FILTER_ATTR, FILTER_PRESET)
type ResearchPriority = list[ResearchProject | str]


class ResearchSelector(ResearchUI):
    projects: list[ResearchProject]
    storage_has_boxes: bool = True

    def research_goto_detail(self, index: int, *, skip_first_screenshot: bool = True) -> None:
        logger.info(f"Research goto detail (project {index})")
        click_timer = Timer(10)
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            # DETAIL_NEXT 会提前出现，还需等待费用区域确认详情页加载完成。
            if not self.appear(DETAIL_NEXT, offset=(20, 20)):
                if click_timer.reached():
                    self.device.click(RESEARCH_ENTRANCE[index])
                    click_timer.reset()
            else:
                self.wait_until_appear(RESEARCH_COST_CHECKER, offset=(20, 20), skip_first_screenshot=True)
                break

    def research_detect(self) -> None:
        timeout = Timer(5, count=5).start()
        while 1:
            projects = research_detect(self.device.image)

            if timeout.reached():
                logger.warning("Failed to OCR research name after 3 trial, assume correct")
                break

            if sum(p.valid for p in projects) < 5:
                # 战令提示可能遮住最左侧科研系列，见 #1037；短暂等待后重试 OCR。
                logger.info("Invalid project detected")
                logger.info("Probably because of battle pass info or too fast screenshot")
                self.device.sleep(1)
                self.device.screenshot()
                continue
            break

        self.projects = projects

    def research_sort_filter(self, *, enforce: bool = False) -> ResearchPriority:
        """按预设返回 ResearchProject 与 shortest、cheapest、reset 等指令的优先级列表。"""
        preset = self.config.Research_PresetFilter
        if preset == "custom":
            string = self.config.Research_CustomFilter
            if enforce:
                string = string + " > " + DICT_FILTER_PRESET[GeneratedConfig.Research_PresetFilter]
        else:
            if (self.config.Research_UseCube == "always_use" or enforce) and f"{preset}_cube" in DICT_FILTER_PRESET:
                preset = f"{preset}_cube"
            if preset not in DICT_FILTER_PRESET:
                logger.warning(f"Preset not found: {preset}, use default preset")
                preset = GeneratedConfig.Research_PresetFilter
            string = DICT_FILTER_PRESET[preset]

        logger.attr("Research preset", preset)
        logger.info(
            f"Use cube: {self.config.Research_UseCube} Use coin: {self.config.Research_UseCoin} "
            f"Use part: {self.config.Research_UsePart}"
        )
        logger.attr("Allow delay", self.config.Research_AllowDelay)

        # 筛选器不区分大小写，并兼容历史别名。
        string = string.lower()
        string = string.replace("hakuryuu", "hakuryu")
        string = string.replace("fastest", "shortest")
        string = re.sub(r"pr([\d\- >])", r"pry\1", string)

        FILTER.load(string)
        priority = FILTER.apply(self.projects, func=partial(self._research_check, enforce=enforce))

        logger.attr("Filter_sort", " > ".join([str(project) for project in priority]))
        return priority

    def _research_check(self, project: ResearchProject, *, enforce: bool = False) -> bool:
        if not project.valid:
            return False
        if not self._research_resource_allowed(project, enforce=enforce):
            return False
        return self._research_genre_allowed(project)

    def _research_resource_allowed(self, project: ResearchProject, *, enforce: bool) -> bool:
        is_05 = str(project.duration) == "0.5"
        resource_rules = (
            (project.need_cube, self.config.Research_UseCube),
            (project.need_coin, self.config.Research_UseCoin),
            (project.need_part, self.config.Research_UsePart),
        )
        for required, config in resource_rules:
            if required and not self._research_resource_config_allowed(
                config,
                is_05=is_05,
                enforce=enforce,
            ):
                return False
        return True

    @staticmethod
    def _research_resource_config_allowed(config: str, *, is_05: bool, enforce: bool) -> bool:
        if config == "do_not_use":
            return False
        if enforce:
            return True
        if config == "only_no_project":
            return False
        return not (config == "only_05_hour" and not is_05)

    def _research_genre_allowed(self, project: ResearchProject) -> bool:
        genre = project.genre.upper()
        # B 类收益低且前置条件不稳定；T 类前置条件不满足时无法入队。
        if genre in {"B", "T"}:
            return False
        return self.storage_has_boxes or genre != "E" or project.equipment_amount == 0

    def research_sort_shortest(self, *, enforce: bool) -> ResearchPriority:
        """返回按耗时排序的项目与预设指令列表。"""
        FILTER.load(FILTER_STRING_SHORTEST)
        priority = FILTER.apply(self.projects, func=partial(self._research_check, enforce=enforce))

        logger.attr("Filter_sort", " > ".join([str(project) for project in priority]))
        return priority

    def research_sort_cheapest(self, *, enforce: bool) -> ResearchPriority:
        """返回按消耗排序的项目与预设指令列表。"""
        FILTER.load(FILTER_STRING_CHEAPEST)
        priority = FILTER.apply(self.projects, func=partial(self._research_check, enforce=enforce))

        logger.attr("Filter_sort", " > ".join([str(project) for project in priority]))
        return priority
