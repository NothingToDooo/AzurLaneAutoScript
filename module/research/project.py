import re
from datetime import timedelta
from typing import ClassVar

import cv2
import numpy as np
from scipy import signal

from module.base.decorator import cached_property
from module.base.utils import color_similarity_2d, crop, extract_white_letters, get_color, resize
from module.logger import logger
from module.ocr.ocr import Ocr
from module.research import assets as research_assets
from module.research.project_data import LIST_RESEARCH_PROJECT
from module.research.series import get_research_series_3

RESEARCH_SERIES = (
    research_assets.SERIES_1,
    research_assets.SERIES_2,
    research_assets.SERIES_3,
    research_assets.SERIES_4,
    research_assets.SERIES_5,
)
RESEARCH_STATUS = [
    research_assets.STATUS_1,
    research_assets.STATUS_2,
    research_assets.STATUS_3,
    research_assets.STATUS_4,
    research_assets.STATUS_5,
]
OCR_RESEARCH = [
    research_assets.OCR_RESEARCH_1,
    research_assets.OCR_RESEARCH_2,
    research_assets.OCR_RESEARCH_3,
    research_assets.OCR_RESEARCH_4,
    research_assets.OCR_RESEARCH_5,
]
OCR_RESEARCH = Ocr(OCR_RESEARCH, name="RESEARCH", threshold=64, alphabet="0123456789BCDEGHQTMIULRF-")


def get_research_series_old(image, series_button=RESEARCH_SERIES):
    """按罗马数字的白色线条峰值识别各项目系列，返回五个系列编号。"""
    result = []
    # prominence=50 用于滤除噪声；2021-07-15 后 IV 更小且 V 的斜线因抗锯齿变暗，故高度降为 160。
    parameters = {"height": 160, "prominence": 50, "width": 1}

    for button in series_button:
        im = color_similarity_2d(resize(crop(image, button.area, copy=False), (46, 25)), color=(255, 255, 255))
        peaks = [len(signal.find_peaks(row, **parameters)[0]) for row in im[5:-5]]
        upper, lower = max(peaks), min(peaks)

        # 忽略仅一两行出现额外峰值的噪声。
        if upper == 3 and lower == 2 and peaks.count(3) <= 2:
            upper = 2

        if upper == lower and 1 <= upper <= 3:
            series = upper
        elif upper == 3 and lower == 2:
            series = 4
        elif upper == 2 and lower == 1:
            series = 5
        else:
            series = 0
            logger.warning(f"Unknown research series: button={button}, upper={upper}, lower={lower}")
        result.append(series)

    return result


def _get_research_series(img):
    img = extract_white_letters(img)
    pos = img.shape[0] * 2 // 5

    img = img[pos - 4 : pos + 5]
    img = cv2.GaussianBlur(img, (5, 5), 1)
    img = img[3:6]

    threshold = np.mean(img)
    edge = np.where(np.diff((img[1] > threshold).astype(np.uint8)) == 1)[0]

    grad_x = cv2.Sobel(img, cv2.CV_16S, 1, 0)[1]
    grad_y = cv2.Sobel(img, cv2.CV_16S, 0, 1)[1]

    edge = np.arctan([grad_y[i] / grad_x[i] for i in edge])
    edge = tuple(0 if i > -0.1 else 1 for i in edge if i < 0.1)

    return {(0,): 1, (0, 0): 2, (0, 0, 0): 3, (0, 1): 4, (1,): 5, (1, 0): 6}.get(edge, 0)


def get_research_series(image, series_button=RESEARCH_SERIES):
    """返回五个科研项目的系列编号。"""
    result = []
    for button in series_button:
        img = crop(image, button.area, copy=False)
        img = cv2.resize(img, (46, 25), interpolation=cv2.INTER_AREA)
        series = _get_research_series(img)
        result.append(series)
    return result


def get_research_name(image, ocr=OCR_RESEARCH):
    """返回五个科研项目名称的字符串列表。"""
    names = ocr.ocr(image)
    if not isinstance(names, list):
        names = [names]
    return names


def get_research_finished(image):
    """返回已完成项目的 0～4 索引；没有已完成项目时返回 None。"""
    for index in [2, 1, 3, 0, 4]:
        button = RESEARCH_STATUS[index]
        color = get_color(image, button.area)
        if max(color) - min(color) < 40:
            logger.warning(f"Unexpected color: {color}")
            continue
        # get_color 返回 RGB；argmax 1 表示绿色已完成，2 表示蓝色未完成。
        color_index = np.argmax(color)
        if color_index == 1:
            return index
        if color_index == 2:
            continue
        logger.warning(f"Unexpected color: {color}")
        continue

    return None


def parse_time(string):
    """解析 HH:MM:SS；格式无效时返回 None。"""
    result = re.search(r"(\d+):(\d+):(\d+)", string)
    if not result:
        logger.warning(f"Invalid time string: {string}")
        return None
    result = [int(s) for s in result.groups()]
    return timedelta(hours=result[0], minutes=result[1], seconds=result[2])


def research_detect(image):
    """从截图返回五个 ResearchProject。"""
    projects = []
    for name, series in zip(get_research_name(image), get_research_series_3(image), strict=False):
        project = ResearchProject(name=name, series=series)
        logger.attr("Project", project)
        projects.append(project)
    return projects


def _research_project_numbers(prefix: str) -> frozenset[str]:
    numbers: set[str] = set()
    for row in LIST_RESEARCH_PROJECT:
        name = row["name"]
        if isinstance(name, str) and name.startswith(f"{prefix}-"):
            numbers.add(name.split("-")[1])
    return frozenset(numbers)


class ResearchProject:
    C_PROJECT_NUMBERS: ClassVar[frozenset[str]] = _research_project_numbers("C")
    D_PROJECT_NUMBERS: ClassVar[frozenset[str]] = _research_project_numbers("D")

    def __init__(self, name, series):
        self.valid = True
        self.raw_series = series
        self.series = f"S{series}"
        self.name = self.check_name(name)
        if self.name != name:
            logger.info(f"Research name {name} is revised to {self.name}")
        self.genre = ""
        self.number = ""
        self.duration = "24"
        self.ship = ""
        self.ship_rarity = ""
        self.need_coin = False
        self.need_cube = False
        self.need_part = False
        self._equipment_amount = 0

        matched = False
        for data in self.get_data(name=self.name, series=series):
            matched = True
            self.data = data
            self.genre = data["name"][0]
            self.number = data["name"][2:5]
            self.duration = str(data["time"] / 3600).rstrip(".0")
            self.need_coin = data.get("need_coin", False)
            self.need_cube = data.get("need_cube", False)
            self.need_part = data.get("need_part", False)
            self.ship = data.get("ship", "")
            self.ship_rarity = data.get("ship_rarity", "")
            self._equipment_amount = data.get("equipment_amount", 0)
            break

        if not matched:
            logger.warning(f"Invalid research {self}")
            self.valid = False

    def __str__(self):
        if self.valid:
            return f"{self.series} {self.name}"
        return f"{self.series} {self.name} (Invalid)"

    def __eq__(self, other):
        return str(self) == str(other)

    __hash__ = None

    def _normalize_project_number(self, prefix, number):
        number = number.replace("D", "0").replace("O", "0").replace("S", "5")
        # 已知 OCR 误识别：E-316-MI 应为 E-315-MI。
        number = number.replace("316", "315")
        # 台服 S5 会把 D-319-MI 识别为 D-349-MI。
        if prefix == "D" and number == "349" and self.raw_series == 5:
            return "319"
        return number

    @staticmethod
    def _normalize_project_suffix(suffix):
        # Drake 的白衣会让 S3 D-022-MI 后缀误识别为 ML。
        suffix = suffix.replace("ML", "MI").replace("MIL", "MI").replace("M1", "MI")
        # 白龙卡面会把 UL 识别为 0C；其他卡面也可能识别为 DC 或 UC。
        suffix = suffix.replace("0C", "UL").replace("UC", "UL")
        suffix = suffix.replace("DC5", "UL").replace("DC3", "UL").replace("DC", "UL")
        # 清理 UL 后的 OCR 尾字符。
        suffix = suffix.replace("UL1", "UL").replace("ULI", "UL").replace("UL5", "UL")
        if suffix == "U":
            return "UL"
        return suffix

    @classmethod
    def _normalize_project_prefix(cls, prefix, number, suffix) -> str:
        if prefix in ["I1", "U"]:
            prefix = "D"
        prefix = prefix.strip("I1")
        # LC-038-RF 应为 C-038-RF。
        prefix = prefix.replace("LC", "C")

        # 台服 OCR 会把 D 识别为 B。
        if prefix == "B" and number in cls.D_PROJECT_NUMBERS:
            # B-397-RF 与 S7 D-397-MI 共用编号，不能按编号改写。
            if number == "397" and suffix == "RF":
                return prefix
            return "D"
        # I-483-RF 清理前缀后为空，应恢复为 D-483-RF。
        if prefix == "" and number in cls.D_PROJECT_NUMBERS:
            return "D"
        # L-153-MI 应为 C-153-MI。
        if prefix == "L" and number in cls.C_PROJECT_NUMBERS:
            return "C"
        return prefix

    def _check_three_part_name(self, parts):
        prefix, number, suffix = parts
        number = self._normalize_project_number(prefix, number)
        suffix = self._normalize_project_suffix(suffix)
        prefix = self._normalize_project_prefix(prefix, number, suffix)
        return f"{prefix}-{number}-{suffix}"

    def check_name(self, name):
        name = name.strip("-")
        # G-185-MI、D-T85-MI 均为 C-185-MI 的已知误识别。
        name = name.replace("G-185", "C-185").replace("D-T85", "C-185")
        # 缺少前缀时仍修正 E-316-MI。
        if name == "316-MI":
            name = "E-315-MI"

        parts = name.split("-")
        parts = [i for i in parts if i]
        if len(parts) == 3:
            return self._check_three_part_name(parts)
        # 尝试插入 '-'，处理 H339-MI 这类结果。
        if len(parts) == 2 and name[0].isalpha() and name[1].isdigit():
            return self.check_name(f"{name[0]}-{name[1:]}")
        return name

    @staticmethod
    def _iter_research_data(name, series):
        for data in LIST_RESEARCH_PROJECT:
            if (data["series"] == series) and (data["name"] == name):
                yield data

    def _iter_similar_research_names(self, name):
        if len(name) and name[0].isdigit():
            for prefix in "QGE":
                yield f"{prefix}-{self.name}"
        if name.startswith("D"):
            # 卡片高光会把 C 识别为 D。
            yield "C" + self.name[1:]

    @staticmethod
    def _iter_research_data_by_trimmed_suffix(name, series):
        name = str(name)
        trimmed_name = name.rstrip("MIRFUL-")
        for data in LIST_RESEARCH_PROJECT:
            if (data["series"] == series) and (str(data["name"]).rstrip("MIRFUL-") == trimmed_name):
                yield data

    def get_data(self, name, series):
        """依次生成精确匹配、近似名称和忽略后缀后的项目数据。"""
        yield from self._iter_research_data(name, series)

        for candidate in self._iter_similar_research_names(name):
            logger.info(f"Testing the most similar candidate {candidate}")
            for data in self._iter_research_data(candidate, series):
                self.name = candidate
                yield data

        yield from self._iter_research_data_by_trimmed_suffix(name, series)

    @cached_property
    def equipment_amount(self):
        return self._equipment_amount
