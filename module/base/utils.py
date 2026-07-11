import random
import re
from dataclasses import dataclass

import cv2
import numpy as np
from PIL import Image

REGEX_NODE = re.compile(r"(-?[A-Za-z]+)(-?\d+)")


@dataclass(slots=True)
class SwipePathOptions:
    box: object
    random_range: tuple[int, int, int, int] = (0, 0, 0, 0)
    padding: int = 15
    whitelist_area: object = None
    blacklist_area: object = None


@dataclass(slots=True)
class ColorBarOptions:
    reverse: bool = False
    starter: int = 0
    threshold: int = 30


def _cv_scalar(value) -> np.ndarray:
    return np.asarray(value)


def random_normal_distribution_int(a, b, n=3):
    """取 n 个闭区间 [a, b] 内均匀随机整数的均值，得到近似正态分布的整数。"""
    a = round(a)
    b = round(b)
    if a < b:
        total = 0
        for _ in range(n):
            total += random.randint(a, b)
        return round(total / n)
    return b


def random_rectangle_point(area, n=3):
    """在左上、右下坐标定义的区域内返回近似正态分布的 (x, y)。"""
    x = random_normal_distribution_int(area[0], area[2], n=n)
    y = random_normal_distribution_int(area[1], area[3], n=n)
    return x, y


def random_rectangle_vector(vector, box, random_range=(0, 0, 0, 0), padding=15):
    """在 box 内随机放置带扰动的 vector，返回起点和终点。

    box 与 random_range 均为左上、右下坐标，padding 保证两端远离边界。
    """
    vector = np.array(vector) + random_rectangle_point(random_range)
    vector = np.round(vector).astype(int)
    half_vector = np.round(vector / 2).astype(int)
    box = np.array(box) + np.append(np.abs(half_vector) + padding, -np.abs(half_vector) - padding)
    center = random_rectangle_point(box)
    start_point = center - half_vector
    end_point = start_point + vector
    return tuple(start_point), tuple(end_point)


def _swipe_path_in_blacklist(end_point, vector, blacklist_area, segment):
    if not blacklist_area:
        return False
    for index in range(segment + 1):
        point = -vector * index / segment + end_point
        if any(point_in_area(point, area, threshold=0) for area in blacklist_area):
            return True
    return False


def _limited_swipe_points(end_point, vector, box):
    return point_limit(end_point - vector, box), point_limit(end_point, box)


def _random_end_point_in_whitelist(vector, box_pad, whitelist_area, blacklist_area, segment):
    for raw_area in whitelist_area:
        area = area_limit(raw_area, box_pad)
        if not all(size > 0 for size in area_size(area)):
            continue

        end_point = random_rectangle_point(area)
        for _ in range(10):
            if _swipe_path_in_blacklist(end_point, vector, blacklist_area, segment):
                continue
            return end_point
    return None


def _random_end_point_outside_blacklist(box_pad, vector, blacklist_area, segment):
    for _ in range(100):
        end_point = random_rectangle_point(box_pad)
        if _swipe_path_in_blacklist(end_point, vector, blacklist_area, segment):
            continue
        return end_point
    return random_rectangle_point(box_pad)


def random_rectangle_vector_opted(vector, options):
    """在指定区域内随机放置滑动向量，返回起点和终点。

    卡顿时滑动可能退化成终点点击，因此终点和路径会按白名单、黑名单过滤。
    """
    vector = np.array(vector) + random_rectangle_point(options.random_range)
    vector = np.round(vector).astype(int)
    half_vector = np.round(vector / 2).astype(int)
    box_pad = np.array(options.box) + np.append(
        np.abs(half_vector) + options.padding, -np.abs(half_vector) - options.padding
    )
    box_pad = area_offset(box_pad, half_vector)
    segment = int(np.linalg.norm(vector) // 70) + 1

    if options.whitelist_area:
        end_point = _random_end_point_in_whitelist(
            vector, box_pad, options.whitelist_area, options.blacklist_area, segment
        )
        if end_point is not None:
            return _limited_swipe_points(end_point, vector, options.box)

    end_point = _random_end_point_outside_blacklist(box_pad, vector, options.blacklist_area, segment)
    return _limited_swipe_points(end_point, vector, options.box)


def random_line_segments(p1, p2, n, random_range=(0, 0, 0, 0)):
    """把 p1 到 p2 均分为 n 段，并为每个点叠加 random_range 内的随机偏移。"""
    return [
        tuple((((n - index) * p1 + index * p2) / n).astype(int) + random_rectangle_point(random_range))
        for index in range(n + 1)
    ]


def ensure_time(second, n=3, precision=3):
    """把秒数或 `10,30`、`10-30`、(10, 30) 归一化为秒；区间按近似正态分布取值。"""
    if isinstance(second, tuple):
        multiply = 10**precision
        result = random_normal_distribution_int(second[0] * multiply, second[1] * multiply, n) / multiply
        return round(result, precision)
    if isinstance(second, str):
        if "," in second:
            lower, upper = second.replace(" ", "").split(",")
            lower, upper = int(lower), int(upper)
            return ensure_time((lower, upper), n=n, precision=precision)
        if "-" in second:
            lower, upper = second.replace(" ", "").split("-")
            lower, upper = int(lower), int(upper)
            return ensure_time((lower, upper), n=n, precision=precision)
        return int(second)
    return second


def ensure_int(*args):
    """递归转换为整数，并保留嵌套结构；单元素层会被折叠。"""

    def to_int(item):
        try:
            return int(item)
        except TypeError:
            result = [to_int(i) for i in item]
            if len(result) == 1:
                result = result[0]
            return result

    return to_int(args)


def area_offset(area, offset):
    """把 (x1, y1, x2, y2) 区域平移 (x, y)。"""
    upper_left_x, upper_left_y, bottom_right_x, bottom_right_y = area
    x, y = offset
    return upper_left_x + x, upper_left_y + y, bottom_right_x + x, bottom_right_y + y


def area_pad(area, pad=10):
    """把 (x1, y1, x2, y2) 区域四边向内收缩 pad。"""
    upper_left_x, upper_left_y, bottom_right_x, bottom_right_y = area
    return upper_left_x + pad, upper_left_y + pad, bottom_right_x - pad, bottom_right_y - pad


def limit_in(x, lower, upper):
    return max(min(x, upper), lower)


def area_limit(area1, area2):
    """逐坐标把 area1 限制在 area2 的 (x1, y1, x2, y2) 范围内。"""
    x_lower, y_lower, x_upper, y_upper = area2
    return (
        limit_in(area1[0], x_lower, x_upper),
        limit_in(area1[1], y_lower, y_upper),
        limit_in(area1[2], x_lower, x_upper),
        limit_in(area1[3], y_lower, y_upper),
    )


def area_size(area):
    """返回 (width, height)，反向或空区域的对应维度为 0。"""
    return (max(area[2] - area[0], 0), max(area[3] - area[1], 0))


def point_limit(point, area):
    """把 (x, y) 逐坐标限制在 (x1, y1, x2, y2) 区域内。"""
    return (limit_in(point[0], area[0], area[2]), limit_in(point[1], area[1], area[3]))


def point_in_area(point, area, threshold=5):
    """判断点是否落入区域；threshold 会向四边扩张区域。"""
    return area[0] - threshold < point[0] < area[2] + threshold and area[1] - threshold < point[1] < area[3] + threshold


def area_in_area(area1, area2, threshold=5):
    """判断 area1 是否包含在 area2 内；threshold 会向四边扩张 area2。"""
    return (
        area2[0] - threshold <= area1[0]
        and area2[1] - threshold <= area1[1]
        and area1[2] <= area2[2] + threshold
        and area1[3] <= area2[3] + threshold
    )


def area_cross_area(area1, area2, threshold=5):
    """判断两个区域是否相交；threshold 会扩张允许的相交距离。"""
    xa1, ya1, xa2, ya2 = area1
    xb1, yb1, xb2, yb2 = area2
    return (
        abs(xb2 + xb1 - xa2 - xa1) <= xa2 - xa1 + xb2 - xb1 + threshold * 2
        and abs(yb2 + yb1 - ya2 - ya1) <= ya2 - ya1 + yb2 - yb1 + threshold * 2
    )


def float2str(n, decimal=3):
    return str(round(n, decimal)).ljust(decimal + 2, "0")


def point2str(x, y, length=4):
    """把坐标右对齐为 `( 100,   80)` 形式，每个数字宽度为 length。"""
    return f"({str(int(x)).rjust(length)}, {str(int(y)).rjust(length)})"


def col2name(col):
    """把从零开始的列索引转为 A1 列名；例如 0→A、35→AJ、-1→-A。"""
    col_neg = col < 0
    col_num = -col if col_neg else col + 1
    col_str = ""

    while col_num:
        remainder = col_num % 26

        if remainder == 0:
            remainder = 26

        col_letter = chr(remainder + 64)

        col_str = col_letter + col_str

        col_num = int((col_num - 1) / 26)

    if col_neg:
        return "-" + col_str
    return col_str


def name2col(col_str):
    """把 A1 列名转为从零开始的列索引，并支持负列名。"""
    col = 0
    col_neg = col_str.startswith("-")
    col_str = col_str.strip("-").upper()

    for expn, char in enumerate(reversed(col_str)):
        col += (ord(char) - 64) * (26**expn)

    if col_neg:
        return -col
    return col - 1


def node2location(node):
    """把 A1 风格节点转为从零开始的 (x, y)，例如 E3→(4, 2)。"""
    res = REGEX_NODE.search(node)
    if res:
        x, y = res.group(1), res.group(2)
        y = int(y)
        if y > 0:
            y -= 1
        return name2col(x), y
    return ord(node[0]) % 32 - 1, int(node[1:]) - 1


def location2node(location):
    """把从零开始的 (x, y) 转为 A1 风格节点，并支持负坐标。"""
    x, y = location
    if y >= 0:
        y += 1
    return col2name(x) + str(y)


def xywh2xyxy(area):
    x, y, w, h = area
    return x, y, x + w, y + h


def xyxy2xywh(area):
    x1, y1, x2, y2 = area
    return min(x1, x2), min(y1, y2), abs(x2 - x1), abs(y2 - y1)


def load_image(file, area=None):
    """按 Pillow 语义读取并可选裁剪图片，RGBA 输入会丢弃 Alpha 通道。"""
    with Image.open(file) as image_file:
        image = np.array(image_file.crop(area)) if area is not None else np.array(image_file)

    channel = image_channel(image)
    if channel == 4:
        image = cv2.cvtColor(image, cv2.COLOR_RGBA2RGB)

    return image


def save_image(image, file):
    Image.fromarray(image).save(file)


def copy_image(src):
    dst = np.empty_like(src)
    np.copyto(dst, src)
    return dst


def _round_area(area):
    x1, y1, x2, y2 = area
    return round(x1), round(y1), round(x2), round(y2)


def _crop_output_shape(image_shape, area):
    x1, y1, x2, y2 = area
    shape = (y2 - y1, x2 - x1)
    if len(image_shape) == 2:
        return shape
    return (*shape, image_shape[2])


def _crop_padding_and_overflow(image_shape, area):
    x1, y1, x2, y2 = area
    h, w = image_shape[:2]
    padding = (max(-y1, 0), max(y2 - h, 0), max(-x1, 0), max(x2 - w, 0))
    overflow = y1 >= h or y2 <= 0 or x1 >= w or x2 <= 0
    return padding, overflow


def _crop_border_value(image_shape):
    if len(image_shape) == 2:
        return 0
    return tuple(0 for _ in range(image_shape[2]))


def crop(image, area, copy=True):
    """按 Pillow 语义裁剪图片；超出边界时用黑色补齐，完全越界时返回全黑图。"""
    area = _round_area(area)
    shape = image.shape
    padding, overflow = _crop_padding_and_overflow(shape, area)
    if overflow:
        return np.zeros(_crop_output_shape(shape, area), dtype=image.dtype)

    x1, y1, x2, y2 = area
    x1 = max(x1, 0)
    y1 = max(y1, 0)
    x2 = max(x2, 0)
    y2 = max(y2, 0)
    image = image[y1:y2, x1:x2]
    if any(padding):
        return cv2.copyMakeBorder(image, *padding, borderType=cv2.BORDER_CONSTANT, value=_crop_border_value(shape))
    if copy:
        return copy_image(image)
    return image


def resize(image, size):
    """按最近邻插值缩放，size 为 (width, height)。"""
    return cv2.resize(image, size, interpolation=cv2.INTER_NEAREST)


def image_channel(image):
    """二维灰度图返回 0，三维图返回 shape[2] 的通道数。"""
    return image.shape[2] if len(image.shape) == 3 else 0


def image_size(image):
    """按 (width, height) 顺序返回图像尺寸。"""
    shape = image.shape
    return shape[1], shape[0]


def image_paste(image, background, origin):
    """以 origin 为左上角原地修改 background，不返回新图像。"""
    x, y = origin
    w, h = image_size(image)
    background[y : y + h, x : x + w] = image


def rgb2gray(image):
    """按 `(max(R,G,B) + min(R,G,B)) / 2` 转为 (height, width) 灰度图。"""
    r, g, b = cv2.split(image)
    maximum = cv2.max(r, g)
    cv2.min(r, g, dst=r)
    cv2.max(maximum, b, dst=maximum)
    cv2.min(r, b, dst=r)
    cv2.convertScaleAbs(maximum, alpha=0.5, dst=maximum)
    cv2.convertScaleAbs(r, alpha=0.5, dst=r)
    cv2.add(maximum, r, dst=maximum)
    return maximum


def rgb2hsv(image):
    """把 RGB 转为 HSV 浮点数组；H 为 0～360，S、V 为 0～100。"""
    image = cv2.cvtColor(image, cv2.COLOR_RGB2HSV).astype(float)
    cv2.multiply(image, _cv_scalar((360 / 180, 100 / 255, 100 / 255, 0)), dst=image)
    return image


def rgb2yuv(image):
    """把 RGB 图像转为 YUV，保持 (height, width, 3) 形状。"""
    return cv2.cvtColor(image, cv2.COLOR_RGB2YUV)


def rgb2luma(image):
    """提取 RGB 图像的 YUV 亮度通道，返回 (height, width) 数组。"""
    image = cv2.cvtColor(image, cv2.COLOR_RGB2YUV)
    luma, _, _ = cv2.split(image)
    return luma


def get_color(image, area):
    """返回 (x1, y1, x2, y2) 区域的平均 RGB。"""
    temp = crop(image, area, copy=False)
    color = cv2.mean(temp)
    return color[:3]


class ImageNotSupported(Exception):
    """图像形状或内容不支持当前计算。"""


PURE_BLACK_BBOX_MESSAGE = "Cannot get bbox from a pure black image"


def get_bbox(image, threshold=0):
    """返回所有亮度大于 threshold 内容的外接 (x1, y1, x2, y2)。

    不支持的通道数、纯黑图或空外接框会抛出 ImageNotSupported。
    """
    channel = image_channel(image)
    if channel == 3:
        mask = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY)
        cv2.threshold(mask, threshold, 255, cv2.THRESH_BINARY, dst=mask)
    elif channel == 0:
        _, mask = cv2.threshold(image, threshold, 255, cv2.THRESH_BINARY)
    elif channel == 4:
        mask = cv2.cvtColor(image, cv2.COLOR_RGBA2GRAY)
        cv2.threshold(mask, threshold, 255, cv2.THRESH_BINARY, dst=mask)
    else:
        message = f"shape={image.shape}"
        raise ImageNotSupported(message)

    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    min_y, min_x = mask.shape
    max_x = 0
    max_y = 0
    if not contours:
        raise ImageNotSupported(PURE_BLACK_BBOX_MESSAGE)
    for contour in contours:
        x1, y1, x2, y2 = cv2.boundingRect(contour)
        x2 += x1
        y2 += y1
        min_x = min(min_x, x1)
        min_y = min(min_y, y1)
        max_x = max(max_x, x2)
        max_y = max(max_y, y2)
    if min_x < max_x and min_y < max_y:
        return min_x, min_y, max_x, max_y
    bbox = (min_x, min_y, max_x, max_y)
    message = f"Empty bbox {bbox}"
    raise ImageNotSupported(message)


def get_bbox_reversed(image, threshold=255):
    """返回所有亮度小于 threshold 内容的外接 (x1, y1, x2, y2)。

    不支持的通道数、纯黑图或空外接框会抛出 ImageNotSupported。
    """
    channel = image_channel(image)
    if channel == 3:
        mask = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY)
        cv2.threshold(mask, 0, threshold, cv2.THRESH_BINARY, dst=mask)
    elif channel == 0:
        mask = cv2.threshold(image, 0, threshold, cv2.THRESH_BINARY)
    elif channel == 4:
        mask = cv2.cvtColor(image, cv2.COLOR_RGBA2GRAY)
        cv2.threshold(mask, 0, threshold, cv2.THRESH_BINARY, dst=mask)
    else:
        message = f"shape={image.shape}"
        raise ImageNotSupported(message)

    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    min_y, min_x = mask.shape
    max_x = 0
    max_y = 0
    if not contours:
        raise ImageNotSupported(PURE_BLACK_BBOX_MESSAGE)
    for contour in contours:
        x1, y1, x2, y2 = cv2.boundingRect(contour)
        x2 += x1
        y2 += y1
        min_x = min(min_x, x1)
        min_y = min(min_y, y1)
        max_x = max(max_x, x2)
        max_y = max(max_y, y2)
    if min_x < max_x and min_y < max_y:
        return min_x, min_y, max_x, max_y
    bbox = (min_x, min_y, max_x, max_y)
    message = f"Empty bbox {bbox}"
    raise ImageNotSupported(message)


def color_similarity(color1, color2):
    """按 `max(正 RGB 差) + max(负 RGB 差的绝对值)` 返回 Photoshop 式色差。"""
    diff_r = color1[0] - color2[0]
    diff_g = color1[1] - color2[1]
    diff_b = color1[2] - color2[2]

    max_positive = 0
    max_negative = 0
    if diff_r > max_positive:
        max_positive = diff_r
    elif diff_r < max_negative:
        max_negative = diff_r
    if diff_g > max_positive:
        max_positive = diff_g
    elif diff_g < max_negative:
        max_negative = diff_g
    if diff_b > max_positive:
        max_positive = diff_b
    elif diff_b < max_negative:
        max_negative = diff_b

    return max_positive - max_negative


def color_similar(color1, color2, threshold=10):
    diff_r = color1[0] - color2[0]
    diff_g = color1[1] - color2[1]
    diff_b = color1[2] - color2[2]

    max_positive = 0
    max_negative = 0
    if diff_r > max_positive:
        max_positive = diff_r
    elif diff_r < max_negative:
        max_negative = diff_r
    if diff_g > max_positive:
        max_positive = diff_g
    elif diff_g < max_negative:
        max_negative = diff_g
    if diff_b > max_positive:
        max_positive = diff_b
    elif diff_b < max_negative:
        max_negative = diff_b

    diff = max_positive - max_negative
    return diff <= threshold


def color_similar_1d(image, color, threshold=10):
    """逐行比较 (n, 3) RGB 数组，返回形状为 (n,) 的布尔掩码。"""
    diff = image.astype(int) - color
    diff = np.max(np.maximum(diff, 0), axis=1) - np.min(np.minimum(diff, 0), axis=1)
    return diff <= threshold


def color_similarity_2d(image, color):
    """逐像素返回与目标 RGB 的反向色差，结果是二维 uint8，255 表示完全相同。"""
    diff = cv2.subtract(image, _cv_scalar((*color, 0)))
    r, g, b = cv2.split(diff)
    cv2.max(r, g, dst=r)
    cv2.max(r, b, dst=r)
    positive = r
    cv2.subtract(_cv_scalar((*color, 0)), image, dst=diff)
    r, g, b = cv2.split(diff)
    cv2.max(r, g, dst=r)
    cv2.max(r, b, dst=r)
    negative = r
    cv2.add(positive, negative, dst=positive)
    cv2.subtract(_cv_scalar((255, 255, 255, 255)), positive, dst=positive)
    return positive


def extract_letters(image, letter=(255, 255, 255), threshold=128):
    """把 (height, width, channel) 图像中的目标 RGB 字符映射为黑色，背景映射为白色。"""
    diff = cv2.subtract(image, _cv_scalar((*letter, 0)))
    r, g, b = cv2.split(diff)
    cv2.max(r, g, dst=r)
    cv2.max(r, b, dst=r)
    positive = r
    cv2.subtract(_cv_scalar((*letter, 0)), image, dst=diff)
    r, g, b = cv2.split(diff)
    cv2.max(r, g, dst=r)
    cv2.max(r, b, dst=r)
    negative = r
    cv2.add(positive, negative, dst=positive)
    if threshold != 255:
        cv2.convertScaleAbs(positive, alpha=255.0 / threshold, dst=positive)
    return positive


def extract_white_letters(image, threshold=128):
    """把白色字符映射为黑色、背景映射为白色，并额外抑制非灰度彩色像素。"""
    r, g, b = cv2.split(cv2.subtract(_cv_scalar((255, 255, 255, 0)), image))
    maximum = cv2.max(r, g)
    cv2.min(r, g, dst=r)
    cv2.max(maximum, b, dst=maximum)
    cv2.min(r, b, dst=r)
    cv2.convertScaleAbs(maximum, alpha=0.5, dst=maximum)
    cv2.convertScaleAbs(r, alpha=0.5, dst=r)
    cv2.subtract(maximum, r, dst=r)
    cv2.add(maximum, r, dst=maximum)
    if threshold != 255:
        cv2.convertScaleAbs(maximum, alpha=255.0 / threshold, dst=maximum)
    return maximum


def color_mapping(image, max_multiply=2):
    """把颜色动态映射到 0～255，并把最大增益限制为 max_multiply。"""
    image = image.astype(float)
    low, high = np.min(image), np.max(image)
    multiply = min(255 / (high - low), max_multiply)
    add = (255 - multiply * (low + high)) / 2
    cv2.multiply(image, _cv_scalar((multiply, multiply, multiply, multiply)), dst=image)
    cv2.add(image, add, dst=image)
    image[image > 255] = 255
    image[image < 0] = 0
    return image.astype(np.uint8)


def image_left_strip(image, threshold, length):
    """从二维图首个平均亮度低于 threshold 的列起裁掉 length 像素。

    threshold 范围为 0～255；例如可从 `DAILY:200/200` 图像中裁掉 `DAILY:`，保留 `200/200`。
    """
    brightness = np.mean(image, axis=0)
    match = np.where(brightness < threshold)[0]

    if len(match):
        left = match[0] + length
        total = image.shape[1]
        if left < total:
            image = image[:, left:]
    return image


def red_overlay_transparency(color1, color2, red=247):
    """根据叠加前后颜色估算 0～1 的红色遮罩透明度；red 范围为 0～255。"""
    return (color2[0] - color1[0]) / (red - color1[0])


def color_bar_percentage(image, area, prev_color, options=None):
    """按扫描方向、起点和颜色阈值估算色条比例，返回 0～1。"""
    if options is None:
        options = ColorBarOptions()
    image = crop(image, area, copy=False)
    image = image[:, ::-1, :] if options.reverse else image
    length = image.shape[1]
    prev_index = options.starter

    for _ in range(1280):
        bar = color_similarity_2d(image, color=prev_color)
        index = np.where(np.any(bar > 255 - options.threshold, axis=0))[0]
        if not index.size:
            return prev_index / length
        index = index[-1]
        if index <= prev_index:
            return index / length
        prev_index = index

        prev_row = bar[:, prev_index] > 255 - options.threshold
        if not prev_row.size:
            return prev_index / length
        # 回看 5 像素更新平均颜色，以跟随渐变色条。
        left = max(prev_index - 5, 0)
        mask = np.where(bar[:, left : prev_index + 1] > 255 - options.threshold)
        prev_color = np.mean(image[:, left : prev_index + 1][mask], axis=0)

    return 0.0
