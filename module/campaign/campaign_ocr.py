import collections
import re
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, TypedDict, Unpack

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

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

    from module.base.button import Button
    from module.base.template import Template
    from module.base.type_alias import ImageArray
    from module.config.config import AzurLaneConfig
    from module.device.device import Device


@dataclass(frozen=True, slots=True)
class StageMatchOptions:
    name_offset: tuple[int, int] = (75, 9)
    name_size: tuple[int, int] = (60, 16)
    name_letter: tuple[int, int, int] = (255, 255, 255)
    name_thresh: int = 128
    similarity: float = 0.85


class StageMatchSettings(TypedDict, total=False):
    name_offset: tuple[int, int]
    name_size: tuple[int, int]
    name_letter: tuple[int, int, int]
    name_thresh: int
    similarity: float


@dataclass(frozen=True, slots=True)
class CampaignStagePage:
    chapter: str
    entrances: Mapping[str, Button]


def stage_match_options(
    options: StageMatchOptions | None = None,
    settings: StageMatchSettings | None = None,
) -> StageMatchOptions:
    options = StageMatchOptions() if options is None else options
    if settings:
        options = replace(options, **settings)
    return options


class CampaignOcr(ModuleBase):
    campaign_chapter: str = "0"
    stage_entrance: dict[str, Button]
    # 大致关卡名区域，用来缩小模板匹配范围。
    _stage_detect_area: tuple[int, int, int, int] = (87, 117, 1151, 636)

    def __init__(
        self,
        config: AzurLaneConfig,
        device: Device,
    ) -> None:
        self.stage_entrance = {}
        super().__init__(config=config, device=device)

    @staticmethod
    def campaign_get_chapter_index(name: str | int) -> int:
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
    def campaign_ocr_result_process(result: str) -> str:
        # 游戏内短横线不是普通 '-'，OCR 结果可能变成 '7--2'。
        result = result.replace("--", "-").replace("--", "-").lstrip("-")

        # 修正 'I1-1'、'1I-1' 这类数字段误识别，同时保留 'isp-2'、'sp1'。
        def replace_func(match: re.Match[str]) -> str:
            segment = match.group(0)
            return segment.replace("I", "1")

        result = re.sub(r"[0-9I]+-[0-9I]+", replace_func, result, count=1)

        # 把 72 修正为 7-2。
        if len(result) == 2 and result[0].isdigit():
            result = "-".join(result)

        return result.lower()

    @staticmethod
    def campaign_separate_name(name: str) -> tuple[str, str]:
        """拆分小写关卡名，返回章节和序号，例如 7-2 → ('7', '2')、sp3 → ('sp', '3')。"""
        name = name.strip("-")
        result = None
        if name == "sp":
            result = ("ex_sp", "1")
        elif name.startswith("extra") or name == "ex":
            result = ("ex_ex", "1")
        elif "-" in name:
            chapter, stage = name.split("-", maxsplit=1)
            result = (chapter, stage)
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
        template: Template,
        image: ImageArray,
        stage_image: ImageArray | None = None,
        options: StageMatchOptions | None = None,
        **settings: Unpack[StageMatchSettings],
    ) -> list[Button]:
        """从 stage_image 匹配入口并返回按钮列表；settings 覆盖 StageMatchOptions。"""
        options = stage_match_options(options, settings)
        digits: list[Button] = []
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
            name_image = crop(image, button_name.area, copy=False)
            name = extract_letters(name_image, letter=options.name_letter, threshold=options.name_thresh)
            button_name = button_name.crop(area=self._extract_stage_name(name))
            # 每个按钮的 area 临时替换成关卡名区域，供 OCR 使用；button 保留关卡图标区域。
            button.load_color(image)
            button.area = button_name.area
            digits.append(button)

        return digits

    @cached_property
    def _stage_image(self) -> ImageArray:
        return crop(self.device.image, self._stage_detect_area, copy=False)

    @cached_property
    def _stage_image_gray(self) -> ImageArray:
        return rgb2gray(self._stage_image)

    def campaign_extract_name_image(
        self,
        image: ImageArray,
        *,
        match_similarity: float | None = None,
    ) -> list[Button]:
        """按 ManualConfig.STAGE_ENTRANCE 处理活动差异并返回全部关卡入口按钮。"""
        digits: list[Button] = []

        def match(
            template: Template,
            stage_image: ImageArray,
            **settings: Unpack[StageMatchSettings],
        ) -> list[Button]:
            if match_similarity is not None:
                settings["similarity"] = match_similarity
            return self.campaign_match_multi(
                template,
                image,
                stage_image,
                **settings,
            )

        if "normal" in self.config.STAGE_ENTRANCE:
            digits += match(
                template_assets.TEMPLATE_STAGE_CLEAR,
                self._stage_image_gray,
                name_offset=(75, 9),
                name_size=(60, 16),
            )
            digits += match(
                template_assets.TEMPLATE_STAGE_PERCENT,
                self._stage_image_gray,
                name_offset=(48, 0),
                name_size=(60, 16),
            )
        if "half" in self.config.STAGE_ENTRANCE:
            digits += match(
                template_assets.TEMPLATE_STAGE_HALF_PERCENT,
                self._stage_image_gray,
                name_offset=(48, 0),
                name_size=(60, 16),
            )
        if "blue" in self.config.STAGE_ENTRANCE:
            digits += match(
                template_assets.TEMPLATE_STAGE_BLUE_PERCENT,
                extract_letters(self._stage_image, letter=(255, 255, 255), threshold=153),
                name_offset=(55, 0),
                name_size=(60, 16),
            )
            digits += match(
                template_assets.TEMPLATE_STAGE_BLUE_CLEAR,
                extract_letters(self._stage_image, letter=(99, 223, 239), threshold=153),
                name_offset=(60, 12),
                name_size=(60, 16),
            )
        if "green" in self.config.STAGE_ENTRANCE:
            digits += match(
                template_assets.TEMPLATE_STAGE_GREEN_CLEAR,
                self._stage_image_gray,
                name_offset=(60, 0),
                name_size=(60, 22),
            )
            digits += match(
                template_assets.TEMPLATE_STAGE_PERCENT,
                self._stage_image_gray,
                similarity=0.6,
                name_offset=(52, 0),
                name_size=(60, 22),
            )
        if "20240725" in self.config.STAGE_ENTRANCE:
            digits += match(
                template_assets.TEMPLATE_STAGE_CLEAR_20240725,
                self._stage_image_gray,
                name_offset=(73, -4),
                name_size=(60, 22),
            )

        return digits

    @staticmethod
    def _extract_stage_name(image: ImageArray) -> tuple[int, int, int, int]:
        """从完整关卡名裁图中返回关卡编号区域坐标，例如 Counterattack! 前的 3-4。"""
        x_skip = 10
        interval = 5
        x_color = np.convolve(np.mean(image, axis=0), np.ones(interval), "valid") / interval
        x_list = np.where(x_color[x_skip:] > 245)[0]
        if len(x_list) == 0:
            logger.warning("No interval between digit and text.")
            area = (0, 0, image.shape[1], image.shape[0])
        else:
            area = (0, 0, x_list[0] + 1 + x_skip, image.shape[0])
        return (
            int(area[0] - 3),
            int(area[1] - 7),
            int(area[2] + 3),
            int(area[3] + 7),
        )

    def read_stage_page(
        self,
        image: ImageArray,
        *,
        normalize_result: Callable[[str], str],
        separate_name: Callable[[str], tuple[str, str]],
        match_similarity: float | None = None,
    ) -> CampaignStagePage:
        """使用显式识别策略读取当前章节和入口，不修改 CampaignUI 的选择状态。"""

        del_cached_property(self, "_stage_image")
        del_cached_property(self, "_stage_image_gray")
        buttons = self.campaign_extract_name_image(image, match_similarity=match_similarity)
        del_cached_property(self, "_stage_image")
        del_cached_property(self, "_stage_image_gray")
        if len(buttons) == 0:
            logger.info("No stage found.")
            raise CampaignNameError

        ocr = Ocr[str](
            buttons,
            name="campaign",
            letter=(255, 255, 255),
            threshold=128,
            alphabet="0123456789ABCDEFGHIJKLMNPQRSTUVWXYZ-",
        )
        result = ocr.ocr_regions(image)
        result = [normalize_result(value) for value in result]

        chapters = [separate_name(value)[0] for value in result if value]
        chapters = [chapter for chapter in chapters if chapter]
        if not chapters:
            raise CampaignNameError

        counter = collections.Counter(chapters)
        chapter = counter.most_common()[0][0]

        if chapter == "0":
            # OCR 误识别示例：'0F'、'F-IB'、'IGI'。
            raise CampaignNameError

        # OCR 后恢复按钮属性。
        # 这些按钮会作为 `MapOperation.enter_map()` 使用的关卡入口。
        # button.area：关卡名区域，例如 'CLEAR' 和 '%'。
        # button.color：关卡图标颜色。
        # button.button：关卡图标区域。
        # button.name：OCR 识别出的关卡名。
        entrances: dict[str, Button] = {}
        for name, button in zip(result, buttons, strict=True):
            button.area = button.button
            button.name = name
            entrances[name] = button

        logger.attr("Chapter", chapter)
        logger.attr("Stage", ", ".join(entrances))
        return CampaignStagePage(chapter, entrances)

    def _get_stage_name(self, image: ImageArray) -> None:
        """解析关卡名，并写入 campaign_chapter 和关卡名到入口按钮的 stage_entrance 映射。"""

        page = self.read_stage_page(
            image,
            normalize_result=self.campaign_ocr_result_process,
            separate_name=self.campaign_separate_name,
        )
        self.campaign_chapter = page.chapter
        self.stage_entrance = dict(page.entrances)

    def try_update_stage_entrances(self, image: ImageArray) -> bool:
        """尝试从截图更新章节和关卡入口；预期的识别失败返回 False。"""
        try:
            self._get_stage_name(image)
        except IndexError, CampaignNameError:
            return False
        return True

    def handle_get_chapter_additional(self) -> bool:
        if self.appear(WITHDRAW, offset=(30, 30)):
            logger.warning("get_chapter_index: WITHDRAW appears")
            raise CampaignNameError
        return False

    def get_chapter_index(self, *, skip_first_screenshot: bool = True) -> int:
        timeout = Timer(2, count=4).start()
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if timeout.reached():
                raise CampaignNameError
            image = self.device.image
            if self.try_update_stage_entrances(image):
                break

            if self.handle_get_chapter_additional():
                continue

        return self.campaign_get_chapter_index(self.campaign_chapter)
