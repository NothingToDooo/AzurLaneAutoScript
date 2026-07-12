import hashlib
import re
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Literal

import cv2
import numpy as np

from module.base.button import Button
from module.base.filter import Filter
from module.base.utils import area_offset, color_similar, crop, extract_letters, get_color
from module.commission.project_data import dictionary_cn
from module.logger import logger
from module.ocr.ocr import Duration, Ocr

if TYPE_CHECKING:
    from module.base.type_alias import Area, ImageArray
    from module.config.config import AzurLaneConfig

type CommissionStatus = Literal["finished", "running", "pending"]

COMMISSION_COMPARE_THRESHOLD = timedelta(seconds=120)
URGENT_BOX_TAGS = ("NYB", "BIW")

COMMISSION_FILTER: Filter[Commission] = Filter(
    regex=re.compile(
        r"(major|daily|extra|urgent|night)?"
        r"-?"
        r"(resource|chip|event|drill|part|cube|oil|book|retrofit|box|gem|ship)?"
        r"-?"
        r"(\d\d?:\d\d)?"
        r"(\d\d?.\d\d?|\d\d?)?"
    ),
    attr=("category_str", "genre_str", "duration_hm", "duration_hour"),
    preset=("shortest",),
)


def crop_suffix_image(image: ImageArray, area: Area) -> ImageArray | None:
    """裁剪委托名的黑字白底后缀；无后缀时返回 None。"""
    name_image = crop(image, area)
    name_image = extract_letters(name_image, letter=(255, 255, 255), threshold=128).astype(np.uint8)

    line = cv2.reduce(name_image[5:-5, :], 0, cv2.REDUCE_AVG).flatten()
    columns = np.where(line < 250)[0]
    if not len(columns):
        return None

    # 从最右侧字符向左回看几个像素，确保罗马数字后缀被包含。
    threshold = 250
    look_back = 10
    rightmost = columns[-1]
    for i in range(rightmost, 0, -1):
        gap = rightmost - i
        if line[i] > threshold and gap > look_back:
            look_back = gap
            break

    left = rightmost - look_back
    right = rightmost + 1
    x1, y1 = area[0:2]
    suffix_area = area_offset((left - 3, -3, right + 3, name_image.shape[0] + 3), (x1, y1))
    image = crop(image, suffix_area)
    return extract_letters(image, letter=(255, 255, 255), threshold=128).astype(np.uint8)


def image_hash(image: ImageArray | None) -> str:
    if image is None:
        return ""

    return hashlib.md5(image.tobytes(), usedforsecurity=False).hexdigest()


class Commission:
    button: Button
    name: str
    valid: bool
    # 裁剪后的后缀图，黑字白底；没有后缀时为 None。
    suffix_image: ImageArray | None
    suffix_hash: str
    genre: str
    # 状态值为 finished、running、pending。
    status: CommissionStatus
    duration: timedelta
    expire: timedelta
    # 过滤分类为 major、daily、extra、urgent、night。
    category_str: str
    # 过滤类型为 resource、chip、event、drill、part、cube 等。
    genre_str: str
    duration_hour: str
    duration_hm: str

    def __init__(self, image: ImageArray, y: int, config: AzurLaneConfig) -> None:
        self.config = config
        self.y = y
        self.area = (188, y - 119, 1199, y)
        self.image = image
        self.valid = True
        self.commission_parse()

        if not self.duration.total_seconds():
            self.valid = False

        self.create_time = datetime.now()
        self.repeat_count = 1
        self.category_str = "unknown"
        self.genre_str = "unknown"
        self.duration_hour = "unknown"
        self.duration_hm = "unknown"
        if self.valid:
            self.category_str, self.genre_str = self.genre.split("_", 1)
            self.duration_hour = str(int(self.duration.total_seconds() / 36) / 100).strip(".0")
            self.duration_hm = str(self.duration).rsplit(":", 1)[0]

    def commission_parse(self) -> None:
        area = area_offset((176, 23, 420, 53), self.area[0:2])
        button = Button(area=area, color=(), button=area, name="COMMISSION")
        ocr = Ocr(button, lang="cnocr", threshold=256)
        self.button = button
        result = ocr.ocr_single(self.image).upper()
        self.name = result
        self.genre = self.commission_name_parse(self.name)

        self.suffix_image = crop_suffix_image(self.image, self.button.area)
        self.suffix_hash = image_hash(self.suffix_image)

        area = area_offset((290, 68, 390, 95), self.area[0:2])
        button = Button(area=area, color=(), button=area, name="DURATION")
        ocr = Duration(button)
        self.duration = ocr.ocr_single(self.image)

        area = area_offset((-49, 68, -45, 84), self.area[0:2])
        button = Button(area=area, color=(189, 65, 66), button=area, name="IS_URGENT")
        if button.appear_on(self.image, threshold=30):
            area = area_offset((-49, 67, 45, 94), self.area[0:2])
            button = Button(area=area, color=(), button=area, name="EXPIRE")
            ocr = Duration(button)
            self.expire = ocr.ocr_single(self.image)
        else:
            self.expire = timedelta(seconds=0)

        area = area_offset((179, 71, 187, 93), self.area[0:2])
        statuses: dict[int, CommissionStatus] = {0: "finished", 1: "running", 2: "pending"}
        color = np.array(get_color(self.image, area))
        if self.genre == "daily_event":
            color -= [50, 30, 20]
        self.status = statuses[int(np.argmax(color))]

    def __str__(self) -> str:
        name = f"{self.name} | {self.suffix_hash}" if self.suffix_hash else self.name
        if not self.valid:
            return f"{name} (Invalid)"
        info = {"Genre": self.genre, "Status": self.status, "Duration": self.duration}
        if self.expire:
            info["Expire"] = self.expire
        if self.repeat_count > 1:
            info["Repeat"] = self.repeat_count
        info = ", ".join([f"{k}: {v}" for k, v in info.items()])
        return f"{name} ({info})"

    @staticmethod
    def _timedelta_close(left: timedelta, right: timedelta) -> bool:
        return left - COMMISSION_COMPARE_THRESHOLD <= right <= left + COMMISSION_COMPARE_THRESHOLD

    def _expire_matches(self, other: Commission) -> bool:
        if bool(self.expire) != bool(other.expire):
            return False
        return not self.expire or self._timedelta_close(self.expire, other.expire)

    def _urgent_box_tags_match(self, other: Commission) -> bool:
        self_name = self.name.upper()
        other_name = other.name.upper()
        return all((tag in self_name) == (tag in other_name) for tag in URGENT_BOX_TAGS)

    def _suffix_required_match(self, other: Commission) -> bool:
        if self.category_str == "daily":
            return self.suffix_match(other)
        if self.genre in {"extra_oil", "night_oil"}:
            return self.suffix_match(other)
        return True

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Commission):
            return False

        return (
            self.valid
            and other.valid
            and self.genre == other.genre
            and self.status == other.status
            and (self.genre != "urgent_box" or self._urgent_box_tags_match(other))
            and self._timedelta_close(self.duration, other.duration)
            and self._expire_matches(other)
            and self.repeat_count == other.repeat_count
            and self._suffix_required_match(other)
        )

    def __hash__(self) -> int:
        return hash(f"{self.genre}_{self.name}")

    def suffix_match(self, other: Commission, similarity: float = 0.75) -> bool:
        if self.suffix_image is None and other.suffix_image is None:
            return True
        if self.suffix_image is None or other.suffix_image is None:
            return False

        def match(image: ImageArray, template: ImageArray) -> float:
            template = crop(template, (3, 3, template.shape[1] - 3, template.shape[0] - 3), copy=False)
            if image.shape[0] < template.shape[0] or image.shape[1] < template.shape[1]:
                return 0.0

            res = cv2.matchTemplate(image, template, cv2.TM_CCOEFF_NORMED)
            _, sim, _, _ = cv2.minMaxLoc(res)
            return sim

        sim = max(match(self.suffix_image, other.suffix_image), match(other.suffix_image, self.suffix_image))
        return sim >= similarity

    def parse_time(self, string: str) -> timedelta | None:
        """解析 HH:MM:SS；无效时标记委托无效并返回 None。"""
        string = string.replace("D", "0")  # OCR 会把 0 识别为 D。
        result = re.search(r"(\d+):(\d+):(\d+)", string)
        if not result:
            logger.warning(f"Invalid time string: {string}")
            self.valid = False
            return None
        result = [int(s) for s in result.groups()]
        return timedelta(hours=result[0], minutes=result[1], seconds=result[2])

    def commission_name_parse(self, string: str) -> str:
        """把委托名解析为 urgent_gem 等类型；未知名称会标记为无效。"""
        if self.is_event_commission():
            return "daily_event"
        for key, value in dictionary_cn.items():
            for keyword in value:
                if keyword in string:
                    return key

        logger.warning(f"Name with unknown genre: {string}")
        self.valid = False
        return ""

    def is_event_commission(self) -> bool:
        # 2023.04.27 Vacation Lane 复刻，粉黄渐变类似偶像大师活动。
        area = area_offset((5, 5, 30, 30), self.area[0:2])
        return color_similar(color1=get_color(self.image, area), color2=(235, 173, 161), threshold=30)

    def convert_to_night(self) -> None:
        if self.valid and self.category_str == "extra":
            self.category_str = "night"
            self.genre = f"{self.category_str}_{self.genre_str}"

    def convert_to_running(self) -> None:
        if self.valid:
            self.status = "running"
            self.create_time = datetime.now()

    @property
    def finish_time(self) -> datetime | None:
        if self.valid and self.status == "running":
            return (self.create_time + self.duration).replace(microsecond=0)
        return None

    @staticmethod
    def beautify_name(name: str) -> str:
        name = name.strip()
        name = re.sub(r"VI$", "Ⅵ", name)
        name = re.sub(r"IV$", "Ⅳ", name)
        name = re.sub(r"V$", "Ⅴ", name)
        name = re.sub(r"III$", "Ⅲ", name)
        name = re.sub(r"II$", "Ⅱ", name)
        return re.sub(r"I$", "Ⅰ", name)
