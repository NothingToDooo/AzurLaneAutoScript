import collections
import re
from dataclasses import dataclass, replace

import numpy as np

from module.base.base import ModuleBase
from module.base.decorator import cached_property, del_cached_property
from module.base.timer import Timer
from module.base.utils import crop, extract_letters, rgb2gray
from module.exception import CampaignNameError
from module.logger import logger
from module.map.assets import WITHDRAW
from module.ocr.ocr import Ocr
from module.template import assets as template_assets


@dataclass(frozen=True, slots=True)
class StageMatchOptions:
    name_offset: tuple[int, int] = (75, 9)
    name_size: tuple[int, int] = (60, 16)
    name_letter: tuple[int, int, int] = (255, 255, 255)
    name_thresh: int = 128
    similarity: float = 0.85


def stage_match_options(options=None, settings=None) -> StageMatchOptions:
    options = StageMatchOptions() if options is None else options
    if settings:
        options = replace(options, **settings)
    return options


class CampaignOcr(ModuleBase):
    campaign_chapter: str = "0"
    # 大致关卡名区域，用来缩小模板匹配范围。
    _stage_detect_area = (87, 117, 1151, 636)

    def __init__(self, *args, **kwargs):
        self.stage_entrance = {}
        super().__init__(*args, **kwargs)

    @staticmethod
    def campaign_get_chapter_index(name):
        if isinstance(name, int):
            return name
        if name.isdigit():
            return int(name)
        if name in ["a", "c", "as", "cs", "t", "ht", "ts", "hts", "sp", "ex_sp"]:
            return 1
        if name in ["b", "d", "bs", "ds", "ex_ex"]:
            return 2
        raise CampaignNameError

    @staticmethod
    def campaign_ocr_result_process(result):
        # 游戏内短横线不是普通 '-'，OCR 结果可能变成 '7--2'。
        result = result.replace("--", "-").replace("--", "-").lstrip("-")

        # 修正 'I1-1'、'1I-1' 这类数字段误识别，同时保留 'isp-2'、'sp1'。
        def replace_func(match):
            segment = match.group(0)
            return segment.replace("I", "1")

        result = re.sub(r"[0-9I]+-[0-9I]+", replace_func, result, count=1)

        # 把 72 修正为 7-2。
        if len(result) == 2 and result[0].isdigit():
            result = "-".join(result)

        return result.lower()

    @staticmethod
    def campaign_separate_name(name):
        """拆分小写关卡名，返回章节和序号，例如 7-2 → ('7', '2')、sp3 → ('sp', '3')。"""
        name = name.strip("-")
        result = None
        if name == "sp":
            result = ("ex_sp", "1")
        elif name.startswith("extra") or name == "ex":
            result = ("ex_ex", "1")
        elif "-" in name:
            result = name.split("-")
        elif name.startswith("sp"):
            result = ("sp", name[-1])
        elif name[-1].isdigit():
            result = (name[:-1], name[-1])
        elif name[0].isdigit() and name[-1].isalpha():
            # 例如 49X。
            logger.warning(f"Unknown stage name: {name}")
            result = ("", "")

        if result is None:
            logger.warning(f"Unknown stage name: {name}")
            result = ("", "")
        return result

    def campaign_match_multi(
        self,
        template,
        image,
        stage_image=None,
        options=None,
        **settings,
    ):
        """从 stage_image 匹配入口并返回按钮列表；settings 覆盖 StageMatchOptions。"""
        options = stage_match_options(options, settings)
        digits = []
        stage_image = image if stage_image is None else stage_image
        result = template.match_multi(stage_image, similarity=options.similarity, name="STAGE")
        name_area = (
            options.name_offset[0],
            options.name_offset[1],
            options.name_offset[0] + options.name_size[0],
            options.name_offset[1] + options.name_size[1],
        )
        for matched_button in result:
            button = matched_button.move(self._stage_detect_area[:2])
            button_name = button.crop(area=name_area, image=image)
            name = extract_letters(button_name.image, letter=options.name_letter, threshold=options.name_thresh)
            button_name = button_name.crop(area=self._extract_stage_name(name))
            # 每个按钮的 area 临时替换成关卡名区域，供 OCR 使用；button 保留关卡图标区域。
            button.load_color(image)
            button.area = button_name.area
            digits.append(button)

        return digits

    @cached_property
    def _stage_image(self):
        return crop(self.device.image, self._stage_detect_area, copy=False)

    @cached_property
    def _stage_image_gray(self):
        return rgb2gray(self._stage_image)

    def campaign_extract_name_image(self, image):
        """按 ManualConfig.STAGE_ENTRANCE 处理活动差异并返回全部关卡入口按钮。"""
        digits = []

        if "normal" in self.config.STAGE_ENTRANCE:
            digits += self.campaign_match_multi(
                template_assets.TEMPLATE_STAGE_CLEAR,
                image,
                self._stage_image_gray,
                name_offset=(75, 9),
                name_size=(60, 16),
            )
            digits += self.campaign_match_multi(
                template_assets.TEMPLATE_STAGE_PERCENT,
                image,
                self._stage_image_gray,
                name_offset=(48, 0),
                name_size=(60, 16),
            )
        if "half" in self.config.STAGE_ENTRANCE:
            digits += self.campaign_match_multi(
                template_assets.TEMPLATE_STAGE_HALF_PERCENT,
                image,
                self._stage_image_gray,
                name_offset=(48, 0),
                name_size=(60, 16),
            )
        if "blue" in self.config.STAGE_ENTRANCE:
            digits += self.campaign_match_multi(
                template_assets.TEMPLATE_STAGE_BLUE_PERCENT,
                image,
                extract_letters(self._stage_image, letter=(255, 255, 255), threshold=153),
                name_offset=(55, 0),
                name_size=(60, 16),
            )
            digits += self.campaign_match_multi(
                template_assets.TEMPLATE_STAGE_BLUE_CLEAR,
                image,
                extract_letters(self._stage_image, letter=(99, 223, 239), threshold=153),
                name_offset=(60, 12),
                name_size=(60, 16),
            )
        if "green" in self.config.STAGE_ENTRANCE:
            digits += self.campaign_match_multi(
                template_assets.TEMPLATE_STAGE_GREEN_CLEAR,
                image,
                self._stage_image_gray,
                name_offset=(60, 0),
                name_size=(60, 22),
            )
            digits += self.campaign_match_multi(
                template_assets.TEMPLATE_STAGE_PERCENT,
                image,
                self._stage_image_gray,
                similarity=0.6,
                name_offset=(52, 0),
                name_size=(60, 22),
            )
        if "20240725" in self.config.STAGE_ENTRANCE:
            digits += self.campaign_match_multi(
                template_assets.TEMPLATE_STAGE_CLEAR_20240725,
                image,
                self._stage_image_gray,
                name_offset=(73, -4),
                name_size=(60, 22),
            )

        return digits

    @staticmethod
    def _extract_stage_name(image):
        """从完整关卡名裁图中返回关卡编号区域坐标，例如 Counterattack! 前的 3-4。"""
        x_skip = 10
        interval = 5
        x_color = np.convolve(np.mean(image, axis=0), np.ones(interval), "valid") / interval
        x_list = np.where(x_color[x_skip:] > 245)[0]
        if x_list is None or len(x_list) == 0:
            logger.warning("No interval between digit and text.")
            area = (0, 0, image.shape[1], image.shape[0])
        else:
            area = (0, 0, x_list[0] + 1 + x_skip, image.shape[0])
        return np.add(area, (-3, -7, 3, 7))

    def _get_stage_name(self, image):
        """解析关卡名，并写入 campaign_chapter 和关卡名到入口按钮的 stage_entrance 映射。"""
        self.stage_entrance = {}
        del_cached_property(self, "_stage_image")
        del_cached_property(self, "_stage_image_gray")
        buttons = self.campaign_extract_name_image(image)
        del_cached_property(self, "_stage_image")
        del_cached_property(self, "_stage_image_gray")
        if len(buttons) == 0:
            logger.info("No stage found.")
            raise CampaignNameError

        ocr = Ocr(
            buttons,
            name="campaign",
            letter=(255, 255, 255),
            threshold=128,
            alphabet="0123456789ABCDEFGHIJKLMNPQRSTUVWXYZ-",
        )
        result = ocr.ocr(image)
        if not isinstance(result, list):
            result = [result]
        result = [self.campaign_ocr_result_process(res) for res in result]

        chapter = [self.campaign_separate_name(res)[0] for res in result if res]
        chapter = list(filter(("").__ne__, chapter))
        if not chapter:
            raise CampaignNameError

        counter = collections.Counter(chapter)
        self.campaign_chapter = counter.most_common()[0][0]

        if self.campaign_chapter in {0, "0"}:
            # OCR 误识别示例：'0F'、'F-IB'、'IGI'。
            raise CampaignNameError

        # OCR 后恢复按钮属性。
        # 这些按钮会作为 `MapOperation.enter_map()` 使用的关卡入口。
        # button.area：关卡名区域，例如 'CLEAR' 和 '%'。
        # button.color：关卡图标颜色。
        # button.button：关卡图标区域。
        # button.name：OCR 识别出的关卡名。
        for name, button in zip(result, buttons, strict=False):
            button.area = button.button
            button.name = name
            self.stage_entrance[name] = button

        logger.attr("Chapter", self.campaign_chapter)
        logger.attr("Stage", ", ".join(self.stage_entrance.keys()))

    def handle_get_chapter_additional(self):
        if self.appear(WITHDRAW, offset=(30, 30)):
            logger.warning("get_chapter_index: WITHDRAW appears")
            raise CampaignNameError

    def get_chapter_index(self, skip_first_screenshot=True):
        timeout = Timer(2, count=4).start()
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if timeout.reached():
                raise CampaignNameError
            image = self.device.image
            try:
                self._get_stage_name(image)
                break
            except IndexError, CampaignNameError:
                pass

            if self.handle_get_chapter_additional():
                continue

        return self.campaign_get_chapter_index(self.campaign_chapter)
