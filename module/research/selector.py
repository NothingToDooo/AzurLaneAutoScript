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
from module.research.project import research_detect
from module.research.ui import ResearchUI

RESEARCH_ENTRANCE = [ENTRANCE_1, ENTRANCE_2, ENTRANCE_3, ENTRANCE_4, ENTRANCE_5]
FILTER_REGEX = re.compile(
    r"(s[12345678])?"
    r"-?"
    r"(neptune|monarch|ibuki|izumo|roon|saintlouis"
    r"|seattle|georgia|kitakaze|azuma|friedrich"
    r"|gascogne|champagne|cheshire|drake|mainz|odin"
    r"|anchorage|hakuryu|agir|august|marcopolo"
    r"|plymouth|rupprecht|harbin|chkalov|brest"
    r"|kearsarge|hindenburg|shimanto|schultz|flandre"
    r"|napoli|nakhimov|halford|bayard|daisen"
    r"|goudenleeuw|mecklenburg|dmitri|kansas|vittorio)?"
    r"(dr|pry)?"
    r"([bcdeghqt])?"
    r"-?"
    r"(\d{3})?"
    r"(\d.\d|\d\d?)?"
)
FILTER_ATTR = ("series", "ship", "ship_rarity", "genre", "number", "duration")
FILTER_PRESET = ("shortest", "cheapest", "reset")
FILTER = Filter(FILTER_REGEX, FILTER_ATTR, FILTER_PRESET)
_RESEARCH_RESOURCE_RULES = (
    ("need_cube", "Research_UseCube"),
    ("need_coin", "Research_UseCoin"),
    ("need_part", "Research_UsePart"),
)


class ResearchSelector(ResearchUI):
    # List of current research projects
    projects: list
    # From StorageHandler
    storage_has_boxes = True

    def research_goto_detail(self, index, skip_first_screenshot=True):
        logger.info(f"Research goto detail (project {index})")
        click_timer = Timer(10)
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            # DETAIL_NEXT appears even when the research detail page is not fully loaded.
            if not self.appear(DETAIL_NEXT, offset=(20, 20)):
                if click_timer.reached():
                    self.device.click(RESEARCH_ENTRANCE[index])
                    click_timer.reset()
            else:
                # Check RESEARCH_COST_CHECKER to ensure that the research detail page is fully loaded.
                self.wait_until_appear(RESEARCH_COST_CHECKER, offset=(20, 20), skip_first_screenshot=True)
                break

    def research_detect(self):
        timeout = Timer(5, count=5).start()
        while 1:
            projects = research_detect(self.device.image)

            if timeout.reached():
                logger.warning("Failed to OCR research name after 3 trial, assume correct")
                break

            if sum(p.valid for p in projects) < 5:
                # Leftmost research series covered by battle pass info, see #1037
                logger.info("Invalid project detected")
                logger.info("Probably because of battle pass info or too fast screenshot")
                # A rare case, poor sleep is acceptable
                self.device.sleep(1)
                self.device.screenshot()
                continue
            break

        self.projects = projects

    def research_sort_filter(self, enforce=False):
        """
        Returns:
            list: A list of ResearchProject objects and preset strings,
                such as [object, object, object, 'reset']
        """
        # Load filter string
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

        # Case insensitive
        string = string.lower()
        # Filter uses `hakuryu`, but allows both `hakuryu` and `hakuryuu`
        string = string.replace("hakuryuu", "hakuryu")
        # Allow both `fastest` and `shortest`
        string = string.replace("fastest", "shortest")
        # Allow both `PR` and `PRY`
        string = re.sub(r"pr([\d\- >])", r"pry\1", string)

        FILTER.load(string)
        priority = FILTER.apply(self.projects, func=partial(self._research_check, enforce=enforce))

        # Log
        logger.attr("Filter_sort", " > ".join([str(project) for project in priority]))
        return priority

    def _research_check(self, project, enforce=False):
        """检查科研项目是否符合当前筛选策略。

        Args:
            project (ResearchProject):
            enforce (bool):

        Returns:
            bool:
        """
        if not project.valid:
            return False
        if not self._research_resource_allowed(project, enforce):
            return False
        return self._research_genre_allowed(project)

    def _research_resource_allowed(self, project, enforce):
        is_05 = str(project.duration) == "0.5"
        for need_attr, config_attr in _RESEARCH_RESOURCE_RULES:
            if getattr(project, need_attr) and not self._research_resource_config_allowed(
                getattr(self.config, config_attr), is_05, enforce
            ):
                return False
        return True

    @staticmethod
    def _research_resource_config_allowed(config, is_05, enforce):
        if config == "do_not_use":
            return False
        if enforce:
            return True
        if config == "only_no_project":
            return False
        return not (config == "only_05_hour" and not is_05)

    def _research_genre_allowed(self, project):
        genre = project.genre.upper()
        # B 类收益低且前置条件不稳定；T 类前置条件不满足时无法入队。
        if genre in {"B", "T"}:
            return False
        return self.storage_has_boxes or genre != "E" or project.equipment_amount == 0

    def research_sort_shortest(self, enforce):
        """
        Returns:
            list: A list of ResearchProject objects and preset strings,
                such as [object, object, object, 'reset']
        """
        FILTER.load(FILTER_STRING_SHORTEST)
        priority = FILTER.apply(self.projects, func=partial(self._research_check, enforce=enforce))

        logger.attr("Filter_sort", " > ".join([str(project) for project in priority]))
        return priority

    def research_sort_cheapest(self, enforce):
        """
        Returns:
            list: A list of ResearchProject objects and preset strings,
                such as [object, object, object, 'reset']
        """
        FILTER.load(FILTER_STRING_CHEAPEST)
        priority = FILTER.apply(self.projects, func=partial(self._research_check, enforce=enforce))

        logger.attr("Filter_sort", " > ".join([str(project) for project in priority]))
        return priority
