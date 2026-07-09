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
    r"""
    Get research series using a simple color detection.
    Counting white lines to detect Roman numerals.

    -------               --- --   --
     | | |   --> 3 lines   |   \   /   --> 3 lines
     | | |                 |   \   /
     | | |   --> 3 lines   |    \ /    --> 2 lines
    -------               ---    v

    Args:
        image (np.ndarray):
        series_button:

    Returns:
        list[int]: Such as [1, 1, 1, 2, 3]
    """
    result = []
    # Set 'prominence = 50' to ignore possible noise.
    # 2021.07.18 Letter IV is now smaller than I, II, III, since the maintenance in 07.15.
    #   The "/" of the "V" in IV become darker because of anti-aliasing.
    #   So lower height to 160 to have a better detection.
    parameters = {"height": 160, "prominence": 50, "width": 1}

    for button in series_button:
        im = color_similarity_2d(resize(crop(image, button.area, copy=False), (46, 25)), color=(255, 255, 255))
        peaks = [len(signal.find_peaks(row, **parameters)[0]) for row in im[5:-5]]
        upper, lower = max(peaks), min(peaks)

        # Remove noise like [2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 3, 2]
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
    """
    Args:
        image (np.ndarray):
        series_button:

    Returns:
        list[int]: Such as [1, 1, 1, 2, 3]
    """
    result = []
    for button in series_button:
        img = crop(image, button.area, copy=False)
        img = cv2.resize(img, (46, 25), interpolation=cv2.INTER_AREA)
        series = _get_research_series(img)
        result.append(series)
    return result


def get_research_name(image, ocr=OCR_RESEARCH):
    """
    Args:
        image (np.ndarray):
        ocr (Ocr):

    Returns:
        list[str]: Such as ['D-057-UL', 'D-057-UL', 'D-057-UL', 'D-057-UL', 'D-057-UL']
    """
    names = ocr.ocr(image)
    if not isinstance(names, list):
        names = [names]
    return names


def get_research_finished(image):
    """
    Args:
        image (np.ndarray):

    Returns:
        int: Index of the finished project, 0 to 4. Return None if no project finished.
    """
    for index in [2, 1, 3, 0, 4]:
        button = RESEARCH_STATUS[index]
        color = get_color(image, button.area)
        if max(color) - min(color) < 40:
            logger.warning(f"Unexpected color: {color}")
            continue
        color_index = np.argmax(color)  # RGB 通道索引。
        if color_index == 1:
            return index  # 绿色。
        if color_index == 2:
            continue  # 蓝色。
        logger.warning(f"Unexpected color: {color}")
        continue

    return None


def parse_time(string):
    """
    Args:
        string (str): Such as 01:00:00, 05:47:10, 17:50:51.

    Returns:
        timedelta: datetime.timedelta instance.
    """
    result = re.search(r"(\d+):(\d+):(\d+)", string)
    if not result:
        logger.warning(f"Invalid time string: {string}")
        return None
    result = [int(s) for s in result.groups()]
    return timedelta(hours=result[0], minutes=result[1], seconds=result[2])


def research_detect(image):
    """
    Args:
        image (np.ndarray): Screenshot

    Return:
        list[ResearchProject]:
    """
    projects = []
    for name, series in zip(get_research_name(image), get_research_series_3(image), strict=False):
        project = ResearchProject(name=name, series=series)
        logger.attr("Project", project)
        projects.append(project)
    return projects


class ResearchProject:
    # 生成方式：
    """
    out = []
    for row in LIST_RESEARCH_PROJECT:
        name = row['name']
        if name.startswith('D'):
            number = name.split('-')[1]
            out.append(number)
    print(out)
    """

    C_PROJECT_NUMBERS: ClassVar[tuple[str, ...]] = ("153", "185", "038")
    D_PROJECT_NUMBERS: ClassVar[tuple[str, ...]] = (
        "718",
        "731",
        "744",
        "759",
        "774",
        "792",
        "318",
        "331",
        "344",
        "359",
        "374",
        "392",
        "705",
        "712",
        "746",
        "757",
        "779",
        "794",
        "305",
        "312",
        "346",
        "357",
        "379",
        "394",
        "721",
        "722",
        "772",
        "777",
        "795",
        "321",
        "322",
        "372",
        "377",
        "395",
        "708",
        "763",
        "775",
        "782",
        "768",
        "308",
        "363",
        "375",
        "382",
        "368",
        "719",
        "778",
        "786",
        "788",
        "793",
        "319",
        "378",
        "386",
        "388",
        "393",
        "783",
        "713",
        "739",
        "771",
        "796",
        "383",
        "313",
        "339",
        "371",
        "396",
        "703",
        "758",
        "766",
        "790",
        "797",
        "303",
        "358",
        "366",
        "390",
        "397",
        "780",
        "736",
        "787",
        "711",
        "764",
        "380",
        "336",
        "387",
        "311",
        "364",
        "418",
        "431",
        "444",
        "459",
        "474",
        "492",
        "018",
        "031",
        "044",
        "059",
        "074",
        "092",
        "405",
        "412",
        "446",
        "457",
        "479",
        "494",
        "005",
        "012",
        "046",
        "057",
        "079",
        "094",
        "421",
        "422",
        "472",
        "477",
        "495",
        "021",
        "022",
        "072",
        "077",
        "095",
        "408",
        "463",
        "475",
        "482",
        "468",
        "008",
        "063",
        "075",
        "082",
        "068",
        "419",
        "478",
        "486",
        "488",
        "493",
        "019",
        "078",
        "086",
        "088",
        "093",
        "483",
        "413",
        "439",
        "471",
        "496",
        "083",
        "013",
        "039",
        "071",
        "096",
        "403",
        "458",
        "466",
        "490",
        "497",
        "003",
        "058",
        "066",
        "090",
        "097",
        "480",
        "436",
        "487",
        "411",
        "464",
        "080",
        "036",
        "087",
        "011",
        "064",
    )

    def __init__(self, name, series):
        """
        Args:
            name (str): Such as 'D-057-UL'
            series (int): Such as 1, 2, 3
        """
        self.valid = True
        # '4'
        self.raw_series = series
        # 'S4'
        self.series = f"S{series}"
        # 'D-057-UL'
        self.name = self.check_name(name)
        if self.name != name:
            logger.info(f"Research name {name} is revised to {self.name}")
        # 'D'
        self.genre = ""
        # '057'
        self.number = ""
        # '0.5'
        self.duration = "24"
        # Ship face, like 'Azuma'
        self.ship = ""
        # 'dr' or 'pry'
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
        # E-316-MI -> E-315-MI
        number = number.replace("316", "315")
        # [TW] S5 D-349-MI -> S5 D-319-MI
        if prefix == "D" and number == "349" and self.raw_series == 5:
            return "319"
        return number

    @staticmethod
    def _normalize_project_suffix(suffix):
        # S3 D-022-MI (S3-Drake-0.5) detected as 'D-022-ML', because of Drake's white cloth.
        suffix = suffix.replace("ML", "MI").replace("MIL", "MI").replace("M1", "MI")
        # S4 D-063-UL (S4-hakuryu-0.5) detected as 'D-063-0C'
        # D-057-DC -> D-057-UL
        suffix = suffix.replace("0C", "UL").replace("UC", "UL")
        suffix = suffix.replace("DC5", "UL").replace("DC3", "UL").replace("DC", "UL")
        # D-075-UL1 -> D-075-UL
        suffix = suffix.replace("UL1", "UL").replace("ULI", "UL").replace("UL5", "UL")
        if suffix == "U":
            return "UL"
        return suffix

    @classmethod
    def _normalize_project_prefix(cls, prefix, number, suffix) -> str:
        if prefix in ["I1", "U"]:
            prefix = "D"
        prefix = prefix.strip("I1")
        # LC-038-RF -> C-038-RF
        prefix = prefix.replace("LC", "C")

        # TW ocr errors, convert B to D
        if prefix == "B" and number in cls.D_PROJECT_NUMBERS:
            # Keep B-397-RF, S7 D-397-MI and S* B-397-RF shares 397
            if number == "397" and suffix == "RF":
                return prefix
            return "D"
        # I-483-RF revised to -483-RF -> D-483-RF
        if prefix == "" and number in cls.D_PROJECT_NUMBERS:
            return "D"
        # L-153-MI -> C-153-MI
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
        """
        Args:
            name (str):

        Returns:
            str:
        """
        name = name.strip("-")
        # G-185-MI, D-T85-MI -> C-185-MI
        name = name.replace("G-185", "C-185").replace("D-T85", "C-185")
        # E-316-MI -> E-315-MI
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
            # Letter 'C' may recognized as 'D', because project card is shining.
            yield "C" + self.name[1:]

    @staticmethod
    def _iter_research_data_by_trimmed_suffix(name, series):
        name = str(name)
        trimmed_name = name.rstrip("MIRFUL-")
        for data in LIST_RESEARCH_PROJECT:
            if (data["series"] == series) and (str(data["name"]).rstrip("MIRFUL-") == trimmed_name):
                yield data

    def get_data(self, name, series):
        """
        Args:
            name (str): Such as 'D-057-UL'
            series (int): Such as 1, 2, 3

        Yields:
            dict:
        """
        yield from self._iter_research_data(name, series)

        for candidate in self._iter_similar_research_names(name):
            logger.info(f"Testing the most similar candidate {candidate}")
            for data in self._iter_research_data(candidate, series):
                self.name = candidate
                yield data

        yield from self._iter_research_data_by_trimmed_suffix(name, series)
        return False

    @cached_property
    def equipment_amount(self):
        return self._equipment_amount
