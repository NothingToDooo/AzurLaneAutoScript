import hashlib
import re
from datetime import datetime, timedelta

import cv2
import numpy as np

from module.base.button import Button
from module.base.filter import Filter
from module.base.utils import area_offset, color_similar, crop, extract_letters, get_color
from module.commission.project_data import dictionary_cn
from module.logger import logger
from module.ocr.ocr import Duration, Ocr

COMMISSION_COMPARE_THRESHOLD = timedelta(seconds=120)
URGENT_BOX_TAGS = ("NYB", "BIW")

COMMISSION_FILTER = Filter(
    regex=re.compile(
        "(major|daily|extra|urgent|night)?"
        "-?"
        "(resource|chip|event|drill|part|cube|oil|book|retrofit|box|gem|ship)?"
        "-?"
        r"(\d\d?:\d\d)?"
        r"(\d\d?.\d\d?|\d\d?)?"
    ),
    attr=("category_str", "genre_str", "duration_hm", "duration_hour"),
    preset=("shortest",),
)


def crop_suffix_image(image, area):
    """
    Args:
        image (np.ndarray):
        area (tuple): Commission name area.

    Returns:
        np.ndarray | None: Cropped suffix image, black letters on white background.
    """
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


def image_hash(image):
    """
    Args:
        image (np.ndarray):

    Returns:
        str:
    """
    if image is None:
        return ""

    return hashlib.md5(image.tobytes(), usedforsecurity=False).hexdigest()


class Commission:
    # 进入委托开始页的按钮。
    button: Button
    # OCR 结果。
    name: str
    # 委托名是否解析成功。
    valid: bool
    # 裁剪后的后缀图，黑字白底；没有后缀时为 None。
    suffix_image: np.ndarray
    # 后缀图 hash，仅用于日志；没有后缀时为空字符串。
    suffix_hash: str
    # project_data.py 中的委托类型名，例如 major_comm、daily_resource。
    genre: str
    # 委托状态：finished、running、pending。
    status: str
    # 委托耗时。
    duration: timedelta
    # 紧急委托的过期时间，其他委托为 None。
    expire: timedelta
    # 过滤分类：major、daily、extra、urgent、night。
    category_str: str
    # 过滤类型：resource、chip、event、drill、part、cube 等。
    genre_str: str
    # 小时形式的耗时。
    duration_hour: str
    # HH:MM 形式的耗时。
    duration_hm: str

    def __init__(self, image, y, config):
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

    def commission_parse(self):
        # Name
        area = area_offset((176, 23, 420, 53), self.area[0:2])
        button = Button(area=area, color=(), button=area, name="COMMISSION")
        ocr = Ocr(button, lang="cnocr", threshold=256)
        self.button = button
        result = ocr.ocr(self.image).upper()
        self.name = result
        self.genre = self.commission_name_parse(self.name)

        # Suffix
        self.suffix_image = crop_suffix_image(self.image, self.button.area)
        self.suffix_hash = image_hash(self.suffix_image)

        # Duration time
        area = area_offset((290, 68, 390, 95), self.area[0:2])
        button = Button(area=area, color=(), button=area, name="DURATION")
        ocr = Duration(button)
        self.duration = ocr.ocr(self.image)

        # Expire time
        area = area_offset((-49, 68, -45, 84), self.area[0:2])
        button = Button(area=area, color=(189, 65, 66), button=area, name="IS_URGENT")
        if button.appear_on(self.image, threshold=30):
            area = area_offset((-49, 67, 45, 94), self.area[0:2])
            button = Button(area=area, color=(), button=area, name="EXPIRE")
            ocr = Duration(button)
            self.expire = ocr.ocr(self.image)
        else:
            self.expire = timedelta(seconds=0)

        # Status
        area = area_offset((179, 71, 187, 93), self.area[0:2])
        dic = {0: "finished", 1: "running", 2: "pending"}
        color = np.array(get_color(self.image, area))
        if self.genre == "daily_event":
            color -= [50, 30, 20]
        self.status = dic[int(np.argmax(color))]

    def __str__(self):
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
    def _timedelta_close(left, right):
        return left - COMMISSION_COMPARE_THRESHOLD <= right <= left + COMMISSION_COMPARE_THRESHOLD

    def _expire_matches(self, other):
        if bool(self.expire) != bool(other.expire):
            return False
        return not self.expire or self._timedelta_close(self.expire, other.expire)

    def _urgent_box_tags_match(self, other):
        self_name = self.name.upper()
        other_name = other.name.upper()
        return all((tag in self_name) == (tag in other_name) for tag in URGENT_BOX_TAGS)

    def _suffix_required_match(self, other):
        if self.category_str == "daily":
            return self.suffix_match(other)
        if self.genre in {"extra_oil", "night_oil"}:
            return self.suffix_match(other)
        return True

    def __eq__(self, other):
        """
        Args:
            other (Commission):

        Returns:
            bool:
        """
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

    def __hash__(self):
        return hash(f"{self.genre}_{self.name}")

    def suffix_match(self, other, similarity=0.75):
        """
        Args:
            other (Commission):
            similarity (float): 0-1. Similarity.

        Returns:
            bool:
        """
        if self.suffix_image is None and other.suffix_image is None:
            return True
        if self.suffix_image is None or other.suffix_image is None:
            return False

        def match(image, template):
            template = crop(template, (3, 3, template.shape[1] - 3, template.shape[0] - 3), copy=False)
            if image.shape[0] < template.shape[0] or image.shape[1] < template.shape[1]:
                return 0.0

            res = cv2.matchTemplate(image, template, cv2.TM_CCOEFF_NORMED)
            _, sim, _, _ = cv2.minMaxLoc(res)
            return sim

        sim = max(match(self.suffix_image, other.suffix_image), match(other.suffix_image, self.suffix_image))
        return sim >= similarity

    def parse_time(self, string):
        """
        Args:
            string (str): Such as 01:00:00, 05:47:10, 17:50:51.

        Returns:
            timedelta: datetime.timedelta instance.
        """
        string = string.replace("D", "0")  # Poor OCR
        result = re.search(r"(\d+):(\d+):(\d+)", string)
        if not result:
            logger.warning(f"Invalid time string: {string}")
            self.valid = False
            return None
        result = [int(s) for s in result.groups()]
        return timedelta(hours=result[0], minutes=result[1], seconds=result[2])

    def commission_name_parse(self, string):
        """
        Args:
            string (str): Commission name, such as 'NYB要员护卫'.

        Returns:
            str: Commission genre, such as 'urgent_gem'.
        """
        if self.is_event_commission():
            return "daily_event"
        for key, value in dictionary_cn.items():
            for keyword in value:
                if keyword in string:
                    return key

        logger.warning(f"Name with unknown genre: {string}")
        self.valid = False
        return ""

    def is_event_commission(self):
        """
        Returns:
            bool:
        """
        # 2023.04.27 Vacation Lane 复刻，粉黄渐变类似偶像大师活动。
        area = area_offset((5, 5, 30, 30), self.area[0:2])
        return color_similar(color1=get_color(self.image, area), color2=(235, 173, 161), threshold=30)

    def convert_to_night(self):
        if self.valid and self.category_str == "extra":
            self.category_str = "night"
            self.genre = f"{self.category_str}_{self.genre_str}"

    def convert_to_running(self):
        if self.valid:
            self.status = "running"
            self.create_time = datetime.now()

    @property
    def finish_time(self):
        if self.valid and self.status == "running":
            return (self.create_time + self.duration).replace(microsecond=0)
        return None

    @staticmethod
    def beautify_name(name):
        name = name.strip()
        name = re.sub(r"VI$", "Ⅵ", name)
        name = re.sub(r"IV$", "Ⅳ", name)
        name = re.sub(r"V$", "Ⅴ", name)
        name = re.sub(r"III$", "Ⅲ", name)
        name = re.sub(r"II$", "Ⅱ", name)
        return re.sub(r"I$", "Ⅰ", name)
